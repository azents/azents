"""Agent decommission coordinator tests."""

import datetime
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionStopSignal
from azents.core.enums import (
    AgentDecommissionStatus,
    AgentSessionRunState,
    AgentSessionStatus,
)
from azents.core.session_lifecycle import (
    SessionLifecycleParticipantDefinition,
    SessionLifecyclePurgePolicy,
    SessionLifecycleTransitionContext,
    SessionLifecycleTransitionPolicy,
)
from azents.repos.agent_decommission.data import AgentDecommissionJob
from azents.repos.external_channel.data import (
    ExternalChannelAgentDecommissionCleanup,
    ExternalChannelArchiveTermination,
)
from azents.services.agent_decommission import AgentDecommissionService
from azents.services.external_channel.provider_effect import ProviderEffectPlan
from azents.services.session_lifecycle.orchestrator import (
    TransitionOperation,
    TransitionParticipantOperation,
)
from azents.services.uploads.schema import StoredImage


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession, None]:
    """Yield a placeholder session for repository doubles."""
    yield cast(AsyncSession, object())


def _job(*, job_id: str, attempt_count: int = 1) -> AgentDecommissionJob:
    """Build one durable job projection."""
    now = datetime.datetime.now(datetime.UTC)
    return AgentDecommissionJob(
        id=job_id,
        agent_id=f"agent-{job_id}",
        workspace_id=f"workspace-{job_id}",
        requested_by_workspace_user_id="workspace-user-1",
        status=AgentDecommissionStatus.PENDING,
        attempt_count=attempt_count,
        lease_owner=None,
        lease_until=None,
        next_attempt_at=None,
        last_error_kind=None,
        last_error_summary=None,
        started_at=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )


class _DecommissionRepositoryDouble:
    """Claim and retry recorder for coordinator tests."""

    def __init__(self, jobs: list[AgentDecommissionJob]) -> None:
        self.jobs = jobs
        self.retries: list[tuple[str, str]] = []

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> AgentDecommissionJob | None:
        """Return one queued job per claim."""
        del session, now, lease_owner, lease_until
        return self.jobs.pop(0) if self.jobs else None

    async def set_status(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        status: AgentDecommissionStatus,
        now: datetime.datetime,
    ) -> bool:
        """Accept status updates outside the retry-focused test path."""
        del session, job_id, lease_owner, status, now
        return True

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
        """Record retry attribution."""
        del session, lease_owner, next_attempt_at, error_summary, now
        self.retries.append((job_id, error_kind))
        return True


class _FailureIsolatingCoordinator(AgentDecommissionService):
    """Coordinator double with deterministic per-job outcomes."""

    async def _advance(
        self,
        *,
        job: AgentDecommissionJob,
        lease_owner: str,
    ) -> tuple[bool, bool]:
        """Fail the first job and complete the second one."""
        del lease_owner
        if job.id == "failed":
            raise RuntimeError("provider unavailable")
        return True, False


@pytest.mark.asyncio
async def test_decommission_continues_after_one_job_retries() -> None:
    """One failed Agent decommission does not prevent a later completion."""
    repository = _DecommissionRepositoryDouble(
        [_job(job_id="failed"), _job(job_id="ok")]
    )
    service = object.__new__(_FailureIsolatingCoordinator)
    service.session_manager = _session_manager
    service.decommission_repository = repository

    summary = await service.decommission_once(
        lease_owner="scheduler-1",
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5),
    )

    assert summary.claimed_count == 2
    assert summary.completed_count == 1
    assert summary.retry_scheduled_count == 1
    assert repository.retries == [("failed", "RuntimeError")]


class _TransactionDouble:
    """Minimal transaction double used to prove archive callback ordering."""

    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        """Record the root archive transaction commit."""
        self.committed = True


@asynccontextmanager
async def _transaction_manager() -> AsyncGenerator[AsyncSession, None]:
    """Yield one stable transaction object to all lifecycle collaborators."""
    yield cast(AsyncSession, _TransactionDouble())


@dataclass(frozen=True)
class _RootSession:
    """Minimal locked Session state consumed during root retirement."""

    id: str
    status: AgentSessionStatus
    run_state: AgentSessionRunState


