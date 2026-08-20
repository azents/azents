"""Scheduler-owned User Session owner lifecycle coordinator."""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import logging
from collections.abc import Sequence
from typing import Annotated, AsyncContextManager, Protocol

from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.deps import get_broker
from azents.broker.types import SessionStopSignal
from azents.core.enums import (
    AgentSessionProductMode,
    AgentSessionRunState,
    AgentSessionStatus,
    OwnerLifecycleKind,
    OwnerLifecycleStatus,
)
from azents.core.session_lifecycle import (
    SessionLifecycleParticipantDefinition,
    SessionLifecycleTransitionContext,
)
from azents.rdb.deps import get_session_manager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session.repository import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.chat_write_request import ChatWriteRequestRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.memory import MemoryRepository
from azents.repos.owner_lifecycle import OwnerLifecycleRepository
from azents.repos.owner_lifecycle.data import OwnerLifecycleJob
from azents.repos.scheduled_task.lifecycle import ScheduledTaskLifecycleCleanup
from azents.repos.user import UserRepository
from azents.services.external_channel.lifecycle import ExternalChannelLifecycleService
from azents.services.scheduled_task.lifecycle import ScheduledTaskLifecycleService
from azents.services.session_lifecycle.registry import (
    get_session_lifecycle_orchestrator,
)

_LEASE_DURATION = datetime.timedelta(minutes=15)
_MAX_RETRY_DELAY = datetime.timedelta(minutes=30)
_JOB_LIMIT = 100
_DEADLINE_SAFETY_MARGIN = datetime.timedelta(seconds=30)

logger = logging.getLogger(__name__)


class OwnerLifecycleSessionManager(Protocol):
    """Open a caller-owned database transaction for owner lifecycle work."""

    def __call__(self) -> AsyncContextManager[AsyncSession]:
        """Return one asynchronous database-session context."""
        ...


class OwnerLifecycleRootSession(Protocol):
    """Read-only root Session state consumed during owner lifecycle."""

    @property
    def id(self) -> str:
        """Return the Session ID."""
        ...

    @property
    def status(self) -> AgentSessionStatus:
        """Return the durable Session lifecycle status."""
        ...

    @property
    def run_state(self) -> AgentSessionRunState:
        """Return the current Session execution state."""
        ...

    @property
    def product_mode(self) -> AgentSessionProductMode | None:
        """Return the root product mode."""
        ...

    @property
    def archived_at(self) -> datetime.datetime | None:
        """Return the archive boundary timestamp when already archived."""
        ...


class OwnerLifecycleRepositoryProtocol(Protocol):
    """Persistence operations consumed by the owner-lifecycle coordinator."""

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> OwnerLifecycleJob | None:
        """Claim one due durable owner-lifecycle job."""
        ...

    async def set_status(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        status: OwnerLifecycleStatus,
        now: datetime.datetime,
    ) -> bool:
        """Persist one owned lifecycle status."""
        ...

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
        """Persist bounded retry state for an owned job."""
        ...

    async def mark_completed(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        now: datetime.datetime,
    ) -> bool:
        """Mark an owned job completed."""
        ...


class OwnerLifecycleAgentSessionRepositoryProtocol(Protocol):
    """Session-tree operations consumed by owner lifecycle."""

    async def list_active_user_roots_by_workspace_and_user(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        associated_user_id: str,
    ) -> Sequence[OwnerLifecycleRootSession]:
        """List active User roots for one membership-loss archive scope."""
        ...

    async def list_user_roots_by_user(
        self,
        session: AsyncSession,
        *,
        associated_user_id: str,
    ) -> Sequence[OwnerLifecycleRootSession]:
        """List all User roots owned by one User across workspaces."""
        ...

    async def has_any_for_associated_user(
        self,
        session: AsyncSession,
        *,
        associated_user_id: str,
    ) -> bool:
        """Return whether any associated User Session rows remain."""
        ...

    async def lock_root_tree_sessions(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
    ) -> Sequence[OwnerLifecycleRootSession]:
        """Lock one root tree for retirement."""
        ...

    async def request_stop(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        stop_request_id: str,
        stop_requester_user_id: str | None,
    ) -> object | None:
        """Record a best-effort stop request for one Session."""
        ...

    async def archive_tree(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
        session_ids: Sequence[str],
        archived_at: datetime.datetime,
        purge_after: datetime.datetime | None,
        policy_revision: int,
        retention_days: int | None,
    ) -> None:
        """Archive one locked root tree."""
        ...


