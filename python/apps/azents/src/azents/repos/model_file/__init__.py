"""ModelFile repository."""

import datetime
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ModelFileStatus
from azents.rdb.models.model_file import RDBModelFile
from azents.rdb.models.model_file_pin import RDBModelFilePin

from .data import ModelFile, ModelFileCreate


def model_file_storage_key(
    *,
    workspace_id: str,
    session_id: str,
    model_file_id: str,
) -> str:
    """Create ModelFile object storage key."""
    return f"model-files/{workspace_id}/{session_id}/{model_file_id}"


class ModelFileRepository:
    """ModelFile CRUD repository."""

    async def create(
        self,
        session: AsyncSession,
        create: ModelFileCreate,
    ) -> ModelFile:
        """Create ModelFile metadata."""
        rdb = RDBModelFile(
            workspace_id=create.workspace_id,
            session_id=create.session_id,
            agent_id=create.agent_id,
            name=create.name,
            media_type=create.media_type,
            kind=create.kind,
            size_bytes=create.size_bytes,
            created_run_index=create.created_run_index,
            status=ModelFileStatus.AVAILABLE,
            normalized_format=create.normalized_format,
            sha256=create.sha256,
            metadata_=create.metadata,
        )
        rdb.id = create.id
        rdb.storage_key = model_file_storage_key(
            workspace_id=create.workspace_id,
            session_id=create.session_id,
            model_file_id=create.id,
        )
        session.add(rdb)
        await session.flush()
        return self._build(rdb)

    async def get_by_id(
        self,
        session: AsyncSession,
        model_file_id: str,
    ) -> ModelFile | None:
        """Fetch ModelFile by ID."""
        rdb = await session.get(RDBModelFile, model_file_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_by_id_for_agent(
        self,
        session: AsyncSession,
        *,
        model_file_id: str,
        agent_id: str,
    ) -> ModelFile | None:
        """Fetch ModelFile only inside current Agent namespace."""
        rdb = await session.scalar(
            sa.select(RDBModelFile).where(
                RDBModelFile.id == model_file_id,
                RDBModelFile.agent_id == agent_id,
            )
        )
        if rdb is None:
            return None
        return self._build(rdb)

    async def list_statuses_for_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        model_file_ids: Sequence[str],
    ) -> dict[str, ModelFileStatus]:
        """Return status by ModelFile ID belonging to session."""
        if not model_file_ids:
            return {}
        rows = (
            await session.execute(
                sa.select(RDBModelFile.id, RDBModelFile.status).where(
                    RDBModelFile.session_id == session_id,
                    RDBModelFile.id.in_(model_file_ids),
                )
            )
        ).all()
        return {row.id: row.status for row in rows}

    async def list_for_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> list[ModelFile]:
        """List ModelFiles owned by a SessionAgent subtree."""
        if not session_ids:
            return []
        rows = (
            await session.scalars(
                sa.select(RDBModelFile)
                .where(RDBModelFile.session_id.in_(session_ids))
                .order_by(RDBModelFile.id)
            )
        ).all()
        return [self._build(row) for row in rows]

    async def mark_deleted_for_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
        deleted_at: datetime.datetime,
    ) -> list[ModelFile]:
        """Mark unpinned subtree ModelFiles deleted for purge."""
        if not session_ids:
            return []
        rows = (
            await session.scalars(
                sa.select(RDBModelFile)
                .where(
                    RDBModelFile.session_id.in_(session_ids),
                    RDBModelFile.status == ModelFileStatus.AVAILABLE,
                    ~sa.exists(
                        sa.select(RDBModelFilePin.model_file_id).where(
                            RDBModelFilePin.model_file_id == RDBModelFile.id
                        )
                    ),
                )
                .order_by(RDBModelFile.id)
            )
        ).all()
        for row in rows:
            row.status = ModelFileStatus.DELETED
            row.deleted_at = deleted_at
        await session.flush()
        return [self._build(row) for row in rows]

    async def delete_purged_for_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> int:
        """Delete subtree ModelFile metadata after blob cleanup."""
        if not session_ids:
            return 0
        deleted_ids = (
            await session.scalars(
                sa.delete(RDBModelFile)
                .where(
                    RDBModelFile.session_id.in_(session_ids),
                    RDBModelFile.status == ModelFileStatus.DELETED,
                    RDBModelFile.blob_deleted_at.is_not(None),
                )
                .returning(RDBModelFile.id)
            )
        ).all()
        return len(deleted_ids)

    async def mark_deleted_if_unpinned(
        self,
        session: AsyncSession,
        *,
        model_file_ids: Sequence[str],
        deleted_at: datetime.datetime,
    ) -> list[ModelFile]:
        """Mark available ModelFiles deleted when no active pin exists."""
        if not model_file_ids:
            return []

        rows = (
            await session.scalars(
                sa.select(RDBModelFile)
                .where(
                    RDBModelFile.id.in_(model_file_ids),
                    RDBModelFile.status == ModelFileStatus.AVAILABLE,
                    ~sa.exists(
                        sa.select(RDBModelFilePin.model_file_id).where(
                            RDBModelFilePin.model_file_id == RDBModelFile.id
                        )
                    ),
                )
                .order_by(RDBModelFile.id)
            )
        ).all()
        for row in rows:
            row.status = ModelFileStatus.DELETED
            row.deleted_at = deleted_at
        await session.flush()
        return [self._build(row) for row in rows]

    async def mark_deleted(
        self,
        session: AsyncSession,
        *,
        model_file_id: str,
        deleted_at: datetime.datetime,
    ) -> ModelFile:
        """Update ModelFile metadata as deleted."""
        row = await session.get_one(RDBModelFile, model_file_id)
        row.status = ModelFileStatus.DELETED
        row.deleted_at = deleted_at
        await session.flush()
        return self._build(row)

    async def list_deleted_pending_blob_deletion(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[ModelFile]:
        """List deleted ModelFiles whose blob deletion has not been recorded."""
        rows = (
            await session.scalars(
                sa.select(RDBModelFile)
                .where(
                    RDBModelFile.status == ModelFileStatus.DELETED,
                    RDBModelFile.blob_deleted_at.is_(None),
                )
                .order_by(RDBModelFile.deleted_at, RDBModelFile.id)
                .limit(limit)
            )
        ).all()
        return [self._build(row) for row in rows]

    async def mark_blob_deleted(
        self,
        session: AsyncSession,
        *,
        model_file_id: str,
        blob_deleted_at: datetime.datetime,
    ) -> None:
        """Record ModelFile blob deletion success."""
        await session.execute(
            sa.update(RDBModelFile)
            .where(RDBModelFile.id == model_file_id)
            .values(blob_deleted_at=blob_deleted_at)
        )
        await session.flush()

    def _build(self, rdb: RDBModelFile) -> ModelFile:
        """Convert RDB model to domain model."""
        return ModelFile(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            session_id=rdb.session_id,
            agent_id=rdb.agent_id,
            name=rdb.name,
            media_type=rdb.media_type,
            kind=rdb.kind,
            size_bytes=rdb.size_bytes,
            created_run_index=rdb.created_run_index,
            storage_key=rdb.storage_key,
            status=rdb.status,
            normalized_format=rdb.normalized_format,
            sha256=rdb.sha256,
            metadata=rdb.metadata_,
            created_at=rdb.created_at,
            deleted_at=rdb.deleted_at,
            blob_deleted_at=rdb.blob_deleted_at,
        )
