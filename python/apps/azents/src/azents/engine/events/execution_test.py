"""Event AgentRunExecution tests."""

import asyncio
import datetime
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import azents.engine.events.execution as execution_module
from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.core.inference_profile import SessionInferenceState
from azents.engine.events.execution import (
    AgentRunExecution,
    AgentRunExecutionRequest,
    InputPollResult,
    ModelCallPreparer,
    PreparedModelCall,
    TurnEndReason,
)
from azents.engine.events.protocols import (
    NativeEvent,
    NativeModelRequest,
    NormalizedAdapterOutput,
    StreamProjection,
)
from azents.engine.events.types import (
    ActiveToolCall,
    AgentRunState,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionSummaryPayload,
    Event,
    EventPayload,
    InterruptedPayload,
    NativeArtifact,
    OutputTextPart,
    ProviderToolCallPayload,
    ReasoningPayload,
    RunMarkerPayload,
    SystemPromptAnalysisPayload,
    SystemPromptFragmentPayload,
    TokenUsagePayload,
    TurnMarkerPayload,
    UserMessagePayload,
    build_native_compat_key,
)
from azents.engine.run.errors import ModelCallError
from azents.engine.run.types import (
    OWNERSHIP_LOST_CANCEL_MESSAGE,
    USER_STOP_CANCEL_MESSAGE,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import (
    AgentRunNotActiveError,
    AgentRunOwnershipLostError,
)
from azents.repos.agent_execution.data import EventCreate
from azents.testing.model_selection import make_test_model_selection


class _Session(AsyncSession):
    """AsyncSession for tests."""

    def __init__(self, commit_value: Callable[[], int] | None = None) -> None:
        """Record values at commit time."""
        self.commits: list[int] = []
        self._commit_value = commit_value
        self.active_scopes = 0

    async def commit(self) -> None:
        """Record commit call."""
        value = self._commit_value() if self._commit_value is not None else 0
        self.commits.append(value)

    async def rollback(self) -> None:
        """Accept rollback calls from rejected admission tests."""

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator["_Session"]:
        """Provide production-like commit and rollback session scopes."""
        self.active_scopes += 1
        try:
            yield self
        except BaseException:
            await self.rollback()
            raise
        else:
            await self.commit()
        finally:
            self.active_scopes -= 1


class _OpenToolAdmissionBarrier:
    """Admission barrier that keeps tests open by default."""

    closed = False

    async def run_if_open(self, action: Callable[[], Awaitable[None]]) -> bool:
        """Run the requested admission action."""
        await action()
        return True


class _MutableToolAdmissionBarrier(_OpenToolAdmissionBarrier):
    """Admission barrier that tests can close after a committed call."""

    closed = False

    def close(self) -> None:
        """Close future admissions and mark TERM as observed."""
        self.closed = True


class _ClosedToolAdmissionBarrier:
    """Admission barrier closed before model output can be admitted."""

    closed = True

    async def run_if_open(self, action: Callable[[], Awaitable[None]]) -> bool:
        """Reject admission without invoking its transaction."""
        del action
        return False


class _RunRepo:
    """Run repository for tests."""

    def __init__(self) -> None:
        self.phases: list[AgentRunPhase] = []
        self.terminal: AgentRunStatus | None = None
        self.active_tool_calls: list[ActiveToolCall] = []
        self.active_tool_call_snapshots: list[list[ActiveToolCall]] = []
        self.model_call_started_at: datetime.datetime | None = None
        self.terminal_result_event_id: str | None = None
        self.terminal_result_message: str | None = None
        self.terminal_conflict_status: AgentRunStatus | None = None
        self.ownership_lost = False
        self.authority_checks: list[tuple[str, str, int]] = []

    async def get_by_id(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> AgentRunState:
        """Return run state."""
        del session
        return AgentRunState(
            id=run_id if len(run_id) == 32 else "1" * 32,
            session_id="session-1",
            run_index=1,
            phase=self.phases[-1] if self.phases else AgentRunPhase.IDLE,
            status=self.terminal or AgentRunStatus.RUNNING,
            parent_agent_run_id=None,
            active_tool_calls=list(self.active_tool_calls),
            created_at=datetime.datetime.now(datetime.UTC),
            started_at=datetime.datetime.now(datetime.UTC),
            model_call_started_at=self.model_call_started_at,
            updated_at=datetime.datetime.now(datetime.UTC),
        )

    async def lock_by_id(
        self,
        session: AsyncSession,
        run_id: str,
    ) -> AgentRunState:
        """Return locked run state."""
        return await self.get_by_id(session, run_id)

    async def lock_active_owner(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        session_id: str,
        owner_generation: int,
    ) -> AgentRunState:
        """Validate the execution's durable authority."""
        self.authority_checks.append((run_id, session_id, owner_generation))
        if self.ownership_lost:
            raise AgentRunOwnershipLostError(
                run_id=run_id,
                session_id=session_id,
                expected_owner_generation=owner_generation,
                current_owner_generation=owner_generation + 1,
                active_run_id="new-run",
            )
        return await self.get_by_id(session, run_id)

    async def update_phase(
        self,
        session: AsyncSession,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> AgentRunState:
        """Record phase update."""
        self.phases.append(phase)
        if phase == AgentRunPhase.WAITING_FOR_MODEL:
            self.model_call_started_at = datetime.datetime.now(datetime.UTC)
        elif phase != AgentRunPhase.STREAMING_MODEL:
            self.model_call_started_at = None
        if active_tool_calls is not None:
            self.active_tool_calls = list(active_tool_calls)
            self.active_tool_call_snapshots.append(list(active_tool_calls))
        return await self.get_by_id(session, run_id)

    async def mark_terminal(
        self,
        session: AsyncSession,
        run_id: str,
        status: AgentRunStatus,
        *,
        ended_at: object,
        last_completed_event_id: str | None = None,
        terminal_result_event_id: str | None = None,
        terminal_result_message: str | None = None,
    ) -> object:
        """Record terminal status."""
        del session, run_id, ended_at, last_completed_event_id
        if self.terminal_conflict_status is not None:
            raise AgentRunNotActiveError("run-1", self.terminal_conflict_status)
        self.terminal = status
        self.terminal_result_event_id = terminal_result_event_id
        self.terminal_result_message = terminal_result_message
        self.active_tool_calls = []
        return object()

    async def update_retry_state(
        self,
        session: AsyncSession,
        run_id: str,
        retry_state: object | None,
    ) -> object:
        """No-op retry-state update for execution tests."""
        del session, run_id, retry_state
        return object()


class _TranscriptRepo:
    """Transcript repository for tests."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.head_event_ids: list[str | None] = []

    async def list_for_model_input(
        self,
        session: AsyncSession,
        session_id: str,
        *,
        head_event_id: str | None = None,
    ) -> list[Event]:
        """Return transcript."""
        del session, session_id
        self.head_event_ids.append(head_event_id)
        return list(self.events)

    async def get_by_external_id(
        self,
        session: AsyncSession,
        session_id: str,
        external_id: str,
    ) -> Event | None:
        """Find event by external ID."""
        del session
        return next(
            (
                event
                for event in self.events
                if event.session_id == session_id and event.external_id == external_id
            ),
            None,
        )

    async def append(
        self,
        session: AsyncSession,
        create: EventCreate,
    ) -> Event:
        """Materialize append request as event."""
        if create.external_id is not None:
            existing = await self.get_by_external_id(
                session,
                create.session_id,
                create.external_id,
            )
            if existing is not None:
                return existing
        payload_type = {
            EventKind.ASSISTANT_MESSAGE: AssistantMessagePayload,
            EventKind.CLIENT_TOOL_CALL: ClientToolCallPayload,
            EventKind.CLIENT_TOOL_RESULT: ClientToolResultPayload,
            EventKind.PROVIDER_TOOL_CALL: ProviderToolCallPayload,
            EventKind.INTERRUPTED: InterruptedPayload,
            EventKind.TURN_MARKER: TurnMarkerPayload,
            EventKind.USER_MESSAGE: UserMessagePayload,
        }.get(create.kind)
        if payload_type is None:
            payload_type = RunMarkerPayload
        event = Event(
            id="1" * 32,
            session_id=create.session_id,
            kind=create.kind,
            payload=payload_type.model_validate(create.payload),
            external_id=create.external_id,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        self.events.append(event)
        return event


class _FailingToolResultTranscriptRepo(_TranscriptRepo):
    """Fail while durably finalizing a client tool result."""

    async def append(
        self,
        session: AsyncSession,
        create: EventCreate,
    ) -> Event:
        """Raise a database-like error for tool result finalization."""
        if create.kind == EventKind.CLIENT_TOOL_RESULT:
            raise RuntimeError("tool result finalization failed")
        return await super().append(session, create)


class _Lowerer:
    """Lowerer for tests."""

    compat_key = "test"

    def __init__(self, native_request: NativeModelRequest | None = None) -> None:
        """Configure optional fixed native request."""
        self._native_request = native_request

    def lower(
        self,
        transcript: Sequence[Event],
        *,
        model: str,
        system_prompt: str | None = None,
    ) -> NativeModelRequest:
        """Return native request."""
        del transcript, system_prompt
        return self._native_request or NativeModelRequest(model=model, input=[])


class _RecordingLowerer:
    """Record transcript at lowerer call time."""

    compat_key = "test"

    def __init__(self) -> None:
        self.transcripts: list[list[Event]] = []

    def lower(
        self,
        transcript: Sequence[Event],
        *,
        model: str,
        system_prompt: str | None = None,
    ) -> NativeModelRequest:
        """Record transcript snapshot and return native request."""
        del system_prompt
        self.transcripts.append(list(transcript))
        return NativeModelRequest(model=model, input=[])


class _PreModelLowerHook:
    """Pre-lower hook for tests."""

    def __init__(self) -> None:
        self.called = False

    async def __call__(
        self,
        *,
        transcript: Sequence[Event],
    ) -> object:
        """Record hook call."""
        self.called = True
        assert transcript
        return object()


class _SessionState:
    """Session state for tests."""

    def __init__(self, head_event_id: str | None) -> None:
        self.model_input_head_event_id = head_event_id
        self.model_input_head_model_order = 1 if head_event_id is not None else None


class _SessionRepo:
    """Session head repository for tests."""

    def __init__(self, head_event_id: str | None) -> None:
        self._state = _SessionState(head_event_id)

    async def get_by_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> _SessionState:
        """Return session head."""
        del session, session_id
        return self._state


class _PreFilter:
    """Pre-lower filter for tests."""

    def __init__(self, events: Sequence[Event]) -> None:
        self._events = list(events)
        self.was_compacted = True

    async def apply(
        self,
        session_manager: SessionManager[AsyncSession],
        transcript: Sequence[Event],
    ) -> list[Event]:
        """Return transcript after compaction."""
        del session_manager, transcript
        return list(self._events)


class _PostFilter:
    """Post-lower filter for tests."""

    def apply(self, request: NativeModelRequest) -> NativeModelRequest:
        """Return request as-is."""
        return request


class _ModelAdapter:
    """Model adapter for tests."""

    async def stream(
        self,
        request: NativeModelRequest,
    ) -> AsyncIterator[NativeEvent]:
        """Return one completed event."""
        yield NativeEvent(type="done", item={})


class _NoSessionModelAdapter(_ModelAdapter):
    """Assert model I/O never runs inside a database session scope."""

    def __init__(self, session_manager: _Session) -> None:
        self._session_manager = session_manager
        self.stream_calls = 0

    async def stream(
        self,
        request: NativeModelRequest,
    ) -> AsyncIterator[NativeEvent]:
        """Fail if a database scope remains active during provider I/O."""
        del request
        assert self._session_manager.active_scopes == 0
        self.stream_calls += 1
        yield NativeEvent(type="done", item={})


class _BlockingModelAdapter:
    """Pause the model stream after yielding its first delta."""

    def __init__(self) -> None:
        self.waiting_after_delta = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(
        self,
        request: NativeModelRequest,
    ) -> AsyncIterator[NativeEvent]:
        """Yield a delta, wait, then finish the native stream."""
        del request
        yield NativeEvent(type="text_delta", item={"delta": "hel"})
        self.waiting_after_delta.set()
        await self.release.wait()
        yield NativeEvent(type="done", item={})


class _CancellingModelAdapter:
    """Yield some native events, then raise user stop cancellation."""

    async def stream(
        self,
        request: NativeModelRequest,
    ) -> AsyncIterator[NativeEvent]:
        """Return user stop cancellation after partial model stream."""
        del request
        yield NativeEvent(
            type="response.output_text.delta",
            item={"delta": "hel"},
        )
        yield NativeEvent(type="response.output_text.delta", item={"delta": "lo"})
        raise asyncio.CancelledError(USER_STOP_CANCEL_MESSAGE)


class _OwnershipLossModelAdapter:
    """Raise ownership fencing after one partial model delta."""

    async def stream(
        self,
        request: NativeModelRequest,
    ) -> AsyncIterator[NativeEvent]:
        """Emit a partial delta without allowing stale-owner durabilization."""
        del request
        yield NativeEvent(
            type="response.output_text.delta",
            item={"delta": "partial"},
        )
        raise asyncio.CancelledError(OWNERSHIP_LOST_CANCEL_MESSAGE)


class _FailingModelAdapter:
    """Model adapter that raises user-visible model call error."""

    async def stream(
        self,
        request: NativeModelRequest,
    ) -> AsyncIterator[NativeEvent]:
        """Return model call failure."""
        del request
        raise ModelCallError("Model call failed (401): Missing scopes")
        yield


class _StaticOutputStream:
    """Incremental normalizer stream that returns predefined durable output."""

    def __init__(self, output: NormalizedAdapterOutput) -> None:
        self._output = output

    def process_event(
        self,
        native_event: NativeEvent,
    ) -> NormalizedAdapterOutput:
        """Ignore one native event because output is predefined."""
        del native_event
        return NormalizedAdapterOutput()

    def complete(self) -> NormalizedAdapterOutput:
        """Return predefined completed output."""
        return self._output

    def interrupt(self) -> NormalizedAdapterOutput:
        """Return predefined interrupted output."""
        return self._output


class _ProjectingOutputStream(_StaticOutputStream):
    """Return a live content projection for the test delta event."""

    def process_event(
        self,
        native_event: NativeEvent,
    ) -> NormalizedAdapterOutput:
        """Project the test adapter's native text delta."""
        if native_event.type != "text_delta":
            return NormalizedAdapterOutput()
        return NormalizedAdapterOutput(
            projections=[
                StreamProjection(
                    type="content_delta",
                    delta=str(native_event.item.get("delta", "")),
                )
            ]
        )


class _ProjectingNormalizer:
    """Create projecting streams with predefined durable output."""

    def __init__(self, events: list[Event]) -> None:
        self._events = events

    def start(self, session_id: str) -> _ProjectingOutputStream:
        """Start one projecting output stream."""
        del session_id
        return _ProjectingOutputStream(
            NormalizedAdapterOutput(events=self._events, usage=_usage())
        )


class _Normalizer:
    """Normalizer for tests."""

    def __init__(
        self,
        events: list[Event],
        usage: TokenUsagePayload | None = None,
    ) -> None:
        self._events = events
        self._usage = usage or _usage()

    def start(self, session_id: str) -> _StaticOutputStream:
        """Return one predefined output stream."""
        del session_id
        return _StaticOutputStream(
            NormalizedAdapterOutput(events=self._events, usage=self._usage)
        )


class _SequenceNormalizer:
    """Return normalized output by stream call order."""

    def __init__(self, event_batches: Sequence[Sequence[Event]]) -> None:
        self._event_batches = [list(events) for events in event_batches]
        self._index = 0

    def start(self, session_id: str) -> _StaticOutputStream:
        """Return the next predefined output stream."""
        del session_id
        if self._index >= len(self._event_batches):
            events: list[Event] = []
        else:
            events = self._event_batches[self._index]
        self._index += 1
        return _StaticOutputStream(
            NormalizedAdapterOutput(events=events, usage=_usage())
        )


class _ToolExecutor:
    """Tool executor for tests."""

    def __init__(self) -> None:
        self.executed_calls: list[ClientToolCallPayload] = []
        self.cancelled_calls: list[ClientToolCallPayload] = []

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Return tool result."""
        self.executed_calls.append(call)
        return ClientToolResultPayload(
            call_id=call.call_id,
            name=call.name,
            status="completed",
            output=[OutputTextPart(text="tool output")],
        )

    def request_cancel(self, call: ClientToolCallPayload) -> None:
        """Record cancellation request."""
        self.cancelled_calls.append(call)


class _NoSessionToolExecutor(_ToolExecutor):
    """Assert tool I/O never runs inside a database session scope."""

    def __init__(self, session_manager: _Session) -> None:
        super().__init__()
        self._session_manager = session_manager

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Fail if a database scope remains active during tool I/O."""
        assert self._session_manager.active_scopes == 0
        return await super().execute(call)


class _OwnershipStealingToolExecutor(_ToolExecutor):
    """Complete external work only after another owner replaces this writer."""

    def __init__(self, run_repo: _RunRepo) -> None:
        super().__init__()
        self._run_repo = run_repo

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Return a result after making the finalization authority stale."""
        result = await super().execute(call)
        self._run_repo.ownership_lost = True
        return result


class _OrderedToolExecutor(_ToolExecutor):
    """Hold one parallel call so completion order is deterministic."""

    def __init__(self) -> None:
        super().__init__()
        self.blocked_started = asyncio.Event()
        self.release_blocked = asyncio.Event()

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Complete call-1 immediately and hold call-2."""
        if call.call_id == "call-2":
            self.blocked_started.set()
            await self.release_blocked.wait()
        return await super().execute(call)


class _FinalizationFailureToolExecutor(_ToolExecutor):
    """Keep one external call running while its sibling is finalized."""

    def __init__(self) -> None:
        super().__init__()
        self.blocked_started = asyncio.Event()
        self.blocked_cancelled = asyncio.Event()
        self.release_blocked = asyncio.Event()

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Complete call-1 after call-2 has entered its blocking external call."""
        if call.call_id == "call-1":
            await self.blocked_started.wait()
            return await super().execute(call)
        if call.call_id == "call-2":
            self.blocked_started.set()
            try:
                await self.release_blocked.wait()
            except asyncio.CancelledError:
                self.blocked_cancelled.set()
                raise
        return await super().execute(call)


class _CancellationAwareBlockingToolExecutor(_ToolExecutor):
    """Detect whether parent cancellation preserves ownership-loss authority."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.child_cancel_args: tuple[object, ...] | None = None
        self.stale_cleanup_writes = 0

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Block and model a stale cleanup write on generic cancellation."""
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError as exc:
            self.child_cancel_args = exc.args
            if exc.args != (OWNERSHIP_LOST_CANCEL_MESSAGE,):
                self.stale_cleanup_writes += 1
            raise
        return await super().execute(call)


class _CancellationResistantToolExecutor(_ToolExecutor):
    """Keep external work alive after task cancellation until explicitly released."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.child_cancel_args: list[tuple[object, ...]] = []

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Swallow cancellation to model an uncooperative external Tool."""
        self.started.set()
        while not self.release.is_set():
            try:
                await self.release.wait()
            except asyncio.CancelledError as exc:
                self.child_cancel_args.append(exc.args)
        return await super().execute(call)


class _FailingToolExecutor:
    """Failing tool executor for tests."""

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Raise tool failure."""
        del call
        raise RuntimeError("boom")

    def request_cancel(self, call: ClientToolCallPayload) -> None:
        """Ignore cancellation requests in tests."""
        del call


class _CancellingToolExecutor:
    """Cancelling tool executor for tests."""

    def __init__(
        self,
        *,
        user_stop: bool = False,
        cancel_message: str | None = None,
    ) -> None:
        self._user_stop = user_stop
        self._cancel_message = cancel_message
        self.cancelled_calls: list[ClientToolCallPayload] = []

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Raise tool cancellation."""
        del call
        if self._cancel_message is not None:
            raise asyncio.CancelledError(self._cancel_message)
        if self._user_stop:
            raise asyncio.CancelledError(USER_STOP_CANCEL_MESSAGE)
        raise asyncio.CancelledError

    def request_cancel(self, call: ClientToolCallPayload) -> None:
        """Record cancellation request."""
        self.cancelled_calls.append(call)


def _model_call_preparer(
    *,
    lowerer: _Lowerer | _RecordingLowerer | None = None,
    tool_executor: _ToolExecutor
    | _FailingToolExecutor
    | _CancellingToolExecutor
    | None = None,
    system_prompt: SystemPromptAnalysisPayload | None = None,
    inference_state: SessionInferenceState | None = None,
) -> ModelCallPreparer:
    """Create a turn-local model call preparer for tests."""
    resolved_lowerer = lowerer or _Lowerer()
    resolved_tool_executor = tool_executor or _ToolExecutor()

    async def prepare_model_call(
        *,
        transcript: Sequence[Event],
        model: str,
    ) -> PreparedModelCall:
        return PreparedModelCall(
            native_request=resolved_lowerer.lower(transcript, model=model),
            inference_state=inference_state,
            system_prompt_analysis=system_prompt,
            tool_executor=resolved_tool_executor,
            on_turn_end=None,
        )

    return prepare_model_call


def _artifact() -> NativeArtifact:
    """Create native artifact for tests."""
    return NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="litellm",
            native_format="responses",
            provider="openai",
            model="gpt-5.1",
            schema_version="1",
        ),
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-5.1",
        schema_version="1",
        item={"type": "message"},
    )


def _assistant_event() -> Event:
    """Create assistant message event."""
    return Event(
        id="0" * 32,
        session_id="session-1",
        kind=EventKind.ASSISTANT_MESSAGE,
        payload=AssistantMessagePayload(content="done", native_artifact=_artifact()),
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _usage() -> TokenUsagePayload:
    """Create token usage for tests."""
    return TokenUsagePayload(
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        raw={
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        },
    )


def _tool_call_event(call_id: str = "call-1") -> Event:
    """Create client tool call event."""
    return Event(
        id="0" * 32,
        session_id="session-1",
        kind=EventKind.CLIENT_TOOL_CALL,
        payload=ClientToolCallPayload(
            call_id=call_id,
            name="read_text",
            arguments="{}",
            native_artifact=_artifact(),
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _tool_result_event(call_id: str = "call-1") -> Event:
    """Create client tool result event."""
    return Event(
        id="2" * 32,
        session_id="session-1",
        kind=EventKind.CLIENT_TOOL_RESULT,
        payload=ClientToolResultPayload(
            call_id=call_id,
            name="read_text",
            status="completed",
            output=[OutputTextPart(text="done")],
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _provider_tool_call_event() -> Event:
    """Create provider-hosted tool call event."""
    return Event(
        id="0" * 32,
        session_id="session-1",
        kind=EventKind.PROVIDER_TOOL_CALL,
        payload=ProviderToolCallPayload(
            call_id="provider-call-1",
            name="web_search",
            arguments=None,
            native_artifact=_artifact(),
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _event(
    event_id: str,
    kind: EventKind,
    payload: EventPayload,
) -> Event:
    """Create event for tests."""
    return Event(
        id=event_id.rjust(32, "0"),
        session_id="session-1",
        kind=kind,
        payload=payload,
        created_at=datetime.datetime.now(datetime.UTC),
    )


async def test_text_run_completes() -> None:
    """End as completed when there are no tool calls."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    emitted_phases: list[tuple[AgentRunPhase, datetime.datetime | None]] = []

    async def collect_phase(
        phase: AgentRunPhase,
        model_call_started_at: datetime.datetime | None,
    ) -> None:
        emitted_phases.append((phase, model_call_started_at))

    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_assistant_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        phase_sink=collect_phase,
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert status == AgentRunStatus.COMPLETED
    assert run_repo.terminal == AgentRunStatus.COMPLETED
    assert run_repo.terminal_result_message == "done"
    assert run_repo.terminal_result_event_id == transcript_repo.events[0].id
    assert AgentRunPhase.STREAMING_MODEL in run_repo.phases
    assert [phase for phase, _ in emitted_phases] == run_repo.phases
    waiting_started_at = next(
        started_at
        for phase, started_at in emitted_phases
        if phase == AgentRunPhase.WAITING_FOR_MODEL
    )
    streaming_started_at = next(
        started_at
        for phase, started_at in emitted_phases
        if phase == AgentRunPhase.STREAMING_MODEL
    )
    assert waiting_started_at is not None
    assert streaming_started_at == waiting_started_at


async def test_terminal_winner_aborts_late_no_tool_completion() -> None:
    """Return the committed stop winner when completion loses its DB transition."""
    run_repo = _RunRepo()
    run_repo.terminal_conflict_status = AgentRunStatus.STOPPED
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_assistant_event()]),
        model_call_preparer=_model_call_preparer(),
        run_repo=run_repo,
        transcript_repo=_TranscriptRepo(),
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert status == AgentRunStatus.STOPPED
    assert run_repo.terminal is None


async def test_model_delta_reaches_output_sink_before_stream_completion() -> None:
    """Project native text while the provider stream remains open."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    model_adapter = _BlockingModelAdapter()
    sink_outputs: list[NormalizedAdapterOutput] = []

    async def output_sink(
        normalized: NormalizedAdapterOutput,
        appended: Sequence[Event],
    ) -> None:
        """Record incremental and durable output sink calls."""
        del appended
        sink_outputs.append(normalized)

    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=model_adapter,
        output_normalizer=_ProjectingNormalizer([_assistant_event()]),
        model_call_preparer=_model_call_preparer(),
        output_sink=output_sink,
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )
    run_task = asyncio.create_task(
        execution.run(
            _Session(),
            AgentRunExecutionRequest(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                run_id="run-1",
                session_id="session-1",
                model="gpt-5.1",
            ),
        )
    )

    await asyncio.wait_for(model_adapter.waiting_after_delta.wait(), timeout=1)

    assert not run_task.done()
    assert len(sink_outputs) == 1
    assert sink_outputs[0].projections == [
        StreamProjection(type="content_delta", delta="hel")
    ]
    assert transcript_repo.events == []

    model_adapter.release.set()
    assert await run_task == AgentRunStatus.COMPLETED
    assert [event.kind for event in transcript_repo.events] == [
        EventKind.ASSISTANT_MESSAGE,
        EventKind.TURN_MARKER,
        EventKind.RUN_MARKER,
    ]


async def test_text_run_commits_durable_events_before_output_sink() -> None:
    """UI emit is delivered only after events commit."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    session = _Session(lambda: len(transcript_repo.events))
    committed_event_counts_at_sink: list[int] = []

    async def output_sink(
        normalized: NormalizedAdapterOutput,
        appended: Sequence[Event],
    ) -> None:
        """Record commit state at output sink call time."""
        del normalized, appended
        committed_event_counts_at_sink.append(session.commits[-1])

    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_assistant_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        output_sink=output_sink,
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        session,
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert status == AgentRunStatus.COMPLETED
    assert committed_event_counts_at_sink == [3]


async def test_text_run_output_sink_receives_run_marker() -> None:
    """Completed turn/run markers are also delivered to projection sink."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    sink_kinds: list[list[EventKind]] = []

    async def output_sink(
        normalized: NormalizedAdapterOutput,
        appended: Sequence[Event],
    ) -> None:
        """Record event kind delivered to output sink."""
        del normalized
        sink_kinds.append([event.kind for event in appended])

    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_assistant_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        output_sink=output_sink,
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert status == AgentRunStatus.COMPLETED
    assert sink_kinds == [
        [
            EventKind.ASSISTANT_MESSAGE,
            EventKind.TURN_MARKER,
            EventKind.RUN_MARKER,
        ]
    ]


async def test_model_usage_is_appended_as_turn_marker(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Durably append normalizer usage as turn marker and debug log."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    usage = TokenUsagePayload(
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        raw={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        cached_tokens=75,
        cache_creation_tokens=10,
        reasoning_tokens=5,
        cost_usd=0.001,
        raw_hidden_params={"response_cost": 0.001, "model_id": "gpt-5.1"},
    )
    inference_state = SessionInferenceState(
        model_target_label="planning",
        model_selection=make_test_model_selection(model_identifier="gpt-5.1"),
        reasoning_effort=None,
        effective_context_window_tokens=128_000,
        effective_auto_compaction_threshold_tokens=102_400,
        resolved_at=datetime.datetime.now(datetime.UTC),
    )
    system_prompt = SystemPromptAnalysisPayload(
        agent_prompt=SystemPromptFragmentPayload(
            id="agent",
            source="agent",
            label="Agent prompt",
            content="Be helpful.",
            preview="Be helpful.",
            length=11,
        ),
    )
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_assistant_event()], usage=usage),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(),
            tool_executor=_ToolExecutor(),
            system_prompt=system_prompt,
            inference_state=inference_state,
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    with caplog.at_level(logging.INFO, logger="azents.engine.events.execution"):
        status = await execution.run(
            _Session(),
            AgentRunExecutionRequest(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                run_id="run-1",
                session_id="session-1",
                model="gpt-5.1",
                run_index=7,
            ),
        )

    assert status == AgentRunStatus.COMPLETED
    turn_markers = [
        event for event in transcript_repo.events if event.kind == EventKind.TURN_MARKER
    ]
    assert len(turn_markers) == 1
    payload = turn_markers[0].payload
    assert isinstance(payload, TurnMarkerPayload)
    assert payload.run_id == "run-1"
    assert payload.usage == usage
    assert payload.applied_inference_profile == inference_state.applied_profile
    assert payload.effective_context_window_tokens == 128_000
    assert payload.effective_auto_compaction_threshold_tokens == 102_400
    assert payload.system_prompt == system_prompt
    serialized_payload = turn_markers[0].payload.model_dump(mode="json")
    assert serialized_payload["applied_inference_profile"]["reasoning_effort"] is None
    assert "provider" not in serialized_payload
    assert "model_selection" not in serialized_payload
    assert "credential_kwargs" not in serialized_payload
    record = next(
        item for item in caplog.records if item.message == "Model token usage"
    )
    fields = record.__dict__
    assert fields["session_id"] == "session-1"
    assert fields["run_id"] == "run-1"
    assert fields["run_index"] == 7
    assert fields["model"] == "gpt-5.1"
    assert fields["prompt_tokens"] == 100
    assert fields["completion_tokens"] == 20
    assert fields["total_tokens"] == 120
    assert fields["cached_tokens"] == 75
    assert fields["cache_creation_tokens"] == 10
    assert fields["cached_token_ratio"] == 0.75
    assert fields["raw_usage"] == usage.raw
    assert fields["raw_hidden_params"] == usage.raw_hidden_params


async def test_model_input_uses_session_head_event_id() -> None:
    """After compaction, model input is fetched from session head."""
    transcript_repo = _TranscriptRepo()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_assistant_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        run_repo=_RunRepo(),
        transcript_repo=transcript_repo,
        session_repo=_SessionRepo("2" * 32),
    )

    await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert transcript_repo.head_event_ids == ["2" * 32]


async def test_closed_admission_barrier_prevents_call_and_handler_start() -> None:
    """TERM observed before admission leaves no call event or handler side effect."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    tool_executor = _ToolExecutor()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_tool_call_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(),
            tool_executor=tool_executor,
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=2,
            tool_admission_barrier=_ClosedToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert status == AgentRunStatus.RUNNING
    assert transcript_repo.events == []
    assert tool_executor.executed_calls == []
    assert run_repo.active_tool_calls == []


async def test_tool_run_with_turn_limit_interrupts_after_tool_result() -> None:
    """Append final-turn tool result at turn limit, then end as interrupted."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    sink_events: list[Event] = []

    async def output_sink(
        normalized: NormalizedAdapterOutput,
        appended: Sequence[Event],
    ) -> None:
        """Collect committed output projected during the bounded run."""
        del normalized
        sink_events.extend(appended)

    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_tool_call_event(), _assistant_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        output_sink=output_sink,
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
            max_turns=1,
        ),
    )

    assert status == AgentRunStatus.INTERRUPTED
    assert AgentRunPhase.EXECUTING_TOOLS in run_repo.phases
    tool_events = [
        event
        for event in transcript_repo.events
        if event.kind in {EventKind.CLIENT_TOOL_CALL, EventKind.CLIENT_TOOL_RESULT}
    ]
    assert [event.external_id for event in tool_events] == [
        "tool-call:run-1:call-1",
        "tool-result:run-1:call-1",
    ]
    assert any(
        isinstance(event.payload, RunMarkerPayload)
        and event.payload.status == "interrupted"
        for event in sink_events
    )


async def test_parallel_calls_finalize_independently() -> None:
    """One parallel completion removes only that call before peers finish."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    tool_executor = _OrderedToolExecutor()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer(
            [_tool_call_event("call-1"), _tool_call_event("call-2")]
        ),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(),
            tool_executor=tool_executor,
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )
    run_task = asyncio.create_task(
        execution.run(
            _Session(),
            AgentRunExecutionRequest(
                owner_generation=3,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                run_id="run-1",
                session_id="session-1",
                model="gpt-5.1",
                max_turns=1,
            ),
        )
    )

    await asyncio.wait_for(tool_executor.blocked_started.wait(), timeout=1)

    async def wait_for_first_result() -> None:
        while not any(
            event.kind == EventKind.CLIENT_TOOL_RESULT
            for event in transcript_repo.events
        ):
            await asyncio.sleep(0)

    await asyncio.wait_for(wait_for_first_result(), timeout=1)
    assert [call.call_id for call in run_repo.active_tool_calls] == ["call-2"]
    assert run_repo.active_tool_calls[0].owner_generation == 3

    tool_executor.release_blocked.set()
    assert await run_task == AgentRunStatus.INTERRUPTED
    assert run_repo.active_tool_calls == []
    result_ids = [
        event.external_id
        for event in transcript_repo.events
        if event.kind == EventKind.CLIENT_TOOL_RESULT
    ]
    assert result_ids == [
        "tool-result:run-1:call-1",
        "tool-result:run-1:call-2",
    ]


