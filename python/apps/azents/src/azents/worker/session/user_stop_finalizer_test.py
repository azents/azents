"""Real PostgreSQL Stop sequencing and completed-operation boundary tests."""

import asyncio
import dataclasses
from datetime import datetime

import pytest

from azents.broker.types import SessionBroker
from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.engine.events.engine_events import RunStopped
from azents.engine.events.types import ActiveToolCall, AgentRunState, Event
from azents.engine.run.emit import PublishedEvent
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.user_stop import UserStopOperationRepository
from azents.repos.user_stop_data import (
    UserStopCancelledCallsInput,
    UserStopDurableEvents,
    UserStopMarkerInput,
    UserStopOwnerInput,
    UserStopPartialInput,
)
from azents.repos.user_stop_test import (
    FaultTranscript,
    StopFixture,
    fault_stop,
    history,
    live_tool,
    partial,
    stop_fixture,
)
from azents.services.chat.live_events import RedisLiveEventStore
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.live.event_projector import LiveEventProjector
from azents.worker.session.lifecycle import SessionLifecycleService
from azents.worker.session.user_stop_finalizer import UserStopFinalizer


class _Broker(SessionBroker):
    """Observe parent-result notification only after committed terminal state."""

    def __init__(self, fixture: StopFixture, trace: list[str]) -> None:
        self.fixture = fixture
        self.trace = trace
        self.notified: list[str] = []

    async def notify_mailbox_activity(self, session_id: str) -> None:
        self.fixture.manager.assert_closed()
        async with self.fixture.manager.manager() as session:
            run = await self.fixture.runs.get_by_id(session, self.fixture.run_id)
            assert run is not None and run.status is AgentRunStatus.STOPPED
            assert run.parent_result_mailbox_item_id is not None
        self.notified.append(session_id)
        self.trace.append("parent-activity")


class _LiveStore(RedisLiveEventStore):
    """Read a live snapshot with no database session retained by the caller."""

    def __init__(
        self, fixture: StopFixture, events: list[Event], trace: list[str]
    ) -> None:
        self.fixture = fixture
        self.events = events
        self.trace = trace

    async def list_by_session_id(self, session_id: str) -> list[Event]:
        assert session_id == self.fixture.owner.session_id
        self.fixture.manager.assert_closed()
        self.trace.append("live-read")
        return list(self.events)


class _Projector(LiveEventProjector):
    """Observe live mutations after prior durable stages have completed."""

    def __init__(self, fixture: StopFixture, trace: list[str]) -> None:
        self.fixture = fixture
        self.trace = trace
        self.removed_events: list[str] = []
        self.removed_calls: list[set[str]] = []

    async def flush_session(self, session_id: str, *, owner_generation: int) -> None:
        assert session_id == self.fixture.owner.session_id
        assert owner_generation == self.fixture.owner.owner_generation
        self.fixture.manager.assert_closed()
        self.trace.append("flush")

    async def remove_event(
        self, session_id: str, event_id: str, *, owner_generation: int
    ) -> None:
        assert session_id == self.fixture.owner.session_id
        assert owner_generation == self.fixture.owner.owner_generation
        self.fixture.manager.assert_closed()
        assert "partial" in self.trace and "cancelled" in self.trace
        self.removed_events.append(event_id)
        self.trace.append("remove")

    async def replace_active_tool_calls(
        self,
        session_id: str,
        active_tool_calls: list[ActiveToolCall],
        *,
        removed_call_ids: set[str],
        owner_generation: int,
    ) -> None:
        assert session_id == self.fixture.owner.session_id
        assert owner_generation == self.fixture.owner.owner_generation
        assert active_tool_calls == []
        self.fixture.manager.assert_closed()
        async with self.fixture.manager.manager() as session:
            run = await self.fixture.runs.get_by_id(session, self.fixture.run_id)
            assert run is not None and run.active_tool_calls == []
        self.removed_calls.append(removed_call_ids)
        self.trace.append("replace")


class _Publisher(WorkerEventPublisher):
    """Observe committed history and uncleared Stop intent at each dispatch."""

    def __init__(
        self, fixture: StopFixture, trace: list[str], fail_at: int | None
    ) -> None:
        self.fixture = fixture
        self.trace = trace
        self.fail_at = fail_at
        self.dispatched: list[PublishedEvent] = []

    async def dispatch_event(
        self,
        session_id: str,
        event: PublishedEvent,
        *,
        owner_generation: int,
    ) -> None:
        assert session_id == self.fixture.owner.session_id
        assert owner_generation == self.fixture.owner.owner_generation
        self.fixture.manager.assert_closed()
        durable = await history(self.fixture)
        assert [item.kind for item in durable][-2:] == [
            EventKind.INTERRUPTED,
            EventKind.RUN_MARKER,
        ]
        async with self.fixture.manager.manager() as session:
            assert await self.fixture.sessions.has_stop_request(session, session_id)
            run = await self.fixture.runs.get_by_id(session, self.fixture.run_id)
            assert run is not None and run.status is AgentRunStatus.STOPPED
        if self.fail_at == len(self.dispatched):
            raise RuntimeError("dispatch unavailable")
        self.dispatched.append(event)
        self.trace.append("dispatch")


