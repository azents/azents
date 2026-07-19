"""ExchangeFile repository."""

import datetime
from collections.abc import Sequence

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExchangeFileStatus
from azents.rdb.models.exchange_file import RDBExchangeFile

from .data import (
    ExchangeFile,
    ExchangeFileClaimError,
    ExchangeFileClaimExpired,
    ExchangeFileClaimNotFound,
    ExchangeFileClaimOwnerConflict,
    ExchangeFileClaimUnavailable,
    ExchangeFileClaimWrongScope,
    ExchangeFileCreate,
)


def exchange_file_object_key(*, workspace_id: str, file_id: str) -> str:
    """Create Exchange file object storage key."""
    return f"exchange/{workspace_id}/files/{file_id}/original"


class ExchangeFileRepository:
    """ExchangeFile CRUD repository."""

    async def create(
        self,
        session: AsyncSession,
        create: ExchangeFileCreate,
    ) -> ExchangeFile:
        """Create ExchangeFile metadata."""
        rdb = RDBExchangeFile(
            workspace_id=create.workspace_id,
            agent_id=create.agent_id,
            origin_type=create.origin_type,
            status=ExchangeFileStatus.AVAILABLE,
            filename=create.filename,
            media_type=create.media_type,
            size_bytes=create.size_bytes,
            sha256=create.sha256,
            created_by_user_id=create.created_by_user_id,
            retention_root_session_id=create.retention_root_session_id,
            retention_bound_at=create.retention_bound_at,
            preview_title=create.preview_title,
            preview_summary=create.preview_summary,
            preview_thumbnail_media_type=create.preview_thumbnail_media_type,
            preview_thumbnail_width=create.preview_thumbnail_width,
            preview_thumbnail_height=create.preview_thumbnail_height,
            preview_generated_at=create.preview_generated_at,
            expires_at=create.expires_at,
        )
        rdb.id = create.id
        rdb.object_key = exchange_file_object_key(
            workspace_id=create.workspace_id,
            file_id=create.id,
        )
        session.add(rdb)
        await session.flush()
        return self._build(rdb)

    async def get_by_id(
        self,
        session: AsyncSession,
        file_id: str,
    ) -> ExchangeFile | None:
        """Fetch ExchangeFile by ID."""
        rdb = await session.get(RDBExchangeFile, file_id)
        if rdb is None:
            return None
        return await self._build_with_preview_uri(session, rdb)

    async def get_by_object_key(
        self,
        session: AsyncSession,
        object_key: str,
    ) -> ExchangeFile | None:
        """Fetch ExchangeFile by object key."""
        rdb = await session.scalar(
            sa.select(RDBExchangeFile).where(RDBExchangeFile.object_key == object_key)
        )
        if rdb is None:
            return None
        return await self._build_with_preview_uri(session, rdb)

    async def get_by_object_key_for_agent(
        self,
        session: AsyncSession,
        *,
        object_key: str,
        agent_id: str,
    ) -> ExchangeFile | None:
        """Fetch object key only inside current Agent namespace."""
        rdb = await session.scalar(
            sa.select(RDBExchangeFile).where(
                RDBExchangeFile.object_key == object_key,
                RDBExchangeFile.agent_id == agent_id,
            )
        )
        if rdb is None:
            return None
        return await self._build_with_preview_uri(session, rdb)

    async def delete_by_id(
        self,
        session: AsyncSession,
        file_id: str,
    ) -> None:
        """Delete ExchangeFile metadata."""
        await session.execute(
            sa.delete(RDBExchangeFile).where(RDBExchangeFile.id == file_id)
        )
        await session.flush()

    async def set_preview_thumbnail_file_id(
        self,
        session: AsyncSession,
        *,
        file_id: str,
        preview_thumbnail_file_id: str,
        preview_thumbnail_media_type: str,
        preview_thumbnail_width: int,
        preview_thumbnail_height: int,
        preview_generated_at: datetime.datetime,
    ) -> ExchangeFile:
        """Link preview thumbnail file ID to source ExchangeFile."""
        rdb = await session.get(RDBExchangeFile, file_id)
        if rdb is None:
            msg = "ExchangeFile not found while setting preview thumbnail"
            raise RuntimeError(msg)
        rdb.preview_thumbnail_file_id = preview_thumbnail_file_id
        rdb.preview_thumbnail_media_type = preview_thumbnail_media_type
        rdb.preview_thumbnail_width = preview_thumbnail_width
        rdb.preview_thumbnail_height = preview_thumbnail_height
        rdb.preview_generated_at = preview_generated_at
        await session.flush()
        preview_thumbnail = await session.get(
            RDBExchangeFile,
            preview_thumbnail_file_id,
        )
        preview_thumbnail_uri = (
            f"exchange://{preview_thumbnail.object_key}"
            if preview_thumbnail is not None
            else None
        )
        return self._build(rdb, preview_thumbnail_uri=preview_thumbnail_uri)

    async def _build_with_preview_uri(
        self,
        session: AsyncSession,
        rdb: RDBExchangeFile,
    ) -> ExchangeFile:
        """Convert RDB model to domain model including preview thumbnail URI."""
        preview_thumbnail_uri: str | None = None
        if rdb.preview_thumbnail_file_id is not None:
            preview_thumbnail = await session.get(
                RDBExchangeFile,
                rdb.preview_thumbnail_file_id,
            )
            if preview_thumbnail is not None:
                preview_thumbnail_uri = f"exchange://{preview_thumbnail.object_key}"
        return self._build(rdb, preview_thumbnail_uri=preview_thumbnail_uri)

    async def claim_for_retention_root(
        self,
        session: AsyncSession,
        *,
        object_keys: Sequence[str],
        workspace_id: str,
        agent_id: str,
        retention_root_session_id: str,
        bound_at: datetime.datetime,
    ) -> Result[None, ExchangeFileClaimError]:
        """Atomically bind referenced source and preview rows to one root session."""
        deduped_keys = sorted(set(object_keys))
        if not deduped_keys:
            return Success(None)

        preview_ids = (
            sa.select(RDBExchangeFile.preview_thumbnail_file_id)
            .where(
                RDBExchangeFile.object_key.in_(deduped_keys),
                RDBExchangeFile.preview_thumbnail_file_id.is_not(None),
            )
            .scalar_subquery()
        )
        rows = list(
            (
                await session.scalars(
                    sa.select(RDBExchangeFile)
                    .where(
                        sa.or_(
                            RDBExchangeFile.object_key.in_(deduped_keys),
                            RDBExchangeFile.id.in_(preview_ids),
                        )
                    )
                    .order_by(RDBExchangeFile.id.asc())
                    .with_for_update()
                )
            ).all()
        )
        sources_by_key = {
            row.object_key: row for row in rows if row.object_key in deduped_keys
        }
        if set(sources_by_key) != set(deduped_keys):
            return Failure(ExchangeFileClaimNotFound())

        rows_by_id = {row.id: row for row in rows}
        claim_ids = set(rows_by_id)
        for source in sources_by_key.values():
            if source.preview_thumbnail_file_id is not None:
                if source.preview_thumbnail_file_id not in rows_by_id:
                    return Failure(ExchangeFileClaimNotFound())
                claim_ids.add(source.preview_thumbnail_file_id)
        claim_rows = [rows_by_id[file_id] for file_id in sorted(claim_ids)]

        if any(
            row.workspace_id != workspace_id or row.agent_id != agent_id
            for row in claim_rows
        ):
            return Failure(ExchangeFileClaimWrongScope())
        if any(
            row.status != ExchangeFileStatus.AVAILABLE or row.expires_at <= bound_at
            for row in claim_rows
        ):
            return Failure(ExchangeFileClaimExpired())
        if any(row.blob_deleted_at is not None for row in claim_rows):
            return Failure(ExchangeFileClaimUnavailable())
        if any(
            row.retention_root_session_id not in {None, retention_root_session_id}
            for row in claim_rows
        ):
            return Failure(ExchangeFileClaimOwnerConflict())

        for row in claim_rows:
            if row.retention_root_session_id is None:
                row.retention_root_session_id = retention_root_session_id
                row.retention_bound_at = bound_at
            elif row.retention_bound_at is None:
                row.retention_bound_at = bound_at
        await session.flush()
        return Success(None)

    async def list_for_retention_root(
        self,
        session: AsyncSession,
        *,
        retention_root_session_id: str,
    ) -> list[ExchangeFile]:
        """List ExchangeFiles owned by one retention root."""
        rows = (
            await session.scalars(
                sa.select(RDBExchangeFile)
                .where(
                    RDBExchangeFile.retention_root_session_id
                    == retention_root_session_id
                )
                .order_by(RDBExchangeFile.id)
            )
        ).all()
        return [self._build(row) for row in rows]

    async def expire_for_retention_root(
        self,
        session: AsyncSession,
        *,
        retention_root_session_id: str,
        expired_at: datetime.datetime,
    ) -> list[ExchangeFile]:
        """Expire available ExchangeFiles owned by one retention root."""
        rows = (
            await session.scalars(
                sa.select(RDBExchangeFile)
                .where(
                    RDBExchangeFile.retention_root_session_id
                    == retention_root_session_id,
                    RDBExchangeFile.status == ExchangeFileStatus.AVAILABLE,
                )
                .order_by(RDBExchangeFile.id)
            )
        ).all()
        for row in rows:
            row.status = ExchangeFileStatus.EXPIRED
            row.expired_at = expired_at
        await session.flush()
        return [self._build(row) for row in rows]

    async def delete_purged_for_retention_root(
        self,
        session: AsyncSession,
        *,
        retention_root_session_id: str,
    ) -> int:
        """Delete owned ExchangeFile metadata after blob cleanup."""
        deleted_ids = (
            await session.scalars(
                sa.delete(RDBExchangeFile)
                .where(
                    RDBExchangeFile.retention_root_session_id
                    == retention_root_session_id,
                    RDBExchangeFile.status == ExchangeFileStatus.EXPIRED,
                    RDBExchangeFile.blob_deleted_at.is_not(None),
                )
                .returning(RDBExchangeFile.id)
            )
        ).all()
        return len(deleted_ids)

    async def expire_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        limit: int,
    ) -> list[ExchangeFile]:
        """Mark ExchangeFiles past expiration time as expired."""
        rows = (
            await session.scalars(
                sa.select(RDBExchangeFile)
                .where(
                    RDBExchangeFile.status == ExchangeFileStatus.AVAILABLE,
                    RDBExchangeFile.expires_at <= now,
                )
                .order_by(RDBExchangeFile.expires_at, RDBExchangeFile.id)
                .limit(limit)
            )
        ).all()
        for row in rows:
            row.status = ExchangeFileStatus.EXPIRED
            row.expired_at = now
        await session.flush()
        return [self._build(row) for row in rows]

    async def list_expired_pending_blob_deletion(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[ExchangeFile]:
        """List expired ExchangeFiles whose blob deletion has not been recorded."""
        rows = (
            await session.scalars(
                sa.select(RDBExchangeFile)
                .where(
                    RDBExchangeFile.status == ExchangeFileStatus.EXPIRED,
                    RDBExchangeFile.blob_deleted_at.is_(None),
                )
                .order_by(RDBExchangeFile.expired_at, RDBExchangeFile.id)
                .limit(limit)
            )
        ).all()
        return [self._build(row) for row in rows]

    async def mark_blob_deleted(
        self,
        session: AsyncSession,
        *,
        file_id: str,
        blob_deleted_at: datetime.datetime,
    ) -> None:
        """Record ExchangeFile blob deletion success."""
        await session.execute(
            sa.update(RDBExchangeFile)
            .where(RDBExchangeFile.id == file_id)
            .values(blob_deleted_at=blob_deleted_at)
        )
        await session.flush()

    async def expire_file_family(
        self,
        session: AsyncSession,
        *,
        file_id: str,
        expired_at: datetime.datetime,
    ) -> list[ExchangeFile]:
        """Mark preview thumbnail linked to source file as expired."""
        rdb = await session.get(RDBExchangeFile, file_id)
        if rdb is None:
            return []
        ids = [rdb.id]
        if rdb.preview_thumbnail_file_id is not None:
            ids.append(rdb.preview_thumbnail_file_id)
        rows = (
            await session.scalars(
                sa.select(RDBExchangeFile).where(
                    RDBExchangeFile.id.in_(ids),
                    RDBExchangeFile.status == ExchangeFileStatus.AVAILABLE,
                )
            )
        ).all()
        for row in rows:
            row.status = ExchangeFileStatus.EXPIRED
            row.expired_at = expired_at
        await session.flush()
        return [self._build(row) for row in rows]

    async def list_statuses_by_object_key(
        self,
        session: AsyncSession,
        *,
        object_keys: Sequence[str],
    ) -> dict[str, ExchangeFileStatus]:
        """Return ExchangeFile status by object key."""
        if not object_keys:
            return {}
        rows = (
            await session.execute(
                sa.select(RDBExchangeFile.object_key, RDBExchangeFile.status).where(
                    RDBExchangeFile.object_key.in_(object_keys)
                )
            )
        ).all()
        return {object_key: status for object_key, status in rows}

    def _build(
        self,
        rdb: RDBExchangeFile,
        *,
        preview_thumbnail_uri: str | None = None,
    ) -> ExchangeFile:
        """Convert RDB model to domain model."""
        return ExchangeFile(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            agent_id=rdb.agent_id,
            origin_type=rdb.origin_type,
            status=rdb.status,
            object_key=rdb.object_key,
            filename=rdb.filename,
            media_type=rdb.media_type,
            size_bytes=rdb.size_bytes,
            sha256=rdb.sha256,
            created_by_user_id=rdb.created_by_user_id,
            retention_root_session_id=rdb.retention_root_session_id,
            retention_bound_at=rdb.retention_bound_at,
            preview_thumbnail_file_id=rdb.preview_thumbnail_file_id,
            preview_thumbnail_uri=preview_thumbnail_uri,
            preview_title=rdb.preview_title,
            preview_summary=rdb.preview_summary,
            preview_thumbnail_media_type=rdb.preview_thumbnail_media_type,
            preview_thumbnail_width=rdb.preview_thumbnail_width,
            preview_thumbnail_height=rdb.preview_thumbnail_height,
            preview_generated_at=rdb.preview_generated_at,
            expires_at=rdb.expires_at,
            expired_at=rdb.expired_at,
            blob_deleted_at=rdb.blob_deleted_at,
            created_at=rdb.created_at,
        )