async def test_tool_finalization_failure_cancels_unfinished_siblings() -> None:
    """Do not leave parallel external tool work detached after a DB failure."""
    tool_executor = _FinalizationFailureToolExecutor()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer(
            [_tool_call_event("call-1"), _tool_call_event("call-2")]
        ),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(),
            tool_executor=tool_executor,
        ),
        run_repo=_RunRepo(),
        transcript_repo=_FailingToolResultTranscriptRepo(),
    )

    try:
        with pytest.raises(RuntimeError, match="tool result finalization failed"):
            await execution.run(
                _Session(),
                AgentRunExecutionRequest(
                    owner_generation=1,
                    tool_admission_barrier=_OpenToolAdmissionBarrier(),
                    run_id="run-1",
                    session_id="session-1",
                    model="gpt-5.1",
                    max_turns=1,
                ),
            )
        assert tool_executor.blocked_cancelled.is_set()
    finally:
        tool_executor.release_blocked.set()
        await asyncio.sleep(0)


async def test_term_after_admission_keeps_normal_result_and_run_recoverable() -> None:
    """Admitted work may finish after TERM without dispatching another model turn."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    tool_executor = _OrderedToolExecutor()
    barrier = _MutableToolAdmissionBarrier()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_tool_call_event("call-2")]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(),
            tool_executor=tool_executor,
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    async def check_stop() -> bool:
        return barrier.closed

    run_task = asyncio.create_task(
        execution.run(
            _Session(),
            AgentRunExecutionRequest(
                owner_generation=4,
                tool_admission_barrier=barrier,
                run_id="run-1",
                session_id="session-1",
                model="gpt-5.1",
            ),
            check_stop=check_stop,
        )
    )
    await asyncio.wait_for(tool_executor.blocked_started.wait(), timeout=1)
    barrier.close()
    tool_executor.release_blocked.set()

    assert await run_task == AgentRunStatus.RUNNING
    result_events = [
        event
        for event in transcript_repo.events
        if event.kind == EventKind.CLIENT_TOOL_RESULT
    ]
    assert len(result_events) == 1
    payload = result_events[0].payload
    assert isinstance(payload, ClientToolResultPayload)
    assert payload.status == "completed"
    assert run_repo.terminal is None
    assert run_repo.active_tool_calls == []


async def test_unlimited_tool_run_executes_tool_then_completes() -> None:
    """max_turns None keeps running to next model turn after tool result."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_SequenceNormalizer(
            [
                [_tool_call_event()],
                [_assistant_event()],
            ]
        ),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
            max_turns=None,
        ),
    )

    assert status == AgentRunStatus.COMPLETED
    assert AgentRunPhase.EXECUTING_TOOLS in run_repo.phases
    assert any(
        event.kind == EventKind.CLIENT_TOOL_RESULT for event in transcript_repo.events
    )