@dataclasses.dataclass(frozen=True)
class _StopOperations(UserStopOperationRepository):
    """Record completed stages while executing the real PostgreSQL operations."""

    fixture: StopFixture
    trace: list[str]

    async def append_partial_events(self, input: UserStopPartialInput) -> None:
        await super().append_partial_events(input)
        self.fixture.manager.assert_closed()
        self.trace.append("partial")

    async def append_cancelled_tool_results(
        self, input: UserStopCancelledCallsInput
    ) -> None:
        await super().append_cancelled_tool_results(input)
        self.fixture.manager.assert_closed()
        self.trace.append("cancelled")

    async def append_user_stop_events(
        self, input: UserStopMarkerInput
    ) -> UserStopDurableEvents:
        events = await super().append_user_stop_events(input)
        self.fixture.manager.assert_closed()
        self.trace.append("markers")
        return events

    async def clear_stop_request(self, input: UserStopOwnerInput) -> None:
        await super().clear_stop_request(input)
        self.fixture.manager.assert_closed()
        self.trace.append("clear")


@dataclasses.dataclass(frozen=True)
class _Lifecycle(SessionLifecycleService):
    """Observe terminal completion without bypassing its repository operation."""

    fixture: StopFixture
    trace: list[str]

    async def mark_session_agent_runs_terminal(
        self, session_id: str, *, owner_generation: int, status: AgentRunStatus
    ) -> list[str]:
        transitioned = await super().mark_session_agent_runs_terminal(
            session_id, owner_generation=owner_generation, status=status
        )
        self.fixture.manager.assert_closed()
        self.trace.append("bulk-terminal")
        return transitioned

    async def mark_agent_run_stopped_for_user_stop(
        self, session_id: str, *, owner_generation: int, run_id: str
    ) -> None:
        await super().mark_agent_run_stopped_for_user_stop(
            session_id, owner_generation=owner_generation, run_id=run_id
        )
        self.fixture.manager.assert_closed()
        self.trace.append("terminal")


@dataclasses.dataclass(frozen=True)
class _FinalizerFixture:
    db: StopFixture
    finalizer: UserStopFinalizer
    trace: list[str]
    projector: _Projector
    publisher: _Publisher
    broker: _Broker


async def _finalizer(
    manager: SessionManager[WriteSession],
    name: str,
    *,
    child: bool,
    fail_dispatch_at: int | None,
) -> _FinalizerFixture:
    db = await stop_fixture(manager, name, child=child)
    trace: list[str] = []
    projector = _Projector(db, trace)
    broker = _Broker(db, trace)
    publisher = _Publisher(db, trace, fail_dispatch_at)
    stop = _StopOperations(
        db.manager,
        db.worker,
        db.sessions,
        db.transcripts,
        db.stop.tool_result_repository,
        db,
        trace,
    )
    lifecycle = _Lifecycle(broker, db.worker, db, trace)
    events = [partial(db.owner.session_id, "a" * 32), live_tool(db.owner.session_id)]
    finalizer = UserStopFinalizer(
        stop, _LiveStore(db, events, trace), projector, publisher, lifecycle
    )
    return _FinalizerFixture(db, finalizer, trace, projector, publisher, broker)


async def _finalize(fixture: _FinalizerFixture) -> None:
    await fixture.finalizer.finalize(
        fixture.db.owner.session_id,
        owner_generation=fixture.db.owner.owner_generation,
        run_id=None,
        active_tool_calls=[],
    )


@pytest.mark.parametrize("child", [False, True])
async def test_finalize_persists_live_events_and_preserves_completed_stage_order(
    rdb_session_manager: SessionManager[WriteSession], child: bool
) -> None:
    fixture = await _finalizer(
        rdb_session_manager,
        "stop-finalizer-order",
        child=child,
        fail_dispatch_at=None,
    )
    await _finalize(fixture)
    events = await history(fixture.db)
    assert [event.external_id for event in events] == [
        "a" * 32,
        f"tool-result:{fixture.db.run_id}:call-1",
        f"interrupted:{fixture.db.run_id}:user_requested",
        f"run-marker:{fixture.db.run_id}:interrupted",
    ]
    assert fixture.trace == [
        "flush",
        "live-read",
        "partial",
        "cancelled",
        "remove",
        "remove",
        "replace",
        "terminal",
        *(["parent-activity"] if child else []),
        "markers",
        "dispatch",
        "dispatch",
        "dispatch",
        "clear",
    ]
    assert fixture.projector.removed_events == ["a" * 32, "b" * 32]
    assert fixture.projector.removed_calls == [{"call-1"}]
    assert fixture.publisher.dispatched[:2] == events[-2:]
    stopped = fixture.publisher.dispatched[2]
    assert isinstance(stopped, RunStopped) and stopped.run_id == fixture.db.run_id
    assert fixture.broker.notified == ([fixture.db.parent_session_id] if child else [])
    async with rdb_session_manager() as session:
        assert not await fixture.db.sessions.has_stop_request(
            session, fixture.db.owner.session_id
        )
    fixture.db.manager.assert_closed()


