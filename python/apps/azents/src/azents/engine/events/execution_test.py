"""Event AgentRunExecution tests."""

import asyncio
import datetime
import logging
from collections.abc import AsyncIterator, Callable, Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
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
from azents.engine.run.types import USER_STOP_CANCEL_MESSAGE
from azents.repos.agent_execution.data import EventCreate


class _Session(AsyncSession):
    """AsyncSession for tests."""

    def __init__(self, commit_value: Callable[[], int] | None = None) -> None:
        """Record values at commit time."""
        self.commits: list[int] = []
        self._commit_value = commit_value

    async def commit(self) -> None:
        """Record commit call."""
        value = self._commit_value() if self._commit_value is not None else 0
        self.commits.append(value)


class _RunRepo:
    """Run repository for tests."""

    def __init__(self) -> None:
        self.phases: list[AgentRunPhase] = []
        self.terminal: AgentRunStatus | None = None
        self.active_tool_calls: list[ActiveToolCall] = []
        self.terminal_result_event_id: str | None = None
        self.terminal_result_message: str | None = None

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
            active_tool_calls=list(self.active_tool_calls),
            started_at=datetime.datetime.now(datetime.UTC),
            updated_at=datetime.datetime.now(datetime.UTC),
        )

    async def update_phase(
        self,
        session: AsyncSession,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> object:
        """Record phase update."""
        del session, run_id
        self.phases.append(phase)
        if active_tool_calls is not None:
            self.active_tool_calls = list(active_tool_calls)
        return object()

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
        session: AsyncSession,
        transcript: Sequence[Event],
    ) -> list[Event]:
        """Return transcript after compaction."""
        del session, transcript
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


class _Normalizer:
    """Normalizer for tests."""

    def __init__(
        self,
        events: list[Event],
        usage: TokenUsagePayload | None = None,
    ) -> None:
        self._events = events
        self._usage = usage or _usage()

    def normalize(
        self,
        session_id: str,
        native_events: Sequence[NativeEvent],
    ) -> NormalizedAdapterOutput:
        """Return predefined event."""
        return NormalizedAdapterOutput(events=self._events, usage=self._usage)


class _SequenceNormalizer:
    """Return normalized output by call order."""

    def __init__(self, event_batches: Sequence[Sequence[Event]]) -> None:
        self._event_batches = [list(events) for events in event_batches]
        self._index = 0

    def normalize(
        self,
        session_id: str,
        native_events: Sequence[NativeEvent],
    ) -> NormalizedAdapterOutput:
        """Return next batch."""
        del session_id, native_events
        if self._index >= len(self._event_batches):
            return NormalizedAdapterOutput(events=[], usage=_usage())
        events = self._event_batches[self._index]
        self._index += 1
        return NormalizedAdapterOutput(events=events, usage=_usage())


class _ToolExecutor:
    """Tool executor for tests."""

    def __init__(self) -> None:
        self.cancelled_calls: list[ClientToolCallPayload] = []

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Return tool result."""
        return ClientToolResultPayload(
            call_id=call.call_id,
            name=call.name,
            status="completed",
            output=[OutputTextPart(text="tool output")],
        )

    def request_cancel(self, call: ClientToolCallPayload) -> None:
        """Record cancellation request."""
        self.cancelled_calls.append(call)


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

    def __init__(self, *, user_stop: bool = False) -> None:
        self._user_stop = user_stop
        self.cancelled_calls: list[ClientToolCallPayload] = []

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Raise tool cancellation."""
        del call
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


