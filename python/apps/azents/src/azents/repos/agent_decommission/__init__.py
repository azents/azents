"""Agent decommission repository."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentDecommissionStatus
from azents.rdb.models.agent_decommission import RDBAgentDecommissionJob

from .data import AgentDecommissionJob


class AgentDecommissionRepository:
    """Repository for durable Agent decommission work."""

    async def create_or_get(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        workspace_id: str,
        requested_by_workspace_user_id: str,
    ) -> AgentDecommissionJob:
        """Create one decommission job or return its durable existing job."""
        result = await session.execute(
            insert(RDBAgentDecommissionJob)
            .values(
                id=uuid7().hex,
                agent_id=agent_id,
                workspace_id=workspace_id,
                requested_by_workspace_user_id=requested_by_workspace_user_id,
            )
            .on_conflict_do_nothing(index_elements=["agent_id"])
            .returning(RDBAgentDecommissionJob)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            rdb = await session.scalar(
                sa.select(RDBAgentDecommissionJob).where(
                    RDBAgentDecommissionJob.agent_id == agent_id
                )
            )
        if rdb is None:
            raise RuntimeError("Agent decommission job creation failed")
        await session.flush()
        return self._build(rdb)

    async def get_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> AgentDecommissionJob | None:
        """Fetch one durable decommission job by Agent ID."""
        rdb = await session.scalar(
            sa.select(RDBAgentDecommissionJob).where(
                RDBAgentDecommissionJob.agent_id == agent_id
            )
        )
        if rdb is None:
            return None
        return self._build(rdb)

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> AgentDecommissionJob | None:
        """Claim one due decommission job with an expired-or-empty lease."""
        claimable_status = sa.or_(
            RDBAgentDecommissionJob.status.in_(
                (
                    AgentDecommissionStatus.PENDING,
                    AgentDecommissionStatus.RETRY_WAIT,
                )
            ),
            sa.and_(
                RDBAgentDecommissionJob.status.in_(
                    (
                        AgentDecommissionStatus.RETIRING_SESSIONS,
                        AgentDecommissionStatus.WAITING_RETENTION,
                        AgentDecommissionStatus.FINALIZING,
                    )
                ),
                RDBAgentDecommissionJob.lease_until < now,
            ),
        )
        candidate = (
            sa.select(RDBAgentDecommissionJob.id)
            .where(
                claimable_status,
                sa.or_(
                    RDBAgentDecommissionJob.next_attempt_at.is_(None),
                    RDBAgentDecommissionJob.next_attempt_at <= now,
                ),
                sa.or_(
                    RDBAgentDecommissionJob.lease_until.is_(None),
                    RDBAgentDecommissionJob.lease_until < now,
                ),
            )
            .order_by(
                RDBAgentDecommissionJob.created_at,
                RDBAgentDecommissionJob.id,
            )
            .with_for_update(skip_locked=True)
            .limit(1)
            .scalar_subquery()
        )
        result = await session.execute(
            sa.update(RDBAgentDecommissionJob)
            .where(RDBAgentDecommissionJob.id == candidate)
            .values(
                status=sa.case(
                    (
                        RDBAgentDecommissionJob.status.in_(
                            (
                                AgentDecommissionStatus.PENDING,
                                AgentDecommissionStatus.RETRY_WAIT,
                            )
                        ),
                        AgentDecommissionStatus.RETIRING_SESSIONS,
                    ),
                    else_=RDBAgentDecommissionJob.status,
                ),
                started_at=sa.func.coalesce(
                    RDBAgentDecommissionJob.started_at,
                    now,
                ),
                attempt_count=RDBAgentDecommissionJob.attempt_count + 1,
                lease_owner=lease_owner,
                lease_until=lease_until,
                next_attempt_at=None,
                last_error_kind=None,
                last_error_summary=None,
                updated_at=now,
            )
            .returning(RDBAgentDecommissionJob)
        )
        rdb = result.scalar_one_or_none()
        return None if rdb is None else self._build(rdb)

    async def set_status(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        status: AgentDecommissionStatus,
        now: datetime.datetime,
    ) -> bool:
        """Advance an owned job to its current coordinator phase."""
        result = await session.execute(
            sa.update(RDBAgentDecommissionJob)
            .where(
                RDBAgentDecommissionJob.id == job_id,
                RDBAgentDecommissionJob.lease_owner == lease_owner,
            )
            .values(
                status=status,
                updated_at=now,
            )
            .returning(RDBAgentDecommissionJob.id)
        )
        return result.scalar_one_or_none() is not None

    async def mark_retry(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        next_attempt_at: datetime.datetime,
        error_kind: str,
        error_summary: str,
        now: datetime.datetime,
    ) -> bool:
        """Release an owned job into bounded retry wait."""
        result = await session.execute(
            sa.update(RDBAgentDecommissionJob)
            .where(
                RDBAgentDecommissionJob.id == job_id,
                RDBAgentDecommissionJob.lease_owner == lease_owner,
            )
            .values(
                status=AgentDecommissionStatus.RETRY_WAIT,
                lease_owner=None,
                lease_until=None,
                next_attempt_at=next_attempt_at,
                last_error_kind=error_kind[:120],
                last_error_summary=error_summary[:500],
                updated_at=now,
            )
            .returning(RDBAgentDecommissionJob.id)
        )
        return result.scalar_one_or_none() is not None

    def _build(self, rdb: RDBAgentDecommissionJob) -> AgentDecommissionJob:
        """Convert a database row to a domain model."""
        return AgentDecommissionJob(
            id=rdb.id,
            agent_id=rdb.agent_id,
            workspace_id=rdb.workspace_id,
            requested_by_workspace_user_id=rdb.requested_by_workspace_user_id,
            status=rdb.status,
            attempt_count=rdb.attempt_count,
            lease_owner=rdb.lease_owner,
            lease_until=rdb.lease_until,
            next_attempt_at=rdb.next_attempt_at,
            last_error_kind=rdb.last_error_kind,
            last_error_summary=rdb.last_error_summary,
            started_at=rdb.started_at,
            completed_at=rdb.completed_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