class OwnerLifecycleRunRepositoryProtocol(Protocol):
    """Execution-state query consumed before root retirement."""

    async def has_active_for_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> bool:
        """Report whether any Session still has active execution."""
        ...


class OwnerLifecycleRetentionSettings(Protocol):
    """Read-only retention settings consumed while archiving a root tree."""

    @property
    def archived_session_retention_days(self) -> int | None:
        """Return the archive retention policy."""
        ...

    @property
    def revision(self) -> int:
        """Return the policy revision."""
        ...


class OwnerLifecycleRetentionRepositoryProtocol(Protocol):
    """Retention settings and purge scheduling consumed by owner lifecycle."""

    async def lock_settings(
        self,
        session: AsyncSession,
    ) -> OwnerLifecycleRetentionSettings:
        """Lock system retention settings."""
        ...

    async def schedule_purge_job(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
        eligible_at: datetime.datetime,
        policy_revision: int,
        now: datetime.datetime,
    ) -> None:
        """Schedule archived-session purge work."""
        ...


class OwnerLifecycleOrchestratorProtocol(Protocol):
    """Shared Session lifecycle archive orchestrator."""

    async def archive(
        self,
        *,
        context: SessionLifecycleTransitionContext,
        participant_operation: object,
        transition: object,
    ) -> None:
        """Run the archive transition under participant orchestration."""
        ...


class OwnerLifecycleExternalChannelLifecycleProtocol(Protocol):
    """External Channel lifecycle operations consumed during archive."""

    async def archive_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecycleTransitionContext,
    ) -> object | None:
        """Apply External Channel archive participant work."""
        ...

    async def consume_archive_cleanup(self, plans: object) -> None:
        """Consume post-commit archive cleanup plans."""
        ...


class OwnerLifecycleScheduledTaskLifecycleProtocol(Protocol):
    """Scheduled Task lifecycle operations consumed during archive."""

    async def archive_allows_active_runs(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
        running_session_ids: Sequence[str],
    ) -> bool:
        """Return whether every active execution is a preserved Scheduled cycle."""
        ...

    async def archive_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecycleTransitionContext,
    ) -> ScheduledTaskLifecycleCleanup | None:
        """Apply Scheduled Task archive participant work."""
        ...


class OwnerLifecycleBrokerProtocol(Protocol):
    """Broker used to deliver stop signals after durable stop requests."""

    async def send_message(self, signal: SessionStopSignal) -> None:
        """Send one stop signal."""
        ...


class OwnerLifecycleMemoryRepositoryProtocol(Protocol):
    """User-scope Memory deletion consumed during account finalization."""

    async def delete_all_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: str,
    ) -> int:
        """Delete every User-scope Memory row for one User."""
        ...


class OwnerLifecycleUserRepositoryProtocol(Protocol):
    """User deletion consumed during account finalization."""

    async def delete(self, session: AsyncSession, user_id: str) -> None:
        """Delete one User row."""
        ...


class OwnerLifecycleChatWriteRequestRepositoryProtocol(Protocol):
    """Chat write request cleanup consumed during account finalization."""

    async def delete_by_requester_user_id(
        self,
        session: AsyncSession,
        *,
        requester_user_id: str,
    ) -> int:
        """Delete retained idempotency rows for one User."""
        ...


class OwnerLifecycleMailboxRepositoryProtocol(Protocol):
    """Mailbox cleanup consumed during account finalization."""

    async def detach_sender_user_id(
        self,
        session: AsyncSession,
        *,
        sender_user_id: str,
    ) -> int:
        """Detach one User from retained MailboxItem rows."""
        ...


class OwnerLifecycleExchangeFileRepositoryProtocol(Protocol):
    """ExchangeFile cleanup consumed during account finalization."""

    async def detach_source_user_id(
        self,
        session: AsyncSession,
        *,
        source_user_id: str,
    ) -> int:
        """Detach one User from retained ExchangeFile provenance."""
        ...


class OwnerLifecycleExternalChannelRepositoryProtocol(Protocol):
    """External Channel cleanup consumed during account finalization."""

    async def detach_user_references(
        self,
        session: AsyncSession,
        *,
        user_id: str,
    ) -> None:
        """Detach or remove retained rows referencing one User."""
        ...