def _tool_call_event() -> Event:
    """Create client tool call event."""
    return Event(
        id="0" * 32,
        session_id="session-1",
        kind=EventKind.CLIENT_TOOL_CALL,
        payload=ClientToolCallPayload(
            call_id="call-1",
            name="read_text",
            arguments="{}",
            native_artifact=_artifact(),
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
    emitted_phases: list[AgentRunPhase] = []

    async def collect_phase(phase: AgentRunPhase) -> None:
        emitted_phases.append(phase)

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
    assert emitted_phases == run_repo.phases


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
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    with caplog.at_level(logging.INFO, logger="azents.engine.events.execution"):
        status = await execution.run(
            _Session(),
            AgentRunExecutionRequest(
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
    assert payload.system_prompt == system_prompt
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
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert transcript_repo.head_event_ids == ["2" * 32]


async def test_tool_run_with_turn_limit_interrupts_after_tool_result() -> None:
    """Append final-turn tool result at turn limit, then end as interrupted."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    execution = AgentRunExecution(
        post_lower_filter=_PostFilter(),
        model_adapter=_ModelAdapter(),
        output_normalizer=_Normalizer([_tool_call_event(), _assistant_event()]),
        model_call_preparer=_model_call_preparer(
            lowerer=_Lowerer(), tool_executor=_ToolExecutor()
        ),
        run_repo=run_repo,
        transcript_repo=transcript_repo,
    )

    status = await execution.run(
        _Session(),
        AgentRunExecutionRequest(
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
            max_turns=1,
        ),
    )

    assert status == AgentRunStatus.INTERRUPTED
    assert AgentRunPhase.EXECUTING_TOOLS in run_repo.phases
    assert any(
        event.kind == EventKind.CLIENT_TOOL_RESULT for event in transcript_repo.events
    )


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
        session: AsyncSession,
        session_id: str,
    ) -> InputPollResult:
        """Append queued user input at second turn boundary."""
        nonlocal poll_count
        poll_count += 1
        if poll_count != 2:
            return InputPollResult(events=[])
        return InputPollResult(
            events=[
                await transcript_repo.append(
                    session,
                    EventCreate(
                        session_id=session_id,
                        kind=EventKind.USER_MESSAGE,
                        payload=UserMessagePayload(
                            content="Is something odd with the grep tool?",
                        ).model_dump(mode="json", exclude_none=True),
                    ),
                )
            ]
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


async def test_context_invalidation_exits_before_next_model_call() -> None:
    """Context invalidation exits the run before stale model lowering."""
    run_repo = _RunRepo()
    transcript_repo = _TranscriptRepo()
    lowerer = _RecordingLowerer()
    poll_count = 0

    async def poll_input_events(
        session: AsyncSession,
        session_id: str,
    ) -> InputPollResult:
        """Request a handoff at the second turn boundary."""
        del session, session_id
        nonlocal poll_count
        poll_count += 1
        return InputPollResult(events=[], context_invalidated=poll_count == 2)

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
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
            max_turns=2,
        ),
        poll_input_events=poll_input_events,
    )

    assert status == AgentRunStatus.CANCELLED
    assert poll_count == 2
    assert len(lowerer.transcripts) == 1
    assert run_repo.terminal == AgentRunStatus.CANCELLED
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


async def test_active_orphan_tool_call_is_not_cancelled_before_lowering() -> None:
    """Active tool calls remaining in state are not cancelled repair targets."""
    run_repo = _RunRepo()
    run_repo.active_tool_calls = [
        ActiveToolCall(
            call_id="call-1",
            name="read_text",
            arguments="{}",
            started_at=datetime.datetime.now(datetime.UTC),
            background=False,
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
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert status == AgentRunStatus.COMPLETED
    assert all(
        event.kind != EventKind.CLIENT_TOOL_RESULT for event in lowerer.transcripts[0]
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
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert status == AgentRunStatus.INTERRUPTED
    assert run_repo.terminal == AgentRunStatus.INTERRUPTED
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
            run_id="run-1",
            session_id="session-1",
            model="gpt-5.1",
        ),
    )

    assert status == AgentRunStatus.INTERRUPTED
    assert [event.kind for event in transcript_repo.events] == [
        EventKind.RUN_MARKER,
    ]


async def test_non_user_tool_cancellation_reraises_without_repair() -> None:
    """Non-user tool cancellation propagates cancellation without durable repair."""
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
    assert result_events == []
    assert run_repo.active_tool_calls
    assert tool_executor.cancelled_calls == []


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
                run_id="run-1",
                session_id="session-1",
                model="gpt-5.1",
            ),
        )

    assert run_repo.terminal is None
    assert transcript_repo.events == []