async def test_external_model_and_tool_calls_run_after_db_scope_closes() -> None:
    """Do not retain a database session across model or tool provider I/O."""
    session_manager = _Session()
    model_adapter = _NoSessionModelAdapter(session_manager)
    tool_executor = _NoSessionToolExecutor(session_manager)
    output_calls = 0
    phase_calls = 0

    async def output_sink(
        normalized: NormalizedAdapterOutput,
        appended: Sequence[Event],
    ) -> None:
        """Assert durable/live publication happens after DB scope exit."""
        del normalized, appended
        nonlocal output_calls
        assert session_manager.active_scopes == 0
        output_calls += 1

    async def phase_sink(
        phase: AgentRunPhase,
        model_call_started_at: datetime.datetime | None,
    ) -> None:
        """Assert committed phase publication happens after DB scope exit."""
        del phase, model_call_started_at
        nonlocal phase_calls
        assert session_manager.active_scopes == 0
        phase_calls += 1

    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=model_adapter,
        output_normalizer=_SequenceNormalizer(
            [
                [_tool_call_event()],
                [_assistant_event()],
            ]
        ),
        model_call_preparer=_model_call_preparer(tool_executor=tool_executor),
        output_sink=output_sink,
        phase_sink=phase_sink,
        run_repo=_RunRepo(),
        transcript_repo=_TranscriptRepo(),
    )

    status = await execution.run(
        session_manager,
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert status == AgentRunStatus.COMPLETED
    assert model_adapter.stream_calls == 2
    assert len(tool_executor.executed_calls) == 1
    assert output_calls > 0
    assert phase_calls > 0
    assert session_manager.active_scopes == 0


async def test_model_call_preparer_runs_for_each_model_turn() -> None:
    """Prepare model input and tools at each model-call turn boundary."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    prepared_transcripts: list[list[Event]] = []
    turn_end_reasons: list[TurnEndReason] = []

    async def prepare_model_call(
        *,
        transcript: Sequence[Event],
        model: str,
    ) -> PreparedModelCall:
        """Record each turn-local preparation."""
        prepared_transcripts.append(list(transcript))

        async def on_turn_end(reason: TurnEndReason) -> None:
            turn_end_reasons.append(reason)

        return PreparedModelCall(
            native_request=NativeModelRequest(model=model, input=[]),
            inference_state=None,
            system_prompt_analysis=None,
            tool_executor=_ToolExecutor(),
            on_turn_end=on_turn_end,
        )

    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_SequenceNormalizer(
            [
                [_tool_call_event()],
                [_assistant_event()],
            ]
        ),
        model_call_preparer=prepare_model_call,
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
            max_turns=None,
        ),
    )

    assert status == AgentRunStatus.COMPLETED
    assert len(prepared_transcripts) == 2
    second_turn_payloads = [event.payload for event in prepared_transcripts[1]]
    tool_result = next(
        payload
        for payload in second_turn_payloads
        if isinstance(payload, ClientToolResultPayload)
    )
    assert tool_result.status == "completed"
    assert tool_result.output == [OutputTextPart(text="tool output")]
    assert turn_end_reasons == ["completed", "completed"]


async def test_model_call_preparer_turn_end_receives_error_reason() -> None:
    """End the prepared turn with error when model execution fails."""
    turn_end_reasons: list[TurnEndReason] = []

    async def prepare_model_call(
        *,
        transcript: Sequence[Event],
        model: str,
    ) -> PreparedModelCall:
        """Return a prepared failing model call."""
        del transcript

        async def on_turn_end(reason: TurnEndReason) -> None:
            turn_end_reasons.append(reason)

        return PreparedModelCall(
            native_request=NativeModelRequest(model=model, input=[]),
            inference_state=None,
            system_prompt_analysis=None,
            tool_executor=_ToolExecutor(),
            on_turn_end=on_turn_end,
        )

    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_FailingModelAdapter(),
        output_normalizer=_Normalizer([_assistant_event()]),
        model_call_preparer=prepare_model_call,
        run_repo=_RunRepo(),
        transcript_repo=_TranscriptRepo(),
    )

    with pytest.raises(ModelCallError, match="Missing scopes"):
        await execution.run(
            _Session(),
            AgentRunExecutionRequest(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                run_id="run-1",
                session_id="session-1",
                model="gpt-5.1",
            ),
        )

    assert turn_end_reasons == ["error"]


async def test_provider_tool_call_completes_without_next_model_turn() -> None:
    """Provider-hosted tool calls do not count as client tool work."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_SequenceNormalizer(
            [
                [_provider_tool_call_event()],
            ]
        ),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
            max_turns=None,
        ),
    )

    assert status == AgentRunStatus.COMPLETED
    assert run_repo.phases.count(AgentRunPhase.STREAMING_MODEL) == 1
    assert [event.kind for event in transcript_repo.events] == [
        EventKind.PROVIDER_TOOL_CALL,
        EventKind.TURN_MARKER,
        EventKind.RUN_MARKER,
    ]


