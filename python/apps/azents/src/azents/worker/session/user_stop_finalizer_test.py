"""UserStopFinalizer tests."""

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.core.inference_profile import AppliedInferenceProfile
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
from azents.engine.run.failure import (
    FailedRunAttempt,
    FailedRunProviderFailure,
    FailedRunRetryState,
    RunRecoveryState,
)
from azents.engine.run.provider_failure import model_provider_failure
from azents.repos.agent_execution.data import EventCreate
from azents.services.chat.data import ChatLiveRunState
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
        self.recovery_states: list[RunRecoveryState | None] = []
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

    async def mark_stopped_with_recovery_if_running(
        self,
        session: AsyncSession,
        run_id: str,
        *,
        recovery_state: RunRecoveryState | None,
        ended_at: datetime,
    ) -> AgentRunState | None:
        """Record stopped terminal state and its recoverable projection."""
        del session
        if self.fail_terminal:
            raise RuntimeError("terminal persistence unavailable")
        self.terminal_runs.append((run_id, AgentRunStatus.STOPPED))
        self.recovery_states.append(recovery_state)
        if self.running_run is None or self.running_run.id != run_id:
            return None
        self.running_run = self.running_run.model_copy(
            update={
                "status": AgentRunStatus.STOPPED,
                "phase": AgentRunPhase.IDLE,
                "active_tool_calls": [],
                "retry_state": None,
                "recovery_state": recovery_state,
                "model_call_started_at": None,
                "ended_at": ended_at,
            }
        )
        return self.running_run


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

    async def get_by_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> object:
        """Return one prepared Session inference projection."""
        del session, session_id
        return SimpleNamespace(
            inference_state=SimpleNamespace(
                applied_profile=AppliedInferenceProfile(
                    model_target_label="default",
                    model_display_name="Test Model",
                    reasoning_effort=None,
                )
            )
        )

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
        self.removed_active_call_ids: list[set[str]] = []
        self.live_run_updates: list[tuple[str, ChatLiveRunState]] = []

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

    async def publish_live_run_updated(
        self,
        session_id: str,
        run: ChatLiveRunState,
    ) -> None:
        """Record the recoverable stopped Run projection."""
        self.live_run_updates.append((session_id, run))


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


def _provider_retry_state() -> FailedRunRetryState:
    """Create one provider-attributed retry state for stopped recovery tests."""
    now = datetime.now(UTC)
    failure = model_provider_failure(
        operation="sampling",
        provider="openai",
        model="gpt-4o",
        integration=None,
        provider_message="The model provider rejected the credentials.",
        status_code=401,
        provider_code="invalid_api_key",
        provider_error_type="authentication_error",
    )
    return FailedRunRetryState.from_attempt(
        FailedRunAttempt(
            user_message=failure.user_message,
            internal_message=None,
            error_type=failure.__class__.__name__,
            source="model",
            visibility="user_visible",
            attempt_number=1,
            occurred_at=now,
            retryability="user_action_required",
            failure_code=failure.failure_code,
            provider_failure=FailedRunProviderFailure.from_failure(failure),
        ),
        max_retries=10,
        backoff_seconds=1,
        next_retry_at=now + timedelta(seconds=1),
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
    assert len(run_repository.recovery_states) == 1
    recovery_state = run_repository.recovery_states[0]
    assert recovery_state is not None
    assert recovery_state.kind == "stopped"
    assert recovery_state.user_message == "Execution stopped."
    assert recovery_state.operation == "sampling"
    assert recovery_state.source_run_id == "11111111111111111111111111111111"
    assert len(projector.live_run_updates) == 1
    live_session_id, live_run = projector.live_run_updates[0]
    assert live_session_id == session_id
    assert live_run.status is AgentRunStatus.STOPPED
    assert live_run.phase is AgentRunPhase.IDLE
    assert live_run.operation is None
    assert live_run.retry is None
    assert live_run.recovery is not None
    assert live_run.recovery.kind == "stopped"
    assert live_run.recovery.source_run_id == live_run.run_id
    assert run_repository.running_run is not None
    assert run_repository.running_run.active_tool_calls == []
    assert session_repository.cleared_stop_request_session_ids == [session_id]
    assert broker.cleared_session_ids == [session_id]
    assert len(event_publisher.dispatched) == 1
    assert event_publisher.dispatched[0][0] == session_id
    stopped_event = event_publisher.dispatched[0][1]
    assert isinstance(stopped_event, RunStopped)
    assert stopped_event.run_id == "11111111111111111111111111111111"


@pytest.mark.asyncio
async def test_finalize_preserves_latest_provider_failure_in_recovery() -> None:
    """Stop retains the safe provider error when retry state is available."""
    session_id = "session-001"
    retry_state = _provider_retry_state()
    running_run = _running_run(session_id).model_copy(
        update={"retry_state": retry_state}
    )
    finalizer, run_repository, _, _, projector, _, _ = _finalizer(
        running_run=running_run,
        live_events=[],
    )

    await finalizer.finalize(
        session_id,
        run_id=running_run.id,
        active_tool_calls=[],
    )

    assert len(run_repository.recovery_states) == 1
    recovery_state = run_repository.recovery_states[0]
    assert recovery_state is not None
    assert recovery_state.kind == "provider_failure"
    assert recovery_state.user_message == retry_state.last_user_message
    assert recovery_state.operation == "sampling"
    assert recovery_state.source_run_id == running_run.id
    assert len(projector.live_run_updates) == 1
    live_run = projector.live_run_updates[0][1]
    assert live_run.recovery is not None
    assert live_run.recovery.kind == "provider_failure"
    assert live_run.recovery.user_message == retry_state.last_user_message


@pytest.mark.asyncio
async def test_finalize_marks_direct_compaction_stop_as_recoverable() -> None:
    """Stopping before a provider failure still retains a fresh-budget Retry."""
    session_id = "session-001"
    compacting_run = _running_run(session_id).model_copy(
        update={"phase": AgentRunPhase.COMPACTING}
    )
    finalizer, run_repository, _, _, _, _, _ = _finalizer(
        running_run=compacting_run,
        live_events=[],
    )

    await finalizer.finalize(
        session_id,
        run_id=compacting_run.id,
        active_tool_calls=[],
    )

    assert len(run_repository.recovery_states) == 1
    recovery_state = run_repository.recovery_states[0]
    assert recovery_state is not None
    assert recovery_state.kind == "stopped"
    assert recovery_state.user_message == "Execution stopped."
    assert recovery_state.operation == "compaction"
    assert recovery_state.source_run_id == compacting_run.id


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
    assert event_publisher.dispatched
    stopped_event = event_publisher.dispatched[0][1]
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
