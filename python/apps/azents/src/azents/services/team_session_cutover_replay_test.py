"""Team Session coordinated cutover replay tests."""

import dataclasses
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.enums import AgentRunStatus, AgentSessionKind, AgentSessionRunState
from azents.repos.session_execution import (
    CanonicalExecutionOwnerGenerationStaleError,
    SessionExecutionRepository,
)
from azents.repos.session_execution.cutover_replay import (
    CutoverReplayCandidate,
    CutoverReplayCandidateBatch,
    SessionCutoverReplayRepository,
)
from azents.repos.session_execution.data import CanonicalExecutionSnapshot

from .team_session_cutover_replay import (
    TeamSessionCutoverReplayBarrierLostError,
    TeamSessionCutoverReplayInvariantFailure,
    TeamSessionCutoverReplayService,
)


class _ReplayRepository(SessionCutoverReplayRepository):
    """Replay repository double returning one fixed durable batch."""

    def __init__(self, batch: CutoverReplayCandidateBatch) -> None:
        self.batch = batch
        self.calls: list[tuple[int, str | None]] = []

    async def read_candidate_batch(
        self,
        session: AsyncSession,
        *,
        batch_size: int,
        after_session_id: str | None,
    ) -> CutoverReplayCandidateBatch:
        """Record bounded batch selection without reading transient state."""
        del session
        self.calls.append((batch_size, after_session_id))
        return self.batch

    async def fence_owner_generation(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        expected_owner_generation: int,
    ) -> int:
        """Return the next deterministic cutover fence generation."""
        del session, session_id
        return expected_owner_generation + 1

    async def read_candidate(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> CutoverReplayCandidate | None:
        """Return the same exact work under the fenced generation."""
        del session
        candidate = next(
            candidate
            for candidate in self.batch.candidates
            if candidate.session_id == session_id
        )
        return dataclasses.replace(
            candidate,
            owner_generation=candidate.owner_generation + 1,
        )


class _CanonicalRepository(SessionExecutionRepository):
    """Canonical snapshot loader double."""

    def __init__(
        self,
        snapshots: dict[
            str,
            CanonicalExecutionSnapshot | CanonicalExecutionOwnerGenerationStaleError,
        ],
    ) -> None:
        self.snapshots = snapshots

    async def load_canonical_snapshot(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        owner_generation: int,
    ) -> CanonicalExecutionSnapshot:
        """Return an exact snapshot or the configured stale-generation failure."""
        del session, owner_generation
        snapshot = self.snapshots[session_id]
        if isinstance(snapshot, CanonicalExecutionOwnerGenerationStaleError):
            raise snapshot
        return snapshot


class _Broker:
    """Broker double recording only cutover notification operations."""

    def __init__(
        self,
        *,
        fail_wake_session_id: str | None = None,
        renew_result: bool = True,
    ) -> None:
        self.calls: list[tuple[str, str | SessionWakeUp]] = []
        self.fail_wake_session_id = fail_wake_session_id
        self.renew_result = renew_result

    async def acquire_cutover_replay_barrier(
        self,
        session_ids: tuple[str, ...],
    ) -> str:
        """Record the batch ownership barrier."""
        self.calls.append(("barrier_acquire", ",".join(session_ids)))
        return "barrier-token"

    async def release_cutover_replay_barrier(
        self,
        session_ids: tuple[str, ...],
        token: str,
    ) -> None:
        """Record exact barrier release."""
        self.calls.append(("barrier_release", f"{','.join(session_ids)}:{token}"))

    async def renew_cutover_replay_barrier(
        self,
        session_ids: tuple[str, ...],
        token: str,
    ) -> bool:
        """Record exact barrier lease renewal."""
        self.calls.append(("barrier_renew", f"{','.join(session_ids)}:{token}"))
        return self.renew_result

    async def purge_session_state(self, session_id: str) -> None:
        """Record broker/ownership state discard."""
        self.calls.append(("purge", session_id))

    async def send_message(self, message: SessionWakeUp) -> None:
        """Record one pure Session routing signal."""
        if message.session_id == self.fail_wake_session_id:
            self.fail_wake_session_id = None
            raise RuntimeError("simulated broker interruption")
        self.calls.append(("wake", message))


class _Session:
    """Transaction-capable AsyncSession double."""

    async def commit(self) -> None:
        """Commit the deterministic replay fence."""

    async def rollback(self) -> None:
        """Rollback a rejected replay fence."""


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession, None]:
    """Yield a fake database session for deterministic service tests."""
    yield cast(AsyncSession, _Session())


