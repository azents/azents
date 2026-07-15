"""Artifact repository."""

import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ArtifactStatus
from azents.rdb.models.artifact import RDBArtifact

from .data import Artifact, ArtifactCreate


def artifact_storage_key(
    *,
    workspace_id: str,
    session_id: str,
    created_run_index: int,
    artifact_id: str,
) -> str:
    """Create Artifact object storage key."""
    return f"artifacts/{workspace_id}/{session_id}/{created_run_index}/{artifact_id}"


class ArtifactRepository:
    """Artifact CRUD repository."""

    async def create(
        self,
        session: AsyncSession,
        create: ArtifactCreate,
    ) -> Artifact:
        """Create Artifact metadata."""
        rdb = RDBArtifact(
            workspace_id=create.workspace_id,
            session_id=create.session_id,
            agent_id=create.agent_id,
            created_run_id=create.created_run_id,
            created_run_index=create.created_run_index,
            expires_at=create.expires_at,
            name=create.name,
            media_type=create.media_type,
            size_bytes=create.size_bytes,
            status=ArtifactStatus.AVAILABLE,
            sha256=create.sha256,
            source_tool_name=create.source_tool_name,
            source_call_id=create.source_call_id,
            source_part_index=create.source_part_index,
            description=create.description,
            metadata_=create.metadata,
        )
        rdb.id = create.id
        rdb.storage_key = artifact_storage_key(
            workspace_id=create.workspace_id,
            session_id=create.session_id,
            created_run_index=create.created_run_index,
            artifact_id=create.id,
        )
        session.add(rdb)
        await session.flush()
        return self._build(rdb)

    async def get_by_id(
        self,
        session: AsyncSession,
        artifact_id: str,
    ) -> Artifact | None:
        """Fetch Artifact by ID."""
        rdb = await session.get(RDBArtifact, artifact_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_by_storage_key(
        self,
        session: AsyncSession,
        storage_key: str,
    ) -> Artifact | None:
        """Fetch Artifact by storage key."""
        rdb = await session.scalar(
            sa.select(RDBArtifact).where(RDBArtifact.storage_key == storage_key)
        )
        if rdb is None:
            return None
        return self._build(rdb)

    async def expire_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        limit: int,
    ) -> list[Artifact]:
        """Mark Artifacts past expiration time as expired."""
        rows = (
            await session.scalars(
                sa.select(RDBArtifact)
                .where(
                    RDBArtifact.status == ArtifactStatus.AVAILABLE,
                    RDBArtifact.expires_at <= now,
                )
                .order_by(RDBArtifact.expires_at, RDBArtifact.id)
                .limit(limit)
            )
        ).all()
        for row in rows:
            row.status = ArtifactStatus.EXPIRED
            row.expired_at = now
        await session.flush()
        return [self._build(row) for row in rows]

    async def list_expired_pending_blob_deletion(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[Artifact]:
        """List expired Artifacts whose blob deletion has not been recorded."""
        rows = (
            await session.scalars(
                sa.select(RDBArtifact)
                .where(
                    RDBArtifact.status == ArtifactStatus.EXPIRED,
                    RDBArtifact.blob_deleted_at.is_(None),
                )
                .order_by(RDBArtifact.expired_at, RDBArtifact.id)
                .limit(limit)
            )
        ).all()
        return [self._build(row) for row in rows]

    async def mark_blob_deleted(
        self,
        session: AsyncSession,
        *,
        artifact_id: str,
        blob_deleted_at: datetime.datetime,
    ) -> None:
        """Record Artifact blob deletion success."""
        await session.execute(
            sa.update(RDBArtifact)
            .where(RDBArtifact.id == artifact_id)
            .values(blob_deleted_at=blob_deleted_at)
        )
        await session.flush()

    def _build(self, rdb: RDBArtifact) -> Artifact:
        """Convert RDB model to domain model."""
        return Artifact(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            session_id=rdb.session_id,
            agent_id=rdb.agent_id,
            created_run_id=rdb.created_run_id,
            created_run_index=rdb.created_run_index,
            expires_at=rdb.expires_at,
            name=rdb.name,
            media_type=rdb.media_type,
            size_bytes=rdb.size_bytes,
            storage_key=rdb.storage_key,
            status=rdb.status,
            sha256=rdb.sha256,
            source_tool_name=rdb.source_tool_name,
            source_call_id=rdb.source_call_id,
            source_part_index=rdb.source_part_index,
            description=rdb.description,
            metadata=rdb.metadata_,
            created_at=rdb.created_at,
            expired_at=rdb.expired_at,
            blob_deleted_at=rdb.blob_deleted_at,
        )
