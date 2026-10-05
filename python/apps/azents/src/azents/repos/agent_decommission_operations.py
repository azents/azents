"""Completed database-only Agent decommission operations."""

import dataclasses
import datetime
from collections.abc import Sequence
from typing import Annotated, Protocol

from azcommon.uuid import uuid7
from fastapi import Depends

from azents.core.chat_operation_data import ChatArchiveMutation
from azents.core.enums import (
    AgentDecommissionStatus,
    AgentSessionRunState,
    AgentSessionStatus,
)
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.core.retirement_data import RetirementBlob, RetirementRoot, RootRetirement
from azents.core.session_lifecycle import SessionLifecycleTransitionContext
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import AgentAvatar
from azents.repos.agent_decommission import AgentDecommissionRepository
from azents.repos.agent_decommission.data import AgentDecommissionJob
from azents.repos.agent_decommission_finalizer import (
    AgentDecommissionFinalizerRepository,
)
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.external_channel.data import ExternalChannelAgentDecommissionCleanup
from azents.repos.external_channel.lifecycle import ExternalChannelLifecycleRepository
from azents.repos.hierarchy_contention import retry_hierarchy_operation
from azents.repos.session_lifecycle_operations import (
    SessionLifecycleOperationsRepository,
)


class AgentDecommissionRootSession(Protocol):
    """Read-only root-tree Session state consumed during retirement."""

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


class AgentDecommissionAgent(Protocol):
    """Read-only Agent state consumed during direct-root cleanup."""

    @property
    def avatar(self) -> AgentAvatar | None:
        """Return the optional Agent avatar projection."""
        ...


class AgentDecommissionRuntime(Protocol):
    """Read-only Runtime state consumed by terminal deletion fencing."""

    @property
    def id(self) -> str:
        """Return the Runtime ID."""
        ...

    @property
    def runtime_provider_resource_id(self) -> str | None:
        """Return the immutable provider resource binding."""
        ...


class AgentDecommissionExchangeFile(Protocol):
    """Read-only ExchangeFile state consumed by blob cleanup."""

    @property
    def id(self) -> str:
        """Return the ExchangeFile ID."""
        ...

    @property
    def object_key(self) -> str:
        """Return the object-store key."""
        ...

    @property
    def blob_deleted_at(self) -> datetime.datetime | None:
        """Return the blob deletion timestamp when already deleted."""
        ...


class AgentDecommissionRetentionSettings(Protocol):
    """Read-only retention settings consumed while archiving a root tree."""

    @property
    def archived_session_retention_days(self) -> int | None:
        """Return the archive retention policy."""
        ...

    @property
    def revision(self) -> int:
        """Return the policy revision."""
        ...