def _candidate(
    *,
    session_id: str = "session-1",
    has_pending_input: bool = True,
    has_pending_command: bool = False,
    pending_command_complete: bool = True,
    has_recoverable_run: bool = False,
    has_pending_idle_continuation: bool = False,
    has_stop_request: bool = False,
    stop_request_complete: bool = True,
    fifo_input_buffer_id: str | None = None,
) -> CutoverReplayCandidate:
    """Create one content-free durable work candidate."""
    return CutoverReplayCandidate(
        session_id=session_id,
        owner_generation=3,
        run_state=AgentSessionRunState.RUNNING,
        wake_input_present=has_pending_input,
        fifo_input_buffer_id=(
            fifo_input_buffer_id
            if fifo_input_buffer_id is not None
            else ("input-1" if has_pending_input else None)
        ),
        pending_command_present=has_pending_command,
        pending_command_id="command-1" if has_pending_command else None,
        pending_command_complete=pending_command_complete,
        recoverable_run_id="run-1" if has_recoverable_run else None,
        recoverable_run_count=1 if has_recoverable_run else 0,
        pending_idle_continuation_run_id=(
            "idle-run-1" if has_pending_idle_continuation else None
        ),
        stop_request_present=has_stop_request,
        stop_request_id="stop-1" if has_stop_request else None,
        stop_request_complete=stop_request_complete,
    )


def _snapshot(
    session_id: str = "session-1",
    *,
    fifo_input_buffer_id: str | None = "input-1",
) -> CanonicalExecutionSnapshot:
    """Create a matching validated canonical snapshot."""
    return CanonicalExecutionSnapshot(
        session_id=session_id,
        root_session_id="root-session-1",
        workspace_id="workspace-1",
        workspace_handle="workspace",
        agent_id="agent-1",
        session_agent_id="session-agent-1",
        root_session_agent_id="root-session-agent-1",
        session_agent_context_id="context-1",
        execution_mode=AgentSessionKind.ROOT,
        owner_generation=3,
        fifo_input_buffer_id=fifo_input_buffer_id,
        pending_command=None,
        recoverable_run_id=None,
        recoverable_run_status=AgentRunStatus.RUNNING,
        pending_idle_continuation_run_id=None,
    )


def _service(
    candidate: CutoverReplayCandidate,
    snapshot: CanonicalExecutionSnapshot | CanonicalExecutionOwnerGenerationStaleError,
) -> tuple[TeamSessionCutoverReplayService, _ReplayRepository, _Broker, list[None]]:
    """Create one service wired only to deterministic durable test doubles."""
    replay_repository = _ReplayRepository(
        CutoverReplayCandidateBatch(
            candidates=(candidate,),
            next_session_cursor="session-1",
        )
    )
    broker = _Broker()
    broker_provider_calls: list[None] = []

    async def provide_broker() -> SessionBroker:
        broker_provider_calls.append(None)
        return cast(SessionBroker, broker)

    service = TeamSessionCutoverReplayService(
        replay_repository=replay_repository,
        canonical_execution_repository=_CanonicalRepository(
            {candidate.session_id: snapshot}
        ),
        session_manager=_session_manager,
        broker_provider=provide_broker,
    )
    return service, replay_repository, broker, broker_provider_calls


