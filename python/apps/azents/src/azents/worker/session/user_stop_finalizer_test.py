"""UserStopFinalizer tests."""

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.engine.events.engine_events import RunStopped
from azents.engine.events.types import (
    ActiveToolCall,
    AgentRunState,
    AssistantMessagePayload,
    ClientToolCallPayload,
    Event,
    InterruptedPayload,
    NativeArtifact,
    RunMarkerPayload,
)
from azents.engine.run.emit import PublishedEvent
from azents.repos.agent_execution.data import EventCreate
from azents.worker.events.publisher import WorkerEventPublisher
from azents.worker.session.user_stop_finalizer import UserStopFinalizer


class _SessionScope(AbstractAsyncContextManager[AsyncSession]):
    """DB session context for tests."""

    def __init__(self) -> None:
        self.session = cast(AsyncSession, object())

    async def __aenter__(self) -> AsyncSession:
        """Return test session."""
        return self.session

    async def __aexit__(self, *exc_info: object) -> None:
        """No resources to clean up."""


class _SessionManager:
    """session manager for tests."""

    def __call__(self) -> _SessionScope:
        """Return new session scope."""
        return _SessionScope()


class _EventPublisher:
    """worker event publisher for tests."""

    def __init__(self) -> None:
        self.dispatched: list[tuple[str, PublishedEvent]] = []

    async def dispatch_event(
        self,
        session_id: str,
        event: PublishedEvent,
    ) -> None:
        """Record publish request."""
        self.dispatched.append((session_id, event))


class _AgentRunRepository:
    """AgentRunRepository test double."""

    def __init__(self, running_run: AgentRunState | None) -> None:
        self.running_run = running_run
        self.terminal_sessions: list[tuple[str, AgentRunStatus]] = []
        self.terminal_runs: list[tuple[str, AgentRunStatus]] = []

    async def get_running_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> AgentRunState | None:
        """Return running AgentRun projection."""
        del session, session_id
        return self.running_run

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
    ) -> object:
        """Record run-level terminal transition request."""
        del session, ended_at
        self.terminal_runs.append((run_id, status))
        return object()


class _EventTranscriptRepository:
    """EventTranscriptRepository test double."""

    def __init__(self) -> None:
        self.existing_external_ids: set[str] = set()
        self.appended: list[EventCreate] = []

    async def get_by_external_id(
        self,
        session: AsyncSession,
        session_id: str,
        external_id: str,
    ) -> object | None:
        """Return whether external_id exists."""
        del session, session_id
        if external_id in self.existing_external_ids:
            return object()
        return None

    async def append(self, session: AsyncSession, create: EventCreate) -> object:
        """Record append request."""
        del session
        self.appended.append(create)
        return object()


class _AgentSessionRepository:
    """AgentSessionRepository test double."""

    def __init__(self) -> None:
        self.cleared_stop_request_session_ids: list[str] = []

    async def clear_stop_request(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> object:
        """Record stop request clear request."""
        del session
        self.cleared_stop_request_session_ids.append(session_id)
        return object()


class _LiveEventStore:
    """RedisLiveEventStore test double."""

    def __init__(self, events: Sequence[Event]) -> None:
        self.events = list(events)

    async def list_by_session_id(self, session_id: str) -> Sequence[Event]:
        """Return live event list of session."""
        del session_id
        return self.events


class _LiveEventProjector:
    """LiveEventProjector test double."""

    def __init__(self) -> None:
        self.flushed_session_ids: list[str] = []
        self.removed_events: list[tuple[str, str]] = []

    async def flush_session(self, session_id: str) -> None:
        """Record flush request."""
        self.flushed_session_ids.append(session_id)

    async def remove_event(self, session_id: str, event_id: str) -> None:
        """Record remove request."""
        self.removed_events.append((session_id, event_id))


class _Broker:
    """Session activity broker test double."""

    def __init__(self) -> None:
        self.cleared_session_ids: list[str] = []

    async def clear_session_activity(self, session_id: str) -> None:
        """Record activity clear request."""
        self.cleared_session_ids.append(session_id)


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
                background=False,
            )
        ],
        last_completed_event_id=None,
        stop_requested_at=None,
        created_at=now,
        started_at=now,
        ended_at=None,
        updated_at=now,
    )


def _finalizer(
    *,
    running_run: AgentRunState | None,
    live_events: Sequence[Event],
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
    session_repository = _AgentSessionRepository()
    transcript_repository = _EventTranscriptRepository()
    projector = _LiveEventProjector()
    broker = _Broker()
    event_publisher = _EventPublisher()
    finalizer = UserStopFinalizer(
        session_manager=_SessionManager(),
        agent_run_repository=cast(Any, run_repository),
        agent_session_repository=cast(Any, session_repository),
        event_transcript_repository=cast(Any, transcript_repository),
        live_event_store=cast(Any, _LiveEventStore(live_events)),
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
        "tool-result:call-1:cancelled",
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
        (session_id, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
    ]
    assert run_repository.terminal_runs == [
        ("11111111111111111111111111111111", AgentRunStatus.STOPPED)
    ]
    assert run_repository.terminal_sessions == []
    assert session_repository.cleared_stop_request_session_ids == [session_id]
    assert broker.cleared_session_ids == [session_id]
    assert len(event_publisher.dispatched) == 1
    assert event_publisher.dispatched[0][0] == session_id
    assert isinstance(event_publisher.dispatched[0][1], RunStopped)


@pytest.mark.asyncio
async def test_record_interrupted_run_only_records_marker_and_stopped_event() -> None:
    """CancelledError path records only marker and RunStopped as before."""
    session_id = "session-001"
    (
        finalizer,
        run_repository,
        session_repository,
        transcripts,
        projector,
        broker,
        event_publisher,
    ) = _finalizer(running_run=None, live_events=[])

    await finalizer.record_interrupted_run(
        session_id,
        run_id="22222222222222222222222222222222",
    )

    assert [event.external_id for event in transcripts.appended] == [
        "interrupted:22222222222222222222222222222222:user_requested",
        "run-marker:22222222222222222222222222222222:interrupted",
    ]
    assert [event.kind for event in transcripts.appended] == [
        EventKind.INTERRUPTED,
        EventKind.RUN_MARKER,
    ]
    assert event_publisher.dispatched and isinstance(
        event_publisher.dispatched[0][1],
        RunStopped,
    )
    assert session_repository.cleared_stop_request_session_ids == [session_id]
    assert projector.flushed_session_ids == []
    assert projector.removed_events == []
    assert broker.cleared_session_ids == []
    assert run_repository.terminal_runs == []
    assert run_repository.terminal_sessions == []
