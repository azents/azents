"""UserStopFinalizer tests."""

import asyncio
import gc
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionOwnershipLostError
from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.engine.events.engine_events import RunStopped
from azents.engine.events.types import (
    ActiveToolCall,
    AgentRunState,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    InterruptedPayload,
    NativeArtifact,
    OutputTextPart,
    RunMarkerPayload,
    validate_event_payload,
)
from azents.engine.run.emit import PublishedEvent
from azents.repos.agent_execution.data import EventCreate
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.session import user_stop_finalizer as user_stop_finalizer_module
from azents.worker.session.user_stop_finalizer import UserStopFinalizer


class _SessionScope(AbstractAsyncContextManager[AsyncSession]):
    """DB session context for tests."""

    def __init__(self, manager: "_SessionManager") -> None:
        self.manager = manager
        self.session = cast(AsyncSession, object())

    async def __aenter__(self) -> AsyncSession:
        """Return test session."""
        self.manager.active_sessions += 1
        return self.session

    async def __aexit__(self, *exc_info: object) -> None:
        """No resources to clean up."""
        self.manager.active_sessions -= 1


class _SessionManager:
    """session manager for tests."""

    def __init__(self) -> None:
        self.active_sessions = 0

    def __call__(self) -> _SessionScope:
        """Return new session scope."""
        return _SessionScope(self)


class _EventPublisher:
    """worker event publisher for tests."""

    def __init__(self, session_manager: _SessionManager) -> None:
        self.session_manager = session_manager
        self.dispatched: list[tuple[str, PublishedEvent]] = []
        self.dispatched_with_open_db_session = False
        self.fail_next_dispatch = False
        self.lose_ownership_next_dispatch = False
        self.hang_next_dispatch = False
        self.hang_event_kinds: set[EventKind] = set()
        self.block_next_dispatch_started: asyncio.Event | None = None
        self.block_next_dispatch_release: asyncio.Event | None = None
        self.ownership_loss_raised: asyncio.Event | None = None

    async def dispatch_event(
        self,
        session_id: str,
        event: PublishedEvent,
    ) -> None:
        """Record publish request."""
        if self.session_manager.active_sessions:
            self.dispatched_with_open_db_session = True
        if (
            self.block_next_dispatch_started is not None
            and self.block_next_dispatch_release is not None
        ):
            started = self.block_next_dispatch_started
            release = self.block_next_dispatch_release
            self.block_next_dispatch_started = None
            self.block_next_dispatch_release = None
            started.set()
            await release.wait()
        if self.fail_next_dispatch:
            self.fail_next_dispatch = False
            raise RuntimeError("event publisher unavailable")
        if self.lose_ownership_next_dispatch:
            self.lose_ownership_next_dispatch = False
            if self.ownership_loss_raised is not None:
                self.ownership_loss_raised.set()
            raise SessionOwnershipLostError(session_id)
        if self.hang_next_dispatch:
            self.hang_next_dispatch = False
            await asyncio.Event().wait()
        if isinstance(event, Event) and event.kind in self.hang_event_kinds:
            self.hang_event_kinds.remove(event.kind)
            await asyncio.Event().wait()
        self.dispatched.append((session_id, event))