@pytest.mark.asyncio
async def test_replay_discards_broker_state_before_sending_pure_wake_up() -> None:
    """Replay uses durable work and emits only a routing-only SessionWakeUp."""
    service, repository, broker, broker_provider_calls = _service(
        _candidate(), _snapshot()
    )

    report = await service.replay(batch_size=10, after_session_id=None)

    assert report.replayed_sessions == 1
    assert repository.calls == [(10, None)]
    assert broker_provider_calls == [None]
    assert broker.calls == [
        ("barrier_acquire", "session-1"),
        ("barrier_renew", "session-1:barrier-token"),
        ("purge", "session-1"),
        ("barrier_renew", "session-1:barrier-token"),
        ("wake", SessionWakeUp(session_id="session-1")),
        ("barrier_release", "session-1:barrier-token"),
    ]
    wake = broker.calls[4][1]
    assert isinstance(wake, SessionWakeUp)
    assert wake == SessionWakeUp(session_id="session-1")


@pytest.mark.asyncio
async def test_replay_rejects_incomplete_durable_state_without_broker_side_effect() -> (
    None
):
    """An invalid pending command blocks the entire replay batch."""
    candidate = _candidate(
        has_pending_input=False,
        has_pending_command=True,
        pending_command_complete=False,
    )
    service, repository, broker, broker_provider_calls = _service(
        candidate, _snapshot()
    )

    with pytest.raises(TeamSessionCutoverReplayInvariantFailure) as raised:
        await service.replay(batch_size=10, after_session_id=None)

    assert raised.value.invariant_failures == (("pending_command_incomplete", 1),)
    assert repository.calls == [(10, None)]
    assert broker_provider_calls == []
    assert broker.calls == []


@pytest.mark.asyncio
async def test_preflight_rejects_stale_owner_without_broker_effect() -> None:
    """A stale canonical owner generation is not replayable."""
    service, repository, broker, broker_provider_calls = _service(
        _candidate(),
        CanonicalExecutionOwnerGenerationStaleError("stale"),
    )

    report = await service.preflight(batch_size=10, after_session_id=None)

    assert report.valid_sessions == 0
    assert report.invariant_failures == (("owner_generation_stale", 1),)
    assert repository.calls == [(10, None)]
    assert broker_provider_calls == []
    assert broker.calls == []


@pytest.mark.asyncio
async def test_preflight_accepts_older_queue_only_input_before_wake_input() -> None:
    """Wake presence and canonical all-input FIFO identity remain separate."""
    service, _repository, broker, broker_provider_calls = _service(
        _candidate(fifo_input_buffer_id="queue-only-input"),
        _snapshot(fifo_input_buffer_id="queue-only-input"),
    )

    report = await service.preflight(batch_size=10, after_session_id=None)

    assert report.valid_sessions == 1
    assert report.invariant_failures == ()
    assert broker_provider_calls == []
    assert broker.calls == []


@pytest.mark.asyncio
async def test_repeated_replay_is_safe_after_interruption() -> None:
    """Repeated replay re-discards broker state before each pure wake-up."""
    service, _repository, broker, broker_provider_calls = _service(
        _candidate(), _snapshot()
    )

    await service.replay(batch_size=1, after_session_id="session-0")
    await service.replay(batch_size=1, after_session_id="session-0")

    assert broker_provider_calls == [None, None]
    assert broker.calls == [
        ("barrier_acquire", "session-1"),
        ("barrier_renew", "session-1:barrier-token"),
        ("purge", "session-1"),
        ("barrier_renew", "session-1:barrier-token"),
        ("wake", SessionWakeUp(session_id="session-1")),
        ("barrier_release", "session-1:barrier-token"),
        ("barrier_acquire", "session-1"),
        ("barrier_renew", "session-1:barrier-token"),
        ("purge", "session-1"),
        ("barrier_renew", "session-1:barrier-token"),
        ("wake", SessionWakeUp(session_id="session-1")),
        ("barrier_release", "session-1:barrier-token"),
    ]


