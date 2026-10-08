"""Common Session lifecycle targets, independent of conversation membership."""

import dataclasses
import datetime
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.orm import lazyload

from azents.core.enums import (
    AgentSessionEndReason,
    AgentSessionRunState,
    AgentSessionStatus,
)
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository


@dataclasses.dataclass(frozen=True)
class LifecycleSession:
    """Detached common lifecycle participant without public conversation fields."""

    id: str
    status: AgentSessionStatus
    run_state: AgentSessionRunState
    owner_generation: int


@dataclasses.dataclass(frozen=True)
class ArchiveRetention:
    """Existing retention policy resolved for an archive transition."""

    archived_at: datetime.datetime
    purge_after: datetime.datetime | None
    policy_revision: int
    retention_days: int | None


class LifecycleTargetRepository:
    """Lock the common root gate and its exact associated Session group."""

    async def lock_target_sessions(
        self, session: WriteSession, *, root_session_id: str
    ) -> list[LifecycleSession]:
        """Lock one lifecycle root before enumerating and locking its members."""
        root = await session.write_session.scalar(
            sa.select(RDBAgentSession)
            .options(lazyload(RDBAgentSession.conversation))
            .where(
                RDBAgentSession.id == root_session_id,
                RDBAgentSession.lifecycle_root_session_id.is_(None),
            )
            .with_for_update(of=RDBAgentSession)
            .execution_options(populate_existing=True)
        )
        if root is None:
            return []
        rows = await session.write_session.scalars(
            sa.select(RDBAgentSession)
            .options(lazyload(RDBAgentSession.conversation))
            .where(
                sa.or_(
                    RDBAgentSession.id == root_session_id,
                    RDBAgentSession.lifecycle_root_session_id == root_session_id,
                )
            )
            .order_by(RDBAgentSession.id)
            .with_for_update(of=RDBAgentSession)
            .execution_options(populate_existing=True)
        )
        members = list(rows)
        if any(
            row.agent_id != root.agent_id or row.workspace_id != root.workspace_id
            for row in members
        ):
            raise ValueError("Session lifecycle target scope is inconsistent.")
        return [
            LifecycleSession(
                id=row.id,
                status=row.status,
                run_state=row.run_state,
                owner_generation=row.owner_generation,
            )
            for row in members
        ]

    async def fence_purge_owner_generations(
        self, session: WriteSession, *, session_ids: Sequence[str]
    ) -> int:
        """Fence every member before cleanup can issue external effects."""
        result = await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id.in_(session_ids))
            .values(owner_generation=RDBAgentSession.owner_generation + 1)
            .returning(RDBAgentSession.id)
        )
        return len(result.scalars().all())

    async def request_stop(
        self,
        session: WriteSession,
        *,
        session_id: str,
        stop_request_id: str,
        stop_requester_user_id: str | None,
    ) -> None:
        """Record a stop request without constructing a Conversation projection."""
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(
                RDBAgentSession.id == session_id,
                RDBAgentSession.run_state == AgentSessionRunState.RUNNING,
            )
            .values(
                stop_requested_at=sa.func.now(),
                stop_requester_user_id=stop_requester_user_id,
                stop_request_id=stop_request_id,
            )
        )

    async def resolve_retention(
        self,
        session: ReadSession,
        *,
        retention_repository: ArchivedSessionRetentionRepository,
        archived_at: datetime.datetime,
    ) -> ArchiveRetention:
        """Use the existing instance policy without a Session-kind override."""
        settings = await retention_repository.get_settings(session)
        days = settings.archived_session_retention_days
        return ArchiveRetention(
            archived_at=archived_at,
            purge_after=None
            if days is None
            else archived_at + datetime.timedelta(days=days),
            policy_revision=settings.revision,
            retention_days=days,
        )

    async def archive_status(
        self,
        session: WriteSession,
        *,
        root_session_id: str,
        session_ids: Sequence[str],
        retention: ArchiveRetention,
        end_reason: AgentSessionEndReason | None,
    ) -> None:
        """Archive an admitted group, preserving canonical records until purge."""
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id.in_(session_ids))
            .values(
                status=AgentSessionStatus.ARCHIVED,
                ended_at=retention.archived_at,
                end_reason=end_reason,
                run_state=AgentSessionRunState.IDLE,
            )
        )
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == root_session_id)
            .values(
                archived_at=retention.archived_at,
                purge_after=retention.purge_after,
                archive_policy_revision=retention.policy_revision,
                archive_retention_days_snapshot=retention.retention_days,
            )
        )
        await session.write_session.flush()

    async def schedule_archive_purge(
        self,
        session: WriteSession,
        *,
        root_session_id: str,
        retention_repository: ArchivedSessionRetentionRepository,
        retention: ArchiveRetention,
        scheduled_at: datetime.datetime,
    ) -> None:
        """Schedule the existing shared job only for finite archive retention."""
        if retention.purge_after is not None:
            await retention_repository.schedule_purge_job(
                session,
                root_session_id=root_session_id,
                eligible_at=retention.purge_after,
                policy_revision=retention.policy_revision,
                now=scheduled_at,
            )

    async def accelerate_account_purge(
        self,
        session: WriteSession,
        *,
        root_session_id: str,
        session_ids: Sequence[str],
        archived_at: datetime.datetime,
        now: datetime.datetime,
        retention_repository: ArchivedSessionRetentionRepository,
    ) -> None:
        """Preserve existing account-removal urgency within the common purge path."""
        policy = await self.resolve_retention(
            session,
            retention_repository=retention_repository,
            archived_at=archived_at,
        )
        immediate = dataclasses.replace(policy, purge_after=now, retention_days=0)
        await self.archive_status(
            session,
            root_session_id=root_session_id,
            session_ids=session_ids,
            retention=immediate,
            end_reason=None,
        )
        await self.schedule_archive_purge(
            session,
            root_session_id=root_session_id,
            retention_repository=retention_repository,
            retention=immediate,
            scheduled_at=now,
        )
