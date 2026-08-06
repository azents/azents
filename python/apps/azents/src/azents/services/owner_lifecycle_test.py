"""Owner lifecycle coordinator tests."""

import datetime
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

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
from azents.repos.owner_lifecycle.data import OwnerLifecycleJob
from azents.services.owner_lifecycle import OwnerLifecycleService


class _SessionDouble:
    """Minimal async session double supporting explicit commit."""

    async def commit(self) -> None:
        """No-op commit used by archive finalization."""
        return None


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession, None]:
    """Yield a placeholder session for repository doubles."""
    yield cast(AsyncSession, _SessionDouble())


def _job(
    *,
    job_id: str,
    kind: OwnerLifecycleKind,
    workspace_id: str | None,
    attempt_count: int = 1,
) -> OwnerLifecycleJob:
    """Build one durable job projection."""
    now = datetime.datetime.now(datetime.UTC)
    return OwnerLifecycleJob(
        id=job_id,
        kind=kind,
        user_id=f"user-{job_id}",
        workspace_id=workspace_id,
        status=OwnerLifecycleStatus.PENDING,
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


@dataclass
class _Root:
    """Root session double."""

    id: str
    status: AgentSessionStatus = AgentSessionStatus.ACTIVE
    run_state: AgentSessionRunState = AgentSessionRunState.IDLE
    product_mode: AgentSessionProductMode | None = AgentSessionProductMode.USER


class _OwnerLifecycleRepositoryDouble:
    """Claim/status/retry recorder for coordinator tests."""

    def __init__(self, jobs: list[OwnerLifecycleJob]) -> None:
        self.jobs = jobs
        self.statuses: list[tuple[str, OwnerLifecycleStatus]] = []
        self.retries: list[tuple[str, str]] = []
        self.completed: list[str] = []

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> OwnerLifecycleJob | None:
        """Return one queued job per claim."""
        del session, now, lease_owner, lease_until
        return self.jobs.pop(0) if self.jobs else None

    async def set_status(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        status: OwnerLifecycleStatus,
        now: datetime.datetime,
    ) -> bool:
        """Record status updates."""
        del session, lease_owner, now
        self.statuses.append((job_id, status))
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

    async def mark_completed(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        now: datetime.datetime,
    ) -> bool:
        """Record completion."""
        del session, lease_owner, now
        self.completed.append(job_id)
        return True


class _SessionRepositoryDouble:
    """Session repository double for owner lifecycle paths."""

    def __init__(
        self,
        *,
        active_roots: list[_Root] | None = None,
        all_roots: list[_Root] | None = None,
        remaining: bool = False,
        tree_active: bool = True,
    ) -> None:
        self.active_roots = active_roots or []
        self.all_roots = all_roots if all_roots is not None else list(self.active_roots)
        self.remaining = remaining
        self.tree_active = tree_active
        self.archived: list[str] = []
        self.stops: list[str] = []

    async def list_active_user_roots_by_workspace_and_user(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        associated_user_id: str,
    ) -> Sequence[_Root]:
        """Return configured active roots."""
        del session, workspace_id, associated_user_id
        return list(self.active_roots)

    async def list_user_roots_by_user(
        self,
        session: AsyncSession,
        *,
        associated_user_id: str,
    ) -> Sequence[_Root]:
        """Return configured roots."""
        del session, associated_user_id
        return list(self.all_roots)

    async def has_any_for_associated_user(
        self,
        session: AsyncSession,
        *,
        associated_user_id: str,
    ) -> bool:
        """Return remaining flag."""
        del session, associated_user_id
        return self.remaining

    async def lock_root_tree_sessions(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
    ) -> Sequence[_Root]:
        """Return a single-node tree."""
        del session
        if not self.tree_active:
            return []
        return [
            _Root(
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
    ) -> object | None:
        """Record stop requests."""
        del session, stop_request_id, stop_requester_user_id
        self.stops.append(session_id)
        return object()

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
        """Record archive."""
        del (
            session,
            session_ids,
            archived_at,
            purge_after,
            policy_revision,
            retention_days,
        )
        self.archived.append(root_session_id)


class _RunRepositoryDouble:
    """Run activity double."""

    def __init__(self, *, active: bool = False) -> None:
        self.active = active

    async def has_active_for_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> bool:
        """Return configured activity."""
        del session, session_ids
        return self.active


class _RetentionSettings:
    """Retention settings double."""

    archived_session_retention_days = 7
    revision = 1


class _RetentionRepositoryDouble:
    """Retention double."""

    def __init__(self) -> None:
        self.scheduled: list[tuple[str, datetime.datetime]] = []

    async def lock_settings(self, session: AsyncSession) -> _RetentionSettings:
        """Return fixed settings."""
        del session
        return _RetentionSettings()

    async def schedule_purge_job(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
        eligible_at: datetime.datetime,
        policy_revision: int,
        now: datetime.datetime,
    ) -> None:
        """Record purge scheduling."""
        del session, policy_revision, now
        self.scheduled.append((root_session_id, eligible_at))


class _MemoryRepositoryDouble:
    """Memory double."""

    def __init__(self) -> None:
        self.deleted_users: list[str] = []

    async def delete_all_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: str,
    ) -> int:
        """Record user-scope memory deletion."""
        del session
        self.deleted_users.append(user_id)
        return 1


class _UserRepositoryDouble:
    """User double."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, session: AsyncSession, user_id: str) -> None:
        """Record final user deletion."""
        del session
        self.deleted.append(user_id)


class _OrchestratorDouble:
    """Lifecycle orchestrator double."""

    async def archive(
        self,
        *,
        context: SessionLifecycleTransitionContext,
        participant_operation: object,
        transition: object,
    ) -> None:
        """Run transition directly."""
        del context, participant_operation
        operation = cast(Callable[[], Awaitable[None]], transition)
        await operation()


class _ExternalChannelDouble:
    """External channel lifecycle double."""

    def __init__(self) -> None:
        self.cleanup_calls = 0

    async def archive_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecycleTransitionContext,
    ) -> None:
        """No-op participant."""
        del session, definition, context
        return None

    async def consume_archive_cleanup(self, plans: object) -> None:
        """Count cleanup consumption."""
        del plans
        self.cleanup_calls += 1


class _BrokerDouble:
    """Broker double."""

    def __init__(self) -> None:
        self.signals: list[str] = []

    async def send_message(self, signal: SessionStopSignal) -> None:
        """Record stop signals."""
        self.signals.append(signal.session_id)


def _service(
    *,
    jobs: list[OwnerLifecycleJob],
    sessions: _SessionRepositoryDouble,
    runs: _RunRepositoryDouble | None = None,
    retention: _RetentionRepositoryDouble | None = None,
    memory: _MemoryRepositoryDouble | None = None,
    users: _UserRepositoryDouble | None = None,
) -> tuple[
    OwnerLifecycleService,
    _OwnerLifecycleRepositoryDouble,
    _RetentionRepositoryDouble,
    _MemoryRepositoryDouble,
    _UserRepositoryDouble,
    _BrokerDouble,
]:
    """Build a coordinator with doubles."""
    lifecycle_repo = _OwnerLifecycleRepositoryDouble(jobs)
    retention_repo = retention or _RetentionRepositoryDouble()
    memory_repo = memory or _MemoryRepositoryDouble()
    user_repo = users or _UserRepositoryDouble()
    broker = _BrokerDouble()
    service = OwnerLifecycleService(
        session_manager=_session_manager,
        owner_lifecycle_repository=lifecycle_repo,
        agent_session_repository=sessions,
        agent_run_repository=runs or _RunRepositoryDouble(),
        retention_repository=retention_repo,
        memory_repository=memory_repo,
        user_repository=user_repo,
        lifecycle_orchestrator=_OrchestratorDouble(),
        external_channel_lifecycle_service=_ExternalChannelDouble(),
        broker=broker,
    )
    return service, lifecycle_repo, retention_repo, memory_repo, user_repo, broker


@pytest.mark.asyncio
async def test_membership_archive_archives_active_user_roots() -> None:
    """Membership archive stops and archives active User roots then completes."""
    job = _job(
        job_id="m1",
        kind=OwnerLifecycleKind.MEMBERSHIP_ARCHIVE,
        workspace_id="workspace-1",
    )
    sessions = _SessionRepositoryDouble(active_roots=[_Root(id="root-1")])
    service, lifecycle_repo, retention, _, _, broker = _service(
        jobs=[job],
        sessions=sessions,
    )

    summary = await service.process_once(
        lease_owner="worker-1",
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5),
    )

    assert summary.claimed_count == 1
    assert summary.completed_count == 1
    assert sessions.archived == ["root-1"]
    assert sessions.stops == ["root-1"]
    assert broker.signals == ["root-1"]
    assert lifecycle_repo.completed == ["m1"]
    assert retention.scheduled
    assert retention.scheduled[0][0] == "root-1"


@pytest.mark.asyncio
async def test_membership_archive_skips_team_scope_by_listing_only_user_roots() -> None:
    """Empty User-root listing completes without archiving Team sessions."""
    job = _job(
        job_id="m2",
        kind=OwnerLifecycleKind.MEMBERSHIP_ARCHIVE,
        workspace_id="workspace-1",
    )
    sessions = _SessionRepositoryDouble(active_roots=[])
    service, lifecycle_repo, retention, _, _, _ = _service(
        jobs=[job],
        sessions=sessions,
    )

    summary = await service.process_once(
        lease_owner="worker-1",
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5),
    )

    assert summary.completed_count == 1
    assert sessions.archived == []
    assert retention.scheduled == []
    assert lifecycle_repo.completed == ["m2"]


@pytest.mark.asyncio
async def test_account_purge_waits_while_session_rows_remain() -> None:
    """Account purge archives immediately-eligible roots then waits for purge."""
    job = _job(
        job_id="p1",
        kind=OwnerLifecycleKind.ACCOUNT_PURGE,
        workspace_id=None,
    )
    sessions = _SessionRepositoryDouble(
        active_roots=[_Root(id="root-p")],
        remaining=True,
    )
    service, lifecycle_repo, retention, memory, users, _ = _service(
        jobs=[job],
        sessions=sessions,
    )

    summary = await service.process_once(
        lease_owner="worker-1",
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5),
    )

    assert summary.claimed_count == 1
    assert summary.completed_count == 0
    assert summary.waiting_purge_count == 1
    assert sessions.archived == ["root-p"]
    assert retention.scheduled
    # Immediate purge eligibility is now-ish.
    assert retention.scheduled[0][1] <= datetime.datetime.now(
        datetime.UTC
    ) + datetime.timedelta(seconds=5)
    assert memory.deleted_users == []
    assert users.deleted == []
    assert lifecycle_repo.retries
    assert lifecycle_repo.retries[0][1] == "WaitingPurge"


@pytest.mark.asyncio
async def test_account_purge_finalizes_user_after_sessions_gone() -> None:
    """Account purge deletes User Memory and User row only after sessions are gone."""
    job = _job(
        job_id="p2",
        kind=OwnerLifecycleKind.ACCOUNT_PURGE,
        workspace_id=None,
    )
    sessions = _SessionRepositoryDouble(active_roots=[], all_roots=[], remaining=False)
    service, lifecycle_repo, _, memory, users, _ = _service(
        jobs=[job],
        sessions=sessions,
    )

    summary = await service.process_once(
        lease_owner="worker-1",
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5),
    )

    assert summary.completed_count == 1
    assert memory.deleted_users == [job.user_id]
    assert users.deleted == [job.user_id]
    assert lifecycle_repo.completed == ["p2"]


@pytest.mark.asyncio
async def test_active_run_defers_archive_with_retry() -> None:
    """Active runs request stop and schedule retry without archiving."""
    job = _job(
        job_id="m3",
        kind=OwnerLifecycleKind.MEMBERSHIP_ARCHIVE,
        workspace_id="workspace-1",
    )
    sessions = _SessionRepositoryDouble(active_roots=[_Root(id="root-run")])
    service, lifecycle_repo, retention, _, _, broker = _service(
        jobs=[job],
        sessions=sessions,
        runs=_RunRepositoryDouble(active=True),
    )

    summary = await service.process_once(
        lease_owner="worker-1",
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5),
    )

    assert summary.completed_count == 0
    assert summary.retry_scheduled_count == 1
    assert sessions.archived == []
    assert retention.scheduled == []
    assert sessions.stops == ["root-run"]
    assert broker.signals == ["root-run"]
    assert lifecycle_repo.retries