@dataclasses.dataclass(frozen=True)
class OwnerLifecycleSummary:
    """Result of one scheduler owner-lifecycle pass."""

    claimed_count: int
    completed_count: int
    retry_scheduled_count: int
    waiting_purge_count: int
    deadline_reached: bool
    limit_reached: bool


@dataclasses.dataclass
class OwnerLifecycleService:
    """Archive/purge User Sessions for membership loss and account deletion."""

    session_manager: Annotated[
        OwnerLifecycleSessionManager, Depends(get_session_manager)
    ]
    owner_lifecycle_repository: Annotated[
        OwnerLifecycleRepositoryProtocol, Depends(OwnerLifecycleRepository)
    ]
    agent_session_repository: Annotated[
        OwnerLifecycleAgentSessionRepositoryProtocol,
        Depends(AgentSessionRepository),
    ]
    agent_run_repository: Annotated[
        OwnerLifecycleRunRepositoryProtocol, Depends(AgentRunRepository)
    ]
    retention_repository: Annotated[
        OwnerLifecycleRetentionRepositoryProtocol,
        Depends(ArchivedSessionRetentionRepository),
    ]
    memory_repository: Annotated[
        OwnerLifecycleMemoryRepositoryProtocol, Depends(MemoryRepository)
    ]
    user_repository: Annotated[
        OwnerLifecycleUserRepositoryProtocol, Depends(UserRepository)
    ]
    chat_write_request_repository: Annotated[
        OwnerLifecycleChatWriteRequestRepositoryProtocol,
        Depends(ChatWriteRequestRepository),
    ]
    mailbox_repository: Annotated[
        OwnerLifecycleMailboxRepositoryProtocol,
        Depends(MailboxRepository),
    ]
    exchange_file_repository: Annotated[
        OwnerLifecycleExchangeFileRepositoryProtocol,
        Depends(ExchangeFileRepository),
    ]
    external_channel_repository: Annotated[
        OwnerLifecycleExternalChannelRepositoryProtocol,
        Depends(ExternalChannelRepository.create),
    ]
    lifecycle_orchestrator: Annotated[
        OwnerLifecycleOrchestratorProtocol,
        Depends(get_session_lifecycle_orchestrator),
    ]
    external_channel_lifecycle_service: Annotated[
        OwnerLifecycleExternalChannelLifecycleProtocol,
        Depends(ExternalChannelLifecycleService),
    ]
    scheduled_task_lifecycle_service: Annotated[
        OwnerLifecycleScheduledTaskLifecycleProtocol,
        Depends(ScheduledTaskLifecycleService),
    ]
    broker: Annotated[OwnerLifecycleBrokerProtocol, Depends(get_broker)]

    async def process_once(
        self,
        *,
        lease_owner: str,
        deadline: datetime.datetime,
    ) -> OwnerLifecycleSummary:
        """Claim and advance a bounded set of owner-lifecycle jobs."""
        claimed_count = 0
        completed_count = 0
        retry_scheduled_count = 0
        waiting_purge_count = 0
        deadline_reached = False

        for _ in range(_JOB_LIMIT):
            now = datetime.datetime.now(datetime.UTC)
            if now + _DEADLINE_SAFETY_MARGIN >= deadline:
                deadline_reached = True
                break
            async with self.session_manager() as session:
                job = await self.owner_lifecycle_repository.claim_due(
                    session,
                    now=now,
                    lease_owner=lease_owner,
                    lease_until=now + _LEASE_DURATION,
                )
            if job is None:
                break
            claimed_count += 1

            try:
                completed, waiting_purge = await self._advance(
                    job=job,
                    lease_owner=lease_owner,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._retry(
                    job=job,
                    lease_owner=lease_owner,
                    error_kind=type(exc).__name__,
                    error_summary=str(exc) or type(exc).__name__,
                )
                retry_scheduled_count += 1
                logger.exception(
                    "Owner lifecycle job failed; retry scheduled",
                    extra={
                        "owner_lifecycle_job_id": job.id,
                        "owner_lifecycle_kind": job.kind.value,
                        "target_user_id": job.user_id,
                        "workspace_id": job.workspace_id,
                        "attempt_count": job.attempt_count,
                    },
                )
                continue

            completed_count += int(completed)
            waiting_purge_count += int(waiting_purge)

        return OwnerLifecycleSummary(
            claimed_count=claimed_count,
            completed_count=completed_count,
            retry_scheduled_count=retry_scheduled_count,
            waiting_purge_count=waiting_purge_count,
            deadline_reached=deadline_reached,
            limit_reached=claimed_count == _JOB_LIMIT,
        )

    async def _advance(
        self,
        *,
        job: OwnerLifecycleJob,
        lease_owner: str,
    ) -> tuple[bool, bool]:
        """Advance one owned owner-lifecycle job."""
        if job.kind is OwnerLifecycleKind.MEMBERSHIP_ARCHIVE:
            return await self._advance_membership_archive(
                job=job,
                lease_owner=lease_owner,
            )
        if job.kind is OwnerLifecycleKind.ACCOUNT_PURGE:
            return await self._advance_account_purge(
                job=job,
                lease_owner=lease_owner,
            )
        raise RuntimeError(f"Unsupported owner lifecycle kind: {job.kind}")

    async def _advance_membership_archive(
        self,
        *,
        job: OwnerLifecycleJob,
        lease_owner: str,
    ) -> tuple[bool, bool]:
        """Archive active User roots after membership loss."""
        if job.workspace_id is None:
            raise RuntimeError("Membership archive job is missing workspace_id")

        async with self.session_manager() as session:
            session_repo = self.agent_session_repository
            roots = await session_repo.list_active_user_roots_by_workspace_and_user(
                session,
                workspace_id=job.workspace_id,
                associated_user_id=job.user_id,
            )

        if roots:
            await self._set_status(
                job_id=job.id,
                lease_owner=lease_owner,
                status=OwnerLifecycleStatus.RETIRING_SESSIONS,
            )
            waiting_for_active_run = False
            for root in roots:
                if root.product_mode is not AgentSessionProductMode.USER:
                    raise RuntimeError("Owner lifecycle saw a non-User root")
                retired = await self._retire_root_tree(
                    job=job,
                    lease_owner=lease_owner,
                    root_session_id=root.id,
                    immediate_purge=False,
                )
                waiting_for_active_run = waiting_for_active_run or not retired
            if waiting_for_active_run:
                raise RuntimeError("User Session root tree still has active work")

        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            completed = await self.owner_lifecycle_repository.mark_completed(
                session,
                job_id=job.id,
                lease_owner=lease_owner,
                now=now,
            )
        if not completed:
            raise RuntimeError("Owner lifecycle lease was lost before completion")
        return True, False

    async def _advance_account_purge(
        self,
        *,
        job: OwnerLifecycleJob,
        lease_owner: str,
    ) -> tuple[bool, bool]:
        """Purge all User Sessions and finalize account deletion."""
        async with self.session_manager() as session:
            roots = await self.agent_session_repository.list_user_roots_by_user(
                session,
                associated_user_id=job.user_id,
            )

        if roots:
            await self._set_status(
                job_id=job.id,
                lease_owner=lease_owner,
                status=OwnerLifecycleStatus.RETIRING_SESSIONS,
            )
            waiting_for_active_run = False
            for root in roots:
                if root.product_mode is not AgentSessionProductMode.USER:
                    raise RuntimeError("Owner lifecycle saw a non-User root")
                retired = await self._retire_root_tree(
                    job=job,
                    lease_owner=lease_owner,
                    root_session_id=root.id,
                    immediate_purge=True,
                )
                waiting_for_active_run = waiting_for_active_run or not retired
            if waiting_for_active_run:
                raise RuntimeError("User Session root tree still has active work")

        async with self.session_manager() as session:
            remaining = await self.agent_session_repository.has_any_for_associated_user(
                session,
                associated_user_id=job.user_id,
            )
        if remaining:
            await self._set_status(
                job_id=job.id,
                lease_owner=lease_owner,
                status=OwnerLifecycleStatus.WAITING_PURGE,
            )
            # Requeue soon so archived purge progress is observed.
            await self._retry(
                job=job,
                lease_owner=lease_owner,
                error_kind="WaitingPurge",
                error_summary="Owned User Session rows remain pending purge",
                delay=datetime.timedelta(minutes=1),
            )
            return False, True

        await self._set_status(
            job_id=job.id,
            lease_owner=lease_owner,
            status=OwnerLifecycleStatus.FINALIZING,
        )
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            completed = await self.owner_lifecycle_repository.mark_completed(
                session,
                job_id=job.id,
                lease_owner=lease_owner,
                now=now,
            )
            if not completed:
                raise RuntimeError("Owner lifecycle lease was lost before finalization")
            await self._detach_retained_user_references(
                session,
                user_id=job.user_id,
            )
            await self.memory_repository.delete_all_for_user(
                session,
                user_id=job.user_id,
            )
            await self.user_repository.delete(session, job.user_id)
        logger.info(
            "Owner lifecycle account purge finalized User deletion",
            extra={
                "owner_lifecycle_job_id": job.id,
                "target_user_id": job.user_id,
            },
        )
        return True, False

    async def _retire_root_tree(
        self,
        *,
        job: OwnerLifecycleJob,
        lease_owner: str,
        root_session_id: str,
        immediate_purge: bool,
    ) -> bool:
        """Stop and archive one User root tree through the shared lifecycle registry."""
        stop_session_ids: list[str] = []
        active = False
        archived = False
        archive_cleanup_plans = ()
        async with self.session_manager() as session:
            tree = await self.agent_session_repository.lock_root_tree_sessions(
                session,
                root_session_id=root_session_id,
            )
            if not tree:
                return True
            if any(item.status is not AgentSessionStatus.ACTIVE for item in tree):
                if immediate_purge and all(
                    item.status is AgentSessionStatus.ARCHIVED for item in tree
                ):
                    # Account purge must not wait on prior retention schedules.
                    archived_at = datetime.datetime.now(datetime.UTC)
                    settings = await self.retention_repository.lock_settings(session)
                    await self.agent_session_repository.archive_tree(
                        session,
                        root_session_id=root_session_id,
                        session_ids=[item.id for item in tree],
                        archived_at=tree[0].archived_at or archived_at,
                        purge_after=archived_at,
                        policy_revision=settings.revision,
                        retention_days=0,
                    )
                    await self.retention_repository.schedule_purge_job(
                        session,
                        root_session_id=root_session_id,
                        eligible_at=archived_at,
                        policy_revision=settings.revision,
                        now=archived_at,
                    )
                    owned = await self.owner_lifecycle_repository.set_status(
                        session,
                        job_id=job.id,
                        lease_owner=lease_owner,
                        status=OwnerLifecycleStatus.WAITING_PURGE,
                        now=archived_at,
                    )
                    if not owned:
                        raise RuntimeError("Owner lifecycle lease was lost")
                    await session.commit()
                    return True
                # Transitional states; let the next pass observe progress.
                return True
            session_ids = [item.id for item in tree]
            active = any(
                item.run_state is AgentSessionRunState.RUNNING for item in tree
            ) or await self.agent_run_repository.has_active_for_session_ids(
                session,
                session_ids=session_ids,
            )
            scheduled_lifecycle = self.scheduled_task_lifecycle_service
            preserve_scheduled = (
                active
                and await scheduled_lifecycle.archive_allows_active_runs(
                    session,
                    session_ids=session_ids,
                    running_session_ids=[
                        item.id
                        for item in tree
                        if item.run_state is AgentSessionRunState.RUNNING
                    ],
                )
            )
            if not preserve_scheduled:
                for session_id in session_ids:
                    await self.agent_session_repository.request_stop(
                        session,
                        session_id=session_id,
                        stop_request_id=uuid7().hex,
                        stop_requester_user_id=None,
                    )
                stop_session_ids = session_ids

            if not active or preserve_scheduled:
                settings = await self.retention_repository.lock_settings(session)
                archived_at = datetime.datetime.now(datetime.UTC)
                if immediate_purge:
                    purge_after = archived_at
                    retention_days = 0
                elif settings.archived_session_retention_days is None:
                    purge_after = None
                    retention_days = None
                else:
                    purge_after = archived_at + datetime.timedelta(
                        days=settings.archived_session_retention_days
                    )
                    retention_days = settings.archived_session_retention_days

                async def archive_tree() -> None:
                    """Archive a system-owned User root tree."""
                    await self.agent_session_repository.archive_tree(
                        session,
                        root_session_id=root_session_id,
                        session_ids=session_ids,
                        archived_at=archived_at,
                        purge_after=purge_after,
                        policy_revision=settings.revision,
                        retention_days=retention_days,
                    )

                async def archive_participant(
                    definition: SessionLifecycleParticipantDefinition,
                    context: SessionLifecycleTransitionContext,
                ) -> None:
                    """Apply lifecycle-owned state before archiving the root tree."""
                    nonlocal archive_cleanup_plans
                    scheduled_result = (
                        await self.scheduled_task_lifecycle_service.archive_participant(
                            session,
                            definition,
                            context,
                        )
                    )
                    if scheduled_result is not None:
                        archive_cleanup_plans += scheduled_result.cleanup_plans
                    external_result = await (
                        self.external_channel_lifecycle_service.archive_participant(
                            session,
                            definition,
                            context,
                        )
                    )
                    if external_result is not None:
                        archive_cleanup_plans += getattr(
                            external_result,
                            "cleanup_plans",
                            (),
                        )

                await self.lifecycle_orchestrator.archive(
                    context=SessionLifecycleTransitionContext(
                        transition_id=f"{job.id}:{root_session_id}:owner-lifecycle",
                        root_session_id=root_session_id,
                        subtree_session_ids=tuple(session_ids),
                    ),
                    participant_operation=archive_participant,
                    transition=archive_tree,
                )
                if purge_after is not None:
                    await self.retention_repository.schedule_purge_job(
                        session,
                        root_session_id=root_session_id,
                        eligible_at=purge_after,
                        policy_revision=settings.revision,
                        now=archived_at,
                    )
                owned = await self.owner_lifecycle_repository.set_status(
                    session,
                    job_id=job.id,
                    lease_owner=lease_owner,
                    status=OwnerLifecycleStatus.RETIRING_SESSIONS,
                    now=archived_at,
                )
                if not owned:
                    raise RuntimeError("Owner lifecycle lease was lost")
                await session.commit()
                archived = True

        if archived:
            await self.external_channel_lifecycle_service.consume_archive_cleanup(
                archive_cleanup_plans
            )
        for session_id in stop_session_ids:
            await self.broker.send_message(SessionStopSignal(session_id=session_id))
        return archived

    async def _detach_retained_user_references(
        self,
        session: AsyncSession,
        *,
        user_id: str,
    ) -> None:
        """Clear retained Team-side foreign keys that would block User deletion.

        Account purge keeps Team Sessions and shared artifacts. Those rows may still
        reference the deleted User through RESTRICT foreign keys, so detach them
        before the final User row delete.
        """
        await self.chat_write_request_repository.delete_by_requester_user_id(
            session,
            requester_user_id=user_id,
        )
        await self.mailbox_repository.detach_sender_user_id(
            session,
            sender_user_id=user_id,
        )
        await self.exchange_file_repository.detach_source_user_id(
            session,
            source_user_id=user_id,
        )
        await self.external_channel_repository.detach_user_references(
            session,
            user_id=user_id,
        )

    async def _set_status(
        self,
        *,
        job_id: str,
        lease_owner: str,
        status: OwnerLifecycleStatus,
    ) -> None:
        """Persist one owned status transition."""
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            owned = await self.owner_lifecycle_repository.set_status(
                session,
                job_id=job_id,
                lease_owner=lease_owner,
                status=status,
                now=now,
            )
        if not owned:
            raise RuntimeError("Owner lifecycle lease was lost")

    async def _retry(
        self,
        *,
        job: OwnerLifecycleJob,
        lease_owner: str,
        error_kind: str,
        error_summary: str,
        delay: datetime.timedelta | None = None,
    ) -> None:
        """Release one owned job into retry wait."""
        now = datetime.datetime.now(datetime.UTC)
        if delay is None:
            # Exponential-ish backoff capped for ordinary failures.
            attempt = max(job.attempt_count, 1)
            seconds = min(
                30 * (2 ** min(attempt - 1, 6)), int(_MAX_RETRY_DELAY.total_seconds())
            )
            delay = datetime.timedelta(seconds=seconds)
        async with self.session_manager() as session:
            await self.owner_lifecycle_repository.mark_retry(
                session,
                job_id=job.id,
                lease_owner=lease_owner,
                next_attempt_at=now + delay,
                error_kind=error_kind,
                error_summary=error_summary,
                now=now,
            )
