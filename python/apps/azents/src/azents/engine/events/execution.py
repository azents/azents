"""Azents-owned event ReAct loop."""

import asyncio
import datetime
import itertools
import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.engine.events.model_file_refs import unique_model_file_ids
from azents.engine.events.protocols import (
    AdapterOutputNormalizer,
    ClientToolExecutor,
    ModelAdapter,
    NativeEvent,
    NativeModelRequest,
    NormalizedAdapterOutput,
    OutputSink,
    PostLowerFilter,
    PreLowerFilter,
    RunStateRepository,
    SessionHeadRepository,
    TranscriptRepository,
)
from azents.engine.events.types import (
    ActiveToolCall,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolResultPayload,
    ReasoningPayload,
    RunMarkerPayload,
    SystemPromptAnalysisPayload,
    TokenUsagePayload,
    TurnMarkerPayload,
    UnknownAdapterOutputPayload,
)
from azents.engine.run.errors import (
    ModelCallError,
    UserVisibleRuntimeError,
)
from azents.engine.run.types import USER_STOP_CANCEL_MESSAGE
from azents.repos.agent_execution import (
    AgentRunRepository,
    EventTranscriptRepository,
)
from azents.repos.agent_execution.data import EventCreate

logger = logging.getLogger(__name__)


CheckStop = Callable[[], Awaitable[bool]]
PhaseSink = Callable[[AgentRunPhase], Awaitable[None]]


@dataclass(frozen=True)
class InputPollResult:
    """Input events polled at a model-call turn boundary."""

    events: list[Event]
    context_invalidated: bool
    complete_run: bool


InputPoller = Callable[[AsyncSession, str], Awaitable[InputPollResult]]
TurnEndReason = Literal["completed", "error", "cancelled", "unknown"]
TurnEndCallback = Callable[[TurnEndReason], Awaitable[None]]


class PreModelLowerHook(Protocol):
    """Request-local preparation hook before model lowering."""

    async def __call__(
        self,
        *,
        transcript: Sequence[Event],
    ) -> object:
        """Prepare request-local state required by native lowerer."""
        ...


@dataclass(frozen=True)
class PreparedModelCall:
    """Turn-local model call dependencies."""

    native_request: NativeModelRequest
    system_prompt_analysis: SystemPromptAnalysisPayload | None
    tool_executor: ClientToolExecutor
    on_turn_end: TurnEndCallback | None


class ModelCallPreparer(Protocol):
    """Prepare turn-local model request and tool executor."""

    async def __call__(
        self,
        *,
        transcript: Sequence[Event],
        model: str,
    ) -> PreparedModelCall:
        """Prepare one model-call turn."""
        ...


class ModelFilePinRepositoryProtocol(Protocol):
    """ModelFile active run pin repository protocol."""

    async def pin_many(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        run_id: str,
        model_file_ids: Sequence[str],
    ) -> None:
        """Pin ModelFiles for an active run."""
        ...

    async def release_run(self, session: AsyncSession, *, run_id: str) -> None:
        """Release ModelFile pins for a run."""
        ...


@dataclass(frozen=True)
class AgentRunExecutionRequest:
    """Agent run execution request."""

    run_id: str
    session_id: str
    model: str
    run_index: int = 1
    max_turns: int | None = None


class _ModelStreamUserInterrupted(Exception):
    """Indicates model stream was interrupted by user stop."""

    def __init__(self, native_events: Sequence[NativeEvent]) -> None:
        super().__init__(USER_STOP_CANCEL_MESSAGE)
        self.native_events = list(native_events)


class _ToolExecutionUserInterrupted(Exception):
    """Indicates tool execution was interrupted by user stop."""