async def test_record_interrupted_run_publishes_history_after_terminal_before_clear(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await _finalizer(
        rdb_session_manager, "stop-record-order", child=True, fail_dispatch_at=None
    )
    await fixture.finalizer.record_interrupted_run(
        fixture.db.owner.session_id,
        owner_generation=fixture.db.owner.owner_generation,
        run_id=fixture.db.run_id,
    )
    assert fixture.trace == [
        "terminal",
        "markers",
        "dispatch",
        "dispatch",
        "dispatch",
        "clear",
    ]
    assert fixture.broker.notified == []
    assert fixture.projector.removed_events == []
    assert [event.kind for event in await history(fixture.db)] == [
        EventKind.INTERRUPTED,
        EventKind.RUN_MARKER,
    ]
    fixture.db.manager.assert_closed()


async def test_finalize_ignores_redis_and_passed_calls_without_durable_ownership(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await _finalizer(
        rdb_session_manager,
        "stop-ignore-stale-calls",
        child=False,
        fail_dispatch_at=None,
    )
    async with rdb_session_manager() as session:
        await fixture.db.runs.update_phase(
            session,
            fixture.db.run_id,
            AgentRunPhase.STREAMING_MODEL,
            active_tool_calls=[],
        )
    await fixture.finalizer.finalize(
        fixture.db.owner.session_id,
        owner_generation=fixture.db.owner.owner_generation,
        run_id=None,
        active_tool_calls=fixture.db.calls,
    )
    assert EventKind.CLIENT_TOOL_RESULT not in [
        event.kind for event in await history(fixture.db)
    ]
    assert fixture.projector.removed_calls == [set()]
    fixture.db.manager.assert_closed()


@pytest.mark.parametrize("record_only", [False, True])
async def test_stale_owner_rejected_before_live_durable_or_external_effects(
    rdb_session_manager: SessionManager[WriteSession], record_only: bool
) -> None:
    fixture = await _finalizer(
        rdb_session_manager,
        "stop-stale-finalizer",
        child=False,
        fail_dispatch_at=None,
    )
    async with rdb_session_manager() as session:
        await fixture.db.sessions.claim_owner_generation(
            session, fixture.db.owner.session_id
        )
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        if record_only:
            await fixture.finalizer.record_interrupted_run(
                fixture.db.owner.session_id,
                owner_generation=fixture.db.owner.owner_generation,
                run_id=fixture.db.run_id,
            )
        else:
            await _finalize(fixture)
    assert fixture.trace == []
    assert await history(fixture.db) == []
    assert fixture.publisher.dispatched == []
    async with rdb_session_manager() as session:
        assert await fixture.db.sessions.has_stop_request(
            session, fixture.db.owner.session_id
        )
    fixture.db.manager.assert_closed()


class _FaultRunRepository(AgentRunRepository):
    """Fail after the actual terminal write to test stage-local rollback."""

    async def mark_stopped_for_user_stop(
        self, session: WriteSession, run_id: str, *, ended_at: datetime
    ) -> AgentRunState | None:
        await super().mark_stopped_for_user_stop(session, run_id, ended_at=ended_at)
        raise RuntimeError("terminal persistence unavailable")


async def test_terminal_failure_keeps_prior_commits_and_stop_intent_for_retry(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await _finalizer(
        rdb_session_manager,
        "stop-terminal-failure",
        child=False,
        fail_dispatch_at=None,
    )
    worker = dataclasses.replace(
        fixture.db.worker, agent_run_repository=_FaultRunRepository()
    )
    finalizer = dataclasses.replace(
        fixture.finalizer,
        session_lifecycle=dataclasses.replace(
            fixture.finalizer.session_lifecycle, repository=worker
        ),
    )
    with pytest.raises(RuntimeError, match="terminal persistence unavailable"):
        await finalizer.finalize(
            fixture.db.owner.session_id,
            owner_generation=fixture.db.owner.owner_generation,
            run_id=None,
            active_tool_calls=[],
        )
    assert [event.kind for event in await history(fixture.db)] == [
        EventKind.ASSISTANT_MESSAGE,
        EventKind.CLIENT_TOOL_RESULT,
    ]
    assert fixture.publisher.dispatched == []
    async with rdb_session_manager() as session:
        run = await fixture.db.runs.get_by_id(session, fixture.db.run_id)
        assert run is not None and run.status is AgentRunStatus.RUNNING
        assert run.active_tool_calls == []
        assert await fixture.db.sessions.has_stop_request(
            session, fixture.db.owner.session_id
        )
    fixture.db.manager.assert_closed()


@pytest.mark.parametrize("cancel", [False, True])
async def test_marker_failure_or_cancellation_preserves_completed_earlier_stages(
    rdb_session_manager: SessionManager[WriteSession], cancel: bool
) -> None:
    fixture = await _finalizer(
        rdb_session_manager,
        "stop-marker-failure",
        child=False,
        fail_dispatch_at=None,
    )
    error = asyncio.CancelledError() if cancel else RuntimeError("marker unavailable")
    stop = fault_stop(fixture.db, FaultTranscript(EventKind.RUN_MARKER, 1, error))
    finalizer = dataclasses.replace(
        fixture.finalizer,
        repository=dataclasses.replace(
            fixture.finalizer.repository,
            event_transcript_repository=stop.event_transcript_repository,
            tool_result_repository=stop.tool_result_repository,
        ),
    )
    with pytest.raises(type(error)):
        await finalizer.finalize(
            fixture.db.owner.session_id,
            owner_generation=fixture.db.owner.owner_generation,
            run_id=None,
            active_tool_calls=[],
        )
    assert [event.kind for event in await history(fixture.db)] == [
        EventKind.ASSISTANT_MESSAGE,
        EventKind.CLIENT_TOOL_RESULT,
    ]
    assert fixture.publisher.dispatched == []
    async with rdb_session_manager() as session:
        run = await fixture.db.runs.get_by_id(session, fixture.db.run_id)
        assert run is not None and run.status is AgentRunStatus.STOPPED
        assert await fixture.db.sessions.has_stop_request(
            session, fixture.db.owner.session_id
        )
    fixture.db.manager.assert_closed()


@pytest.mark.parametrize("fail_at", [0, 1, 2])
async def test_dispatch_failure_keeps_committed_history_and_stop_intent_until_retry(
    rdb_session_manager: SessionManager[WriteSession], fail_at: int
) -> None:
    fixture = await _finalizer(
        rdb_session_manager,
        "stop-dispatch-failure",
        child=False,
        fail_dispatch_at=fail_at,
    )
    with pytest.raises(RuntimeError, match="dispatch unavailable"):
        await _finalize(fixture)
    assert len(fixture.publisher.dispatched) == fail_at
    assert [event.kind for event in await history(fixture.db)] == [
        EventKind.ASSISTANT_MESSAGE,
        EventKind.CLIENT_TOOL_RESULT,
        EventKind.INTERRUPTED,
        EventKind.RUN_MARKER,
    ]
    assert "clear" not in fixture.trace
    async with rdb_session_manager() as session:
        assert await fixture.db.sessions.has_stop_request(
            session, fixture.db.owner.session_id
        )
    fixture.publisher.fail_at = None
    await fixture.finalizer.record_interrupted_run(
        fixture.db.owner.session_id,
        owner_generation=fixture.db.owner.owner_generation,
        run_id=fixture.db.run_id,
    )
    assert len(await history(fixture.db)) == 4
    async with rdb_session_manager() as session:
        assert not await fixture.db.sessions.has_stop_request(
            session, fixture.db.owner.session_id
        )
    fixture.db.manager.assert_closed()


async def test_no_effective_run_clears_stop_without_fabricated_markers(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await _finalizer(
        rdb_session_manager,
        "stop-no-effective-run",
        child=False,
        fail_dispatch_at=None,
    )
    await fixture.db.worker.mark_agent_run_stopped_for_user_stop(
        fixture.db.owner.session_id,
        owner_generation=fixture.db.owner.owner_generation,
        run_id=fixture.db.run_id,
    )
    await _finalize(fixture)
    assert [event.kind for event in await history(fixture.db)] == [
        EventKind.ASSISTANT_MESSAGE
    ]
    assert fixture.publisher.dispatched == []
    assert fixture.broker.notified == []
    assert fixture.trace == [
        "flush",
        "live-read",
        "partial",
        "cancelled",
        "remove",
        "remove",
        "replace",
        "bulk-terminal",
        "clear",
    ]
    async with rdb_session_manager() as session:
        assert not await fixture.db.sessions.has_stop_request(
            session, fixture.db.owner.session_id
        )
    fixture.db.manager.assert_closed()