class _RootSessionRepositoryDouble:
    """Record root-tree lifecycle calls in their transaction order."""

    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def list_root_trees_by_agent_id(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> list[_RootSession]:
        """Return no roots outside the focused locked-tree path."""
        del session, agent_id
        return []

    async def lock_root_tree_sessions(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
    ) -> list[_RootSession]:
        """Return an idle active root tree."""
        del session
        return [
            _RootSession(
                id=root_session_id,
                status=AgentSessionStatus.ACTIVE,
                run_state=AgentSessionRunState.IDLE,
            )
        ]

    async def request_stop(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        stop_request_id: str,
        stop_requester_user_id: str | None,
    ) -> None:
        """Record the decommission stop request."""
        del session, session_id, stop_request_id, stop_requester_user_id
        self.events.append("stop-request")

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
        """Record the root archive after participant completion."""
        del (
            session,
            root_session_id,
            session_ids,
            archived_at,
            purge_after,
            policy_revision,
            retention_days,
        )
        self.events.append("archive-tree")


class _AgentRunRepositoryDouble:
    """Report an idle root tree."""

    async def has_active_for_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> bool:
        """Return no residual active runs."""
        del session, session_ids
        return False


@dataclass(frozen=True)
class _RetentionSettings:
    """Finite retention setting projection consumed during root archive."""

    archived_session_retention_days: int | None
    revision: int


class _RetentionRepositoryDouble:
    """Provide a finite retention policy and record purge scheduling."""

    async def lock_settings(self, session: AsyncSession) -> _RetentionSettings:
        """Return a deterministic finite retention setting."""
        del session
        return _RetentionSettings(archived_session_retention_days=7, revision=3)

    async def schedule_purge_job(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
        eligible_at: datetime.datetime,
        policy_revision: int,
        now: datetime.datetime,
    ) -> None:
        """Accept the scheduled root purge."""
        del session, root_session_id, eligible_at, policy_revision, now


class _LifecycleOrchestratorDouble:
    """Execute the supplied participant operation before root mutation."""

    def __init__(self, participant: SessionLifecycleParticipantDefinition) -> None:
        self.participant = participant

    async def archive(
        self,
        *,
        context: SessionLifecycleTransitionContext,
        participant_operation: TransitionParticipantOperation,
        transition: TransitionOperation,
    ) -> None:
        """Apply the participant and root operations in production order."""
        await participant_operation(self.participant, context)
        await transition()


class _ExternalChannelLifecycleDouble:
    """Record the transaction-bound External Channel archive dispatch."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls: list[
            tuple[
                AsyncSession,
                SessionLifecycleParticipantDefinition,
                SessionLifecycleTransitionContext,
            ]
        ] = []

    async def archive_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecycleTransitionContext,
    ) -> ExternalChannelArchiveTermination:
        """Capture the exact transaction and lifecycle context."""
        self.calls.append((session, definition, context))
        self.events.append("external-channel-archive")
        return ExternalChannelArchiveTermination(
            disconnected_binding_count=0,
            finished_work_count=0,
            direct_cleanup_count=0,
            cleanup_plans=(),
        )

    async def cleanup_decommissioned_agent(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelAgentDecommissionCleanup:
        """Reject direct-root cleanup outside this archive-focused double."""
        del session, agent_id, now
        raise AssertionError("Direct Agent cleanup was not expected")

    async def purge_decommissioned_provider_state(
        self,
        session: AsyncSession,
        connection_ids: Sequence[str],
    ) -> int:
        """Reject provider-state cleanup outside this archive-focused double."""
        del session, connection_ids
        raise AssertionError("Provider state cleanup was not expected")

    async def consume_archive_cleanup(
        self,
        plans: Sequence[ProviderEffectPlan],
    ) -> int:
        """Report no pending provider cleanup in the focused lifecycle test."""
        del plans
        return 0


class _DecommissionStatusRepositoryDouble:
    """Always retain the scheduler-owned job lease."""

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> AgentDecommissionJob | None:
        """Return no scheduler work outside the status-focused paths."""
        del session, now, lease_owner, lease_until
        return None

    async def set_status(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        status: AgentDecommissionStatus,
        now: datetime.datetime,
    ) -> bool:
        """Accept phase progress for the owned job."""
        del session, job_id, lease_owner, status, now
        return True

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
        """Accept retry persistence outside this focused path."""
        del (
            session,
            job_id,
            lease_owner,
            next_attempt_at,
            error_kind,
            error_summary,
            now,
        )
        return True


class _BrokerDouble:
    """Record post-commit stop signals."""

    def __init__(self) -> None:
        self.session_ids: list[str] = []

    async def send_message(self, signal: SessionStopSignal) -> None:
        """Capture the emitted stop signal."""
        self.session_ids.append(signal.session_id)


@pytest.mark.asyncio
async def test_retire_tree_terminates_external_channel_before_archive() -> None:
    """External Channel termination precedes Session archive in the same transaction."""
    events: list[str] = []
    participant = SessionLifecycleParticipantDefinition(
        key="session.external-channel",
        policy_version=1,
        dependencies=(),
        owned_resources=(),
        archive_policy=SessionLifecycleTransitionPolicy.TERMINATE,
        restore_policy=SessionLifecycleTransitionPolicy.PRESERVE,
        purge_policy=SessionLifecyclePurgePolicy.REQUIRED,
    )
    external_channel_lifecycle = _ExternalChannelLifecycleDouble(events)
    service = object.__new__(AgentDecommissionService)
    service.session_manager = _transaction_manager
    service.agent_session_repository = _RootSessionRepositoryDouble(events)
    service.agent_run_repository = _AgentRunRepositoryDouble()
    service.retention_repository = _RetentionRepositoryDouble()
    service.lifecycle_orchestrator = _LifecycleOrchestratorDouble(participant)
    service.external_channel_lifecycle_service = external_channel_lifecycle
    service.decommission_repository = _DecommissionStatusRepositoryDouble()
    service.broker = _BrokerDouble()

    retired = (
        await service._retire_root_tree(  # Pin transaction-bound participant dispatch.
            job=_job(job_id="decommission"),
            lease_owner="scheduler-1",
            root_session_id="root-session-1",
        )
    )

    assert retired is True
    assert events == [
        "stop-request",
        "external-channel-archive",
        "archive-tree",
    ]
    session, definition, context = external_channel_lifecycle.calls[0]
    assert isinstance(session, _TransactionDouble)
    assert definition is participant
    assert context.root_session_id == "root-session-1"
    assert context.subtree_session_ids == ("root-session-1",)


@dataclass(frozen=True)
class _AgentProjection:
    """Minimal Agent state consumed by direct-root cleanup."""

    avatar: StoredImage | None


class _AgentRepositoryDouble:
    """Return one decommissioning Agent without an avatar."""

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> _AgentProjection:
        """Return the direct owner required by cleanup."""
        del session, agent_id
        return _AgentProjection(avatar=None)


class _ExternalChannelDecommissionCleanupDouble:
    """Record cleanup of direct Agent-owned External Channel state."""

    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def archive_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecycleTransitionContext,
    ) -> ExternalChannelArchiveTermination:
        """Reject archive participation outside this cleanup-focused double."""
        del session, definition, context
        raise AssertionError("Archive participation was not expected")

    async def cleanup_decommissioned_agent(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelAgentDecommissionCleanup:
        """Record cleanup before unrelated Agent file expiration."""
        del session, agent_id, now
        self.events.append("external-channel-cleanup")
        return ExternalChannelAgentDecommissionCleanup(
            cleanup_plans=(),
            provider_state_purge_connection_ids=("connection-1",),
            deleted_route_count=0,
            deleted_access_request_count=0,
            deleted_agent_grant_count=0,
            deleted_block_count=0,
        )

    async def purge_decommissioned_provider_state(
        self,
        session: AsyncSession,
        connection_ids: Sequence[str],
    ) -> int:
        """Purge credentials only after provider targets were captured."""
        del session
        assert tuple(connection_ids) == ("connection-1",)
        self.events.append("purge-provider-state")
        return 1

    async def consume_archive_cleanup(
        self,
        plans: Sequence[ProviderEffectPlan],
    ) -> int:
        """Record one post-commit provider cleanup attempt."""
        assert not plans
        self.events.append("consume-cleanup")
        return 0


@dataclass(frozen=True)
class _ExchangeFileProjection:
    """Minimal ExchangeFile state consumed by post-commit blob cleanup."""

    id: str
    object_key: str
    blob_deleted_at: datetime.datetime | None


class _ExchangeFileRepositoryDouble:
    """Expose an Agent with no remaining unbound files."""

    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def expire_unbound_by_agent_id(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        expired_at: datetime.datetime,
    ) -> list[_ExchangeFileProjection]:
        """Record the preexisting file lifecycle cleanup."""
        del session, agent_id, expired_at
        self.events.append("expire-unbound-files")
        return []

    async def list_unbound_by_agent_id(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> list[_ExchangeFileProjection]:
        """Return no remote blobs requiring deletion."""
        del session, agent_id
        return []

    async def mark_blob_deleted(
        self,
        session: AsyncSession,
        *,
        file_id: str,
        blob_deleted_at: datetime.datetime,
    ) -> None:
        """Accept blob deletion persistence outside the empty-file fixture."""
        del session, file_id, blob_deleted_at

    async def delete_unbound_expired_by_agent_id(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> int:
        """Accept deletion of an already-empty file set."""
        del session, agent_id
        return 0


class _RuntimeRepositoryDouble:
    """Report no runtime requiring terminal acknowledgement."""

    async def get_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> None:
        """Return no runtime row."""
        del session, agent_id
        return None

    async def get_terminal_delete_acknowledged(
        self,
        session: AsyncSession,
        runtime_id: str,
    ) -> None:
        """Report no acknowledgement when no Runtime exists."""
        del session, runtime_id
        return None


@dataclass(frozen=True)
class _RuntimeProjection:
    """Minimal immutable Runtime binding projection."""

    id: str
    runtime_provider_resource_id: str | None


class _BoundRuntimeRepositoryDouble:
    """Expose one Runtime through its immutable Provider resource binding."""

    runtime = _RuntimeProjection(
        id="runtime-1",
        runtime_provider_resource_id="provider-resource-1",
    )

    async def get_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> _RuntimeProjection:
        """Return the bound Runtime for both cleanup checks."""
        del session, agent_id
        return self.runtime

    async def get_terminal_delete_acknowledged(
        self,
        session: AsyncSession,
        runtime_id: str,
    ) -> _RuntimeProjection:
        """Return the acknowledged Runtime for the current generation."""
        del session
        assert runtime_id == "runtime-1"
        return self.runtime


class _AgentRuntimeServiceDouble:
    """Capture terminal deletion targeting through the Runtime Profile path."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def request_terminal_delete_for_agent(self, agent_id: str) -> None:
        """Record the exact terminal lifecycle target."""
        self.calls.append({"agent_id": agent_id})
        return None


@pytest.mark.asyncio
async def test_decommission_cleanup_removes_external_agent_roots_first() -> None:
    """Direct External Channel roots are cleaned before finalizer eligibility."""
    events: list[str] = []
    service = object.__new__(AgentDecommissionService)
    cleanup_lifecycle = _ExternalChannelDecommissionCleanupDouble(events)
    service.session_manager = _transaction_manager
    service.agent_repository = _AgentRepositoryDouble()
    service.external_channel_lifecycle_service = cleanup_lifecycle
    service.exchange_file_repository = _ExchangeFileRepositoryDouble(events)
    service.runtime_repository = _RuntimeRepositoryDouble()
    service.decommission_repository = _DecommissionStatusRepositoryDouble()

    await service._cleanup_agent_external_roots(  # Pin finalizer precondition cleanup.
        job=_job(job_id="decommission"),
        lease_owner="scheduler-1",
    )

    assert events == [
        "external-channel-cleanup",
        "purge-provider-state",
        "expire-unbound-files",
        "consume-cleanup",
    ]


@pytest.mark.asyncio
async def test_decommission_targets_terminal_delete_from_resource_binding() -> None:
    """Terminal deletion uses the immutable Provider resource binding."""
    events: list[str] = []
    runtime_service = _AgentRuntimeServiceDouble()
    service = object.__new__(AgentDecommissionService)
    cleanup_lifecycle = _ExternalChannelDecommissionCleanupDouble(events)
    service.session_manager = _transaction_manager
    service.agent_repository = _AgentRepositoryDouble()
    service.external_channel_lifecycle_service = cleanup_lifecycle
    service.exchange_file_repository = _ExchangeFileRepositoryDouble(events)
    service.runtime_repository = _BoundRuntimeRepositoryDouble()
    service.agent_runtime_service = runtime_service
    service.decommission_repository = _DecommissionStatusRepositoryDouble()

    await service._cleanup_agent_external_roots(  # Pin terminal deletion fencing.
        job=_job(job_id="decommission"),
        lease_owner="scheduler-1",
    )

    assert runtime_service.calls == [{"agent_id": "agent-decommission"}]
