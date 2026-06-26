"""Artifact repository."""

import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ArtifactStatus
from azents.rdb.models.artifact import RDBArtifact

from .data import Artifact, ArtifactCreate


def _storage_key(rdb: RDBArtifact) -> str:
    """Create Artifact object storage key."""
    return (
        f"artifacts/{rdb.workspace_id}/{rdb.session_id}/"
        f"{rdb.created_run_index}/{rdb.id}"
    )


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
            expires_after_run_index=create.expires_after_run_index,
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
        rdb.storage_key = _storage_key(rdb)
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

    async def expire_for_run_boundary(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        current_run_index: int,
        expired_at: datetime.datetime,
    ) -> list[Artifact]:
        """Mark Artifacts expired when they expire by run boundary."""
        rows = (
            await session.scalars(
                sa.select(RDBArtifact).where(
                    RDBArtifact.session_id == session_id,
                    RDBArtifact.status == ArtifactStatus.AVAILABLE,
                    RDBArtifact.expires_after_run_index < current_run_index,
                )
            )
        ).all()
        for row in rows:
            row.status = ArtifactStatus.EXPIRED
            row.expired_at = expired_at
        await session.flush()
        return [self._build(row) for row in rows]

    async def list_candidate_session_ids(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[str]:
        """Return Artifact sessions with available lifecycle candidates."""
        rows = (
            await session.scalars(
                sa.select(RDBArtifact.session_id)
                .where(RDBArtifact.status == ArtifactStatus.AVAILABLE)
                .group_by(RDBArtifact.session_id)
                .order_by(sa.func.min(RDBArtifact.expires_after_run_index))
                .limit(limit)
            )
        ).all()
        return list(rows)

    async def expire_due_by_latest_run_index(
        self,
        session: AsyncSession,
        *,
        latest_run_indexes: dict[str, int],
        expired_at: datetime.datetime,
        limit: int,
    ) -> list[Artifact]:
        """Expire available Artifacts using per-session latest run indexes."""
        due_by_session = [
            sa.and_(
                RDBArtifact.session_id == session_id,
                RDBArtifact.expires_after_run_index < latest_run_index,
            )
            for session_id, latest_run_index in latest_run_indexes.items()
        ]
        if not due_by_session:
            return []
        rows = (
            await session.scalars(
                sa.select(RDBArtifact)
                .where(
                    RDBArtifact.status == ArtifactStatus.AVAILABLE,
                    sa.or_(*due_by_session),
                )
                .order_by(RDBArtifact.created_run_index, RDBArtifact.id)
                .limit(limit)
            )
        ).all()
        for row in rows:
            row.status = ArtifactStatus.EXPIRED
            row.expired_at = expired_at
        expired_rows = list(rows)
        await session.flush()
        return [self._build(row) for row in expired_rows]

    async def list_expired_with_blob(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[Artifact]:
        """Fetch expired Artifacts whose blobs still need deletion."""
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
    ) -> None:
        """Record successful Artifact blob deletion."""
        row = await session.get(RDBArtifact, artifact_id)
        if row is None or row.blob_deleted_at is not None:
            return
        row.blob_deleted_at = datetime.datetime.now(datetime.UTC)
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
            expires_after_run_index=rdb.expires_after_run_index,
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