class _AgentRunRepository:
    """AgentRunRepository test double."""

    def __init__(self, running_run: AgentRunState | None) -> None:
        self.running_run = running_run
        self.active_candidate_override: AgentRunState | None = None
        self.terminal_sessions: list[tuple[str, AgentRunStatus]] = []
        self.terminal_runs: list[tuple[str, AgentRunStatus]] = []
        self.terminal_result_event_id: str | None = None
        self.terminal_result_message: str | None = None
        self.fail_terminal = False

    async def lock_by_id(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> AgentRunState | None:
        """Return the running Run as a locked projection."""
        del session, run_id
        return self.running_run

    async def update_phase(
        self,
        session: AsyncSession,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> object:
        """Apply active-call cleanup to the test projection."""
        del session, run_id, phase
        if self.running_run is not None and active_tool_calls is not None:
            self.running_run = self.running_run.model_copy(
                update={"active_tool_calls": list(active_tool_calls)}
            )
        return object()

    async def get_running_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> AgentRunState | None:
        """Return running AgentRun projection."""
        del session, session_id
        return self.running_run

    async def get_active_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> AgentRunState | None:
        """Return the active fixture Run only while pending or running."""
        del session, session_id
        if self.active_candidate_override is not None:
            return self.active_candidate_override
        if self.running_run is None or self.running_run.status not in {
            AgentRunStatus.PENDING,
            AgentRunStatus.RUNNING,
        }:
            return None
        return self.running_run

    async def list_latest_by_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> dict[str, AgentRunState]:
        """Return the fixture Run as the latest projection."""
        del session
        if self.running_run is None or self.running_run.session_id not in session_ids:
            return {}
        return {self.running_run.session_id: self.running_run}

    async def mark_session_running_terminal(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        status: AgentRunStatus,
        ended_at: datetime,
    ) -> object:
        """Record session-level terminal transition request."""
        del session, ended_at
        self.terminal_sessions.append((session_id, status))
        return object()

    async def mark_terminal_if_running(
        self,
        session: AsyncSession,
        run_id: str,
        status: AgentRunStatus,
        *,
        ended_at: datetime,
        last_completed_event_id: str | None = None,
        terminal_result_event_id: str | None = None,
        terminal_result_message: str | None = None,
    ) -> object:
        """Record run-level terminal transition request."""
        del session
        if self.fail_terminal:
            raise RuntimeError("terminal persistence unavailable")
        self.terminal_runs.append((run_id, status))
        self.terminal_result_event_id = terminal_result_event_id
        self.terminal_result_message = terminal_result_message
        if self.running_run is not None:
            self.running_run = self.running_run.model_copy(
                update={
                    "status": status,
                    "phase": AgentRunPhase.IDLE,
                    "active_tool_calls": [],
                    "ended_at": ended_at,
                    "last_completed_event_id": last_completed_event_id,
                    "terminal_result_event_id": terminal_result_event_id,
                    "terminal_result_message": terminal_result_message,
                }
            )
        return object()

    async def mark_terminal(
        self,
        session: AsyncSession,
        run_id: str,
        status: AgentRunStatus,
        *,
        ended_at: datetime,
        last_completed_event_id: str | None = None,
        terminal_result_event_id: str | None = None,
        terminal_result_message: str | None = None,
    ) -> object:
        """Record an unconditional terminal transition request."""
        return await self.mark_terminal_if_running(
            session,
            run_id,
            status,
            ended_at=ended_at,
            last_completed_event_id=last_completed_event_id,
            terminal_result_event_id=terminal_result_event_id,
            terminal_result_message=terminal_result_message,
        )

    async def mark_stopped_for_user_stop(
        self,
        session: AsyncSession,
        run_id: str,
        *,
        ended_at: datetime,
        last_completed_event_id: str | None = None,
        terminal_result_event_id: str | None = None,
        terminal_result_message: str | None = None,
    ) -> object:
        """Record the explicit User-stop convergence used by production."""
        return await self.mark_terminal_if_running(
            session,
            run_id,
            AgentRunStatus.STOPPED,
            ended_at=ended_at,
            last_completed_event_id=last_completed_event_id,
            terminal_result_event_id=terminal_result_event_id,
            terminal_result_message=terminal_result_message,
        )


class _EventTranscriptRepository:
    """EventTranscriptRepository test double."""

    def __init__(self) -> None:
        self.existing_events: dict[str, Event] = {}
        self.appended: list[EventCreate] = []

    async def get_by_external_id(
        self,
        session: AsyncSession,
        session_id: str,
        external_id: str,
    ) -> object | None:
        """Return whether external_id exists."""
        del session, session_id
        return self.existing_events.get(external_id)

    async def append(self, session: AsyncSession, create: EventCreate) -> Event:
        """Record append request."""
        del session
        self.appended.append(create)
        event = Event(
            id=f"{len(self.appended):032x}",
            session_id=create.session_id,
            kind=create.kind,
            payload=validate_event_payload(create.kind, create.payload),
            model_order=len(self.appended) * 1000,
            external_id=create.external_id,
            adapter=create.adapter,
            provider=create.provider,
            model=create.model,
            native_format=create.native_format,
            schema_version=create.schema_version,
            created_at=datetime.now(UTC),
        )
        if create.external_id is not None:
            self.existing_events[create.external_id] = event
        return event


class _AgentSessionRepository:
    """AgentSessionRepository test double."""

    def __init__(self, *, stop_requested_at: datetime | None = None) -> None:
        self.stop_requested_at = stop_requested_at
        self.cleared_stop_request_session_ids: list[str] = []

    async def lock_by_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> object:
        """Return a locked Session sentinel."""
        del session, session_id
        return SimpleNamespace(stop_requested_at=self.stop_requested_at)

    async def clear_stop_request(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> object:
        """Record stop request clear request."""
        del session
        self.cleared_stop_request_session_ids.append(session_id)
        self.stop_requested_at = None
        return object()


class _LiveEventStore:
    """RedisLiveEventStore test double."""

    def __init__(self, events: Sequence[Event]) -> None:
        self.events = list(events)

    async def list_by_session_id(self, session_id: str) -> Sequence[Event]:
        """Return live event list of session."""
        del session_id
        return self.events


class _HangingLiveEventStore:
    """Redis test double that never completes a read on its own."""

    async def list_by_session_id(self, session_id: str) -> Sequence[Event]:
        """Wait until the finalizer's per-step timeout cancels this read."""
        del session_id
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _FailingSecondLiveEventStore(_LiveEventStore):
    """Redis test double that fails the post-commit cleanup read."""

    def __init__(self, events: Sequence[Event]) -> None:
        super().__init__(events)
        self.calls = 0

    async def list_by_session_id(self, session_id: str) -> Sequence[Event]:
        """Return the pre-commit snapshot, then fail the cleanup refresh."""
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("redis unavailable")
        return await super().list_by_session_id(session_id)


class _AppendingAfterSnapshotLiveEventStore(_LiveEventStore):
    """Redis test double that receives a new delta after returning the snapshot."""

    def __init__(self, events: Sequence[Event], new_event: Event) -> None:
        super().__init__(events)
        self.new_event = new_event
        self.calls = 0

    async def list_by_session_id(self, session_id: str) -> Sequence[Event]:
        """Return a stable snapshot, then expose a newly arrived live event."""
        del session_id
        self.calls += 1
        snapshot = tuple(self.events)
        if self.calls == 1:
            self.events.append(self.new_event)
        return snapshot


class _LiveEventProjector:
    """LiveEventProjector test double."""

    def __init__(self) -> None:
        self.flushed_session_ids: list[str] = []
        self.removed_events: list[tuple[str, str]] = []
        self.removed_active_call_ids: list[set[str]] = []
        self.cleared_live_runs: list[tuple[str, str]] = []
        self.orphan_cleared_session_ids: list[str] = []

    async def flush_session(self, session_id: str) -> None:
        """Record flush request."""
        self.flushed_session_ids.append(session_id)

    async def remove_event(
        self,
        session_id: str,
        event_id: str,
        *,
        run_id: str,
    ) -> None:
        """Record remove request."""
        del run_id
        self.removed_events.append((session_id, event_id))

    async def replace_active_tool_calls(
        self,
        session_id: str,
        active_tool_calls: list[ActiveToolCall],
        *,
        run_id: str,
        removed_call_ids: set[str],
    ) -> None:
        """Record deterministic active-call removals."""
        del session_id, run_id
        assert active_tool_calls == []
        self.removed_active_call_ids.append(removed_call_ids)

    async def publish_live_run_cleared(
        self,
        session_id: str,
        *,
        run_id: str,
    ) -> None:
        """Record live Run clear broadcasts."""
        self.cleared_live_runs.append((session_id, run_id))

    async def clear_session_if_no_active_run(self, session_id: str) -> bool:
        """Record authority-aware orphan projection cleanup."""
        self.orphan_cleared_session_ids.append(session_id)
        return True


class _Broker:
    """Session activity broker test double."""

    def __init__(self) -> None:
        self.cleared_session_ids: list[str] = []
        self.cleared = asyncio.Event()

    async def clear_session_activity(self, session_id: str) -> None:
        """Record activity clear request."""
        self.cleared_session_ids.append(session_id)
        self.cleared.set()

    async def clear_session_activity_for_run(
        self,
        session_id: str,
        *,
        run_id: str,
    ) -> None:
        """Record activity clear request for one authoritative Run."""
        del run_id
        self.cleared_session_ids.append(session_id)
        self.cleared.set()


def _native_artifact() -> NativeArtifact:
    """Create native artifact for tests."""
    return NativeArtifact(
        compat_key="azents-live:live_projection:azents:live:1",
        adapter="azents-live",
        native_format="live_projection",
        provider="azents",
        model="live",
        schema_version="1",
        item={"live_projection": "test"},
    )


def _assistant_event(session_id: str) -> Event:
    """Create assistant live event for tests."""
    return Event(
        id="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        session_id=session_id,
        kind=EventKind.ASSISTANT_MESSAGE,
        payload=AssistantMessagePayload(
            content="partial",
            attachments=[],
            native_artifact=_native_artifact(),
        ),
        created_at=datetime.now(UTC),
    )


def _tool_call_event(session_id: str) -> Event:
    """Create client tool call live event for tests."""
    return Event(
        id="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        session_id=session_id,
        kind=EventKind.CLIENT_TOOL_CALL,
        payload=ClientToolCallPayload(
            call_id="call-1",
            name="bash",
            arguments="{}",
            native_artifact=_native_artifact(),
        ),
        created_at=datetime.now(UTC),
    )


def _running_run(session_id: str) -> AgentRunState:
    """Create running AgentRunState for tests."""
    now = datetime.now(UTC)
    return AgentRunState(
        id="11111111111111111111111111111111",
        session_id=session_id,
        run_index=1,
        phase=AgentRunPhase.STREAMING_MODEL,
        status=AgentRunStatus.RUNNING,
        parent_agent_run_id=None,
        active_tool_calls=[
            ActiveToolCall(
                call_id="call-1",
                name="bash",
                arguments="{}",
                started_at=now,
                owner_generation=1,
            )
        ],
        last_completed_event_id=None,
        stop_requested_at=None,
        created_at=now,
        started_at=now,
        model_call_started_at=now,
        ended_at=None,
        updated_at=now,
    )


def _finalizer(
    *,
    running_run: AgentRunState | None,
    live_events: Sequence[Event],
    stop_requested_at: datetime | None = None,
    live_event_store: object | None = None,
) -> tuple[
    UserStopFinalizer,
    _AgentRunRepository,
    _AgentSessionRepository,
    _EventTranscriptRepository,
    _LiveEventProjector,
    _Broker,
    _EventPublisher,
]:
    """Create subject under test and main dependency doubles."""
    run_repository = _AgentRunRepository(running_run)
    session_repository = _AgentSessionRepository(
        stop_requested_at=stop_requested_at,
    )
    transcript_repository = _EventTranscriptRepository()
    projector = _LiveEventProjector()
    broker = _Broker()
    session_manager = _SessionManager()
    event_publisher = _EventPublisher(session_manager)
    finalizer = UserStopFinalizer(
        session_manager=session_manager,
        agent_run_repository=cast(Any, run_repository),
        agent_session_repository=cast(Any, session_repository),
        event_transcript_repository=cast(Any, transcript_repository),
        live_event_store=cast(
            Any,
            live_event_store or _LiveEventStore(live_events),
        ),
        live_event_projector=cast(Any, projector),
        event_publisher=cast(WorkerEventPublisher, event_publisher),
        broker=cast(Any, broker),
    )
    return (
        finalizer,
        run_repository,
        session_repository,
        transcript_repository,
        projector,
        broker,
        event_publisher,
    )


@pytest.mark.asyncio
async def test_finalize_persists_live_events_and_marks_run_terminal() -> None:
    """User stop full finalize cleans up live projection and run state."""
    session_id = "session-001"
    (
        finalizer,
        run_repository,
        session_repository,
        transcripts,
        projector,
        broker,
        event_publisher,
    ) = _finalizer(
        running_run=_running_run(session_id),
        live_events=[_assistant_event(session_id), _tool_call_event(session_id)],
    )

    await finalizer.finalize(
        session_id,
        run_id=None,
        active_tool_calls=[],
    )

    appended_external_ids = [event.external_id for event in transcripts.appended]
    assert appended_external_ids == [
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "tool-result:11111111111111111111111111111111:call-1",
        "interrupted:11111111111111111111111111111111:user_requested",
        "run-marker:11111111111111111111111111111111:interrupted",
    ]
    interrupted = transcripts.appended[2]
    marker = transcripts.appended[3]
    assert interrupted.kind == EventKind.INTERRUPTED
    assert isinstance(
        InterruptedPayload.model_validate(interrupted.payload),
        InterruptedPayload,
    )
    assert marker.kind == EventKind.RUN_MARKER
    assert isinstance(RunMarkerPayload.model_validate(marker.payload), RunMarkerPayload)
    assert projector.flushed_session_ids == [session_id]
    assert projector.removed_events == [
        (session_id, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"),
    ]
    assert projector.removed_active_call_ids == [{"call-1"}]
    assert run_repository.terminal_runs == [
        ("11111111111111111111111111111111", AgentRunStatus.STOPPED)
    ]
    assert run_repository.terminal_sessions == []
    assert run_repository.running_run is not None
    assert run_repository.running_run.active_tool_calls == []
    assert run_repository.terminal_result_event_id == (
        "00000000000000000000000000000001"
    )
    assert run_repository.terminal_result_message == "partial"
    assert session_repository.cleared_stop_request_session_ids == [session_id]
    assert broker.cleared_session_ids == [session_id]
    assert [
        event.kind if isinstance(event, Event) else type(event)
        for _, event in event_publisher.dispatched
    ] == [
        EventKind.INTERRUPTED,
        EventKind.RUN_MARKER,
        RunStopped,
        EventKind.ASSISTANT_MESSAGE,
        EventKind.CLIENT_TOOL_RESULT,
    ]
    assert all(
        dispatched_session_id == session_id
        for dispatched_session_id, _ in event_publisher.dispatched
    )
    assert event_publisher.dispatched_with_open_db_session is False
    stopped_event = next(
        event
        for _, event in event_publisher.dispatched
        if isinstance(event, RunStopped)
    )
    assert isinstance(stopped_event, RunStopped)
    assert stopped_event.run_id == "11111111111111111111111111111111"
    assert projector.cleared_live_runs == [
        (session_id, "11111111111111111111111111111111")
    ]


@pytest.mark.asyncio
async def test_finalize_preserves_recovery_state_when_terminal_persistence_fails() -> (
    None
):
    """Stop intent and activity remain available for retry after DB failure."""
    session_id = "session-001"
    (
        finalizer,
        run_repository,
        session_repository,
        _,
        _,
        broker,
        event_publisher,
    ) = _finalizer(running_run=_running_run(session_id), live_events=[])
    run_repository.fail_terminal = True

    with pytest.raises(RuntimeError, match="terminal persistence unavailable"):
        await finalizer.finalize(
            session_id,
            run_id=None,
            active_tool_calls=[],
        )

    assert session_repository.cleared_stop_request_session_ids == []
    assert broker.cleared_session_ids == []
    assert event_publisher.dispatched == []


@pytest.mark.asyncio
async def test_record_interrupted_run_publishes_committed_history_and_live_clear() -> (
    None
):
    """CancelledError path publishes stop history and clears live state."""
    session_id = "session-001"
    run_id = "22222222222222222222222222222222"
    running_run = _running_run(session_id).model_copy(
        update={"id": run_id, "active_tool_calls": []}
    )
    (
        finalizer,
        run_repository,
        session_repository,
        transcripts,
        projector,
        broker,
        event_publisher,
    ) = _finalizer(running_run=running_run, live_events=[])

    await finalizer.record_interrupted_run(
        session_id,
        run_id=run_id,
        active_tool_calls=(),
    )

    assert [event.external_id for event in transcripts.appended] == [
        "interrupted:22222222222222222222222222222222:user_requested",
        "run-marker:22222222222222222222222222222222:interrupted",
    ]
    assert [event.kind for event in transcripts.appended] == [
        EventKind.INTERRUPTED,
        EventKind.RUN_MARKER,
    ]
    assert [
        event.kind if isinstance(event, Event) else type(event)
        for _, event in event_publisher.dispatched
    ] == [EventKind.INTERRUPTED, EventKind.RUN_MARKER, RunStopped]
    stopped_event = event_publisher.dispatched[-1][1]
    assert isinstance(stopped_event, RunStopped)
    assert stopped_event.run_id == "22222222222222222222222222222222"
    assert session_repository.cleared_stop_request_session_ids == [session_id]
    assert projector.flushed_session_ids == [session_id]
    assert projector.removed_events == []
    assert projector.cleared_live_runs == [
        (session_id, "22222222222222222222222222222222")
    ]
    assert broker.cleared_session_ids == [session_id]
    assert event_publisher.dispatched_with_open_db_session is False
    assert run_repository.terminal_runs == [
        ("22222222222222222222222222222222", AgentRunStatus.STOPPED)
    ]
    assert run_repository.terminal_sessions == []


@pytest.mark.asyncio
async def test_record_interrupted_run_recovers_engine_terminalization() -> None:
    """An exact user-stop retry canonicalizes an engine INTERRUPTED Run."""
    session_id = "session-001"
    run_id = "22222222222222222222222222222222"
    partial_event_id = "33333333333333333333333333333333"
    active_call = _running_run(session_id).active_tool_calls[0]
    interrupted_run = _running_run(session_id).model_copy(
        update={
            "id": run_id,
            "status": AgentRunStatus.INTERRUPTED,
            "phase": AgentRunPhase.IDLE,
            "active_tool_calls": [],
            "last_completed_event_id": "44444444444444444444444444444444",
            "terminal_result_event_id": partial_event_id,
            "terminal_result_message": "durable partial",
            "ended_at": datetime.now(UTC),
        }
    )
    live_assistant = _assistant_event(session_id)
    live_tool_call = _tool_call_event(session_id)
    (
        finalizer,
        run_repository,
        session_repository,
        transcripts,
        projector,
        broker,
        event_publisher,
    ) = _finalizer(
        running_run=interrupted_run,
        live_events=[live_assistant, live_tool_call],
    )
    transcripts.existing_events[live_assistant.id] = live_assistant.model_copy(
        update={"id": partial_event_id, "external_id": live_assistant.id}
    )
    tool_call_external_id = f"tool-call:{run_id}:{active_call.call_id}"
    transcripts.existing_events[tool_call_external_id] = live_tool_call.model_copy(
        update={
            "id": "55555555555555555555555555555555",
            "external_id": tool_call_external_id,
        }
    )
    tool_result_external_id = f"tool-result:{run_id}:{active_call.call_id}"
    transcripts.existing_events[tool_result_external_id] = Event(
        id="66666666666666666666666666666666",
        session_id=session_id,
        kind=EventKind.CLIENT_TOOL_RESULT,
        payload=ClientToolResultPayload(
            call_id=active_call.call_id,
            name=active_call.name,
            status="cancelled",
            output=[OutputTextPart(text="cancelled")],
        ),
        external_id=tool_result_external_id,
        created_at=datetime.now(UTC),
    )
    marker_external_id = f"run-marker:{run_id}:interrupted"
    transcripts.existing_events[marker_external_id] = Event(
        id="77777777777777777777777777777777",
        session_id=session_id,
        kind=EventKind.RUN_MARKER,
        payload=RunMarkerPayload(run_id=run_id, status="interrupted"),
        external_id=marker_external_id,
        created_at=datetime.now(UTC),
    )

    await finalizer.record_interrupted_run(
        session_id,
        run_id=run_id,
        active_tool_calls=[active_call],
    )

    assert [event.external_id for event in transcripts.appended] == [
        f"interrupted:{run_id}:user_requested"
    ]
    assert run_repository.terminal_runs == [(run_id, AgentRunStatus.STOPPED)]
    assert run_repository.running_run is not None
    assert run_repository.running_run.status == AgentRunStatus.STOPPED
    assert run_repository.running_run.last_completed_event_id == (
        "44444444444444444444444444444444"
    )
    assert run_repository.terminal_result_event_id == partial_event_id
    assert run_repository.terminal_result_message == "durable partial"
    assert session_repository.cleared_stop_request_session_ids == [session_id]
    assert [
        event.kind if isinstance(event, Event) else type(event)
        for _, event in event_publisher.dispatched
    ] == [
        EventKind.INTERRUPTED,
        EventKind.RUN_MARKER,
        RunStopped,
        EventKind.ASSISTANT_MESSAGE,
        EventKind.CLIENT_TOOL_RESULT,
    ]
    assert projector.removed_events == [
        (session_id, live_assistant.id),
        (session_id, live_tool_call.id),
    ]
    assert projector.removed_active_call_ids == [{active_call.call_id}]
    assert projector.cleared_live_runs == [(session_id, run_id)]
    assert broker.cleared_session_ids == [session_id]


@pytest.mark.asyncio
async def test_finalize_recovers_latest_terminal_run_for_current_stop_intent() -> None:
    """A restarted finalizer recovers the Run terminalized by the current stop."""
    session_id = "session-001"
    stop_requested_at = datetime.now(UTC)
    run_id = "22222222222222222222222222222222"
    interrupted_run = _running_run(session_id).model_copy(
        update={
            "id": run_id,
            "status": AgentRunStatus.INTERRUPTED,
            "phase": AgentRunPhase.IDLE,
            "active_tool_calls": [],
            "stop_requested_at": stop_requested_at,
            # Exact durable correlation is authoritative across host clock skew.
            "ended_at": stop_requested_at - timedelta(milliseconds=1),
        }
    )
    (
        finalizer,
        run_repository,
        session_repository,
        transcripts,
        projector,
        broker,
        event_publisher,
    ) = _finalizer(
        running_run=interrupted_run,
        live_events=[],
        stop_requested_at=stop_requested_at,
    )

    finalized_run_id = await finalizer.finalize(
        session_id,
        run_id=None,
        active_tool_calls=[],
    )

    assert finalized_run_id == run_id
    assert run_repository.terminal_runs == [(run_id, AgentRunStatus.STOPPED)]
    assert [event.external_id for event in transcripts.appended] == [
        f"interrupted:{run_id}:user_requested",
        f"run-marker:{run_id}:interrupted",
    ]
    assert [
        event.kind if isinstance(event, Event) else type(event)
        for _, event in event_publisher.dispatched
    ] == [EventKind.INTERRUPTED, EventKind.RUN_MARKER, RunStopped]
    assert session_repository.cleared_stop_request_session_ids == [session_id]
    assert projector.cleared_live_runs == [(session_id, run_id)]
    assert broker.cleared_session_ids == [session_id]


@pytest.mark.asyncio
async def test_finalize_recovers_run_terminalized_between_lookup_and_lock() -> None:
    """A Run that stops after active lookup still receives stop history."""
    session_id = "session-001"
    stop_requested_at = datetime.now(UTC)
    run_id = "22222222222222222222222222222222"
    active_candidate = _running_run(session_id).model_copy(
        update={"id": run_id, "stop_requested_at": stop_requested_at}
    )
    interrupted_run = active_candidate.model_copy(
        update={
            "status": AgentRunStatus.INTERRUPTED,
            "phase": AgentRunPhase.IDLE,
            "active_tool_calls": [],
            "ended_at": stop_requested_at + timedelta(milliseconds=1),
        }
    )
    (
        finalizer,
        run_repository,
        session_repository,
        transcripts,
        projector,
        broker,
        event_publisher,
    ) = _finalizer(
        running_run=interrupted_run,
        live_events=[],
        stop_requested_at=stop_requested_at,
    )
    run_repository.active_candidate_override = active_candidate

    finalized_run_id = await finalizer.finalize(
        session_id,
        run_id=None,
        active_tool_calls=[],
    )

    assert finalized_run_id == run_id
    assert run_repository.terminal_runs == [(run_id, AgentRunStatus.STOPPED)]
    assert [event.external_id for event in transcripts.appended] == [
        f"interrupted:{run_id}:user_requested",
        f"run-marker:{run_id}:interrupted",
    ]
    assert [
        event.kind if isinstance(event, Event) else type(event)
        for _, event in event_publisher.dispatched
    ] == [EventKind.INTERRUPTED, EventKind.RUN_MARKER, RunStopped]
    assert session_repository.cleared_stop_request_session_ids == [session_id]
    assert projector.cleared_live_runs == [(session_id, run_id)]
    assert broker.cleared_session_ids == [session_id]


@pytest.mark.asyncio
async def test_finalize_does_not_recover_terminal_run_older_than_stop_intent() -> None:
    """A new stop-only intent must not attach to an older terminal Run."""
    session_id = "session-001"
    stop_requested_at = datetime.now(UTC)
    old_run = _running_run(session_id).model_copy(
        update={
            "status": AgentRunStatus.STOPPED,
            "phase": AgentRunPhase.IDLE,
            "active_tool_calls": [],
            "ended_at": stop_requested_at - timedelta(seconds=1),
        }
    )
    (
        finalizer,
        run_repository,
        session_repository,
        transcripts,
        projector,
        broker,
        event_publisher,
    ) = _finalizer(
        running_run=old_run,
        live_events=[],
        stop_requested_at=stop_requested_at,
    )

    finalized_run_id = await finalizer.finalize(
        session_id,
        run_id=None,
        active_tool_calls=[],
    )

    assert finalized_run_id is None
    assert run_repository.terminal_runs == []
    assert transcripts.appended == []
    assert event_publisher.dispatched == []
    assert session_repository.cleared_stop_request_session_ids == [session_id]
    assert projector.cleared_live_runs == []
    assert broker.cleared_session_ids == [session_id]


@pytest.mark.asyncio
async def test_explicit_legacy_terminal_does_not_clear_newer_stop_intent() -> None:
    """A delayed legacy finalizer cannot consume a later stop-only request."""
    session_id = "session-001"
    stop_requested_at = datetime.now(UTC)
    old_run = _running_run(session_id).model_copy(
        update={
            "status": AgentRunStatus.STOPPED,
            "phase": AgentRunPhase.IDLE,
            "active_tool_calls": [],
            "stop_requested_at": None,
            "ended_at": stop_requested_at - timedelta(seconds=1),
        }
    )
    (
        finalizer,
        run_repository,
        session_repository,
        transcripts,
        projector,
        broker,
        event_publisher,
    ) = _finalizer(
        running_run=old_run,
        live_events=[],
        stop_requested_at=stop_requested_at,
    )

    finalized_run_id = await finalizer.finalize(
        session_id,
        run_id=old_run.id,
        active_tool_calls=[],
    )

    assert finalized_run_id == old_run.id
    assert run_repository.terminal_runs == []
    assert session_repository.cleared_stop_request_session_ids == []
    assert transcripts.appended == []
    assert event_publisher.dispatched == []
    assert projector.cleared_live_runs == []
    assert broker.cleared_session_ids == []


@pytest.mark.asyncio
async def test_record_interrupted_run_retry_does_not_duplicate_history_delivery() -> (
    None
):
    """Retrying finalization reuses durable IDs without duplicate live delivery."""
    session_id = "session-001"
    run_id = "22222222222222222222222222222222"
    finalizer, _, _, transcripts, projector, _, event_publisher = _finalizer(
        running_run=_running_run(session_id).model_copy(
            update={"id": run_id, "active_tool_calls": []}
        ),
        live_events=[],
    )

    await finalizer.record_interrupted_run(
        session_id,
        run_id=run_id,
        active_tool_calls=(),
    )
    await finalizer.record_interrupted_run(
        session_id,
        run_id=run_id,
        active_tool_calls=(),
    )

    assert [event.external_id for event in transcripts.appended] == [
        f"interrupted:{run_id}:user_requested",
        f"run-marker:{run_id}:interrupted",
    ]
    assert [
        event.kind if isinstance(event, Event) else type(event)
        for _, event in event_publisher.dispatched
    ] == [
        EventKind.INTERRUPTED,
        EventKind.RUN_MARKER,
        RunStopped,
        EventKind.INTERRUPTED,
        EventKind.RUN_MARKER,
        RunStopped,
    ]
    assert projector.cleared_live_runs == [
        (session_id, run_id),
        (session_id, run_id),
    ]


@pytest.mark.asyncio
async def test_finalize_does_not_interrupt_run_that_completed_before_lock() -> None:
    """A completed Run wins the race without stop history or live cleanup."""
    session_id = "session-001"
    completed_run = _running_run(session_id).model_copy(
        update={
            "status": AgentRunStatus.COMPLETED,
            "phase": AgentRunPhase.IDLE,
            "active_tool_calls": [],
            "ended_at": datetime.now(UTC),
        }
    )
    (
        finalizer,
        run_repository,
        session_repository,
        transcripts,
        projector,
        broker,
        event_publisher,
    ) = _finalizer(
        running_run=completed_run,
        live_events=[_assistant_event(session_id)],
    )

    await finalizer.finalize(
        session_id,
        run_id=completed_run.id,
        active_tool_calls=[],
    )

    assert transcripts.appended == []
    assert run_repository.terminal_runs == []
    assert session_repository.cleared_stop_request_session_ids == [session_id]
    assert event_publisher.dispatched == []
    assert projector.removed_events == []
    assert projector.removed_active_call_ids == []
    assert projector.cleared_live_runs == []
    assert broker.cleared_session_ids == []


@pytest.mark.asyncio
async def test_stop_only_signal_cleans_stale_activity_without_active_run() -> None:
    """A stop-only wake clears loading state even before an AgentRun exists."""
    session_id = "session-001"
    (
        finalizer,
        run_repository,
        session_repository,
        transcripts,
        projector,
        broker,
        event_publisher,
    ) = _finalizer(
        running_run=None,
        live_events=[_assistant_event(session_id), _tool_call_event(session_id)],
    )

    await finalizer.finalize(
        session_id,
        run_id=None,
        active_tool_calls=[],
    )

    assert run_repository.terminal_runs == []
    assert session_repository.cleared_stop_request_session_ids == [session_id]
    assert [event.external_id for event in transcripts.appended] == [
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    ]
    assert len(event_publisher.dispatched) == 1
    published = event_publisher.dispatched[0][1]
    assert isinstance(published, Event)
    assert published.kind == EventKind.ASSISTANT_MESSAGE
    assert projector.orphan_cleared_session_ids == [session_id]
    assert projector.removed_events == []
    assert projector.removed_active_call_ids == []
    assert projector.cleared_live_runs == []
    assert broker.cleared_session_ids == [session_id]


@pytest.mark.asyncio
async def test_finalize_ignores_redis_tool_call_without_durable_ownership() -> None:
    """A Redis tool projection is not a user-stop cancellation candidate."""
    session_id = "session-001"
    stale_call = _running_run(session_id).active_tool_calls[0]
    running_run = _running_run(session_id).model_copy(update={"active_tool_calls": []})
    finalizer, _, _, transcripts, projector, _, _ = _finalizer(
        running_run=running_run,
        live_events=[_tool_call_event(session_id)],
    )

    await finalizer.finalize(
        session_id,
        run_id=None,
        active_tool_calls=[stale_call],
    )

    assert [event.external_id for event in transcripts.appended] == [
        "interrupted:11111111111111111111111111111111:user_requested",
        "run-marker:11111111111111111111111111111111:interrupted",
    ]
    assert projector.removed_events == []


@pytest.mark.asyncio
async def test_finalize_times_out_redis_read_before_db_terminalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unavailable live store cannot block durable stop convergence."""
    monkeypatch.setattr(
        user_stop_finalizer_module,
        "_PRE_COMMIT_SNAPSHOT_TIMEOUT_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        user_stop_finalizer_module,
        "_EXTERNAL_STEP_TIMEOUT_SECONDS",
        0.01,
    )
    session_id = "session-001"
    (
        finalizer,
        run_repository,
        session_repository,
        transcripts,
        projector,
        broker,
        event_publisher,
    ) = _finalizer(
        running_run=_running_run(session_id),
        live_events=[],
        live_event_store=_HangingLiveEventStore(),
    )

    finalized_run_id = await asyncio.wait_for(
        finalizer.finalize(
            session_id,
            run_id=None,
            active_tool_calls=[],
        ),
        timeout=0.5,
    )

    assert finalized_run_id == "11111111111111111111111111111111"
    assert run_repository.terminal_runs == [
        ("11111111111111111111111111111111", AgentRunStatus.STOPPED)
    ]
    assert [event.external_id for event in transcripts.appended] == [
        "tool-result:11111111111111111111111111111111:call-1",
        "interrupted:11111111111111111111111111111111:user_requested",
        "run-marker:11111111111111111111111111111111:interrupted",
    ]
    assert session_repository.cleared_stop_request_session_ids == [session_id]
    assert projector.removed_active_call_ids == [{"call-1"}]
    assert projector.cleared_live_runs == [
        (session_id, "11111111111111111111111111111111")
    ]
    assert projector.removed_events == []
    assert broker.cleared_session_ids == [session_id]
    assert any(isinstance(event, RunStopped) for _, event in event_publisher.dispatched)


@pytest.mark.asyncio
async def test_finalize_cleanup_does_not_refresh_the_live_snapshot() -> None:
    """Cleanup uses committed capture IDs instead of a second broad Redis read."""
    session_id = "session-001"
    store = _FailingSecondLiveEventStore([_assistant_event(session_id)])
    (
        finalizer,
        run_repository,
        session_repository,
        transcripts,
        projector,
        broker,
        event_publisher,
    ) = _finalizer(
        running_run=_running_run(session_id),
        live_events=[],
        live_event_store=store,
    )

    finalized_run_id = await finalizer.finalize(
        session_id,
        run_id=None,
        active_tool_calls=[],
    )

    assert finalized_run_id == "11111111111111111111111111111111"
    assert run_repository.terminal_runs == [
        ("11111111111111111111111111111111", AgentRunStatus.STOPPED)
    ]
    assert session_repository.cleared_stop_request_session_ids == [session_id]
    assert [event.external_id for event in transcripts.appended] == [
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "tool-result:11111111111111111111111111111111:call-1",
        "interrupted:11111111111111111111111111111111:user_requested",
        "run-marker:11111111111111111111111111111111:interrupted",
    ]
    assert store.calls == 1
    assert projector.removed_events == [
        (session_id, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    ]
    assert projector.removed_active_call_ids == [{"call-1"}]
    assert projector.cleared_live_runs == [
        (session_id, "11111111111111111111111111111111")
    ]
    assert broker.cleared_session_ids == [session_id]
    assert any(isinstance(event, RunStopped) for _, event in event_publisher.dispatched)


@pytest.mark.asyncio
async def test_finalize_preserves_live_event_arriving_after_snapshot() -> None:
    """Cleanup cannot delete a delta that was not captured and committed."""
    session_id = "session-001"
    captured_event = _assistant_event(session_id)
    new_event = captured_event.model_copy(
        update={"id": "cccccccccccccccccccccccccccccccc"}
    )
    store = _AppendingAfterSnapshotLiveEventStore([captured_event], new_event)
    finalizer, _, _, _, projector, _, _ = _finalizer(
        running_run=_running_run(session_id).model_copy(
            update={"active_tool_calls": []}
        ),
        live_events=[],
        live_event_store=store,
    )

    await finalizer.finalize(
        session_id,
        run_id=None,
        active_tool_calls=[],
    )

    assert store.calls == 1
    assert [event.id for event in store.events] == [
        captured_event.id,
        new_event.id,
    ]
    assert projector.removed_events == [(session_id, captured_event.id)]


@pytest.mark.asyncio
async def test_finalize_continues_after_history_dispatch_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung earlier event cannot suppress the marker or RunStopped signal."""
    monkeypatch.setattr(
        user_stop_finalizer_module,
        "_EXTERNAL_STEP_TIMEOUT_SECONDS",
        0.01,
    )
    session_id = "session-001"
    finalizer, _, _, _, projector, broker, event_publisher = _finalizer(
        running_run=_running_run(session_id).model_copy(
            update={"active_tool_calls": []}
        ),
        live_events=[_assistant_event(session_id)],
    )
    event_publisher.hang_event_kinds.add(EventKind.ASSISTANT_MESSAGE)

    finalized_run_id = await asyncio.wait_for(
        finalizer.finalize(
            session_id,
            run_id=None,
            active_tool_calls=[],
        ),
        timeout=0.5,
    )

    assert finalized_run_id == "11111111111111111111111111111111"
    assert [
        event.kind if isinstance(event, Event) else type(event)
        for _, event in event_publisher.dispatched
    ] == [EventKind.INTERRUPTED, EventKind.RUN_MARKER, RunStopped]
    assert projector.cleared_live_runs == [
        (session_id, "11111111111111111111111111111111")
    ]
    assert broker.cleared_session_ids == [session_id]


@pytest.mark.asyncio
async def test_finalize_continues_after_history_dispatch_failure() -> None:
    """A history delivery failure cannot block terminal live projections."""
    session_id = "session-001"
    (
        finalizer,
        run_repository,
        session_repository,
        transcripts,
        projector,
        broker,
        event_publisher,
    ) = _finalizer(
        running_run=_running_run(session_id).model_copy(
            update={"active_tool_calls": []}
        ),
        live_events=[],
    )
    event_publisher.fail_next_dispatch = True

    finalized_run_id = await finalizer.finalize(
        session_id,
        run_id=None,
        active_tool_calls=[],
    )

    assert finalized_run_id == "11111111111111111111111111111111"
    assert run_repository.terminal_runs == [
        ("11111111111111111111111111111111", AgentRunStatus.STOPPED)
    ]
    assert session_repository.cleared_stop_request_session_ids == [session_id]
    assert [event.external_id for event in transcripts.appended] == [
        "interrupted:11111111111111111111111111111111:user_requested",
        "run-marker:11111111111111111111111111111111:interrupted",
    ]
    assert [
        event.kind if isinstance(event, Event) else type(event)
        for _, event in event_publisher.dispatched
    ] == [EventKind.RUN_MARKER, RunStopped]
    assert projector.cleared_live_runs == [
        (session_id, "11111111111111111111111111111111")
    ]
    assert broker.cleared_session_ids == [session_id]


@pytest.mark.asyncio
async def test_finalize_stops_external_cleanup_after_ownership_loss() -> None:
    """Ownership loss fences every later projector and broker mutation."""
    session_id = "session-001"
    (
        finalizer,
        run_repository,
        _,
        _,
        projector,
        broker,
        event_publisher,
    ) = _finalizer(
        running_run=_running_run(session_id).model_copy(
            update={"active_tool_calls": []}
        ),
        live_events=[],
    )
    event_publisher.lose_ownership_next_dispatch = True

    with pytest.raises(SessionOwnershipLostError):
        await finalizer.finalize(
            session_id,
            run_id=None,
            active_tool_calls=[],
        )

    assert run_repository.terminal_runs == [
        ("11111111111111111111111111111111", AgentRunStatus.STOPPED)
    ]
    assert event_publisher.dispatched == []
    assert projector.cleared_live_runs == []
    assert projector.removed_active_call_ids == []
    assert projector.removed_events == []
    assert broker.cleared_session_ids == []


@pytest.mark.asyncio
async def test_finalize_continues_delivery_after_caller_cancel() -> None:
    """A committed stop still publishes its marker and clears live state."""
    session_id = "session-001"
    finalizer, _, _, _, projector, broker, event_publisher = _finalizer(
        running_run=_running_run(session_id).model_copy(
            update={"active_tool_calls": []}
        ),
        live_events=[],
    )
    dispatch_started = asyncio.Event()
    release_dispatch = asyncio.Event()
    event_publisher.block_next_dispatch_started = dispatch_started
    event_publisher.block_next_dispatch_release = release_dispatch

    finalize_task = asyncio.create_task(
        finalizer.finalize(
            session_id,
            run_id=None,
            active_tool_calls=[],
        )
    )
    await asyncio.wait_for(dispatch_started.wait(), timeout=0.5)

    finalize_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(finalize_task, timeout=0.1)
    assert not release_dispatch.is_set()

    release_dispatch.set()
    await asyncio.wait_for(broker.cleared.wait(), timeout=0.5)

    assert [
        event.kind if isinstance(event, Event) else type(event)
        for _, event in event_publisher.dispatched
    ] == [EventKind.INTERRUPTED, EventKind.RUN_MARKER, RunStopped]
    assert projector.cleared_live_runs == [
        (session_id, "11111111111111111111111111111111")
    ]
    assert broker.cleared_session_ids == [session_id]


@pytest.mark.asyncio
async def test_detached_delivery_exception_is_observed() -> None:
    """Ownership loss in detached delivery cannot leak an unobserved exception."""
    session_id = "session-001"
    finalizer, _, _, _, projector, broker, event_publisher = _finalizer(
        running_run=_running_run(session_id).model_copy(
            update={"active_tool_calls": []}
        ),
        live_events=[],
    )
    dispatch_started = asyncio.Event()
    release_dispatch = asyncio.Event()
    ownership_loss_raised = asyncio.Event()
    event_publisher.block_next_dispatch_started = dispatch_started
    event_publisher.block_next_dispatch_release = release_dispatch
    event_publisher.lose_ownership_next_dispatch = True
    event_publisher.ownership_loss_raised = ownership_loss_raised
    loop = asyncio.get_running_loop()
    previous_exception_handler = loop.get_exception_handler()
    unhandled_contexts: list[dict[str, Any]] = []
    loop.set_exception_handler(
        lambda _loop, context: unhandled_contexts.append(context)
    )

    try:
        finalize_task = asyncio.create_task(
            finalizer.finalize(
                session_id,
                run_id=None,
                active_tool_calls=[],
            )
        )
        await asyncio.wait_for(dispatch_started.wait(), timeout=0.5)

        finalize_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(finalize_task, timeout=0.1)

        release_dispatch.set()
        await asyncio.wait_for(ownership_loss_raised.wait(), timeout=0.5)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert projector.cleared_live_runs == []
        assert broker.cleared_session_ids == []

        del finalize_task
        gc.collect()
        await asyncio.sleep(0)
        assert unhandled_contexts == []
    finally:
        release_dispatch.set()
        loop.set_exception_handler(previous_exception_handler)
