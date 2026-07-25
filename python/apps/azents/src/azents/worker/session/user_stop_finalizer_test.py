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
from azents.worker.session.execution_snapshot import (
    CanonicalExecutionOwnerGenerationStaleError,
)
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

    async def get_by_id(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> AgentRunState | None:
        """Return the configured Run only when its ID matches."""
        del session
        if self.running_run is None or self.running_run.id != run_id:
            return None
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
        if self.fail_terminal:
            raise RuntimeError("terminal persistence unavailable")
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
        if create.kind == EventKind.INTERRUPTED:
            return Event(
                id="cccccccccccccccccccccccccccccccc",
                session_id=create.session_id,
                kind=create.kind,
                payload=InterruptedPayload.model_validate(create.payload),
                external_id=create.external_id,
                created_at=datetime.now(UTC),
            )
        if create.kind == EventKind.RUN_MARKER:
            return Event(
                id="dddddddddddddddddddddddddddddddd",
                session_id=create.session_id,
                kind=create.kind,
                payload=RunMarkerPayload.model_validate(create.payload),
                external_id=create.external_id,
                created_at=datetime.now(UTC),
            )
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


class _SessionLifecycle:
    """SessionLifecycleService test double."""

    def __init__(
        self,
        run_repository: _AgentRunRepository,
        *,
        owner_generation: int = 1,
    ) -> None:
        self.run_repository = run_repository
        self.owner_generation = owner_generation

    def _assert_owner_generation(self, owner_generation: int) -> None:
        """Reject a stale Worker generation."""
        if owner_generation != self.owner_generation:
            raise CanonicalExecutionOwnerGenerationStaleError(
                "Session owner generation is stale"
            )

    async def get_running_agent_run(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> AgentRunState | None:
        """Return the configured running Run under the owner fence."""
        del session_id
        self._assert_owner_generation(owner_generation)
        return self.run_repository.running_run

    async def assert_owner_generation(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        owner_generation: int,
    ) -> None:
        """Validate the owner generation for a mutation transaction."""
        del session, session_id
        self._assert_owner_generation(owner_generation)


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
        self.removed_active_call_ids: list[set[str]] = []

    async def flush_session(self, session_id: str) -> None:
        """Record flush request."""
        self.flushed_session_ids.append(session_id)

    async def remove_event(self, session_id: str, event_id: str) -> None:
        """Record remove request."""
        self.removed_events.append((session_id, event_id))

    async def replace_active_tool_calls(
        self,
        session_id: str,
        active_tool_calls: list[ActiveToolCall],
        *,
        removed_call_ids: set[str],
    ) -> None:
        """Record deterministic active-call removals."""
        del session_id
        assert active_tool_calls == []
        self.removed_active_call_ids.append(removed_call_ids)


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
            wire_dialect="json_function",
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
                wire_dialect="json_function",
            )
        ],
        last_completed_event_id=None,
        parent_result_delivery_state=None,
        parent_result_input_buffer_id=None,
        parent_result_enqueued_at=None,
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
        session_lifecycle=cast(Any, _SessionLifecycle(run_repository)),
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
        owner_generation=1,
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
        (session_id, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"),
    ]
    assert projector.removed_active_call_ids == [{"call-1"}]
    assert run_repository.terminal_runs == [
        ("11111111111111111111111111111111", AgentRunStatus.STOPPED)
    ]
    assert run_repository.terminal_sessions == []
    assert run_repository.running_run is not None
    assert run_repository.running_run.active_tool_calls == []
    assert session_repository.cleared_stop_request_session_ids == [session_id]
    assert broker.cleared_session_ids == []
    published_durable_events = [
        event for _, event in event_publisher.dispatched[:2] if isinstance(event, Event)
    ]
    assert [event.kind for event in published_durable_events] == [
        EventKind.INTERRUPTED,
        EventKind.RUN_MARKER,
    ]
    published_session_ids = [
        published_session_id for published_session_id, _ in event_publisher.dispatched
    ]
    assert published_session_ids == [
        session_id,
        session_id,
        session_id,
    ]
    stopped_event = event_publisher.dispatched[2][1]
    assert isinstance(stopped_event, RunStopped)
    assert stopped_event.run_id == "11111111111111111111111111111111"


@pytest.mark.asyncio
async def test_finalize_preserves_retry_state_when_terminal_persistence_fails() -> None:
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
            owner_generation=1,
            run_id=None,
            active_tool_calls=[],
        )

    assert session_repository.cleared_stop_request_session_ids == []
    assert broker.cleared_session_ids == []
    assert event_publisher.dispatched == []


@pytest.mark.asyncio
async def test_record_interrupted_run_publishes_durable_history_before_stop() -> None:
    """CancelledError path publishes durable User stop history before RunStopped."""
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
        owner_generation=1,
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
    published_durable_events = [
        event for _, event in event_publisher.dispatched[:2] if isinstance(event, Event)
    ]
    assert [event.kind for event in published_durable_events] == [
        EventKind.INTERRUPTED,
        EventKind.RUN_MARKER,
    ]
    stopped_event = event_publisher.dispatched[2][1]
    assert isinstance(stopped_event, RunStopped)
    assert stopped_event.run_id == "22222222222222222222222222222222"
    assert session_repository.cleared_stop_request_session_ids == [session_id]
    assert projector.flushed_session_ids == []
    assert projector.removed_events == []
    assert broker.cleared_session_ids == []
    assert run_repository.terminal_runs == [
        ("22222222222222222222222222222222", AgentRunStatus.STOPPED)
    ]
    assert run_repository.terminal_sessions == []


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
        owner_generation=1,
        run_id=None,
        active_tool_calls=[stale_call],
    )

    assert [event.external_id for event in transcripts.appended] == [
        "interrupted:11111111111111111111111111111111:user_requested",
        "run-marker:11111111111111111111111111111111:interrupted",
    ]
    assert projector.removed_events == [
        (session_id, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    ]


@pytest.mark.asyncio
async def test_finalize_rejects_stale_owner_before_live_or_durable_mutation() -> None:
    """A stale Worker cannot finalize or clear another owner's stop state."""
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
        live_events=[_assistant_event(session_id)],
    )

    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await finalizer.finalize(
            session_id,
            owner_generation=2,
            run_id=None,
            active_tool_calls=[],
        )

    assert run_repository.terminal_runs == []
    assert session_repository.cleared_stop_request_session_ids == []
    assert transcripts.appended == []
    assert projector.flushed_session_ids == []
    assert broker.cleared_session_ids == []
    assert event_publisher.dispatched == []
