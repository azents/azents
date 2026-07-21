"""Agent decommission coordinator tests."""

import datetime
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentDecommissionStatus,
    AgentSessionRunState,
    AgentSessionStatus,
)
from azents.core.session_lifecycle import SessionLifecycleTransitionContext
from azents.repos.agent_decommission.data import AgentDecommissionJob
from azents.services.agent_decommission import AgentDecommissionService


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
    service.decommission_repository = repository  # type: ignore[assignment]

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


class _RootSessionRepositoryDouble:
    """Record root-tree lifecycle calls in their transaction order."""

    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def lock_root_tree_sessions(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
    ) -> list[SimpleNamespace]:
        """Return an idle active root tree."""
        del session
        return [
            SimpleNamespace(
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
        user_id: str | None,
    ) -> None:
        """Record the decommission stop request."""
        del session, session_id, stop_request_id, user_id
        self.events.append("stop-request")

    async def archive_tree(self, session: AsyncSession, **kwargs: object) -> None:
        """Record the root archive after participant completion."""
        del session, kwargs
        self.events.append("archive-tree")


class _AgentRunRepositoryDouble:
    """Report an idle root tree."""

    async def has_active_for_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: list[str],
    ) -> bool:
        """Return no residual active runs."""
        del session, session_ids
        return False


class _RetentionRepositoryDouble:
    """Provide a finite retention policy and record purge scheduling."""

    async def lock_settings(self, session: AsyncSession) -> SimpleNamespace:
        """Return a deterministic finite retention setting."""
        del session
        return SimpleNamespace(archived_session_retention_days=7, revision=3)

    async def schedule_purge_job(
        self,
        session: AsyncSession,
        **kwargs: object,
    ) -> None:
        """Accept the scheduled root purge."""
        del session, kwargs


class _LifecycleOrchestratorDouble:
    """Execute the supplied participant operation before root mutation."""

    def __init__(self, participant: object) -> None:
        self.participant = participant

    async def archive(
        self,
        *,
        context: SessionLifecycleTransitionContext,
        participant_operation: Callable[
            [object, SessionLifecycleTransitionContext],
            Awaitable[None],
        ],
        transition: Callable[[], Awaitable[None]],
    ) -> None:
        """Apply the participant and root operations in production order."""
        await participant_operation(self.participant, context)
        await transition()


class _ExternalChannelLifecycleDouble:
    """Record the transaction-bound External Channel archive dispatch."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls: list[
            tuple[AsyncSession, object, SessionLifecycleTransitionContext]
        ] = []

    async def archive_participant(
        self,
        session: AsyncSession,
        definition: object,
        context: SessionLifecycleTransitionContext,
    ) -> None:
        """Capture the exact transaction and lifecycle context."""
        self.calls.append((session, definition, context))
        self.events.append("external-channel-archive")


class _DecommissionStatusRepositoryDouble:
    """Always retain the scheduler-owned job lease."""

    async def set_status(self, session: AsyncSession, **kwargs: object) -> bool:
        """Accept phase progress for the owned job."""
        del session, kwargs
        return True


class _BrokerDouble:
    """Record post-commit stop signals."""

    def __init__(self) -> None:
        self.session_ids: list[str] = []

    async def send_message(self, signal: SimpleNamespace) -> None:
        """Capture the emitted stop signal."""
        self.session_ids.append(signal.session_id)


@pytest.mark.asyncio
async def test_retire_tree_terminates_external_channel_before_archive() -> None:
    """External Channel termination precedes Session archive in the same transaction."""
    events: list[str] = []
    participant = SimpleNamespace(key="session.external-channel")
    external_channel_lifecycle = _ExternalChannelLifecycleDouble(events)
    service = object.__new__(AgentDecommissionService)
    service.session_manager = _transaction_manager
    service.agent_session_repository = _RootSessionRepositoryDouble(events)  # type: ignore[assignment]
    service.agent_run_repository = _AgentRunRepositoryDouble()  # type: ignore[assignment]
    service.retention_repository = _RetentionRepositoryDouble()  # type: ignore[assignment]
    service.lifecycle_orchestrator = _LifecycleOrchestratorDouble(participant)  # type: ignore[assignment]
    service.external_channel_lifecycle_service = external_channel_lifecycle  # type: ignore[assignment]
    service.decommission_repository = _DecommissionStatusRepositoryDouble()  # type: ignore[assignment]
    service.broker = _BrokerDouble()  # type: ignore[assignment]

    retired = await service._retire_root_tree(  # pyright: ignore[reportPrivateUsage]  # Pin transaction-bound participant dispatch.
        job=_job(job_id="decommission"),
        lease_owner="scheduler-1",
        root_session_id="root-session-1",
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


class _AgentRepositoryDouble:
    """Return one decommissioning Agent without an avatar."""

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> SimpleNamespace:
        """Return the direct owner required by cleanup."""
        del session, agent_id
        return SimpleNamespace(avatar=None)


class _ExternalChannelDecommissionCleanupDouble:
    """Record cleanup of direct Agent-owned External Channel state."""

    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def cleanup_decommissioned_agent(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        now: datetime.datetime,
    ) -> None:
        """Record cleanup before unrelated Agent file expiration."""
        del session, agent_id, now
        self.events.append("external-channel-cleanup")


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
    ) -> None:
        """Record the preexisting file lifecycle cleanup."""
        del session, agent_id, expired_at
        self.events.append("expire-unbound-files")

    async def list_unbound_by_agent_id(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> list[object]:
        """Return no remote blobs requiring deletion."""
        del session, agent_id
        return []

    async def delete_unbound_expired_by_agent_id(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> None:
        """Accept deletion of an already-empty file set."""
        del session, agent_id


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


@pytest.mark.asyncio
async def test_decommission_cleanup_removes_external_agent_roots_first() -> None:
    """Direct External Channel roots are cleaned before finalizer eligibility."""
    events: list[str] = []
    service = object.__new__(AgentDecommissionService)
    service.session_manager = _transaction_manager
    service.agent_repository = _AgentRepositoryDouble()  # type: ignore[assignment]
    service.external_channel_lifecycle_service = (
        _ExternalChannelDecommissionCleanupDouble(events)  # type: ignore[assignment]
    )
    service.exchange_file_repository = _ExchangeFileRepositoryDouble(events)  # type: ignore[assignment]
    service.runtime_repository = _RuntimeRepositoryDouble()  # type: ignore[assignment]
    service.decommission_repository = _DecommissionStatusRepositoryDouble()  # type: ignore[assignment]

    await service._cleanup_agent_external_roots(  # pyright: ignore[reportPrivateUsage]  # Pin finalizer precondition cleanup.
        job=_job(job_id="decommission"),
        lease_owner="scheduler-1",
    )

    assert events == ["external-channel-cleanup", "expire-unbound-files"]
