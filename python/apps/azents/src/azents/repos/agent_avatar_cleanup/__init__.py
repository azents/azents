"""Repository for durable superseded Agent avatar cleanup."""

import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.agent_avatar_cleanup import RDBAgentAvatarCleanupJob
from azents.services.uploads.schema import StoredImage

from .data import AgentAvatarCleanupJob


class AgentAvatarCleanupRepository:
    """Claim and settle superseded Agent avatar cleanup jobs."""

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        lease_token: str,
        lease_until: datetime.datetime,
        limit: int,
    ) -> list[AgentAvatarCleanupJob]:
        """Claim a bounded page of due cleanup jobs."""
        candidates = (
            sa.select(RDBAgentAvatarCleanupJob.id)
            .where(
                RDBAgentAvatarCleanupJob.next_attempt_at.is_not(None),
                RDBAgentAvatarCleanupJob.next_attempt_at <= now,
                sa.or_(
                    RDBAgentAvatarCleanupJob.lease_until.is_(None),
                    RDBAgentAvatarCleanupJob.lease_until < now,
                ),
            )
            .order_by(
                RDBAgentAvatarCleanupJob.next_attempt_at,
                RDBAgentAvatarCleanupJob.created_at,
                RDBAgentAvatarCleanupJob.id,
            )
            .with_for_update(skip_locked=True)
            .limit(limit)
            .cte("due_agent_avatar_cleanup_jobs")
        )
        result = await session.execute(
            sa.update(RDBAgentAvatarCleanupJob)
            .where(
                RDBAgentAvatarCleanupJob.id.in_(sa.select(candidates.c.id)),
            )
            .values(
                attempt_count=RDBAgentAvatarCleanupJob.attempt_count + 1,
                lease_token=lease_token,
                lease_until=lease_until,
                updated_at=now,
            )
            .returning(RDBAgentAvatarCleanupJob)
        )
        return [self._build(row) for row in result.scalars().all()]

    async def mark_retry(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_token: str,
        next_attempt_at: datetime.datetime,
        failure_kind: str,
        now: datetime.datetime,
    ) -> bool:
        """Release one token-owned job for bounded retry after a failed delete."""
        result = await session.execute(
            sa.update(RDBAgentAvatarCleanupJob)
            .where(
                RDBAgentAvatarCleanupJob.id == job_id,
                RDBAgentAvatarCleanupJob.lease_token == lease_token,
            )
            .values(
                next_attempt_at=next_attempt_at,
                lease_token=None,
                lease_until=None,
                last_failure_kind=failure_kind[:120],
                updated_at=now,
            )
            .returning(RDBAgentAvatarCleanupJob.id)
        )
        return result.scalar_one_or_none() is not None

    async def delete_completed(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_token: str,
    ) -> bool:
        """Delete one successfully handled, token-owned cleanup job."""
        result = await session.execute(
            sa.delete(RDBAgentAvatarCleanupJob)
            .where(
                RDBAgentAvatarCleanupJob.id == job_id,
                RDBAgentAvatarCleanupJob.lease_token == lease_token,
            )
            .returning(RDBAgentAvatarCleanupJob.id)
        )
        return result.scalar_one_or_none() is not None

    def _build(self, row: RDBAgentAvatarCleanupJob) -> AgentAvatarCleanupJob:
        """Convert one RDB row to its repository data model."""
        return AgentAvatarCleanupJob(
            id=row.id,
            agent_id=row.agent_id,
            avatar=StoredImage.model_validate(row.avatar),
            attempt_count=row.attempt_count,
            next_attempt_at=row.next_attempt_at,
            lease_token=row.lease_token,
            lease_until=row.lease_until,
            last_failure_kind=row.last_failure_kind,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
