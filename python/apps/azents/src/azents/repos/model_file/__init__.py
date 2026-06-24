"""ModelFile repository."""

import datetime
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ModelFileStatus
from azents.rdb.models.model_file import RDBModelFile

from .data import ModelFile, ModelFileCreate


def _storage_key(rdb: RDBModelFile) -> str:
    """Create ModelFile object storage key."""
    return f"model-files/{rdb.workspace_id}/{rdb.session_id}/{rdb.id}"


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
            expires_after_run_index=create.expires_after_run_index,
            status=ModelFileStatus.AVAILABLE,
            normalized_format=create.normalized_format,
            sha256=create.sha256,
            metadata_=create.metadata,
        )
        rdb.storage_key = _storage_key(rdb)
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

    async def list_for_run_boundary(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        current_run_index: int,
    ) -> list[ModelFile]:
        """Fetch ModelFiles subject to run boundary lifecycle."""
        rows = (
            await session.scalars(
                sa.select(RDBModelFile)
                .where(
                    RDBModelFile.session_id == session_id,
                    RDBModelFile.status.in_(
                        [
                            ModelFileStatus.AVAILABLE,
                            ModelFileStatus.DEGRADED,
                            ModelFileStatus.UNREACHABLE,
                        ]
                    ),
                    RDBModelFile.created_run_index < current_run_index,
                )
                .order_by(RDBModelFile.created_run_index, RDBModelFile.id)
            )
        ).all()
        return [self._build(row) for row in rows]

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

    async def mark_degraded(
        self,
        session: AsyncSession,
        *,
        model_file_id: str,
        size_bytes: int,
        normalized_format: str,
        sha256: str,
        degraded_at: datetime.datetime,
    ) -> ModelFile:
        """Update ModelFile metadata with degraded blob info."""
        row = await session.get_one(RDBModelFile, model_file_id)
        row.status = ModelFileStatus.DEGRADED
        row.size_bytes = size_bytes
        row.normalized_format = normalized_format
        row.sha256 = sha256
        row.degraded_at = degraded_at
        await session.flush()
        return self._build(row)

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

    async def mark_unreachable(
        self,
        session: AsyncSession,
        *,
        model_file_id: str,
        unreachable_run_index: int,
        unreachable_at: datetime.datetime,
    ) -> ModelFile:
        """Update ModelFile metadata as unreachable."""
        row = await session.get_one(RDBModelFile, model_file_id)
        row.status = ModelFileStatus.UNREACHABLE
        row.unreachable_run_index = unreachable_run_index
        row.unreachable_at = unreachable_at
        await session.flush()
        return self._build(row)

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
            expires_after_run_index=rdb.expires_after_run_index,
            storage_key=rdb.storage_key,
            status=rdb.status,
            normalized_format=rdb.normalized_format,
            sha256=rdb.sha256,
            metadata=rdb.metadata_,
            created_at=rdb.created_at,
            degraded_at=rdb.degraded_at,
            unreachable_run_index=rdb.unreachable_run_index,
            unreachable_at=rdb.unreachable_at,
            deleted_at=rdb.deleted_at,
        )