class AgentDecommissionRepositoryProtocol(Protocol):
    """Persistence operations consumed by the decommission coordinator."""

    async def claim_due(
        self,
        session: WriteSession,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> AgentDecommissionJob | None:
        """Claim one due durable decommission job."""
        ...

    async def set_status(
        self,
        session: WriteSession,
        *,
        job_id: str,
        lease_owner: str,
        expected_attempt: int,
        status: AgentDecommissionStatus,
        now: datetime.datetime,
    ) -> bool:
        """Persist one owned decommission status."""
        ...

    async def mark_retry(
        self,
        session: WriteSession,
        *,
        job_id: str,
        lease_owner: str,
        expected_attempt: int,
        next_attempt_at: datetime.datetime,
        error_kind: str,
        error_summary: str,
        now: datetime.datetime,
    ) -> bool:
        """Persist bounded retry state for an owned job."""
        ...


class AgentDecommissionAgentSessionRepositoryProtocol(Protocol):
    """Session-tree operations consumed by Agent retirement."""

    async def list_root_trees_by_agent_id(
        self,
        session: ReadSession,
        *,
        agent_id: str,
    ) -> Sequence[AgentDecommissionRootSession]:
        """List every root tree owned by an Agent."""
        ...

    async def lock_root_tree_sessions(
        self,
        session: WriteSession,
        *,
        root_session_id: str,
    ) -> Sequence[AgentDecommissionRootSession]:
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


class AgentDecommissionRunRepositoryProtocol(Protocol):
    """Execution-state query consumed before root retirement."""

    async def has_active_for_session_ids(
        self,
        session: ReadSession,
        *,
        session_ids: Sequence[str],
    ) -> bool:
        """Report whether any Session still has active execution."""
        ...


class AgentDecommissionRetentionRepositoryProtocol(Protocol):
    """Retention operations consumed while retiring an idle root tree."""

    async def get_settings(
        self,
        session: ReadSession,
    ) -> AgentDecommissionRetentionSettings:
        """Read the active retention policy."""
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
        """Schedule durable purge work after root archive."""
        ...


class AgentDecommissionAgentRepositoryProtocol(Protocol):
    """Agent lookup consumed by direct-root cleanup."""

    async def get_by_id(
        self,
        session: ReadSession,
        agent_id: str,
    ) -> AgentDecommissionAgent | None:
        """Fetch the decommissioning Agent's avatar projection."""
        ...


class AgentDecommissionExchangeFileRepositoryProtocol(Protocol):
    """Direct Agent-owned ExchangeFile cleanup operations."""

    async def expire_unbound_by_agent_id(
        self,
        session: WriteSession,
        *,
        agent_id: str,
        expired_at: datetime.datetime,
    ) -> Sequence[AgentDecommissionExchangeFile]:
        """Expire direct Agent-owned files before blob cleanup."""
        ...

    async def list_unbound_by_agent_id(
        self,
        session: ReadSession,
        *,
        agent_id: str,
    ) -> Sequence[AgentDecommissionExchangeFile]:
        """List direct Agent-owned files requiring blob cleanup."""
        ...

    async def mark_blob_deleted(
        self,
        session: WriteSession,
        *,
        file_id: str,
        blob_deleted_at: datetime.datetime,
    ) -> None:
        """Persist one blob deletion acknowledgement."""
        ...

    async def delete_unbound_expired_by_agent_id(
        self,
        session: WriteSession,
        *,
        agent_id: str,
    ) -> int:
        """Delete externally-cleaned direct Agent-owned metadata."""
        ...


class AgentDecommissionRuntimeRepositoryProtocol(Protocol):
    """Runtime lookup and acknowledgement operations used by finalization."""

    async def get_by_agent_id(
        self,
        session: ReadSession,
        agent_id: str,
    ) -> AgentDecommissionRuntime | None:
        """Fetch the Runtime currently owned by an Agent."""
        ...

    async def get_terminal_delete_acknowledged(
        self,
        session: ReadSession,
        runtime_id: str,
    ) -> AgentDecommissionRuntime | None:
        """Return a Runtime only after terminal deletion acknowledgement."""
        ...


class RetirementLifecycleRepository(Protocol):
    """Database-only lifecycle composition shared with locked root retirement."""

    async def archive_allows_active_runs(
        self,
        session: ReadSession,
        *,
        session_ids: Sequence[str],
        running_session_ids: Sequence[str],
    ) -> bool:
        """Read Scheduled eligibility within the root mutation group."""
        ...

    async def archive(
        self,
        session: WriteSession,
        command: ChatArchiveMutation,
    ) -> tuple[ProviderEffectPlan, ...]:
        """Apply ordered participant and root mutations in the same transaction."""
        ...


class DecommissionExternalRepository(Protocol):
    """Direct Agent-owned External Channel mutations in a composed transaction."""

    async def cleanup_decommissioned_agent(
        self,
        session: WriteSession,
        *,
        agent_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelAgentDecommissionCleanup:
        """Capture provider targets and remove direct roots atomically."""
        ...

    async def purge_disconnected_connection_provider_state(
        self,
        session: WriteSession,
        *,
        connection_ids: Sequence[str],
    ) -> int:
        """Remove deferred credentials after target capture."""
        ...


@dataclasses.dataclass(frozen=True)
class AgentExternalCleanup:
    """Detached direct roots returned after cleanup preparation commits."""

    agent: AgentDecommissionAgent
    files: tuple[RetirementBlob, ...]
    cleanup_plans: tuple[ProviderEffectPlan, ...]


@dataclasses.dataclass
class AgentDecommissionOperationsRepository:
    """Own complete decommission groups and compose locked root retirement."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    agent_repository: Annotated[
        AgentDecommissionAgentRepositoryProtocol, Depends(AgentRepository)
    ]
    decommission_repository: Annotated[
        AgentDecommissionRepositoryProtocol, Depends(AgentDecommissionRepository)
    ]
    finalizer_repository: Annotated[AgentDecommissionFinalizerRepository, Depends()]
    agent_session_repository: Annotated[
        AgentDecommissionAgentSessionRepositoryProtocol, Depends(AgentSessionRepository)
    ]
    agent_run_repository: Annotated[
        AgentDecommissionRunRepositoryProtocol, Depends(AgentRunRepository)
    ]
    retention_repository: Annotated[
        AgentDecommissionRetentionRepositoryProtocol,
        Depends(ArchivedSessionRetentionRepository),
    ]
    runtime_repository: Annotated[
        AgentDecommissionRuntimeRepositoryProtocol, Depends(AgentRuntimeRepository)
    ]
    exchange_file_repository: Annotated[
        AgentDecommissionExchangeFileRepositoryProtocol, Depends(ExchangeFileRepository)
    ]
    lifecycle_repository: Annotated[
        RetirementLifecycleRepository, Depends(SessionLifecycleOperationsRepository)
    ]
    external_channel_repository: Annotated[
        DecommissionExternalRepository,
        Depends(ExternalChannelLifecycleRepository.create),
    ]

    async def claim_due(
        self,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> AgentDecommissionJob | None:
        """Finish one durable claim before scheduler effects."""
        async with self.session_manager() as session:
            return await self.decommission_repository.claim_due(
                session,
                now=now,
                lease_owner=lease_owner,
                lease_until=lease_until,
            )

    async def list_roots(self, *, agent_id: str) -> tuple[RetirementRoot, ...]:
        """Complete descriptive root reads without mutation capability."""
        async with self.read_session_manager() as session:
            roots = await self.agent_session_repository.list_root_trees_by_agent_id(
                session, agent_id=agent_id
            )
            return tuple(
                RetirementRoot(id=root.id, status=root.status, product_mode=None)
                for root in roots
            )

    async def finalize(self, *, job: AgentDecommissionJob, lease_owner: str) -> bool:
        """Finish the original fenced finalizer group atomically."""
        async with self.session_manager() as session:
            return await self.finalizer_repository.finalize(
                session,
                job_id=job.id,
                agent_id=job.agent_id,
                lease_owner=lease_owner,
                expected_attempt=job.attempt_count,
                now=datetime.datetime.now(datetime.UTC),
            )

    async def runtime_bound(self, *, agent_id: str) -> bool:
        """Complete a descriptive immutable Runtime resource binding lookup."""
        async with self.read_session_manager() as session:
            runtime = await self.runtime_repository.get_by_agent_id(session, agent_id)
            return (
                runtime is not None and runtime.runtime_provider_resource_id is not None
            )

    async def prepare_external_cleanup(
        self,
        *,
        job: AgentDecommissionJob,
        lease_owner: str,
    ) -> AgentExternalCleanup:
        """Remove direct roots, capture targets, expire files and CAS phase together."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, job.agent_id)
            if agent is None:
                raise RuntimeError("Decommissioning Agent is missing")
            now = datetime.datetime.now(datetime.UTC)
            cleanup = (
                await self.external_channel_repository.cleanup_decommissioned_agent(
                    session,
                    agent_id=job.agent_id,
                    now=now,
                )
            )
            external_repository = self.external_channel_repository
            await external_repository.purge_disconnected_connection_provider_state(
                session,
                connection_ids=cleanup.provider_state_purge_connection_ids,
            )
            await self.exchange_file_repository.expire_unbound_by_agent_id(
                session,
                agent_id=job.agent_id,
                expired_at=now,
            )
            files = await self.exchange_file_repository.list_unbound_by_agent_id(
                session, agent_id=job.agent_id
            )
            owned = await self.decommission_repository.set_status(
                session,
                job_id=job.id,
                lease_owner=lease_owner,
                expected_attempt=job.attempt_count,
                status=AgentDecommissionStatus.FINALIZING,
                now=now,
            )
            if not owned:
                raise RuntimeError("Agent decommission lease was lost")
            return AgentExternalCleanup(
                agent=agent,
                cleanup_plans=cleanup.cleanup_plans,
                files=tuple(
                    RetirementBlob(
                        id=file.id,
                        object_key=file.object_key,
                        blob_deleted_at=file.blob_deleted_at,
                    )
                    for file in files
                ),
            )

    async def mark_blob_deleted(self, *, file_id: str) -> None:
        """Finish one successful object-store deletion checkpoint."""
        async with self.session_manager() as session:
            await self.exchange_file_repository.mark_blob_deleted(
                session,
                file_id=file_id,
                blob_deleted_at=datetime.datetime.now(datetime.UTC),
            )

    async def finish_external_cleanup(self, *, agent_id: str) -> None:
        """Delete expired unbound rows and require the Runtime acknowledgement."""
        async with self.session_manager() as session:
            await self.exchange_file_repository.delete_unbound_expired_by_agent_id(
                session, agent_id=agent_id
            )
            runtime = await self.runtime_repository.get_by_agent_id(session, agent_id)
            if runtime is not None and runtime.runtime_provider_resource_id is not None:
                acknowledged = (
                    await self.runtime_repository.get_terminal_delete_acknowledged(
                        session, runtime.id
                    )
                )
                if acknowledged is None:
                    raise RuntimeError(
                        "AgentRuntime terminal deletion acknowledgement is pending"
                    )

    async def set_status(
        self,
        *,
        job_id: str,
        lease_owner: str,
        expected_attempt: int,
        status: AgentDecommissionStatus,
    ) -> bool:
        """Complete the existing owned status CAS."""
        async with self.session_manager() as session:
            return await self.decommission_repository.set_status(
                session,
                job_id=job_id,
                lease_owner=lease_owner,
                expected_attempt=expected_attempt,
                status=status,
                now=datetime.datetime.now(datetime.UTC),
            )

    async def mark_retry(
        self,
        *,
        job: AgentDecommissionJob,
        lease_owner: str,
        next_attempt_at: datetime.datetime,
        error_kind: str,
        error_summary: str,
        now: datetime.datetime,
    ) -> bool:
        """Finish the existing retry CAS before returning to scheduler sequencing."""
        async with self.session_manager() as session:
            return await self.decommission_repository.mark_retry(
                session,
                job_id=job.id,
                lease_owner=lease_owner,
                expected_attempt=job.attempt_count,
                next_attempt_at=next_attempt_at,
                error_kind=error_kind,
                error_summary=error_summary,
                now=now,
            )

    @retry_hierarchy_operation
    async def retire_root_tree(
        self,
        *,
        job: AgentDecommissionJob,
        lease_owner: str,
        root_session_id: str,
    ) -> RootRetirement:
        """Stop and archive one root tree through the shared lifecycle registry."""
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
                return RootRetirement(
                    retired=True, archived=False, stop_session_ids=(), cleanup_plans=()
                )
            if any(item.status is not AgentSessionStatus.ACTIVE for item in tree):
                raise RuntimeError("Agent root tree changed during decommission")
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
                if settings.archived_session_retention_days is None:
                    raise RuntimeError(
                        "Agent decommission cannot retire roots under Unlimited "
                        "retention"
                    )
                archived_at = datetime.datetime.now(datetime.UTC)
                purge_after = archived_at + datetime.timedelta(
                    days=settings.archived_session_retention_days
                )

                archive_cleanup_plans = await self.lifecycle_repository.archive(
                    session,
                    ChatArchiveMutation(
                        context=SessionLifecycleTransitionContext(
                            transition_id=f"{job.id}:{root_session_id}:decommission",
                            root_session_id=root_session_id,
                            subtree_session_ids=tuple(session_ids),
                        ),
                        archived_at=archived_at,
                        purge_after=purge_after,
                        policy_revision=settings.revision,
                        retention_days=settings.archived_session_retention_days,
                    ),
                )
                await self.retention_repository.schedule_purge_job(
                    session,
                    root_session_id=root_session_id,
                    eligible_at=purge_after,
                    policy_revision=settings.revision,
                    now=archived_at,
                )
                owned = await self.decommission_repository.set_status(
                    session,
                    job_id=job.id,
                    lease_owner=lease_owner,
                    expected_attempt=job.attempt_count,
                    status=AgentDecommissionStatus.RETIRING_SESSIONS,
                    now=archived_at,
                )
                if not owned:
                    raise RuntimeError("Agent decommission lease was lost")
                archived = True

        return RootRetirement(
            retired=archived,
            archived=archived,
            stop_session_ids=tuple(stop_session_ids),
            cleanup_plans=archive_cleanup_plans,
        )
