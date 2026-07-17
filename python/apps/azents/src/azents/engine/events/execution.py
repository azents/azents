"""Azents-owned event ReAct loop."""

import asyncio
import datetime
import itertools
import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Literal, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.core.inference_profile import SessionInferenceState
from azents.engine.events.model_file_refs import unique_model_file_ids
from azents.engine.events.protocols import (
    AdapterOutputNormalizer,
    AdapterOutputStream,
    AsyncClosableAdapter,
    ClientToolExecutor,
    ModelAdapter,
    NativeRequestInspection,
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
from azents.engine.model_stream import ModelStreamCallContext, ModelStreamWatchdog
from azents.engine.run.contracts import ToolAdmissionBarrier
from azents.engine.run.errors import (
    ModelCallError,
    UserVisibleRuntimeError,
)
from azents.engine.run.types import USER_STOP_CANCEL_MESSAGE
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import (
    AgentRunRepository,
    EventTranscriptRepository,
)
from azents.repos.agent_execution.data import EventCreate

logger = logging.getLogger(__name__)


CheckStop = Callable[[], Awaitable[bool]]
PhaseSink = Callable[[AgentRunPhase, datetime.datetime | None], Awaitable[None]]


@dataclass(frozen=True)
class InputPollResult:
    """Input events polled at a model-call turn boundary."""

    events: list[Event]
    context_invalidated: bool
    complete_run: bool


@dataclass(frozen=True)
class TerminalResult:
    """User-safe terminal event projection for a run."""

    event_id: str | None
    message: str | None


InputPoller = Callable[[str], Awaitable[InputPollResult]]
TurnEndReason = Literal["completed", "error", "cancelled", "unknown"]
TurnEndCallback = Callable[[TurnEndReason], Awaitable[None]]


class PreparedProviderOutputProtocol(Protocol):
    """Provider output prepared for transactional metadata admission."""

    normalized: NormalizedAdapterOutput
    admitted: bool

    async def persist(self, session: AsyncSession) -> None:
        """Persist prepared metadata in the model-output transaction."""
        ...

    async def cleanup(self) -> None:
        """Compensate uploaded objects after failed output admission."""
        ...


class ProviderOutputMaterializerProtocol(Protocol):
    """Prepare transient provider output for transactional admission."""

    async def prepare(
        self,
        normalized: NormalizedAdapterOutput,
    ) -> PreparedProviderOutputProtocol:
        """Upload provider files and return transaction-ready output."""
        ...


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
class PreparedModelCall[TNativeRequest]:
    """Turn-local model call dependencies."""

    native_request: TNativeRequest
    inference_state: SessionInferenceState | None
    system_prompt_analysis: SystemPromptAnalysisPayload | None
    tool_executor: ClientToolExecutor
    on_turn_end: TurnEndCallback | None


class ModelCallPreparer[TNativeRequest](Protocol):
    """Prepare turn-local model request and tool executor."""

    async def __call__(
        self,
        *,
        transcript: Sequence[Event],
        model: str,
    ) -> PreparedModelCall[TNativeRequest]:
        """Prepare one model-call turn."""
        ...


class AutoCompactionFilter(Protocol):
    """Model-input compaction that owns its persistence sessions."""

    was_compacted: bool

    async def compact(
        self,
        transcript: Sequence[Event],
        *,
        on_started: Callable[[], Awaitable[None]] | None = None,
    ) -> list[Event]:
        """Compact model input outside a caller-owned DB session."""
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


class _ToolExecutionUserInterrupted(Exception):
    """Indicates tool execution was interrupted by user stop."""


@dataclass(frozen=True)
class _ToolExecutionOutcome:
    """One foreground tool execution outcome."""

    call: ClientToolCallPayload
    result: ClientToolResultPayload


class AgentRunExecution[
    TNativeRequest: NativeRequestInspection,
    TNativeStreamEvent,
]:
    """ReAct loop based on event transcript."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        post_lower_filter: PostLowerFilter[TNativeRequest],
        model_adapter: ModelAdapter[TNativeRequest, TNativeStreamEvent],
        model_stream_watchdog: ModelStreamWatchdog,
        model_stream_provider: str,
        model_stream_provider_integration_id: str | None,
        model_stream_inference_profile: str | None,
        output_normalizer: AdapterOutputNormalizer[TNativeStreamEvent],
        model_call_preparer: ModelCallPreparer[TNativeRequest],
        pre_lower_filter: PreLowerFilter | None = None,
        auto_compaction_filter: AutoCompactionFilter | None = None,
        output_sink: OutputSink | None = None,
        phase_sink: PhaseSink | None = None,
        provider_output_materializer: ProviderOutputMaterializerProtocol | None = None,
        pre_model_lower_hook: PreModelLowerHook | None = None,
        model_file_pin_repo: ModelFilePinRepositoryProtocol | None = None,
        run_repo: RunStateRepository | None = None,
        transcript_repo: TranscriptRepository | None = None,
        session_repo: SessionHeadRepository | None = None,
    ) -> None:
        """Inject loop dependencies."""
        self.session_manager = session_manager
        self.post_lower_filter = post_lower_filter
        self.model_adapter = model_adapter
        self.model_stream_watchdog = model_stream_watchdog
        self.model_stream_provider = model_stream_provider
        self.model_stream_provider_integration_id = model_stream_provider_integration_id
        self.model_stream_inference_profile = model_stream_inference_profile
        self.output_normalizer = output_normalizer
        self.pre_lower_filter = pre_lower_filter
        self.auto_compaction_filter = auto_compaction_filter
        self.model_call_preparer = model_call_preparer
        self.output_sink = output_sink
        self.phase_sink = phase_sink
        self.provider_output_materializer = provider_output_materializer
        self.pre_model_lower_hook = pre_model_lower_hook
        self.model_file_pin_repo = model_file_pin_repo
        self.run_repo = run_repo or AgentRunRepository()
        self.transcript_repo = transcript_repo or EventTranscriptRepository()
        self.session_repo = session_repo

    async def run(
        self,
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
                    async with self.session_manager() as session:
                        await self._mark_terminal(
                            session,
                            request.run_id,
                            AgentRunStatus.INTERRUPTED,
                        )
                    return AgentRunStatus.INTERRUPTED

                if poll_input_events is not None:
                    poll_result = await poll_input_events(request.session_id)
                    if poll_result.complete_run:
                        async with self.session_manager() as session:
                            await self._mark_terminal(
                                session,
                                request.run_id,
                                AgentRunStatus.COMPLETED,
                            )
                        return AgentRunStatus.COMPLETED
                    if poll_result.context_invalidated:
                        return AgentRunStatus.RUNNING

                async with self.session_manager() as session:
                    head_event_id = await self._model_input_head_event_id(
                        session,
                        request.session_id,
                    )
                    transcript = await self._list_model_input_transcript(
                        session,
                        request,
                        head_event_id=head_event_id,
                    )
                    repaired_events = await self._append_missing_tool_results(
                        session,
                        request,
                        transcript,
                    )
                    if repaired_events:
                        transcript = await self._list_model_input_transcript(
                            session,
                            request,
                            head_event_id=head_event_id,
                        )
                    model_call_started_at = await self._update_phase_in_session(
                        session,
                        request.run_id,
                        AgentRunPhase.PREPARING_INPUT,
                    )
                    if self.pre_lower_filter is not None:
                        transcript = await self.pre_lower_filter.apply(
                            session, transcript
                        )
                if self.output_sink is not None:
                    for repaired_event in repaired_events:
                        await self.output_sink(
                            NormalizedAdapterOutput(
                                needs_follow_up=False,
                                events=[],
                            ),
                            [repaired_event],
                        )
                await self._publish_phase(
                    AgentRunPhase.PREPARING_INPUT,
                    model_call_started_at,
                )

                compacted = (
                    self.pre_lower_filter.was_compacted
                    if self.pre_lower_filter is not None
                    else False
                )
                if self.auto_compaction_filter is not None:
                    compaction_started = False

                    async def on_compaction_started() -> None:
                        nonlocal compaction_started
                        compaction_started = True
                        await self._update_phase(
                            request.run_id,
                            AgentRunPhase.COMPACTING,
                        )

                    try:
                        transcript = await self.auto_compaction_filter.compact(
                            transcript,
                            on_started=on_compaction_started,
                        )
                        compacted = (
                            compacted or self.auto_compaction_filter.was_compacted
                        )
                    finally:
                        if compaction_started:
                            await self._update_phase(
                                request.run_id,
                                AgentRunPhase.PREPARING_INPUT,
                            )
                if self.model_file_pin_repo is not None:
                    async with self.session_manager() as session:
                        await self.model_file_pin_repo.pin_many(
                            session,
                            session_id=request.session_id,
                            run_id=request.run_id,
                            model_file_ids=unique_model_file_ids(transcript),
                        )
                if self.pre_model_lower_hook is not None:
                    await self.pre_model_lower_hook(transcript=transcript)
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
                    native_request = self.post_lower_filter.apply(
                        prepared.native_request
                    )

                    await self._update_phase(
                        request.run_id,
                        AgentRunPhase.WAITING_FOR_MODEL,
                    )
                    try:
                        output_stream = await self._stream_model(
                            request.run_id,
                            request.session_id,
                            native_request,
                            check_stop=check_stop,
                        )
                    except _ModelStreamUserInterrupted:
                        await finish_turn("cancelled")
                        raise asyncio.CancelledError(USER_STOP_CANCEL_MESSAGE) from None

                    await self._update_phase(
                        request.run_id,
                        AgentRunPhase.NORMALIZING_OUTPUT,
                    )
                    normalized = output_stream.complete()
                    _log_model_token_usage(
                        request=request,
                        usage=normalized.usage,
                    )
                    prepared_provider_output = (
                        await self.provider_output_materializer.prepare(normalized)
                        if self.provider_output_materializer is not None
                        else None
                    )
                    if prepared_provider_output is not None:
                        normalized = prepared_provider_output.normalized

                    try:
                        await self._update_phase(
                            request.run_id,
                            AgentRunPhase.APPENDING_EVENTS,
                        )
                        if not _has_durable_model_output(normalized.events):
                            raise ModelCallError(
                                "Model completed without assistant output."
                            )
                    except asyncio.CancelledError:
                        if prepared_provider_output is not None:
                            await prepared_provider_output.cleanup()
                        raise
                    except Exception:
                        if prepared_provider_output is not None:
                            await prepared_provider_output.cleanup()
                        raise
                    normalized_tool_calls = [
                        event.payload
                        for event in normalized.events
                        if isinstance(event.payload, ClientToolCallPayload)
                    ]
                    appended: list[Event] = []
                    turn_marker: Event | None = None
                    model_needs_follow_up = normalized.needs_follow_up

                    async def append_model_output(
                        normalized_output: NormalizedAdapterOutput,
                        prepared_call: PreparedModelCall[TNativeRequest],
                        tool_calls: list[ClientToolCallPayload],
                        prepared_output: PreparedProviderOutputProtocol | None,
                    ) -> None:
                        """Append output and admit its complete foreground call set."""
                        nonlocal appended, turn_marker
                        model_call_started_at: datetime.datetime | None = None
                        async with self.session_manager() as session:
                            if prepared_output is not None:
                                await prepared_output.persist(session)
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
                            # Successful output admission completes this model turn's
                            # retry cycle. Keep the clear in the output transaction so
                            # takeover cannot revive retry state after output commits.
                            await self.run_repo.update_retry_state(
                                session,
                                request.run_id,
                                None,
                            )
                            if tool_calls:
                                model_call_started_at = (
                                    await self._update_phase_in_session(
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
                        if tool_calls:
                            await self._publish_phase(
                                AgentRunPhase.EXECUTING_TOOLS,
                                model_call_started_at,
                            )

                    bound_append_model_output = partial(
                        append_model_output,
                        normalized,
                        prepared,
                        normalized_tool_calls,
                        prepared_provider_output,
                    )
                    output_admitted = False
                    try:
                        if normalized_tool_calls:
                            admitted = await request.tool_admission_barrier.run_if_open(
                                bound_append_model_output
                            )
                            if not admitted:
                                await finish_turn("cancelled")
                                return AgentRunStatus.RUNNING
                        else:
                            await bound_append_model_output()
                        output_admitted = True
                        if prepared_provider_output is not None:
                            prepared_provider_output.admitted = True
                    finally:
                        if prepared_provider_output is not None and not output_admitted:
                            await prepared_provider_output.cleanup()

                    turn_events = [turn_marker] if turn_marker is not None else []
                    client_tool_calls = [
                        event.payload
                        for event in appended
                        if isinstance(event.payload, ClientToolCallPayload)
                    ]
                    if not client_tool_calls and not model_needs_follow_up:
                        async with self.session_manager() as session:
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
                        if self.output_sink is not None:
                            await self.output_sink(
                                normalized,
                                [*appended, *turn_events, run_marker],
                            )
                        await finish_turn("completed")
                        return AgentRunStatus.COMPLETED

                    if self.output_sink is not None:
                        await self.output_sink(normalized, [*appended, *turn_events])
                    if not client_tool_calls:
                        await finish_turn("completed")
                        continue
                    try:
                        await self._execute_tools(
                            request.run_id,
                            request.session_id,
                            client_tool_calls,
                            tool_executor=prepared.tool_executor,
                        )
                    except _ToolExecutionUserInterrupted:
                        await finish_turn("cancelled")
                        raise asyncio.CancelledError(USER_STOP_CANCEL_MESSAGE) from None
                    await finish_turn("completed")
                except asyncio.CancelledError:
                    raise
                except Exception:
                    await finish_turn("error")
                    raise
        except UserVisibleRuntimeError:
            raise
        finally:
            if isinstance(self.model_adapter, AsyncClosableAdapter):
                await self.model_adapter.close()

        async with self.session_manager() as session:
            await self._append_run_marker(
                session,
                request.session_id,
                request.run_id,
                "interrupted",
            )
            await self._mark_terminal(
                session, request.run_id, AgentRunStatus.INTERRUPTED
            )
        return AgentRunStatus.INTERRUPTED

    async def _prepare_model_call(
        self,
        *,
        transcript: Sequence[Event],
        model: str,
    ) -> PreparedModelCall[TNativeRequest]:
        """Prepare turn-local model request and tool executor."""
        return await self.model_call_preparer(
            transcript=transcript,
            model=model,
        )

    async def _stream_model(
        self,
        run_id: str,
        session_id: str,
        native_request: TNativeRequest,
        *,
        check_stop: CheckStop | None,
    ) -> AdapterOutputStream[TNativeStreamEvent]:
        """Normalize and project watched model stream events as they arrive."""
        await self._update_phase(
            run_id,
            AgentRunPhase.STREAMING_MODEL,
        )
        output_stream = self.output_normalizer.start(session_id)
        timeout_policy = self.model_stream_watchdog.resolve_policy(
            provider=self.model_stream_provider,
            model=native_request.model,
            inference_profile=self.model_stream_inference_profile,
        )
        call_context = ModelStreamCallContext(
            call_kind="sampling",
            provider=self.model_stream_provider,
            provider_integration_id=self.model_stream_provider_integration_id,
            model=native_request.model,
            session_id=session_id,
            run_id=run_id,
            attempt_number=None,
            check_stop=check_stop,
        )
        try:
            async for event in self.model_adapter.stream(
                native_request,
                watchdog=self.model_stream_watchdog,
                timeout_policy=timeout_policy,
                call_context=call_context,
            ):
                incremental = output_stream.process_event(event)
                if self.output_sink is not None and incremental.projections:
                    await self.output_sink(incremental, [])
        except asyncio.CancelledError as exc:
            if _is_user_stop_cancellation(exc):
                raise _ModelStreamUserInterrupted from exc
            raise
        return output_stream

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
                await self.transcript_repo.append(
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
        run_id: str,
        session_id: str,
        tool_calls: Sequence[ClientToolCallPayload],
        *,
        tool_executor: ClientToolExecutor,
    ) -> None:
        """Run foreground calls in parallel and durably complete each one."""
        completed_call_ids: set[str] = set()
        tasks = [
            asyncio.create_task(
                self._execute_tool_with_call(call, tool_executor=tool_executor)
            )
            for call in tool_calls
        ]
        try:
            for completed in asyncio.as_completed(tasks):
                outcome = await completed
                await self._finalize_tool_result(
                    run_id=run_id,
                    session_id=session_id,
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
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._append_cancelled_tool_results(
                session_id,
                unresolved,
                run_id=run_id,
            )
            if _is_user_stop_cancellation(exc):
                stopping_updated = False
                stopping_started_at: datetime.datetime | None = None
                async with self.session_manager() as session:
                    run_state = await self.run_repo.get_by_id(session, run_id)
                    if (
                        run_state is not None
                        and run_state.status == AgentRunStatus.RUNNING
                    ):
                        stopping_started_at = await self._update_phase_in_session(
                            session,
                            run_id,
                            AgentRunPhase.STOPPING,
                            active_tool_calls=[],
                        )
                        stopping_updated = True
                if stopping_updated:
                    await self._publish_phase(
                        AgentRunPhase.STOPPING,
                        stopping_started_at,
                    )
                raise _ToolExecutionUserInterrupted from exc
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
        *,
        run_id: str,
        session_id: str,
        call: ClientToolCallPayload,
        result: ClientToolResultPayload,
    ) -> Event:
        """Append one terminal result and remove only its active ownership entry."""
        async with self.session_manager() as session:
            event = await self._finalize_tool_result_in_session(
                session,
                run_id=run_id,
                session_id=session_id,
                call=call,
                result=result,
            )
        if self.output_sink is not None:
            await self.output_sink(
                NormalizedAdapterOutput(needs_follow_up=False, events=[]),
                [event],
            )
        return event

    async def _finalize_tool_result_in_session(
        self,
        session: AsyncSession,
        *,
        run_id: str,
        session_id: str,
        call: ClientToolCallPayload,
        result: ClientToolResultPayload,
    ) -> Event:
        """Finalize one tool result in the caller's DB transaction."""
        return await finalize_tool_result(
            session,
            run_repo=self.run_repo,
            transcript_repo=self.transcript_repo,
            run_id=run_id,
            session_id=session_id,
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
        run_state = await self.run_repo.get_by_id(session, request.run_id)
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
        appended = await self._append_cancelled_tool_results_in_session(
            session,
            request.session_id,
            unresolved_calls,
            run_id=request.run_id,
        )

        stale_resolved_ids = {
            active.call_id
            for active in run_state.active_tool_calls
            if active.call_id in result_call_ids
        }
        if stale_resolved_ids:
            refreshed = await self.run_repo.get_by_id(session, request.run_id)
            if refreshed is None:
                raise ValueError("Agent run not found")
            remaining = [
                active
                for active in refreshed.active_tool_calls
                if active.call_id not in stale_resolved_ids
            ]
            await self._update_phase_in_session(
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
        session_id: str,
        tool_calls: Sequence[ClientToolCallPayload],
        *,
        run_id: str,
    ) -> list[Event]:
        """Idempotently cancel calls and remove their active ownership entries."""
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
            appended.append(
                await self._finalize_tool_result(
                    run_id=run_id,
                    session_id=session_id,
                    call=call,
                    result=payload,
                )
            )
        return appended

    async def _append_cancelled_tool_results_in_session(
        self,
        session: AsyncSession,
        session_id: str,
        tool_calls: Sequence[ClientToolCallPayload],
        *,
        run_id: str,
    ) -> list[Event]:
        """Cancel calls atomically inside the caller's DB transaction."""
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
            appended.append(
                await self._finalize_tool_result_in_session(
                    session,
                    run_id=run_id,
                    session_id=session_id,
                    call=call,
                    result=payload,
                )
            )
        return appended

    async def _list_model_input_transcript(
        self,
        session: AsyncSession,
        request: AgentRunExecutionRequest,
        *,
        head_event_id: str | None,
    ) -> list[Event]:
        """Build model input while preserving retry source history."""
        transcript = await self.transcript_repo.list_for_model_input(
            session,
            request.session_id,
            head_event_id=head_event_id,
        )
        run = await self.run_repo.get_by_id(session, request.run_id)
        if run is None or run.retry_source_run_id is None:
            return transcript
        source_input_event_ids = await self.run_repo.list_input_event_ids(
            session,
            run_id=run.retry_source_run_id,
        )
        return _without_retry_source_run_output(
            transcript,
            source_run_id=run.retry_source_run_id,
            source_input_event_ids=source_input_event_ids,
        )

    async def _model_input_head_event_id(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> str | None:
        """Fetch model input head of event session."""
        if self.session_repo is None:
            return None
        state = await self.session_repo.get_by_id(session, session_id)
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
        existing = await self.transcript_repo.get_by_external_id(
            session,
            session_id,
            external_id,
        )
        if existing is not None:
            return existing
        return await self.transcript_repo.append(
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
        return await self.transcript_repo.append(
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
        await self.run_repo.mark_terminal(
            session,
            run_id,
            status,
            ended_at=datetime.datetime.now(datetime.UTC),
            terminal_result_event_id=terminal_result_event_id,
            terminal_result_message=terminal_result_message,
        )
        if self.model_file_pin_repo is not None:
            await self.model_file_pin_repo.release_run(session, run_id=run_id)

    async def _update_phase(
        self,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> None:
        """Reflect run phase in durable state and UI projection."""
        async with self.session_manager() as session:
            model_call_started_at = await self._update_phase_in_session(
                session,
                run_id,
                phase,
                active_tool_calls=active_tool_calls,
            )
        await self._publish_phase(phase, model_call_started_at)

    async def _update_phase_in_session(
        self,
        session: AsyncSession,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> datetime.datetime | None:
        """Update the durable phase inside the caller's DB transaction."""
        run = await self.run_repo.update_phase(
            session,
            run_id,
            phase,
            active_tool_calls=active_tool_calls,
        )
        return run.model_call_started_at

    async def _publish_phase(
        self,
        phase: AgentRunPhase,
        model_call_started_at: datetime.datetime | None,
    ) -> None:
        """Publish a committed phase after its DB session has closed."""
        if self.phase_sink is not None:
            await self.phase_sink(phase, model_call_started_at)


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
) -> TerminalResult:
    """Project the latest assistant text from terminal run events."""
    for event in reversed(events):
        payload = event.payload
        if isinstance(payload, AssistantMessagePayload):
            text = _assistant_content_text(payload.content)
            if text is not None:
                return TerminalResult(event_id=event.id, message=text)
    return TerminalResult(event_id=None, message=None)


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


async def _stopped(check_stop: CheckStop | None) -> bool:
    """Check whether stop was requested."""
    if check_stop is None:
        return False
    return await check_stop()


def _without_retry_source_run_output(
    transcript: Sequence[Event],
    *,
    source_run_id: str,
    source_input_event_ids: Sequence[str],
) -> list[Event]:
    """Exclude one retry source Run's output from model input only."""
    source_input_ids = set(source_input_event_ids)
    source_input_indexes = [
        index for index, event in enumerate(transcript) if event.id in source_input_ids
    ]
    if not source_input_indexes:
        return list(transcript)
    last_source_input_index = max(source_input_indexes)
    source_marker_index = next(
        (
            index
            for index, event in enumerate(
                transcript[last_source_input_index + 1 :],
                start=last_source_input_index + 1,
            )
            if isinstance(event.payload, RunMarkerPayload)
            and event.payload.run_id == source_run_id
        ),
        None,
    )
    if source_marker_index is None:
        return list(transcript)
    return [
        *transcript[: last_source_input_index + 1],
        *transcript[source_marker_index + 1 :],
    ]


def _without_existing_terminal_run_markers(
    transcript: Sequence[Event],
) -> list[Event]:
    """Exclude past terminal run markers from resume input after compaction."""
    return [
        event for event in transcript if not isinstance(event.payload, RunMarkerPayload)
    ]