async def test_provider_tool_call_with_message_completes_one_turn() -> None:
    """Provider tool trace plus final message completes in one model turn."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_SequenceNormalizer(
            [
                [_provider_tool_call_event(), _assistant_event()],
            ]
        ),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
            max_turns=None,
        ),
    )

    assert status == AgentRunStatus.COMPLETED
    assert run_repo.phases.count(AgentRunPhase.STREAMING_MODEL) == 1
    assert [event.kind for event in transcript_repo.events] == [
        EventKind.PROVIDER_TOOL_CALL,
        EventKind.ASSISTANT_MESSAGE,
        EventKind.TURN_MARKER,
        EventKind.RUN_MARKER,
    ]


async def test_compacted_run_continues_with_summary_without_terminal_marker() -> None:
    """After auto compaction, continue model call without past run marker."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    lowerer = _RecordingLowerer()
    summary_event = Event(
        id="2" * 32,
        session_id="session-1",
        kind=EventKind.COMPACTION_SUMMARY,
        payload=CompactionSummaryPayload(
            compaction_id="compact-1",
            content="summary",
            covered_until_event_id="1" * 32,
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )
    run_marker = Event(
        id="3" * 32,
        session_id="session-1",
        kind=EventKind.RUN_MARKER,
        payload=RunMarkerPayload(run_id="old-run", status="completed"),
        created_at=datetime.datetime.now(datetime.UTC),
    )

    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_assistant_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=lowerer, tool_executor=_ToolExecutor()
        ),
        pre_lower_filter=_PreFilter([summary_event, run_marker]),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert status == AgentRunStatus.COMPLETED
    assert run_repo.terminal == AgentRunStatus.COMPLETED
    assert lowerer.transcripts == [[summary_event]]