class AgentRunExecution:
    """ReAct loop based on event transcript."""

    def __init__(
        self,
        *,
        post_lower_filter: PostLowerFilter,
        model_adapter: ModelAdapter,
        output_normalizer: AdapterOutputNormalizer,
        model_call_preparer: ModelCallPreparer,
        pre_lower_filter: PreLowerFilter | None = None,
        output_sink: OutputSink | None = None,
        phase_sink: PhaseSink | None = None,
        pre_model_lower_hook: PreModelLowerHook | None = None,
        model_file_pin_repo: ModelFilePinRepositoryProtocol | None = None,
        run_repo: RunStateRepository | None = None,
        transcript_repo: TranscriptRepository | None = None,
        session_repo: SessionHeadRepository | None = None,
    ) -> None:
        """Inject loop dependencies."""
        self._post_lower_filter = post_lower_filter
        self._model_adapter = model_adapter
        self._output_normalizer = output_normalizer
        self._pre_lower_filter = pre_lower_filter
        self._model_call_preparer = model_call_preparer
        self._output_sink = output_sink
        self._phase_sink = phase_sink
        self._pre_model_lower_hook = pre_model_lower_hook
        self._model_file_pin_repo = model_file_pin_repo
        self._run_repo = run_repo or AgentRunRepository()
        self._transcript_repo = transcript_repo or EventTranscriptRepository()
        self._session_repo = session_repo

    async def run(
        self,
        session: AsyncSession,
        request: AgentRunExecutionRequest,
        *,
        check_stop: CheckStop | None = None,
        poll_input_events: InputPoller | None = None,
    ) -> AgentRunStatus:
        """Run until terminal state."""
        try:
            for _model_call_index in _turn_range(request.max_turns):
                if await _stopped(check_stop):
                    await self._mark_terminal(
                        session,
                        request.run_id,
                        AgentRunStatus.INTERRUPTED,
                    )
                    await session.commit()
                    return AgentRunStatus.INTERRUPTED

                if poll_input_events is not None:
                    poll_result = await poll_input_events(
                        session,
                        request.session_id,
                    )
                    if poll_result.complete_run:
                        await self._mark_terminal(
                            session,
                            request.run_id,
                            AgentRunStatus.COMPLETED,
                        )
                        await session.commit()
                        return AgentRunStatus.COMPLETED
                    if poll_result.context_invalidated:
                        await session.commit()
                        return AgentRunStatus.RUNNING
                    if poll_result.events:
                        await session.commit()

                head_event_id = await self._model_input_head_event_id(
                    session,
                    request.session_id,
                )
                transcript = await self._transcript_repo.list_for_model_input(
                    session,
                    request.session_id,
                    head_event_id=head_event_id,
                )
                repaired_events = await self._append_missing_tool_results(
                    session,
                    request,
                    transcript,
                )
                if repaired_events:
                    await session.commit()
                    transcript = await self._transcript_repo.list_for_model_input(
                        session,
                        request.session_id,
                        head_event_id=head_event_id,
                    )
                await self._update_phase(
                    session,
                    request.run_id,
                    AgentRunPhase.PREPARING_INPUT,
                )
                compacted = False
                if self._pre_lower_filter is not None:
                    transcript = await self._pre_lower_filter.apply(session, transcript)
                    compacted = self._pre_lower_filter.was_compacted
                if compacted:
                    await session.commit()
                if self._model_file_pin_repo is not None:
                    await self._model_file_pin_repo.pin_many(
                        session,
                        session_id=request.session_id,
                        run_id=request.run_id,
                        model_file_ids=unique_model_file_ids(transcript),
                    )
                    await session.commit()
                if self._pre_model_lower_hook is not None:
                    await self._pre_model_lower_hook(transcript=transcript)
                model_input_transcript = (
                    _without_existing_terminal_run_markers(transcript)
                    if compacted
                    else transcript
                )
                prepared = await self._prepare_model_call(
                    transcript=model_input_transcript,
                    model=request.model,
                )
                turn_end_callback = prepared.on_turn_end
                turn_ended = False

                async def finish_turn(
                    reason: TurnEndReason,
                    callback: TurnEndCallback | None = turn_end_callback,
                ) -> None:
                    """Dispatch this turn's end hook at most once."""
                    nonlocal turn_ended
                    if turn_ended:
                        return
                    turn_ended = True
                    await _finish_turn(callback, reason)

                try:
                    native_request = self._post_lower_filter.apply(
                        prepared.native_request
                    )

                    await self._update_phase(
                        session,
                        request.run_id,
                        AgentRunPhase.WAITING_FOR_MODEL,
                    )
                    await session.commit()
                    try:
                        native_events = await self._stream_model(
                            session,
                            request.run_id,
                            native_request,
                        )
                    except _ModelStreamUserInterrupted as exc:
                        await finish_turn("cancelled")
                        return await self._complete_user_interrupted_model_stream(
                            session,
                            request,
                            exc.native_events,
                        )

                    await self._update_phase(
                        session,
                        request.run_id,
                        AgentRunPhase.NORMALIZING_OUTPUT,
                    )
                    normalized = self._output_normalizer.normalize(
                        request.session_id,
                        native_events,
                    )
                    _log_model_token_usage(
                        request=request,
                        usage=normalized.usage,
                    )

                    await self._update_phase(
                        session,
                        request.run_id,
                        AgentRunPhase.APPENDING_EVENTS,
                    )
                    if not _has_durable_model_output(normalized.events):
                        raise ModelCallError(
                            "Model completed without assistant output."
                        )
                    appended = await self._append_events(session, normalized.events)
                    turn_marker = await self._append_turn_marker(
                        session,
                        request.session_id,
                        request.run_id,
                        normalized.usage,
                        system_prompt=prepared.system_prompt_analysis,
                    )
                    turn_events = [turn_marker] if turn_marker is not None else []
                    client_tool_calls = [
                        event.payload
                        for event in appended
                        if isinstance(event.payload, ClientToolCallPayload)
                    ]
                    if not client_tool_calls:
                        run_marker = await self._append_run_marker(
                            session,
                            request.session_id,
                            request.run_id,
                            "completed",
                        )
                        terminal_event_id, terminal_message = (
                            _terminal_result_from_events(appended)
                        )
                        await self._mark_terminal(
                            session,
                            request.run_id,
                            AgentRunStatus.COMPLETED,
                            terminal_result_event_id=terminal_event_id,
                            terminal_result_message=terminal_message,
                        )
                        await session.commit()
                        if self._output_sink is not None:
                            await self._output_sink(
                                normalized,
                                [*appended, *turn_events, run_marker],
                            )
                        await finish_turn("completed")
                        return AgentRunStatus.COMPLETED

                    await session.commit()
                    if self._output_sink is not None:
                        await self._output_sink(normalized, [*appended, *turn_events])
                    try:
                        await self._execute_tools(
                            session,
                            request.run_id,
                            request.session_id,
                            client_tool_calls,
                            tool_executor=prepared.tool_executor,
                        )
                    except _ToolExecutionUserInterrupted:
                        run_marker = await self._append_run_marker(
                            session,
                            request.session_id,
                            request.run_id,
                            "interrupted",
                        )
                        await self._mark_terminal(
                            session,
                            request.run_id,
                            AgentRunStatus.INTERRUPTED,
                        )
                        await session.commit()
                        if self._output_sink is not None:
                            await self._output_sink(
                                NormalizedAdapterOutput(events=[]),
                                [run_marker],
                            )
                        await finish_turn("cancelled")
                        return AgentRunStatus.INTERRUPTED
                    await finish_turn("completed")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await finish_turn("error")
                    raise
        except UserVisibleRuntimeError:
            raise

        await self._append_run_marker(
            session,
            request.session_id,
            request.run_id,
            "interrupted",
        )
        await self._mark_terminal(session, request.run_id, AgentRunStatus.INTERRUPTED)
        await session.commit()
        return AgentRunStatus.INTERRUPTED

    async def _prepare_model_call(
        self,
        *,
        transcript: Sequence[Event],
        model: str,
    ) -> PreparedModelCall:
        """Prepare turn-local model request and tool executor."""
        return await self._model_call_preparer(
            transcript=transcript,
            model=model,
        )

    async def _stream_model(
        self,
        session: AsyncSession,
        run_id: str,
        native_request: NativeModelRequest,
    ) -> list[NativeEvent]:
        """Collect model stream."""
        await self._update_phase(
            session,
            run_id,
            AgentRunPhase.STREAMING_MODEL,
        )
        await session.commit()
        events: list[NativeEvent] = []
        try:
            async for event in self._model_adapter.stream(native_request):
                events.append(event)
        except asyncio.CancelledError as exc:
            if _is_user_stop_cancellation(exc):
                raise _ModelStreamUserInterrupted(events) from exc
            raise
        return events

    async def _complete_user_interrupted_model_stream(
        self,
        session: AsyncSession,
        request: AgentRunExecutionRequest,
        native_events: Sequence[NativeEvent],
    ) -> AgentRunStatus:
        """Durabilize partial text from model stream interrupted by user stop."""
        await self._update_phase(
            session,
            request.run_id,
            AgentRunPhase.APPENDING_EVENTS,
        )
        normalized = self._output_normalizer.normalize(
            request.session_id,
            native_events,
        )
        assistant_events = [
            event
            for event in normalized.events
            if event.kind == EventKind.ASSISTANT_MESSAGE
            and isinstance(event.payload, AssistantMessagePayload)
            and _assistant_content_is_non_empty(event.payload.content)
        ]
        appended = await self._append_events(session, assistant_events)
        run_marker = await self._append_run_marker(
            session,
            request.session_id,
            request.run_id,
            "interrupted",
        )
        terminal_event_id, terminal_message = _terminal_result_from_events(appended)
        await self._mark_terminal(
            session,
            request.run_id,
            AgentRunStatus.INTERRUPTED,
            terminal_result_event_id=terminal_event_id,
            terminal_result_message=terminal_message,
        )
        await session.commit()
        if self._output_sink is not None:
            await self._output_sink(
                NormalizedAdapterOutput(events=assistant_events),
                [*appended, run_marker],
            )
        return AgentRunStatus.INTERRUPTED

    async def _append_events(
        self,
        session: AsyncSession,
        events: Sequence[Event],
    ) -> list[Event]:
        """Append events to durable transcript."""
        appended: list[Event] = []
        for event in events:
            appended.append(
                await self._transcript_repo.append(
                    session,
                    EventCreate(
                        session_id=event.session_id,
                        kind=event.kind,
                        payload=event.payload.model_dump(
                            mode="json",
                            exclude_none=True,
                        ),
                        external_id=event.external_id,
                        adapter=event.adapter,
                        provider=event.provider,
                        model=event.model,
                        native_format=event.native_format,
                        schema_version=event.schema_version,
                    ),
                )
            )
        return appended

    async def _execute_tools(
        self,
        session: AsyncSession,
        run_id: str,
        session_id: str,
        tool_calls: Sequence[ClientToolCallPayload],
        *,
        tool_executor: ClientToolExecutor,
    ) -> None:
        """Run foreground client tool calls in parallel and append results."""
        active_calls = [
            _active_tool_call(call, background=False) for call in tool_calls
        ]
        await self._update_phase(
            session,
            run_id,
            AgentRunPhase.EXECUTING_TOOLS,
            active_tool_calls=active_calls,
        )
        await session.commit()
        try:
            results = await asyncio.gather(
                *(
                    self._execute_tool_safely(call, tool_executor=tool_executor)
                    for call in tool_calls
                )
            )
        except asyncio.CancelledError as exc:
            if not _is_user_stop_cancellation(exc):
                raise
            for call in tool_calls:
                tool_executor.request_cancel(call)
            await self._append_cancelled_tool_results(
                session,
                session_id,
                tool_calls,
            )
            await self._update_phase(
                session,
                run_id,
                AgentRunPhase.STOPPING,
                active_tool_calls=[],
            )
            await session.commit()
            raise _ToolExecutionUserInterrupted from exc
        appended: list[Event] = []
        for result in results:
            appended.append(
                await self._transcript_repo.append(
                    session,
                    EventCreate(
                        session_id=session_id,
                        kind=EventKind.CLIENT_TOOL_RESULT,
                        payload=result.model_dump(mode="json", exclude_none=True),
                    ),
                )
            )
        await self._update_phase(
            session,
            run_id,
            AgentRunPhase.APPENDING_EVENTS,
            active_tool_calls=[],
        )
        await session.commit()
        if self._output_sink is not None:
            await self._output_sink(NormalizedAdapterOutput(events=[]), appended)

    async def _append_missing_tool_results(
        self,
        session: AsyncSession,
        request: AgentRunExecutionRequest,
        transcript: Sequence[Event],
    ) -> list[Event]:
        """Repair orphan tool calls absent from state with cancelled results."""
        unresolved_calls = _unresolved_client_tool_calls(transcript)
        if not unresolved_calls:
            return []

        run_state = await self._run_repo.get_by_id(session, request.run_id)
        active_call_ids = (
            {active.call_id for active in run_state.active_tool_calls}
            if run_state is not None
            else set()
        )
        orphan_calls = [
            call for call in unresolved_calls if call.call_id not in active_call_ids
        ]
        return await self._append_cancelled_tool_results(
            session,
            request.session_id,
            orphan_calls,
        )

    async def _append_cancelled_tool_results(
        self,
        session: AsyncSession,
        session_id: str,
        tool_calls: Sequence[ClientToolCallPayload],
    ) -> list[Event]:
        """Append tool call as cancelled event result."""
        appended: list[Event] = []
        for call in tool_calls:
            payload = ClientToolResultPayload(
                call_id=call.call_id,
                name=call.name,
                status="cancelled",
                output=[
                    OutputTextPart(
                        text=(
                            "Tool execution was cancelled before a result was recorded."
                        ),
                    )
                ],
            )
            external_id = f"tool-result:{call.call_id}:cancelled"
            existing = await self._transcript_repo.get_by_external_id(
                session,
                session_id,
                external_id,
            )
            if existing is not None:
                appended.append(existing)
                continue
            appended.append(
                await self._transcript_repo.append(
                    session,
                    EventCreate(
                        session_id=session_id,
                        kind=EventKind.CLIENT_TOOL_RESULT,
                        payload=payload.model_dump(mode="json", exclude_none=True),
                        external_id=external_id,
                    ),
                )
            )
        if appended and self._output_sink is not None:
            await self._output_sink(NormalizedAdapterOutput(events=[]), appended)
        return appended

    async def _model_input_head_event_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> str | None:
        """Fetch model input head of event session."""
        if self._session_repo is None:
            return None
        state = await self._session_repo.get_by_id(session, session_id)
        if state is None:
            return None
        return state.model_input_head_event_id

    async def _execute_tool_safely(
        self,
        call: ClientToolCallPayload,
        *,
        tool_executor: ClientToolExecutor,
    ) -> ClientToolResultPayload:
        """Repair tool exception as failed tool result."""
        try:
            return await tool_executor.execute(call)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Client tool execution failed",
                extra={
                    "call_id": call.call_id,
                    "tool_name": call.name,
                    "error_type": exc.__class__.__name__,
                },
            )
            return ClientToolResultPayload(
                call_id=call.call_id,
                name=call.name,
                status="failed",
                output=[
                    OutputTextPart(
                        text=f"Tool execution failed: {exc.__class__.__name__}",
                    )
                ],
            )

    async def _append_run_marker(
        self,
        session: AsyncSession,
        session_id: str,
        run_id: str,
        status: Literal["completed", "stopped", "failed", "interrupted"],
    ) -> Event:
        """Append run marker."""
        external_id = f"run-marker:{run_id}:{status}"
        existing = await self._transcript_repo.get_by_external_id(
            session,
            session_id,
            external_id,
        )
        if existing is not None:
            return existing
        return await self._transcript_repo.append(
            session,
            EventCreate(
                session_id=session_id,
                kind=EventKind.RUN_MARKER,
                payload=RunMarkerPayload(
                    run_id=run_id,
                    status=status,
                ).model_dump(mode="json", exclude_none=True),
                external_id=external_id,
            ),
        )

    async def _append_turn_marker(
        self,
        session: AsyncSession,
        session_id: str,
        run_id: str,
        usage: TokenUsagePayload | None,
        *,
        system_prompt: SystemPromptAnalysisPayload | None = None,
    ) -> Event | None:
        """Append turn marker."""
        if usage is None:
            return None
        return await self._transcript_repo.append(
            session,
            EventCreate(
                session_id=session_id,
                kind=EventKind.TURN_MARKER,
                payload=TurnMarkerPayload(
                    run_id=run_id,
                    usage=usage,
                    system_prompt=system_prompt,
                ).model_dump(mode="json", exclude_none=True),
            ),
        )

    async def _mark_terminal(
        self,
        session: AsyncSession,
        run_id: str,
        status: AgentRunStatus,
        *,
        terminal_result_event_id: str | None = None,
        terminal_result_message: str | None = None,
    ) -> None:
        """Record run terminal state."""
        await self._run_repo.mark_terminal(
            session,
            run_id,
            status,
            ended_at=datetime.datetime.now(datetime.UTC),
            terminal_result_event_id=terminal_result_event_id,
            terminal_result_message=terminal_result_message,
        )
        if self._model_file_pin_repo is not None:
            await self._model_file_pin_repo.release_run(session, run_id=run_id)

    async def _update_phase(
        self,
        session: AsyncSession,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> None:
        """Reflect run phase in durable state and UI projection."""
        await self._run_repo.update_phase(
            session,
            run_id,
            phase,
            active_tool_calls=active_tool_calls,
        )
        if self._phase_sink is not None:
            await self._phase_sink(phase)


async def _finish_turn(
    callback: TurnEndCallback | None,
    reason: TurnEndReason,
) -> None:
    """Dispatch a prepared turn-end callback when present."""
    if callback is None:
        return
    await callback(reason)


def _log_model_token_usage(
    *,
    request: AgentRunExecutionRequest,
    usage: TokenUsagePayload | None,
) -> None:
    """Log per-turn token usage, including prompt cache counters."""
    if usage is None:
        logger.info(
            "Model token usage",
            extra={
                "session_id": request.session_id,
                "run_id": request.run_id,
                "run_index": request.run_index,
                "model": request.model,
                "usage_present": False,
            },
        )
        return
    cached_tokens = usage.cached_tokens or 0
    prompt_tokens = usage.prompt_tokens
    cached_ratio = cached_tokens / prompt_tokens if prompt_tokens > 0 else None
    logger.info(
        "Model token usage",
        extra={
            "session_id": request.session_id,
            "run_id": request.run_id,
            "run_index": request.run_index,
            "model": request.model,
            "usage_present": True,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
            "cached_tokens": usage.cached_tokens,
            "cache_creation_tokens": usage.cache_creation_tokens,
            "reasoning_tokens": usage.reasoning_tokens,
            "cost_usd": usage.cost_usd,
            "cached_token_ratio": (
                round(cached_ratio, 4) if cached_ratio is not None else None
            ),
            "raw_usage": usage.raw,
            "raw_hidden_params": usage.raw_hidden_params,
        },
    )


def _terminal_result_from_events(
    events: Sequence[Event],
) -> tuple[str | None, str | None]:
    """Project the latest assistant text from terminal run events."""
    for event in reversed(events):
        payload = event.payload
        if isinstance(payload, AssistantMessagePayload):
            text = _assistant_content_text(payload.content)
            if text is not None:
                return event.id, text
    return None, None


def _assistant_content_text(content: object) -> str | None:
    """Extract text from assistant content for terminal result projection."""
    if isinstance(content, str):
        stripped = content.strip()
        return stripped or None
    if isinstance(content, list):
        parts = [
            part.text.strip() for part in content if isinstance(part, OutputTextPart)
        ]
        text = "\n".join(part for part in parts if part)
        return text or None
    return None


def _turn_range(max_turns: int | None) -> Iterable[int]:
    """Return unbounded turn iterator when max_turns is None."""
    if max_turns is None:
        return itertools.count()
    return range(max_turns)


def _is_user_stop_cancellation(exc: asyncio.CancelledError) -> bool:
    """Check whether CancelledError is user stop cancellation."""
    return any(arg == USER_STOP_CANCEL_MESSAGE for arg in exc.args)


def _has_durable_model_output(events: Sequence[Event]) -> bool:
    """Check whether model turn contains at least one durable output."""
    for event in events:
        match event.payload:
            case AssistantMessagePayload(content=content):
                if _assistant_content_is_non_empty(content):
                    return True
            case ReasoningPayload(text=text, summary=summary):
                if text or summary:
                    return True
            case (
                ClientToolCallPayload()
                | ProviderToolCallPayload()
                | ProviderToolResultPayload()
                | UnknownAdapterOutputPayload()
            ):
                return True
            case _:
                pass
    return False


def _assistant_content_is_non_empty(content: object) -> bool:
    """Check whether assistant content contains text to durabilize."""
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, Sequence):
        return bool(content)
    return False


def _active_tool_call(
    call: ClientToolCallPayload,
    *,
    background: bool,
) -> ActiveToolCall:
    """Create active tool call projection."""
    return ActiveToolCall(
        call_id=call.call_id,
        name=call.name,
        arguments=call.arguments,
        started_at=datetime.datetime.now(datetime.UTC),
        background=background,
    )


async def _stopped(check_stop: CheckStop | None) -> bool:
    """Check whether stop was requested."""
    if check_stop is None:
        return False
    return await check_stop()


def _without_existing_terminal_run_markers(
    transcript: Sequence[Event],
) -> list[Event]:
    """Exclude past terminal run markers from resume input after compaction."""
    return [
        event for event in transcript if not isinstance(event.payload, RunMarkerPayload)
    ]


def _unresolved_client_tool_calls(
    transcript: Sequence[Event],
) -> list[ClientToolCallPayload]:
    """Return client tool calls that do not yet have results in transcript."""
    pending: dict[str, ClientToolCallPayload] = {}
    for event in transcript:
        payload = event.payload
        if isinstance(payload, ClientToolCallPayload):
            pending[payload.call_id] = payload
        elif isinstance(payload, ClientToolResultPayload):
            pending.pop(payload.call_id, None)
    return list(pending.values())