@pytest.mark.asyncio
async def test_mid_batch_broker_interruption_releases_barrier_and_retries() -> None:
    """A partial broker batch remains safe to replay from PostgreSQL."""
    candidates = (
        _candidate(session_id="session-1"),
        _candidate(session_id="session-2"),
    )
    replay_repository = _ReplayRepository(
        CutoverReplayCandidateBatch(candidates=candidates, next_session_cursor=None)
    )
    broker = _Broker(fail_wake_session_id="session-2")

    async def provide_broker() -> SessionBroker:
        return cast(SessionBroker, broker)

    service = TeamSessionCutoverReplayService(
        replay_repository=replay_repository,
        canonical_execution_repository=_CanonicalRepository(
            {
                "session-1": _snapshot("session-1"),
                "session-2": _snapshot("session-2"),
            }
        ),
        session_manager=_session_manager,
        broker_provider=provide_broker,
    )

    with pytest.raises(RuntimeError, match="simulated broker interruption"):
        await service.replay(batch_size=2, after_session_id=None)
    report = await service.replay(batch_size=2, after_session_id=None)

    assert report.replayed_sessions == 2
    assert broker.calls == [
        ("barrier_acquire", "session-1,session-2"),
        ("barrier_renew", "session-1,session-2:barrier-token"),
        ("purge", "session-1"),
        ("barrier_renew", "session-1,session-2:barrier-token"),
        ("wake", SessionWakeUp(session_id="session-1")),
        ("barrier_renew", "session-1,session-2:barrier-token"),
        ("purge", "session-2"),
        ("barrier_renew", "session-1,session-2:barrier-token"),
        ("barrier_release", "session-1,session-2:barrier-token"),
        ("barrier_acquire", "session-1,session-2"),
        ("barrier_renew", "session-1,session-2:barrier-token"),
        ("purge", "session-1"),
        ("barrier_renew", "session-1,session-2:barrier-token"),
        ("wake", SessionWakeUp(session_id="session-1")),
        ("barrier_renew", "session-1,session-2:barrier-token"),
        ("purge", "session-2"),
        ("barrier_renew", "session-1,session-2:barrier-token"),
        ("wake", SessionWakeUp(session_id="session-2")),
        ("barrier_release", "session-1,session-2:barrier-token"),
    ]


@pytest.mark.asyncio
async def test_lost_barrier_aborts_before_broker_mutation() -> None:
    """Replay exposes barrier loss directly and releases the exact token."""
    candidate = _candidate()
    replay_repository = _ReplayRepository(
        CutoverReplayCandidateBatch(
            candidates=(candidate,),
            next_session_cursor=None,
        )
    )
    broker = _Broker(renew_result=False)

    async def provide_broker() -> SessionBroker:
        return cast(SessionBroker, broker)

    service = TeamSessionCutoverReplayService(
        replay_repository=replay_repository,
        canonical_execution_repository=_CanonicalRepository({"session-1": _snapshot()}),
        session_manager=_session_manager,
        broker_provider=provide_broker,
    )

    with pytest.raises(TeamSessionCutoverReplayBarrierLostError):
        await service.replay(batch_size=1, after_session_id=None)

    assert broker.calls == [
        ("barrier_acquire", "session-1"),
        ("barrier_renew", "session-1:barrier-token"),
        ("barrier_release", "session-1:barrier-token"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("batch_size", (0, 501))
async def test_candidate_repository_rejects_unbounded_batch_size(
    batch_size: int,
) -> None:
    """Repository rejects batch sizes outside the fixed operator bound."""
    repository = SessionCutoverReplayRepository()

    with pytest.raises(ValueError, match="batch_size"):
        await repository.read_candidate_batch(
            cast(AsyncSession, object()),
            batch_size=batch_size,
            after_session_id=None,
        )