async def test_tool_turn_polls_input_before_next_model_call() -> None:
    """New input after tool turn is included in next model call transcript."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    lowerer = _RecordingLowerer()
    poll_count = 0

    async def poll_input_events(
        session_id: str,
    ) -> InputPollResult:
        """Append queued user input at second turn boundary."""
        nonlocal poll_count
        poll_count += 1
        if poll_count != 2:
            return InputPollResult(
                events=[],
                context_invalidated=False,
                complete_run=False,
            )
        return InputPollResult(
            context_invalidated=False,
            complete_run=False,
            events=[
                await transcript_repo.append(
                    _Session(),
                    EventCreate(
                        session_id=session_id,
                        kind=EventKind.USER_MESSAGE,
                        payload=UserMessagePayload(
                            content="Is something odd with the grep tool?",
                        ).model_dump(mode="json", exclude_none=True),
                    ),
                )
            ],
        )

    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_SequenceNormalizer(
            [
                [_tool_call_event()],
                [_assistant_event()],
            ]
        ),
        model_call_preparer=_model_call_preparer(
            lowerer=lowerer, tool_executor=_ToolExecutor()
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
            max_turns=2,
        ),
        poll_input_events=poll_input_events,
    )

    assert status == AgentRunStatus.COMPLETED
    assert poll_count == 2
    assert len(lowerer.transcripts) == 2
    second_turn_payloads = [event.payload for event in lowerer.transcripts[1]]
    assert any(
        isinstance(payload, ClientToolResultPayload) for payload in second_turn_payloads
    )
    assert (
        UserMessagePayload(content="Is something odd with the grep tool?")
        in second_turn_payloads
    )


async def test_context_invalidation_yields_for_request_refresh() -> None:
    """Context invalidation yields without terminating the active AgentRun."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    lowerer = _RecordingLowerer()
    poll_count = 0

    async def poll_input_events(
        session_id: str,
    ) -> InputPollResult:
        """Request a handoff at the second turn boundary."""
        del session_id
        nonlocal poll_count
        poll_count += 1
        return InputPollResult(
            events=[],
            context_invalidated=poll_count == 2,
            complete_run=False,
        )

    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_SequenceNormalizer(
            [
                [_tool_call_event()],
                [_assistant_event()],
            ]
        ),
        model_call_preparer=_model_call_preparer(
            lowerer=lowerer,
            tool_executor=_ToolExecutor(),
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
            max_turns=2,
        ),
        poll_input_events=poll_input_events,
    )

    assert status == AgentRunStatus.RUNNING
    assert poll_count == 2
    assert len(lowerer.transcripts) == 1
    assert run_repo.terminal is None
    assert all(
        event.kind is not EventKind.RUN_MARKER for event in transcript_repo.events
    )


