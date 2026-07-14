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
from azents.core.inference_profile import SessionInferenceState
from azents.engine.events.model_file_refs import unique_model_file_ids
from azents.engine.events.protocols import (
    AdapterOutputNormalizer,
    AdapterOutputStream,
    ClientToolExecutor,
    ModelAdapter,
    NativeModelRequest,
    NormalizedAdapterOutput,
    OutputSink,
    PostLowerFilter,
    PreLowerFilter,
    RunStateRepository,
    SessionHeadRepository,
    TranscriptRepository,
)
from azents.engine.events.tool_calls import (
    finalize_tool_result,
    tool_call_external_id,
)
from azents.engine.events.types import (
    ActiveToolCall,
    AgentRunState,
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
from azents.engine.run.contracts import ToolAdmissionBarrier
from azents.engine.run.errors import (
    ModelCallError,
    UserVisibleRuntimeError,
)
from azents.engine.run.types import (
    OWNERSHIP_LOST_CANCEL_MESSAGE,
    USER_STOP_CANCEL_MESSAGE,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import (
    AgentRunNotActiveError,
    AgentRunOwnershipLostError,
    AgentRunRepository,
    EventTranscriptRepository,
)
from azents.repos.agent_execution.data import EventCreate

logger = logging.getLogger(__name__)

_TOOL_CANCELLATION_CLEANUP_TIMEOUT_SECONDS = 0.25

CheckStop = Callable[[], Awaitable[bool]]
PhaseSink = Callable[[AgentRunPhase, datetime.datetime | None], Awaitable[None]]


@dataclass(frozen=True)
class InputPollResult:
    """Input events polled at a model-call turn boundary."""

    events: list[Event]
    context_invalidated: bool
    complete_run: bool


InputPoller = Callable[[str], Awaitable[InputPollResult]]
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
    inference_state: SessionInferenceState | None
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
    owner_generation: int
    tool_admission_barrier: ToolAdmissionBarrier
    run_index: int = 1
    max_turns: int | None = None


class _ModelStreamUserInterrupted(Exception):
    """Indicates model stream was interrupted by user stop."""

    def __init__(self, normalized: NormalizedAdapterOutput) -> None:
        super().__init__(USER_STOP_CANCEL_MESSAGE)
        self.normalized = normalized


class _ToolExecutionUserInterrupted(Exception):
    """Indicates tool execution was interrupted by user stop."""


@dataclass(frozen=True)
class _ToolExecutionOutcome:
    """One foreground tool execution outcome."""

    call: ClientToolCallPayload
    result: ClientToolResultPayload


_RETAINED_TOOL_EXECUTION_TASKS: set[asyncio.Task[_ToolExecutionOutcome]] = set()


def _on_retained_tool_execution_done(
    task: asyncio.Task[_ToolExecutionOutcome],
) -> None:
    """Release a detached Tool task after consuming its terminal outcome."""
    _RETAINED_TOOL_EXECUTION_TASKS.discard(task)
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.warning("Detached Tool execution failed", exc_info=True)


def _retain_tool_execution_task(
    task: asyncio.Task[_ToolExecutionOutcome],
) -> None:
    """Keep a cancellation-resistant Tool task alive until it finishes."""
    if task in _RETAINED_TOOL_EXECUTION_TASKS:
        return
    _RETAINED_TOOL_EXECUTION_TASKS.add(task)
    task.add_done_callback(_on_retained_tool_execution_done)


def _consume_tool_execution_outcome(
    task: asyncio.Task[_ToolExecutionOutcome],
) -> None:
    """Retrieve a cleanup-completed Tool task without replacing the primary error."""
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.warning("Tool execution failed during sibling cleanup", exc_info=True)


async def _cancel_and_drain_tool_tasks(
    tasks: Sequence[asyncio.Task[_ToolExecutionOutcome]],
    *,
    cancellation_reason: object | None,
) -> None:
    """Cancel Tool tasks, then hard-bound their drain and retain any stragglers."""
    for task in tasks:
        if task.done():
            continue
        if cancellation_reason is None:
            task.cancel()
        else:
            task.cancel(cancellation_reason)

    try:
        done, pending = await asyncio.wait(
            tasks,
            timeout=_TOOL_CANCELLATION_CLEANUP_TIMEOUT_SECONDS,
        )
    except asyncio.CancelledError:
        for task in tasks:
            if task.done():
                _consume_tool_execution_outcome(task)
            else:
                if cancellation_reason is None:
                    task.cancel()
                else:
                    task.cancel(cancellation_reason)
                _retain_tool_execution_task(task)
        raise

    for task in done:
        _consume_tool_execution_outcome(task)
    if not pending:
        return

    for task in pending:
        if cancellation_reason is None:
            task.cancel()
        else:
            task.cancel(cancellation_reason)
        _retain_tool_execution_task(task)
    logger.error(
        "Tool executions ignored cancellation cleanup deadline; detached",
        extra={
            "pending_tool_count": len(pending),
            "timeout": _TOOL_CANCELLATION_CLEANUP_TIMEOUT_SECONDS,
        },
    )


@dataclass(frozen=True)
class _TerminalResult:
    """User-visible terminal result projected from durable events."""

    event_id: str | None
    message: str | None


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
        session_manager: SessionManager[AsyncSession],
        request: AgentRunExecutionRequest,
        *,
        check_stop: CheckStop | None = None,
        poll_input_events: InputPoller | None = None,
    ) -> AgentRunStatus:
        """Run until terminal state."""
        try:
            for _model_call_index in _turn_range(request.max_turns):
                if await _stopped(check_stop):
                    if request.tool_admission_barrier.closed:
                        return AgentRunStatus.RUNNING
                    async with session_manager() as session:
                        await self._lock_run_authority(session, request)
                        await self._mark_terminal(
                            session,
                            request.run_id,
                            AgentRunStatus.INTERRUPTED,
                        )
                    return AgentRunStatus.INTERRUPTED

                if poll_input_events is not None:
                    poll_result = await poll_input_events(request.session_id)
                    if poll_result.complete_run:
                        async with session_manager() as session:
                            await self._lock_run_authority(session, request)
                            await self._mark_terminal(
                                session,
                                request.run_id,
                                AgentRunStatus.COMPLETED,
                            )
                        return AgentRunStatus.COMPLETED
                    if poll_result.context_invalidated:
                        return AgentRunStatus.RUNNING

                async with session_manager() as session:
                    await self._lock_run_authority(session, request)
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
                        transcript = await self._transcript_repo.list_for_model_input(
                            session,
                            request.session_id,
                            head_event_id=head_event_id,
                        )
                    preparing_started_at = await self._update_phase_in_transaction(
                        session,
                        request.run_id,
                        AgentRunPhase.PREPARING_INPUT,
                    )
                if repaired_events and self._output_sink is not None:
                    await self._output_sink(
                        NormalizedAdapterOutput(events=[]),
                        repaired_events,
                    )
                await self._publish_phase(
                    AgentRunPhase.PREPARING_INPUT,
                    preparing_started_at,
                )
                compacted = False
                if self._pre_lower_filter is not None:
                    transcript = await self._pre_lower_filter.apply(
                        session_manager,
                        transcript,
                    )
                    compacted = self._pre_lower_filter.was_compacted
                if self._model_file_pin_repo is not None:
                    async with session_manager() as session:
                        await self._lock_run_authority(session, request)
                        await self._model_file_pin_repo.pin_many(
                            session,
                            session_id=request.session_id,
                            run_id=request.run_id,
                            model_file_ids=unique_model_file_ids(transcript),
                        )
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

                    await self._set_phase(
                        session_manager,
                        request,
                        AgentRunPhase.WAITING_FOR_MODEL,
                    )
                    try:
                        output_stream = await self._stream_model(
                            session_manager,
                            request,
                            native_request,
                        )
                    except _ModelStreamUserInterrupted as exc:
                        await finish_turn("cancelled")
                        return await self._complete_user_interrupted_model_stream(
                            session_manager,
                            request,
                            exc.normalized,
                        )

                    await self._set_phase(
                        session_manager,
                        request,
                        AgentRunPhase.NORMALIZING_OUTPUT,
                    )
                    normalized = output_stream.complete()
                    _log_model_token_usage(
                        request=request,
                        usage=normalized.usage,
                    )

                    await self._set_phase(
                        session_manager,
                        request,
                        AgentRunPhase.APPENDING_EVENTS,
                    )
                    if not _has_durable_model_output(normalized.events):
                        raise ModelCallError(
                            "Model completed without assistant output."
                        )
                    normalized_tool_calls = [
                        event.payload
                        for event in normalized.events
                        if isinstance(event.payload, ClientToolCallPayload)
                    ]
                    appended: list[Event] = []
                    turn_marker: Event | None = None
                    run_marker: Event | None = None
                    executing_tools_started_at: datetime.datetime | None = None

                    async def append_model_output(
                        normalized_output: NormalizedAdapterOutput = normalized,
                        prepared_call: PreparedModelCall = prepared,
                        tool_calls: list[ClientToolCallPayload] = normalized_tool_calls,
                    ) -> None:
                        """Append output and admit its complete foreground call set."""
                        nonlocal appended, turn_marker, run_marker
                        nonlocal executing_tools_started_at
                        async with session_manager() as session:
                            await self._lock_run_authority(session, request)
                            appended = await self._append_events(
                                session,
                                normalized_output.events,
                                tool_call_run_id=request.run_id,
                            )
                            turn_marker = await self._append_turn_marker(
                                session,
                                request.session_id,
                                request.run_id,
                                normalized_output.usage,
                                inference_state=prepared_call.inference_state,
                                system_prompt=prepared_call.system_prompt_analysis,
                            )
                            if tool_calls:
                                executing_tools_started_at = (
                                    await self._update_phase_in_transaction(
                                        session,
                                        request.run_id,
                                        AgentRunPhase.EXECUTING_TOOLS,
                                        active_tool_calls=[
                                            _active_tool_call(
                                                call,
                                                owner_generation=(
                                                    request.owner_generation
                                                ),
                                            )
                                            for call in tool_calls
                                        ],
                                    )
                                )
                            else:
                                run_marker = await self._append_run_marker(
                                    session,
                                    request.session_id,
                                    request.run_id,
                                    "completed",
                                )
                                terminal_result = _terminal_result_from_events(appended)
                                await self._mark_terminal(
                                    session,
                                    request.run_id,
                                    AgentRunStatus.COMPLETED,
                                    terminal_result_event_id=terminal_result.event_id,
                                    terminal_result_message=terminal_result.message,
                                )

                    if normalized_tool_calls:
                        admitted = await request.tool_admission_barrier.run_if_open(
                            append_model_output
                        )
                        if not admitted:
                            await finish_turn("cancelled")
                            return AgentRunStatus.RUNNING
                    else:
                        await append_model_output()

                    turn_events = [turn_marker] if turn_marker is not None else []
                    client_tool_calls = [
                        event.payload
                        for event in appended
                        if isinstance(event.payload, ClientToolCallPayload)
                    ]
                    if normalized_tool_calls:
                        await self._publish_phase(
                            AgentRunPhase.EXECUTING_TOOLS,
                            executing_tools_started_at,
                        )
                    if self._output_sink is not None:
                        durable_events = [*appended, *turn_events]
                        if run_marker is not None:
                            durable_events.append(run_marker)
                        await self._output_sink(normalized, durable_events)
                    if not client_tool_calls:
                        await finish_turn("completed")
                        return AgentRunStatus.COMPLETED

                    try:
                        await self._execute_tools(
                            session_manager,
                            request,
                            client_tool_calls,
                            tool_executor=prepared.tool_executor,
                        )
                    except _ToolExecutionUserInterrupted:
                        async with session_manager() as session:
                            await self._lock_run_authority(session, request)
                            interrupted_marker = await self._append_run_marker(
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
                        if self._output_sink is not None:
                            await self._output_sink(
                                NormalizedAdapterOutput(events=[]),
                                [interrupted_marker],
                            )
                        await finish_turn("cancelled")
                        return AgentRunStatus.INTERRUPTED
                    await finish_turn("completed")
                except asyncio.CancelledError:
                    raise
                except AgentRunOwnershipLostError:
                    await finish_turn("cancelled")
                    raise
                except Exception:
                    await finish_turn("error")
                    raise
        except AgentRunOwnershipLostError as exc:
            logger.info(
                "AgentRun durable writer lost Session ownership",
                extra={
                    "run_id": exc.run_id,
                    "session_id": exc.session_id,
                    "expected_owner_generation": exc.expected_owner_generation,
                    "current_owner_generation": exc.current_owner_generation,
                    "active_run_id": exc.active_run_id,
                },
            )
            raise asyncio.CancelledError(OWNERSHIP_LOST_CANCEL_MESSAGE) from exc
        except AgentRunNotActiveError as exc:
            logger.info(
                "AgentRun terminal winner rejected a stale execution write",
                extra={"run_id": exc.run_id, "status": exc.status.value},
            )
            return exc.status
        except UserVisibleRuntimeError:
            raise

        async with session_manager() as session:
            await self._lock_run_authority(session, request)
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
        if self._output_sink is not None:
            await self._output_sink(
                NormalizedAdapterOutput(events=[]),
                [run_marker],
            )
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
        session_manager: SessionManager[AsyncSession],
        request: AgentRunExecutionRequest,
        native_request: NativeModelRequest,
    ) -> AdapterOutputStream:
        """Normalize and project model stream events as they arrive."""
        await self._set_phase(
            session_manager,
            request,
            AgentRunPhase.STREAMING_MODEL,
        )
        output_stream = self._output_normalizer.start(request.session_id)
        try:
            async for event in self._model_adapter.stream(native_request):
                incremental = output_stream.process_event(event)
                if self._output_sink is not None and incremental.projections:
                    await self._output_sink(incremental, [])
        except asyncio.CancelledError as exc:
            if _is_user_stop_cancellation(exc):
                raise _ModelStreamUserInterrupted(output_stream.interrupt()) from exc
            raise
        return output_stream

    async def _complete_user_interrupted_model_stream(
        self,
        session_manager: SessionManager[AsyncSession],
        request: AgentRunExecutionRequest,
        normalized: NormalizedAdapterOutput,
    ) -> AgentRunStatus:
        """Durabilize partial text from model stream interrupted by user stop."""
        await self._set_phase(
            session_manager,
            request,
            AgentRunPhase.APPENDING_EVENTS,
        )
        assistant_events = [
            event
            for event in normalized.events
            if event.kind == EventKind.ASSISTANT_MESSAGE
            and isinstance(event.payload, AssistantMessagePayload)
            and _assistant_content_is_non_empty(event.payload.content)
        ]
        async with session_manager() as session:
            await self._lock_run_authority(session, request)
            appended = await self._append_events(session, assistant_events)
            run_marker = await self._append_run_marker(
                session,
                request.session_id,
                request.run_id,
                "interrupted",
            )
            terminal_result = _terminal_result_from_events(appended)
            await self._mark_terminal(
                session,
                request.run_id,
                AgentRunStatus.INTERRUPTED,
                terminal_result_event_id=terminal_result.event_id,
                terminal_result_message=terminal_result.message,
            )
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
        *,
        tool_call_run_id: str | None = None,
    ) -> list[Event]:
        """Append events to durable transcript."""
        appended: list[Event] = []
        for event in events:
            external_id = event.external_id
            if tool_call_run_id is not None and isinstance(
                event.payload, ClientToolCallPayload
            ):
                external_id = tool_call_external_id(
                    tool_call_run_id,
                    event.payload.call_id,
                )
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
                        external_id=external_id,
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
        session_manager: SessionManager[AsyncSession],
        request: AgentRunExecutionRequest,
        tool_calls: Sequence[ClientToolCallPayload],
        *,
        tool_executor: ClientToolExecutor,
    ) -> None:
        """Run foreground calls in parallel and durably complete each one."""
        completed_call_ids: set[str] = set()
        tasks = [
            asyncio.create_task(
                self._execute_tool_with_call(call, tool_executor=tool_executor),
                name=f"tool-execution:{call.call_id}",
            )
            for call in tool_calls
        ]

        try:
            for completed in asyncio.as_completed(tasks):
                outcome = await completed
                await self._finalize_tool_result(
                    session_manager,
                    request=request,
                    call=outcome.call,
                    result=outcome.result,
                )
                completed_call_ids.add(outcome.call.call_id)
        except asyncio.CancelledError as exc:
            unresolved = [
                call for call in tool_calls if call.call_id not in completed_call_ids
            ]
            for call in unresolved:
                tool_executor.request_cancel(call)
            await _cancel_and_drain_tool_tasks(
                tasks, cancellation_reason=exc.args[0] if exc.args else None
            )
            if _is_ownership_loss_cancellation(exc):
                raise
            await self._append_cancelled_tool_results(
                session_manager,
                request,
                unresolved,
            )
            if _is_user_stop_cancellation(exc):
                stopping_started_at: datetime.datetime | None = None
                async with session_manager() as session:
                    await self._lock_run_authority(session, request)
                    stopping_started_at = await self._update_phase_in_transaction(
                        session,
                        request.run_id,
                        AgentRunPhase.STOPPING,
                        active_tool_calls=[],
                    )
                await self._publish_phase(
                    AgentRunPhase.STOPPING,
                    stopping_started_at,
                )
                raise _ToolExecutionUserInterrupted from exc
            raise
        except Exception:
            await _cancel_and_drain_tool_tasks(tasks, cancellation_reason=None)
            raise

    async def _execute_tool_with_call(
        self,
        call: ClientToolCallPayload,
        *,
        tool_executor: ClientToolExecutor,
    ) -> _ToolExecutionOutcome:
        """Execute one call while preserving its identity with the result."""
        result = await self._execute_tool_safely(call, tool_executor=tool_executor)
        return _ToolExecutionOutcome(call=call, result=result)

    async def _finalize_tool_result(
        self,
        session_manager: SessionManager[AsyncSession],
        *,
        request: AgentRunExecutionRequest,
        call: ClientToolCallPayload,
        result: ClientToolResultPayload,
    ) -> Event:
        """Commit one tool result, then publish it outside the transaction."""
        async with session_manager() as session:
            event = await self._finalize_tool_result_in_transaction(
                session,
                request=request,
                call=call,
                result=result,
            )
        if self._output_sink is not None:
            await self._output_sink(NormalizedAdapterOutput(events=[]), [event])
        return event

    async def _finalize_tool_result_in_transaction(
        self,
        session: AsyncSession,
        *,
        request: AgentRunExecutionRequest,
        call: ClientToolCallPayload,
        result: ClientToolResultPayload,
    ) -> Event:
        """Append one tool result inside the caller's transaction."""
        return await finalize_tool_result(
            session,
            run_repo=self._run_repo,
            transcript_repo=self._transcript_repo,
            run_id=request.run_id,
            session_id=request.session_id,
            owner_generation=request.owner_generation,
            call=call,
            result=result,
        )

    async def _append_missing_tool_results(
        self,
        session: AsyncSession,
        request: AgentRunExecutionRequest,
        transcript: Sequence[Event],
    ) -> list[Event]:
        """Reconcile durable tool calls before any resumed model dispatch."""
        run_state = await self._run_repo.get_by_id(session, request.run_id)
        if run_state is None:
            raise ValueError("Agent run not found")

        calls_by_id = {
            payload.call_id: payload
            for event in transcript
            if isinstance((payload := event.payload), ClientToolCallPayload)
        }
        result_call_ids = {
            payload.call_id
            for event in transcript
            if isinstance((payload := event.payload), ClientToolResultPayload)
        }
        for active in run_state.active_tool_calls:
            if active.call_id not in calls_by_id:
                raise RuntimeError("Active tool call has no durable call event")
            if active.owner_generation > request.owner_generation:
                raise RuntimeError("Active tool call owner generation is in the future")

        unresolved_calls = [
            call
            for call_id, call in calls_by_id.items()
            if call_id not in result_call_ids
        ]
        appended = await self._append_cancelled_tool_results_in_transaction(
            session,
            request,
            unresolved_calls,
        )

        stale_resolved_ids = {
            active.call_id
            for active in run_state.active_tool_calls
            if active.call_id in result_call_ids
        }
        if stale_resolved_ids:
            refreshed = await self._run_repo.get_by_id(session, request.run_id)
            if refreshed is None:
                raise ValueError("Agent run not found")
            remaining = [
                active
                for active in refreshed.active_tool_calls
                if active.call_id not in stale_resolved_ids
            ]
            await self._update_phase_in_transaction(
                session,
                request.run_id,
                AgentRunPhase.EXECUTING_TOOLS
                if remaining
                else AgentRunPhase.APPENDING_EVENTS,
                active_tool_calls=remaining,
            )
        return appended

    async def _append_cancelled_tool_results(
        self,
        session_manager: SessionManager[AsyncSession],
        request: AgentRunExecutionRequest,
        tool_calls: Sequence[ClientToolCallPayload],
    ) -> list[Event]:
        """Commit cancelled results without retaining a session across calls."""
        appended: list[Event] = []
        for call in tool_calls:
            payload = _cancelled_tool_result(call)
            appended.append(
                await self._finalize_tool_result(
                    session_manager,
                    request=request,
                    call=call,
                    result=payload,
                )
            )
        return appended

    async def _append_cancelled_tool_results_in_transaction(
        self,
        session: AsyncSession,
        request: AgentRunExecutionRequest,
        tool_calls: Sequence[ClientToolCallPayload],
    ) -> list[Event]:
        """Append cancelled results inside one caller-owned transaction."""
        appended: list[Event] = []
        for call in tool_calls:
            appended.append(
                await self._finalize_tool_result_in_transaction(
                    session,
                    request=request,
                    call=call,
                    result=_cancelled_tool_result(call),
                )
            )
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
        inference_state: SessionInferenceState | None,
        system_prompt: SystemPromptAnalysisPayload | None = None,
    ) -> Event | None:
        """Append turn marker."""
        if usage is None:
            return None
        applied_profile = (
            inference_state.applied_profile if inference_state is not None else None
        )
        payload = TurnMarkerPayload(
            run_id=run_id,
            usage=usage,
            applied_inference_profile=applied_profile,
            effective_context_window_tokens=(
                inference_state.effective_context_window_tokens
                if inference_state is not None
                else None
            ),
            effective_auto_compaction_threshold_tokens=(
                inference_state.effective_auto_compaction_threshold_tokens
                if inference_state is not None
                else None
            ),
            system_prompt=system_prompt,
        ).model_dump(mode="json", exclude_none=True)
        if applied_profile is not None:
            payload["applied_inference_profile"] = applied_profile.model_dump(
                mode="json"
            )
        return await self._transcript_repo.append(
            session,
            EventCreate(
                session_id=session_id,
                kind=EventKind.TURN_MARKER,
                payload=payload,
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

    async def _set_phase(
        self,
        session_manager: SessionManager[AsyncSession],
        request: AgentRunExecutionRequest,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> None:
        """Commit a run phase, then publish it after the session closes."""
        async with session_manager() as session:
            await self._lock_run_authority(session, request)
            model_call_started_at = await self._update_phase_in_transaction(
                session,
                request.run_id,
                phase,
                active_tool_calls=active_tool_calls,
            )
        await self._publish_phase(phase, model_call_started_at)

    async def _update_phase_in_transaction(
        self,
        session: AsyncSession,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> datetime.datetime | None:
        """Update a run phase inside the caller-owned transaction."""
        run = await self._run_repo.update_phase(
            session,
            run_id,
            phase,
            active_tool_calls=active_tool_calls,
        )
        return run.model_call_started_at

    async def _lock_run_authority(
        self,
        session: AsyncSession,
        request: AgentRunExecutionRequest,
    ) -> AgentRunState:
        """Fence a durable execution transaction to its exact Session owner."""
        return await self._run_repo.lock_active_owner(
            session,
            run_id=request.run_id,
            session_id=request.session_id,
            owner_generation=request.owner_generation,
        )

    async def _publish_phase(
        self,
        phase: AgentRunPhase,
        model_call_started_at: datetime.datetime | None,
    ) -> None:
        """Publish a committed phase to the live projection."""
        if self._phase_sink is not None:
            await self._phase_sink(phase, model_call_started_at)


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
) -> _TerminalResult:
    """Project the latest assistant text from terminal run events."""
    for event in reversed(events):
        payload = event.payload
        if isinstance(payload, AssistantMessagePayload):
            text = _assistant_content_text(payload.content)
            if text is not None:
                return _TerminalResult(event_id=event.id, message=text)
    return _TerminalResult(event_id=None, message=None)


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


def _is_ownership_loss_cancellation(exc: asyncio.CancelledError) -> bool:
    """Check whether cancellation fences a stale Session owner."""
    return any(arg == OWNERSHIP_LOST_CANCEL_MESSAGE for arg in exc.args)


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
    owner_generation: int,
) -> ActiveToolCall:
    """Create active tool call projection."""
    return ActiveToolCall(
        call_id=call.call_id,
        name=call.name,
        arguments=call.arguments,
        started_at=datetime.datetime.now(datetime.UTC),
        owner_generation=owner_generation,
    )


def _cancelled_tool_result(
    call: ClientToolCallPayload,
) -> ClientToolResultPayload:
    """Build the durable terminal result for a cancelled tool call."""
    return ClientToolResultPayload(
        call_id=call.call_id,
        name=call.name,
        status="cancelled",
        output=[
            OutputTextPart(
                text="Tool execution was cancelled before a result was recorded.",
            )
        ],
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
