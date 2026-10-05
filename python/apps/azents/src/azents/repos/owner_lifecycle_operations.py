"""Completed database-only User owner lifecycle operations."""

import dataclasses
import datetime
from collections.abc import Sequence
from typing import Annotated, Protocol

import sqlalchemy as sa
from azcommon.uuid import uuid7
from fastapi import Depends

from azents.core.chat_operation_data import ChatArchiveMutation
from azents.core.enums import (
    AgentSessionProductMode,
    AgentSessionRunState,
    AgentSessionStatus,
    OwnerLifecycleStatus,
)
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.core.retirement_data import RetirementRoot, RootRetirement
from azents.core.session_lifecycle import SessionLifecycleTransitionContext
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_decommission_operations import RetirementLifecycleRepository
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.chat_write_request import ChatWriteRequestRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.hierarchy_contention import retry_hierarchy_operation
from azents.repos.mailbox import MailboxRepository
from azents.repos.memory import MemoryRepository
from azents.repos.owner_lifecycle import OwnerLifecycleRepository
from azents.repos.owner_lifecycle.data import OwnerLifecycleJob
from azents.repos.session_lifecycle_operations import (
    SessionLifecycleOperationsRepository,
)
from azents.repos.user import UserRepository


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
        session: WriteSession,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> OwnerLifecycleJob | None:
        """Claim one due durable owner-lifecycle job."""
        ...

    async def set_status(
        self,
        session: WriteSession,
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
        session: WriteSession,
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
        session: WriteSession,
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
        session: ReadSession,
        *,
        workspace_id: str,
        associated_user_id: str,
    ) -> Sequence[OwnerLifecycleRootSession]:
        """List active User roots for one membership-loss archive scope."""
        ...

    async def list_user_roots_by_user(
        self,
        session: ReadSession,
        *,
        associated_user_id: str,
    ) -> Sequence[OwnerLifecycleRootSession]:
        """List all User roots owned by one User across workspaces."""
        ...

    async def lock_root_tree_sessions(
        self,
        session: WriteSession,
        *,
        root_session_id: str,
    ) -> Sequence[OwnerLifecycleRootSession]:
        """Lock one root tree for retirement."""
        ...

    async def request_stop(
        self,
        session: WriteSession,
        *,
        session_id: str,
        stop_request_id: str,
        stop_requester_user_id: str | None,
    ) -> object | None:
        """Record a best-effort stop request for one Session."""
        ...

    async def archive_tree(
        self,
        session: WriteSession,
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
        session: ReadSession,
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

    async def get_settings(
        self,
        session: ReadSession,
    ) -> OwnerLifecycleRetentionSettings:
        """Read system retention settings."""
        ...

    async def schedule_purge_job(
        self,
        session: WriteSession,
        *,
        root_session_id: str,
        eligible_at: datetime.datetime,
        policy_revision: int,
        now: datetime.datetime,
    ) -> None:
        """Schedule archived-session purge work."""
        ...


class OwnerLifecycleMemoryRepositoryProtocol(Protocol):
    """User-scope Memory deletion consumed during account finalization."""

    async def delete_all_for_user(
        self,
        session: WriteSession,
        *,
        user_id: str,
    ) -> int:
        """Delete every User-scope Memory row for one User."""
        ...


class OwnerLifecycleUserRepositoryProtocol(Protocol):
    """User deletion consumed during account finalization."""

    async def delete(self, session: WriteSession, user_id: str) -> None:
        """Delete one User row."""
        ...


class OwnerLifecycleChatWriteRequestRepositoryProtocol(Protocol):
    """Chat write request cleanup consumed during account finalization."""

    async def delete_by_requester_user_id(
        self,
        session: WriteSession,
        *,
        requester_user_id: str,
    ) -> int:
        """Delete retained idempotency rows for one User."""
        ...


class OwnerLifecycleMailboxRepositoryProtocol(Protocol):
    """Mailbox cleanup consumed during account finalization."""

    async def detach_sender_user_id(
        self,
        session: WriteSession,
        *,
        sender_user_id: str,
    ) -> int:
        """Detach one User from retained MailboxItem rows."""
        ...


class OwnerLifecycleExchangeFileRepositoryProtocol(Protocol):
    """ExchangeFile cleanup consumed during account finalization."""

    async def detach_source_user_id(
        self,
        session: WriteSession,
        *,
        source_user_id: str,
    ) -> int:
        """Detach one User from retained ExchangeFile provenance."""
        ...


class OwnerLifecycleExternalChannelRepositoryProtocol(Protocol):
    """External Channel cleanup consumed during account finalization."""

    async def detach_user_references(
        self,
        session: WriteSession,
        *,
        user_id: str,
    ) -> None:
        """Detach or remove retained rows referencing one User."""
        ...


@dataclasses.dataclass
class OwnerLifecycleOperationsRepository:
    """Own atomic User retirement and final account cleanup database groups."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    owner_lifecycle_repository: Annotated[
        OwnerLifecycleRepositoryProtocol, Depends(OwnerLifecycleRepository)
    ]
    agent_session_repository: Annotated[
        OwnerLifecycleAgentSessionRepositoryProtocol, Depends(AgentSessionRepository)
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
        OwnerLifecycleMailboxRepositoryProtocol, Depends(MailboxRepository)
    ]
    exchange_file_repository: Annotated[
        OwnerLifecycleExchangeFileRepositoryProtocol, Depends(ExchangeFileRepository)
    ]
    external_channel_repository: Annotated[
        OwnerLifecycleExternalChannelRepositoryProtocol,
        Depends(ExternalChannelRepository.create),
    ]
    lifecycle_repository: Annotated[
        RetirementLifecycleRepository, Depends(SessionLifecycleOperationsRepository)
    ]

    async def claim_due(
        self,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> OwnerLifecycleJob | None:
        """Finish one durable claim before scheduler effects."""
        async with self.session_manager() as session:
            return await self.owner_lifecycle_repository.claim_due(
                session,
                now=now,
                lease_owner=lease_owner,
                lease_until=lease_until,
            )

    async def membership_roots(
        self, *, workspace_id: str, user_id: str
    ) -> tuple[RetirementRoot, ...]:
        """Complete User membership root descriptions in a native read-only scope."""
        async with self.read_session_manager() as session:
            repository = self.agent_session_repository
            roots = await repository.list_active_user_roots_by_workspace_and_user(
                session,
                workspace_id=workspace_id,
                associated_user_id=user_id,
            )
            return tuple(
                RetirementRoot(
                    id=root.id, status=root.status, product_mode=root.product_mode
                )
                for root in roots
            )

    async def account_roots(self, *, user_id: str) -> tuple[RetirementRoot, ...]:
        """Complete all private User root descriptions without mutation capability."""
        async with self.read_session_manager() as session:
            roots = await self.agent_session_repository.list_user_roots_by_user(
                session, associated_user_id=user_id
            )
            return tuple(
                RetirementRoot(
                    id=root.id, status=root.status, product_mode=root.product_mode
                )
                for root in roots
            )

    async def remaining_user_sessions(self, *, user_id: str) -> bool:
        """Complete the existing User Session absence observation."""
        async with self.read_session_manager() as session:
            return bool(
                await session.read_session.scalar(
                    sa.select(
                        sa.exists().where(RDBAgentSession.associated_user_id == user_id)
                    )
                )
            )

    async def complete_membership(self, *, job_id: str, lease_owner: str) -> bool:
        """Finish the owned membership job completion CAS."""
        async with self.session_manager() as session:
            return await self.owner_lifecycle_repository.mark_completed(
                session,
                job_id=job_id,
                lease_owner=lease_owner,
                now=datetime.datetime.now(datetime.UTC),
            )

    async def finalize_account(
        self, *, job: OwnerLifecycleJob, lease_owner: str
    ) -> None:
        """Atomically complete the job, references, Memory and User cleanup."""
        async with self.session_manager() as session:
            completed = await self.owner_lifecycle_repository.mark_completed(
                session,
                job_id=job.id,
                lease_owner=lease_owner,
                now=datetime.datetime.now(datetime.UTC),
            )
            if not completed:
                raise RuntimeError("Owner lifecycle lease was lost before finalization")
            await self.chat_write_request_repository.delete_by_requester_user_id(
                session, requester_user_id=job.user_id
            )
            await self.mailbox_repository.detach_sender_user_id(
                session, sender_user_id=job.user_id
            )
            await self.exchange_file_repository.detach_source_user_id(
                session, source_user_id=job.user_id
            )
            await self.external_channel_repository.detach_user_references(
                session, user_id=job.user_id
            )
            await self.memory_repository.delete_all_for_user(
                session, user_id=job.user_id
            )
            await self.user_repository.delete(session, job.user_id)

    async def set_status(
        self, *, job_id: str, lease_owner: str, status: OwnerLifecycleStatus
    ) -> bool:
        """Complete one owned status CAS."""
        async with self.session_manager() as session:
            return await self.owner_lifecycle_repository.set_status(
                session,
                job_id=job_id,
                lease_owner=lease_owner,
                status=status,
                now=datetime.datetime.now(datetime.UTC),
            )

    async def mark_retry(
        self,
        *,
        job: OwnerLifecycleJob,
        lease_owner: str,
        next_attempt_at: datetime.datetime,
        error_kind: str,
        error_summary: str,
        now: datetime.datetime,
    ) -> bool:
        """Finish retry attribution and lease release in its existing group."""
        async with self.session_manager() as session:
            return await self.owner_lifecycle_repository.mark_retry(
                session,
                job_id=job.id,
                lease_owner=lease_owner,
                next_attempt_at=next_attempt_at,
                error_kind=error_kind,
                error_summary=error_summary,
                now=now,
            )

    @retry_hierarchy_operation
    async def retire_root_tree(
        self,
        *,
        job: OwnerLifecycleJob,
        lease_owner: str,
        root_session_id: str,
        immediate_purge: bool,
    ) -> RootRetirement:
        """Stop and archive one User root tree through the shared lifecycle registry."""
        stop_session_ids: list[str] = []
        active = False
        archived = False
        archive_cleanup_plans: tuple[ProviderEffectPlan, ...] = ()
        async with self.session_manager() as session:
            tree = await self.agent_session_repository.lock_root_tree_sessions(
                session,
                root_session_id=root_session_id,
            )
            if not tree:
                return RootRetirement(
                    retired=True, archived=False, stop_session_ids=(), cleanup_plans=()
                )
            if any(item.status is not AgentSessionStatus.ACTIVE for item in tree):
                if immediate_purge and all(
                    item.status is AgentSessionStatus.ARCHIVED for item in tree
                ):
                    # Account purge must not wait on prior retention schedules.
                    archived_at = datetime.datetime.now(datetime.UTC)
                    settings = await self.retention_repository.get_settings(session)
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
                    return RootRetirement(
                        retired=True,
                        archived=False,
                        stop_session_ids=(),
                        cleanup_plans=(),
                    )
                # Transitional states; let the next pass observe progress.
                return RootRetirement(
                    retired=True, archived=False, stop_session_ids=(), cleanup_plans=()
                )
            session_ids = [item.id for item in tree]
            active = any(
                item.run_state is AgentSessionRunState.RUNNING for item in tree
            ) or await self.agent_run_repository.has_active_for_session_ids(
                session,
                session_ids=session_ids,
            )
            scheduled_lifecycle = self.lifecycle_repository
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
                settings = await self.retention_repository.get_settings(session)
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

                archive_cleanup_plans = await self.lifecycle_repository.archive(
                    session,
                    ChatArchiveMutation(
                        context=SessionLifecycleTransitionContext(
                            transition_id=f"{job.id}:{root_session_id}:owner-lifecycle",
                            root_session_id=root_session_id,
                            subtree_session_ids=tuple(session_ids),
                        ),
                        archived_at=archived_at,
                        purge_after=purge_after,
                        policy_revision=settings.revision,
                        retention_days=retention_days,
                    ),
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
                archived = True

        return RootRetirement(
            retired=archived,
            archived=archived,
            stop_session_ids=tuple(stop_session_ids),
            cleanup_plans=archive_cleanup_plans,
        )