async def test_orphan_tool_call_without_state_is_cancelled_before_lowering() -> None:
    """Repair orphan tool call absent from state before model call."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    transcript_repo.events.append(_tool_call_event())
    lowerer = _RecordingLowerer()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_assistant_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=lowerer, tool_executor=_ToolExecutor()
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert status == AgentRunStatus.COMPLETED
    result_events = [
        event
        for event in transcript_repo.events
        if event.kind == EventKind.CLIENT_TOOL_RESULT
    ]
    assert len(result_events) == 1
    payload = result_events[0].payload
    assert isinstance(payload, ClientToolResultPayload)
    assert payload.status == "cancelled"
    assert payload.call_id == "call-1"
    assert result_events[0] in lowerer.transcripts[0]


async def test_active_unresolved_tool_call_is_cancelled_before_lowering() -> None:
    """Never replay an admitted call when execution resumes."""
    run_repo = _RunRepo()
    run_repo.active_tool_calls = [
        ActiveToolCall(
            call_id="call-1",
            name="read_text",
            arguments="{}",
            started_at=datetime.datetime.now(datetime.UTC),
            owner_generation=1,
        )
    ]
    transcript_repo = _TranscriptRepo()
    transcript_repo.events.append(_tool_call_event())
    lowerer = _RecordingLowerer()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_assistant_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=lowerer, tool_executor=_ToolExecutor()
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert status == AgentRunStatus.COMPLETED
    result_events = [
        event
        for event in lowerer.transcripts[0]
        if event.kind == EventKind.CLIENT_TOOL_RESULT
    ]
    assert len(result_events) == 1
    payload = result_events[0].payload
    assert isinstance(payload, ClientToolResultPayload)
    assert payload.status == "cancelled"
    assert run_repo.active_tool_calls == []


async def test_stale_active_entry_with_result_is_removed_without_replacement() -> None:
    """Preserve the terminal result and clear only stale active ownership."""
    run_repo = _RunRepo()
    run_repo.active_tool_calls = [
        ActiveToolCall(
            call_id="call-1",
            name="read_text",
            arguments="{}",
            started_at=datetime.datetime.now(datetime.UTC),
            owner_generation=1,
        )
    ]
    transcript_repo = _TranscriptRepo()
    transcript_repo.events.extend([_tool_call_event(), _tool_result_event()])
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_assistant_event()]),
        model_call_preparer=_model_call_preparer(),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=2,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert status == AgentRunStatus.COMPLETED
    assert run_repo.active_tool_calls == []
    results = [
        event
        for event in transcript_repo.events
        if event.kind == EventKind.CLIENT_TOOL_RESULT
    ]
    assert len(results) == 1
    result_payload = results[0].payload
    assert isinstance(result_payload, ClientToolResultPayload)
    assert result_payload.status == "completed"


async def test_active_entry_without_call_event_fails_invariant() -> None:
    """Never execute state that lacks its authoritative durable call event."""
    run_repo = _RunRepo()
    run_repo.active_tool_calls = [
        ActiveToolCall(
            call_id="missing-call",
            name="read_text",
            arguments="{}",
            started_at=datetime.datetime.now(datetime.UTC),
            owner_generation=1,
        )
    ]
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_assistant_event()]),
        model_call_preparer=_model_call_preparer(),
        run_repo=run_repo,
        transcript_repo=_TranscriptRepo(),
    )

    with pytest.raises(RuntimeError, match="no durable call event"):
        await execution.run(
            _Session(),
            AgentRunExecutionRequest(
                owner_generation=2,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                run_id="run-1",
                session_id="session-1",
                model="gpt-5.1",
            ),
        )


async def test_model_stream_user_stop_appends_only_assistant_text() -> None:
    """User stop during streaming stores only assistant text and interrupted marker."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    assistant = _event(
        "1",
        EventKind.ASSISTANT_MESSAGE,
        AssistantMessagePayload(content="hello", native_artifact=_artifact()),
    )
    reasoning = _event(
        "2",
        EventKind.REASONING,
        ReasoningPayload(text="hidden", native_artifact=_artifact()),
    )
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_CancellingModelAdapter(),
        output_normalizer=_Normalizer([assistant, reasoning, _tool_call_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert status == AgentRunStatus.INTERRUPTED
    assert run_repo.terminal == AgentRunStatus.INTERRUPTED
    assert run_repo.terminal_result_event_id == transcript_repo.events[0].id
    assert run_repo.terminal_result_message == "hello"
    assert [event.kind for event in transcript_repo.events] == [
        EventKind.ASSISTANT_MESSAGE,
        EventKind.RUN_MARKER,
    ]
    marker_payload = transcript_repo.events[-1].payload
    assert isinstance(marker_payload, RunMarkerPayload)
    assert marker_payload.status == "interrupted"


async def test_model_stream_user_stop_without_text_appends_only_marker() -> None:
    """Store only interrupted marker when assistant text is absent."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_CancellingModelAdapter(),
        output_normalizer=_Normalizer([]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert status == AgentRunStatus.INTERRUPTED
    assert [event.kind for event in transcript_repo.events] == [
        EventKind.RUN_MARKER,
    ]


async def test_model_stream_ownership_loss_skips_partial_terminalization() -> None:
    """A stale owner never persists partial output or an interrupted marker."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_OwnershipLossModelAdapter(),
        output_normalizer=_Normalizer([_assistant_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    with pytest.raises(asyncio.CancelledError) as cancelled:
        await execution.run(
            _Session(),
            AgentRunExecutionRequest(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                run_id="run-1",
                session_id="session-1",
                model="gpt-5.1",
            ),
        )

    assert cancelled.value.args == (OWNERSHIP_LOST_CANCEL_MESSAGE,)
    assert transcript_repo.events == []
    assert run_repo.terminal is None


async def test_shutdown_tool_cancellation_repairs_before_reraising() -> None:
    """Shutdown cancellation records one deterministic result before handover."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    tool_executor = _CancellingToolExecutor()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_tool_call_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=tool_executor
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    with pytest.raises(asyncio.CancelledError):
        await execution.run(
            _Session(),
            AgentRunExecutionRequest(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                run_id="run-1",
                session_id="session-1",
                model="gpt-5.1",
            ),
        )

    result_events = [
        event
        for event in transcript_repo.events
        if event.kind == EventKind.CLIENT_TOOL_RESULT
    ]
    assert len(result_events) == 1
    payload = result_events[0].payload
    assert isinstance(payload, ClientToolResultPayload)
    assert payload.status == "cancelled"
    assert run_repo.active_tool_calls == []
    assert [call.call_id for call in tool_executor.cancelled_calls] == ["call-1"]


async def test_tool_user_stop_appends_cancelled_result_and_interrupts() -> None:
    """User stop during tool execution stores cancelled result and marker."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    tool_executor = _CancellingToolExecutor(user_stop=True)
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_tool_call_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=tool_executor
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert status == AgentRunStatus.INTERRUPTED
    assert run_repo.terminal == AgentRunStatus.INTERRUPTED
    assert len(tool_executor.cancelled_calls) == 1
    assert [event.kind for event in transcript_repo.events] == [
        EventKind.CLIENT_TOOL_CALL,
        EventKind.TURN_MARKER,
        EventKind.CLIENT_TOOL_RESULT,
        EventKind.RUN_MARKER,
    ]
    result_payload = transcript_repo.events[2].payload
    assert isinstance(result_payload, ClientToolResultPayload)
    assert result_payload.status == "cancelled"
    marker_payload = transcript_repo.events[3].payload
    assert isinstance(marker_payload, RunMarkerPayload)
    assert marker_payload.status == "interrupted"


async def test_tool_ownership_loss_skips_cancelled_result_and_phase_writes() -> None:
    """Tool cancellation fencing leaves unresolved state for the new owner."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    tool_executor = _CancellingToolExecutor(
        cancel_message=OWNERSHIP_LOST_CANCEL_MESSAGE
    )
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_tool_call_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=tool_executor
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    with pytest.raises(asyncio.CancelledError) as cancelled:
        await execution.run(
            _Session(),
            AgentRunExecutionRequest(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                run_id="run-1",
                session_id="session-1",
                model="gpt-5.1",
            ),
        )

    assert cancelled.value.args == (OWNERSHIP_LOST_CANCEL_MESSAGE,)
    assert [event.kind for event in transcript_repo.events] == [
        EventKind.CLIENT_TOOL_CALL,
        EventKind.TURN_MARKER,
    ]
    assert run_repo.terminal is None
    assert AgentRunPhase.STOPPING not in run_repo.phases
    assert [call.call_id for call in tool_executor.cancelled_calls] == ["call-1"]


async def test_stale_owner_cannot_append_completed_tool_result() -> None:
    """A lease steal after external I/O rejects the result before transcript write."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_tool_call_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(),
            tool_executor=_OwnershipStealingToolExecutor(run_repo),
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    with pytest.raises(asyncio.CancelledError) as cancelled:
        await execution.run(
            _Session(),
            AgentRunExecutionRequest(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                run_id="run-1",
                session_id="session-1",
                model="gpt-5.1",
            ),
        )

    assert cancelled.value.args == (OWNERSHIP_LOST_CANCEL_MESSAGE,)
    assert [event.kind for event in transcript_repo.events] == [
        EventKind.CLIENT_TOOL_CALL,
        EventKind.TURN_MARKER,
    ]
    assert run_repo.terminal is None
    assert [call.call_id for call in run_repo.active_tool_calls] == ["call-1"]
    assert run_repo.phases[-1] == AgentRunPhase.EXECUTING_TOOLS


async def test_parent_ownership_loss_reason_reaches_child_tool_task() -> None:
    """Cancelling the Run cannot downgrade child tools to generic cleanup."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    tool_executor = _CancellationAwareBlockingToolExecutor()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_tool_call_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=tool_executor
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    run_task = asyncio.create_task(
        execution.run(
            _Session(),
            AgentRunExecutionRequest(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                run_id="run-1",
                session_id="session-1",
                model="gpt-5.1",
            ),
        )
    )
    await tool_executor.started.wait()
    run_task.cancel(OWNERSHIP_LOST_CANCEL_MESSAGE)

    with pytest.raises(asyncio.CancelledError) as cancelled:
        await run_task

    assert cancelled.value.args == (OWNERSHIP_LOST_CANCEL_MESSAGE,)
    assert tool_executor.child_cancel_args == (OWNERSHIP_LOST_CANCEL_MESSAGE,)
    assert tool_executor.stale_cleanup_writes == 0
    assert [event.kind for event in transcript_repo.events] == [
        EventKind.CLIENT_TOOL_CALL,
        EventKind.TURN_MARKER,
    ]
    assert run_repo.terminal is None
    assert AgentRunPhase.STOPPING not in run_repo.phases


async def test_user_stop_detaches_tool_that_ignores_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An uncooperative Tool cannot block the interrupted marker indefinitely."""
    monkeypatch.setattr(
        execution_module,
        "_TOOL_CANCELLATION_CLEANUP_TIMEOUT_SECONDS",
        0.01,
    )
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    tool_executor = _CancellationResistantToolExecutor()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_tool_call_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=tool_executor
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )
    run_task = asyncio.create_task(
        execution.run(
            _Session(),
            AgentRunExecutionRequest(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                run_id="run-1",
                session_id="session-1",
                model="gpt-5.1",
            ),
        )
    )

    await asyncio.wait_for(tool_executor.started.wait(), timeout=1)
    run_task.cancel(USER_STOP_CANCEL_MESSAGE)
    retained_task: asyncio.Task[Any] | None = None

    try:
        assert await asyncio.wait_for(run_task, timeout=1) == AgentRunStatus.INTERRUPTED
        assert tool_executor.child_cancel_args
        assert all(
            args == (USER_STOP_CANCEL_MESSAGE,)
            for args in tool_executor.child_cancel_args
        )
        marker_payload = transcript_repo.events[-1].payload
        assert isinstance(marker_payload, RunMarkerPayload)
        assert marker_payload.status == "interrupted"
        retained_task = next(
            task
            for task in execution_module._RETAINED_TOOL_EXECUTION_TASKS  # pyright: ignore[reportPrivateUsage]
            if task.get_name() == "tool-execution:call-1"
        )
        assert not retained_task.done()
    finally:
        tool_executor.release.set()
        if retained_task is not None:
            await asyncio.wait_for(retained_task, timeout=1)
            await asyncio.sleep(0)

    assert retained_task is not None
    assert (
        retained_task not in execution_module._RETAINED_TOOL_EXECUTION_TASKS  # pyright: ignore[reportPrivateUsage]
    )


async def test_tool_result_output_sink_receives_tool_result() -> None:
    """Tool result is also delivered to projection sink."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    sink_kinds: list[list[EventKind]] = []

    async def output_sink(
        normalized: NormalizedAdapterOutput,
        appended: Sequence[Event],
    ) -> None:
        """Record event kind delivered to output sink."""
        del normalized
        sink_kinds.append([event.kind for event in appended])

    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_tool_call_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        output_sink=output_sink,
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
            max_turns=1,
        ),
    )

    assert status == AgentRunStatus.INTERRUPTED
    assert [EventKind.CLIENT_TOOL_RESULT] in sink_kinds


async def test_tool_failure_appends_failed_tool_result() -> None:
    """Repair tool exception as failed tool result so next turn is not broken."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_tool_call_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_FailingToolExecutor()
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
            max_turns=1,
        ),
    )

    assert status == AgentRunStatus.INTERRUPTED
    result_events = [
        event
        for event in transcript_repo.events
        if event.kind == EventKind.CLIENT_TOOL_RESULT
    ]
    assert len(result_events) == 1
    payload = result_events[0].payload
    assert isinstance(payload, ClientToolResultPayload)
    assert payload.status == "failed"
    output = payload.output[0]
    assert isinstance(output, OutputTextPart)
    assert "Tool execution failed" in output.text


async def test_run_input_preparation_does_not_run_lifecycle_cleanup() -> None:
    """File lifecycle cleanup is scheduler-owned, not run-loop-owned."""
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_assistant_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        run_repo=_RunRepo(),
        transcript_repo=_TranscriptRepo(),
        session_repo=_SessionRepo(None),
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
            run_index=7,
            max_turns=1,
        ),
    )

    assert status == AgentRunStatus.COMPLETED


async def test_pre_model_lower_hook_runs_before_lowerer() -> None:
    """Request-local materialization hook runs right before native lower."""
    transcript_repo = _TranscriptRepo()
    transcript_repo.events.append(
        Event(
            id="2" * 32,
            session_id="session-1",
            kind=EventKind.USER_MESSAGE,
            payload=UserMessagePayload(content="hello"),
            created_at=datetime.datetime.now(datetime.UTC),
        )
    )
    lowerer = _RecordingLowerer()
    hook = _PreModelLowerHook()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_assistant_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=lowerer, tool_executor=_ToolExecutor()
        ),
        run_repo=_RunRepo(),
        transcript_repo=transcript_repo,
        session_repo=_SessionRepo(None),
        pre_model_lower_hook=hook,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            owner_generation=1,
            tool_admission_barrier=_OpenToolAdmissionBarrier(),
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
            max_turns=1,
        ),
    )

    assert status == AgentRunStatus.COMPLETED
    assert hook.called is True
    assert lowerer.transcripts[0] == transcript_repo.events[:1]


async def test_empty_model_output_propagates_for_retry() -> None:
    """Empty model turn propagates without finalizing before retry."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    with pytest.raises(ModelCallError, match="without assistant output"):
        await execution.run(
            _Session(),
            AgentRunExecutionRequest(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                run_id="run-1",
                session_id="session-1",
                model="gpt-5.1",
            ),
        )

    assert run_repo.terminal is None
    assert transcript_repo.events == []


async def test_blank_assistant_message_propagates_for_retry() -> None:
    """Blank assistant message propagates without finalizing before retry."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    blank_message = _event(
        "1",
        EventKind.ASSISTANT_MESSAGE,
        AssistantMessagePayload(content=" ", native_artifact=_artifact()),
    )
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([blank_message]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    with pytest.raises(ModelCallError, match="without assistant output"):
        await execution.run(
            _Session(),
            AgentRunExecutionRequest(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                run_id="run-1",
                session_id="session-1",
                model="gpt-5.1",
            ),
        )

    assert run_repo.terminal is None
    assert transcript_repo.events == []


async def test_model_call_error_propagates_for_retry() -> None:
    """LLM call error propagates to the worker retry boundary."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_FailingModelAdapter(),
        output_normalizer=_Normalizer([]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    with pytest.raises(ModelCallError, match="Missing scopes"):
        await execution.run(
            _Session(),
            AgentRunExecutionRequest(
                owner_generation=1,
                tool_admission_barrier=_OpenToolAdmissionBarrier(),
                run_id="run-1",
                session_id="session-1",
                model="gpt-5.1",
            ),
        )

    assert run_repo.terminal is None
    assert transcript_repo.events == []
