"""Azents-owned event ReAct loop."""

import asyncio
import datetime
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.core.inference_profile import SessionInferenceState
from azents.engine.events.iteration import (
    AdmittedIteration,
    IterationEndReason,
    IterationFinished,
    IterationValue,
    ModelToolIterationCore,
)
from azents.engine.events.iteration_stream import (
    InterruptedIterationStream,
    consume_iteration_stream,
)
from azents.engine.events.iteration_tools import ParallelIterationTools
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
)
from azents.engine.events.tool_results import cancelled_tool_result
from azents.engine.events.types import (
    ActiveToolCall,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    OutputTextPart,
    RunMarkerPayload,
    SystemPromptAnalysisPayload,
    TokenUsagePayload,
)
from azents.engine.model_stream import ModelStreamCallContext, ModelStreamWatchdog
from azents.engine.run.contracts import ToolAdmissionBarrier
from azents.engine.run.errors import (
    ModelCallError,
    ModelInputTooLargeError,
    NativeRequestSizeExceededError,
)
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
)
from azents.engine.run.turn_action_bridge import TurnActionBridgeBoundary
from azents.engine.run.types import USER_STOP_CANCEL_MESSAGE
from azents.repos.engine_execution_operation import (
    EngineExecutionOperationRepository,
)
from azents.repos.engine_model_input_operation import (
    EngineModelInputOperationRepository,
)
from azents.repos.engine_output_operation import (
    EngineOutputOperationRepository,
    ModelOutputAdmission,
)
from azents.repos.engine_run_finalization_operation import (
    EngineRunFinalizationOperationRepository,
)
from azents.repos.engine_tool_result_operation import (
    EngineToolResultOperationRepository,
)
from azents.repos.model_operation_completion import ModelOperationCompletion
from azents.repos.provider_output_operation import (
    ProviderOutputMetadataAdmission,
    ProviderOutputOperationError,
)
from azents.repos.session_execution import (
    CanonicalExecutionOwnerGenerationStaleError,
)

logger = logging.getLogger(__name__)


CheckStop = Callable[[], Awaitable[bool]]
PhaseSink = Callable[[AgentRunPhase, datetime.datetime | None], Awaitable[None]]


@dataclass(frozen=True)
class InputPollResult:
    """Input events polled at a model-call turn boundary."""

    events: list[Event]
    context_invalidated: bool
    complete_run: bool
    suppress_parent_result: bool


InputPoller = Callable[[str], Awaitable[InputPollResult]]
TurnEndReason = Literal["completed", "error", "cancelled", "unknown"]
TurnEndCallback = Callable[[TurnEndReason], Awaitable[None]]
ClientToolCallEnricher = Callable[[ClientToolCallPayload], ClientToolCallPayload]


class PreparedProviderOutputProtocol(Protocol):
    """Provider output prepared for transactional metadata admission."""

    normalized: NormalizedAdapterOutput
    admitted: bool

    @property
    def metadata_admission(self) -> ProviderOutputMetadataAdmission:
        """Return detached metadata for model-output repository admission."""
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


class PreparedClientToolOutputProtocol(Protocol):
    """Client tool result prepared for transactional file admission."""

    result: ClientToolResultPayload
    admitted: bool

    @property
    def metadata_admission(self) -> ProviderOutputMetadataAdmission:
        """Return detached metadata for tool-result repository admission."""
        ...

    async def cleanup(self) -> None:
        """Compensate uploaded objects after failed result admission."""
        ...


class ClientToolOutputMaterializerProtocol(Protocol):
    """Prepare transient client tool output for transactional admission."""

    async def prepare_client_result(
        self,
        result: ClientToolResultPayload,
    ) -> PreparedClientToolOutputProtocol:
        """Prepare client-generated files and return transaction-ready output."""
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


def _preserve_client_tool_call(
    call: ClientToolCallPayload,
) -> ClientToolCallPayload:
    """Keep call data unchanged for preparers without a catalog source."""
    return call


@dataclass(frozen=True)
class PreparedModelCall[TNativeRequest]:
    """Turn-local model call dependencies."""

    native_request: TNativeRequest
    inference_state: SessionInferenceState | None
    system_prompt_analysis: SystemPromptAnalysisPayload | None
    tool_executor: ClientToolExecutor
    on_turn_end: TurnEndCallback | None
    enrich_client_tool_call: ClientToolCallEnricher = _preserve_client_tool_call


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

    async def force_compact(
        self,
        transcript: Sequence[Event],
        *,
        reason: str,
        on_started: Callable[[], Awaitable[None]] | None,
    ) -> list[Event]:
        """Compact independently of the automatic token threshold."""
        ...


@dataclass(frozen=True)
class AgentRunExecutionRequest:
    """Agent run execution request."""

    run_id: str
    session_id: str
    model: str
    owner_generation: int
    tool_admission_barrier: ToolAdmissionBarrier
    turn_action_bridge_boundary: TurnActionBridgeBoundary
    run_index: int = 1
    max_turns: int | None = None


class _ModelStreamUserInterrupted(Exception):
    """Indicates model stream was interrupted by user stop."""

    def __init__(self, normalized: NormalizedAdapterOutput) -> None:
        super().__init__(USER_STOP_CANCEL_MESSAGE)
        self.normalized = normalized


class _ToolExecutionUserInterrupted(Exception):
    """Indicates tool execution was interrupted by user stop."""


class AgentRunExecution[
    TNativeRequest: NativeRequestInspection,
    TNativeStreamEvent,
]:
    """ReAct loop based on event transcript."""

    def __init__(
        self,
        *,
        execution_operation_repository: EngineExecutionOperationRepository,
        model_input_operation_repository: EngineModelInputOperationRepository,
        tool_result_operation_repository: EngineToolResultOperationRepository,
        output_operation_repository: EngineOutputOperationRepository,
        run_finalization_operation_repository: EngineRunFinalizationOperationRepository,
        model_operation_completion: ModelOperationCompletion | None,
        post_lower_filter: PostLowerFilter[TNativeRequest],
        model_adapter: ModelAdapter[TNativeRequest, TNativeStreamEvent],
        model_stream_watchdog: ModelStreamWatchdog,
        model_stream_provider: str,
        model_stream_provider_integration_id: str | None,
        model_stream_inference_profile: str | None,
        output_normalizer: AdapterOutputNormalizer[TNativeStreamEvent],
        model_call_preparer: ModelCallPreparer[TNativeRequest],
        auto_compaction_filter: AutoCompactionFilter | None = None,
        output_sink: OutputSink | None = None,
        phase_sink: PhaseSink | None = None,
        provider_output_materializer: ProviderOutputMaterializerProtocol | None = None,
        client_tool_output_materializer: ClientToolOutputMaterializerProtocol
        | None = None,
        pre_model_lower_hook: PreModelLowerHook | None = None,
    ) -> None:
        """Inject loop dependencies."""
        self.operation_repository = execution_operation_repository
        self.model_input_operation_repository = model_input_operation_repository
        self.tool_result_operation_repository = tool_result_operation_repository
        self.output_repository = output_operation_repository
        self.terminal = run_finalization_operation_repository
        self.model_operation_completion = model_operation_completion
        self.post_lower_filter = post_lower_filter
        self.model_adapter = model_adapter
        self.model_stream_watchdog = model_stream_watchdog
        self.model_stream_provider = model_stream_provider
        self.model_stream_provider_integration_id = model_stream_provider_integration_id
        self.model_stream_inference_profile = model_stream_inference_profile
        self.output_normalizer = output_normalizer
        self.auto_compaction_filter = auto_compaction_filter
        self.model_call_preparer = model_call_preparer
        self.output_sink = output_sink
        self.phase_sink = phase_sink
        self.provider_output_materializer = provider_output_materializer
        self.client_tool_output_materializer = client_tool_output_materializer
        self.pre_model_lower_hook = pre_model_lower_hook

    async def run(
        self,
        request: AgentRunExecutionRequest,
        *,
        check_stop: CheckStop | None = None,
        poll_input_events: InputPoller | None = None,
    ) -> AgentRunStatus:
        """Run the common iteration algorithm with durable foreground operations."""
        host = ForegroundIterationHost(
            execution=self,
            request=request,
            check_stop=check_stop,
            poll_input_events=poll_input_events,
        )
        return await ModelToolIterationCore(host=host).run(max_turns=request.max_turns)

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
        output_stream = self.output_normalizer.for_native_replay(
            native_request.native_replay_schema_version()
        ).start(session_id)
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

        async def publish_incremental(incremental: NormalizedAdapterOutput) -> None:
            if self.output_sink is not None and incremental.projections:
                await self.output_sink(incremental, [])

        outcome = await consume_iteration_stream(
            events_factory=lambda: self.model_adapter.stream(
                native_request,
                watchdog=self.model_stream_watchdog,
                timeout_policy=timeout_policy,
                call_context=call_context,
            ),
            output_stream=output_stream,
            on_incremental=publish_incremental,
            is_user_stop=_is_user_stop_cancellation,
        )
        if isinstance(outcome, InterruptedIterationStream):
            raise _ModelStreamUserInterrupted(outcome.partial) from outcome.cancellation
        return output_stream

    async def _complete_user_interrupted_model_stream(
        self,
        request: AgentRunExecutionRequest,
        normalized: NormalizedAdapterOutput,
    ) -> AgentRunStatus:
        """Durabilize partial text from model stream interrupted by user stop."""
        await self._update_phase(
            request.run_id,
            AgentRunPhase.APPENDING_EVENTS,
        )
        assistant_events = [
            event
            for event in normalized.events
            if event.kind == EventKind.ASSISTANT_MESSAGE
            and isinstance(event.payload, AssistantMessagePayload)
            and _assistant_content_is_non_empty(event.payload.content)
        ]
        interrupted = await self.terminal.interrupt_model_stream(
            session_id=request.session_id,
            run_id=request.run_id,
            assistant_events=assistant_events,
        )
        if self.output_sink is not None:
            await self.output_sink(
                NormalizedAdapterOutput(
                    needs_follow_up=False,
                    events=assistant_events,
                ),
                [*interrupted.events, interrupted.run_marker],
            )
        return AgentRunStatus.INTERRUPTED

    async def _execute_tools(
        self,
        run_id: str,
        session_id: str,
        tool_calls: Sequence[ClientToolCallPayload],
        *,
        tool_executor: ClientToolExecutor,
    ) -> bool:
        """Bind durable admission to the shared parallel tool-batch algorithm."""
        return await ParallelIterationTools(
            host=ForegroundToolBatchHost(
                execution=self,
                run_id=run_id,
                session_id=session_id,
                tool_executor=tool_executor,
            )
        ).run(tool_calls)

    async def _finalize_tool_result(
        self,
        *,
        run_id: str,
        session_id: str,
        call: ClientToolCallPayload,
        result: ClientToolResultPayload,
    ) -> Event:
        """Append one terminal result and remove only its active ownership entry."""
        prepared: PreparedClientToolOutputProtocol | None = None
        if (
            result.pending_generated_files
            and self.client_tool_output_materializer is None
        ):
            logger.error(
                "Client generated-file materializer is unavailable",
                extra={"call_id": call.call_id, "tool_name": call.name},
            )
            result = ClientToolResultPayload(
                call_id=call.call_id,
                name=call.name,
                wire_dialect=call.wire_dialect,
                status="failed",
                output=[
                    OutputTextPart(
                        text="Generated image output storage is unavailable."
                    )
                ],
            )
        if result.pending_generated_files:
            materializer = self.client_tool_output_materializer
            if materializer is None:
                raise AssertionError("Generated-file materializer invariant violated")
            try:
                prepared = await materializer.prepare_client_result(result)
                try:
                    event = await self.output_repository.admit_client_tool_result(
                        run_id=run_id,
                        session_id=session_id,
                        call=call,
                        result=prepared.result,
                        metadata_admission=prepared.metadata_admission,
                    )
                except ProviderOutputOperationError as exc:
                    raise ModelCallError(str(exc)) from None
                prepared.admitted = True
            except asyncio.CancelledError:
                if prepared is not None:
                    await prepared.cleanup()
                raise
            except CanonicalExecutionOwnerGenerationStaleError:
                if prepared is not None:
                    await prepared.cleanup()
                raise
            except Exception as exc:
                if prepared is not None:
                    await prepared.cleanup()
                logger.exception(
                    "Client generated-file admission failed",
                    extra={
                        "call_id": call.call_id,
                        "tool_name": call.name,
                        "error_type": exc.__class__.__name__,
                    },
                )
                failed = ClientToolResultPayload(
                    call_id=call.call_id,
                    name=call.name,
                    wire_dialect=call.wire_dialect,
                    status="failed",
                    output=[
                        OutputTextPart(
                            text="Generated image output could not be stored."
                        )
                    ],
                )
                event = await self.tool_result_operation_repository.finalize(
                    run_id=run_id,
                    session_id=session_id,
                    call=call,
                    result=failed,
                )
        else:
            event = await self.tool_result_operation_repository.finalize(
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

    async def _complete_committed_terminal_run(
        self,
        request: AgentRunExecutionRequest,
    ) -> bool:
        """Complete a Run whose terminal client tool already committed its result."""
        run_marker = await self.terminal.complete_committed_scheduled_result(
            session_id=request.session_id,
            run_id=request.run_id,
            completion=self.model_operation_completion,
        )
        if run_marker is None:
            return False
        if self.output_sink is not None:
            await self.output_sink(
                NormalizedAdapterOutput(needs_follow_up=False, events=[]),
                [run_marker],
            )
        return True

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
            payload = cancelled_tool_result(call)
            appended.append(
                await self._finalize_tool_result(
                    run_id=run_id,
                    session_id=session_id,
                    call=call,
                    result=payload,
                )
            )
        return appended

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
        except CanonicalExecutionOwnerGenerationStaleError:
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
                wire_dialect=call.wire_dialect,
                status="failed",
                output=[
                    OutputTextPart(
                        text="Internal error",
                    )
                ],
            )

    async def _update_phase(
        self,
        run_id: str,
        phase: AgentRunPhase,
        *,
        active_tool_calls: list[ActiveToolCall] | None = None,
    ) -> None:
        """Reflect run phase in durable state and UI projection."""
        model_call_started_at = await self.operation_repository.update_phase(
            run_id=run_id,
            phase=phase,
            active_tool_calls=active_tool_calls,
        )
        await self._publish_phase(phase, model_call_started_at)

    async def _publish_phase(
        self,
        phase: AgentRunPhase,
        model_call_started_at: datetime.datetime | None,
    ) -> None:
        """Publish a committed phase after its DB session has closed."""
        if self.phase_sink is not None:
            await self.phase_sink(phase, model_call_started_at)


@dataclass
class ForegroundToolBatchHost[
    TNativeRequest: NativeRequestInspection,
    TNativeStreamEvent,
]:
    """Foreground result transactions around the neutral batch scheduler."""

    execution: AgentRunExecution[TNativeRequest, TNativeStreamEvent]
    run_id: str
    session_id: str
    tool_executor: ClientToolExecutor

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        return await self.execution._execute_tool_safely(
            call, tool_executor=self.tool_executor
        )

    async def finalize(
        self, call: ClientToolCallPayload, result: ClientToolResultPayload
    ) -> bool:
        await self.execution._finalize_tool_result(
            run_id=self.run_id,
            session_id=self.session_id,
            call=call,
            result=result,
        )
        return result.status == "completed" and result.terminal_run

    def request_cancel(self, call: ClientToolCallPayload) -> None:
        self.tool_executor.request_cancel(call)

    async def finalize_cancelled(self, calls: Sequence[ClientToolCallPayload]) -> None:
        await self.execution._append_cancelled_tool_results(
            self.session_id, calls, run_id=self.run_id
        )

    async def handle_cancellation(self, error: asyncio.CancelledError) -> None:
        if _is_user_stop_cancellation(error):
            stopping = (
                await self.execution.operation_repository.update_phase_if_running(
                    run_id=self.run_id,
                    phase=AgentRunPhase.STOPPING,
                    active_tool_calls=[],
                )
            )
            if stopping.updated:
                await self.execution._publish_phase(
                    AgentRunPhase.STOPPING, stopping.model_call_started_at
                )
            raise _ToolExecutionUserInterrupted from error


@dataclass
class ForegroundPreparedTurn[TNativeRequest]:
    """Prepared foreground dependencies and once-only turn-end bookkeeping."""

    call: PreparedModelCall[TNativeRequest]
    ended: bool


@dataclass(frozen=True)
class ForegroundModelOutput:
    """Normalized foreground output awaiting durable admission."""

    normalized: NormalizedAdapterOutput
    materialized: PreparedProviderOutputProtocol | None


@dataclass(frozen=True)
class ForegroundAdmittedTurn:
    """Durable foreground events retained for delivery and tool execution."""

    normalized: NormalizedAdapterOutput
    events: list[Event]
    turn_events: list[Event]
    tool_calls: list[ClientToolCallPayload]


@dataclass
class ForegroundIterationHost[
    TNativeRequest: NativeRequestInspection,
    TNativeStreamEvent,
]:
    """Bind public execution authority and atomic operations to the shared core."""

    execution: AgentRunExecution[TNativeRequest, TNativeStreamEvent]
    request: AgentRunExecutionRequest
    check_stop: CheckStop | None
    poll_input_events: InputPoller | None

    async def prepare_turn(
        self,
    ) -> (
        IterationValue[ForegroundPreparedTurn[TNativeRequest]]
        | IterationFinished[AgentRunStatus]
    ):
        """Prepare an ordinary model turn with token-threshold compaction."""
        return await self._prepare_turn(force_compaction_reason=None)

    async def _prepare_turn(
        self, *, force_compaction_reason: str | None
    ) -> (
        IterationValue[ForegroundPreparedTurn[TNativeRequest]]
        | IterationFinished[AgentRunStatus]
    ):
        """Recover durable input and honor foreground stop/mailbox boundaries."""
        execution = self.execution
        request = self.request
        if await _stopped(self.check_stop):
            if request.tool_admission_barrier.closed:
                return IterationFinished(AgentRunStatus.RUNNING, "cancelled")
            await execution.terminal.interrupt_before_turn(run_id=request.run_id)
            return IterationFinished(AgentRunStatus.INTERRUPTED, "cancelled")
        if self.poll_input_events is not None:
            polled = await self.poll_input_events(request.session_id)
            if polled.complete_run:
                await execution.terminal.complete_polled_run(
                    run_id=request.run_id,
                    suppress_parent_result=polled.suppress_parent_result,
                )
                return IterationFinished(AgentRunStatus.COMPLETED, "completed")
            if polled.context_invalidated:
                return IterationFinished(AgentRunStatus.RUNNING, "completed")
        prepared_input = await execution.model_input_operation_repository.prepare_input(
            run_id=request.run_id,
            session_id=request.session_id,
            owner_generation=request.owner_generation,
        )
        transcript = prepared_input.transcript
        if execution.output_sink is not None:
            for repaired in prepared_input.repaired_events:
                await execution.output_sink(
                    NormalizedAdapterOutput(needs_follow_up=False, events=[]),
                    [repaired],
                )
        if await execution._complete_committed_terminal_run(request):
            return IterationFinished(AgentRunStatus.COMPLETED, "completed")
        await execution._publish_phase(
            AgentRunPhase.PREPARING_INPUT, prepared_input.model_call_started_at
        )
        compacted = False
        if execution.auto_compaction_filter is not None:
            compaction_started = False

            async def on_compaction_started() -> None:
                nonlocal compaction_started
                compaction_started = True
                await execution._update_phase(request.run_id, AgentRunPhase.COMPACTING)

            if force_compaction_reason is None:
                transcript = await execution.auto_compaction_filter.compact(
                    transcript, on_started=on_compaction_started
                )
            else:
                transcript = await execution.auto_compaction_filter.force_compact(
                    transcript,
                    reason=force_compaction_reason,
                    on_started=on_compaction_started,
                )
                if not execution.auto_compaction_filter.was_compacted:
                    raise ModelInputTooLargeError(
                        "The model input is too large and could not be compacted."
                    )
            compacted = execution.auto_compaction_filter.was_compacted
            if compaction_started:
                await execution._update_phase(
                    request.run_id, AgentRunPhase.PREPARING_INPUT
                )
        await execution.operation_repository.pin_model_files(
            session_id=request.session_id,
            run_id=request.run_id,
            model_file_ids=unique_model_file_ids(transcript),
        )
        if execution.pre_model_lower_hook is not None:
            await execution.pre_model_lower_hook(transcript=transcript)
        model_input = (
            _without_existing_terminal_run_markers(transcript)
            if compacted
            else transcript
        )
        prepared = await execution._prepare_model_call(
            transcript=model_input, model=request.model
        )
        return IterationValue(ForegroundPreparedTurn(call=prepared, ended=False))

    async def invoke_model(
        self, prepared: ForegroundPreparedTurn[TNativeRequest]
    ) -> IterationValue[ForegroundModelOutput] | IterationFinished[AgentRunStatus]:
        """Stream through the unchanged provider/normalizer foreground adapters."""
        execution = self.execution
        request = self.request
        recovered = False
        while True:
            try:
                native_request = execution.post_lower_filter.apply(
                    prepared.call.native_request
                )
                await execution._update_phase(
                    request.run_id, AgentRunPhase.WAITING_FOR_MODEL
                )
                stream = await execution._stream_model(
                    request.run_id,
                    request.session_id,
                    native_request,
                    check_stop=self.check_stop,
                )
                await execution._update_phase(
                    request.run_id, AgentRunPhase.NORMALIZING_OUTPUT
                )
                normalized = stream.complete()
                break
            except _ModelStreamUserInterrupted as exc:
                await self.finish_turn(prepared, "cancelled")
                status = await execution._complete_user_interrupted_model_stream(
                    request, exc.normalized
                )
                return IterationFinished(status, "cancelled")
            except (NativeRequestSizeExceededError, ModelProviderFailure) as exc:
                if (
                    isinstance(exc, ModelProviderFailure)
                    and exc.category is not ModelProviderFailureCategory.CONTEXT_LIMIT
                ):
                    raise
                if recovered or execution.auto_compaction_filter is None:
                    raise ModelInputTooLargeError(
                        "The model input is too large after compaction. "
                        "Reduce the current input or attached image sizes."
                    ) from exc
                reason = (
                    "native_request_size_exceeded"
                    if isinstance(exc, NativeRequestSizeExceededError)
                    else "provider_context_limit"
                )
                diagnostics: dict[str, object] = {
                    "session_id": request.session_id,
                    "run_id": request.run_id,
                    "compaction_reason": reason,
                }
                if isinstance(exc, NativeRequestSizeExceededError):
                    diagnostics.update(
                        native_request_actual_chars=exc.actual_chars,
                        native_request_limit_chars=exc.limit_chars,
                    )
                logger.info(
                    "Compacting model input after input limit exceeded",
                    extra=diagnostics,
                )
                await self.finish_turn(prepared, "error")
                recovery = await self._prepare_turn(force_compaction_reason=reason)
                if isinstance(recovery, IterationFinished):
                    return recovery
                prepared.call = recovery.value.call
                prepared.ended = False
                recovered = True
        normalized = _enrich_client_tool_calls(
            normalized, prepared.call.enrich_client_tool_call
        )
        _log_model_token_usage(request=request, usage=normalized.usage)
        materialized = (
            await execution.provider_output_materializer.prepare(normalized)
            if execution.provider_output_materializer is not None
            else None
        )
        if materialized is not None:
            normalized = materialized.normalized
        return IterationValue(
            ForegroundModelOutput(normalized=normalized, materialized=materialized)
        )

    async def admit_output(
        self,
        prepared: ForegroundPreparedTurn[TNativeRequest],
        output: ForegroundModelOutput,
    ) -> AdmittedIteration[ForegroundAdmittedTurn] | IterationFinished[AgentRunStatus]:
        """Preserve atomic event/metadata/call admission before any handler starts."""
        execution = self.execution
        request = self.request
        normalized = output.normalized
        materialized = output.materialized
        normalized_calls = [
            event.payload
            for event in normalized.events
            if isinstance(event.payload, ClientToolCallPayload)
        ]
        appended: list[Event] = []
        turn_marker: Event | None = None

        async def append_output() -> None:
            nonlocal appended, turn_marker
            try:
                admitted = await execution.output_repository.admit_model_output(
                    ModelOutputAdmission(
                        session_id=request.session_id,
                        run_id=request.run_id,
                        owner_generation=request.owner_generation,
                        events=normalized.events,
                        usage=normalized.usage,
                        inference_state=prepared.call.inference_state,
                        system_prompt_analysis=prepared.call.system_prompt_analysis,
                        metadata_admission=(
                            materialized.metadata_admission
                            if materialized is not None
                            else None
                        ),
                    )
                )
            except ProviderOutputOperationError as exc:
                raise ModelCallError(str(exc)) from None
            appended = admitted.events
            turn_marker = admitted.turn_marker
            if normalized_calls:
                await execution._publish_phase(
                    AgentRunPhase.EXECUTING_TOOLS, admitted.model_call_started_at
                )

        output_admitted = False
        try:
            await execution._update_phase(
                request.run_id, AgentRunPhase.APPENDING_EVENTS
            )
            if normalized_calls:
                allowed = await request.tool_admission_barrier.run_if_open(
                    append_output
                )
                if not allowed:
                    await self.finish_turn(prepared, "cancelled")
                    return IterationFinished(AgentRunStatus.RUNNING, "cancelled")
            else:
                await append_output()
            output_admitted = True
            if materialized is not None:
                materialized.admitted = True
        finally:
            if materialized is not None and not output_admitted:
                await materialized.cleanup()
        calls = [
            event.payload
            for event in appended
            if isinstance(event.payload, ClientToolCallPayload)
        ]
        return AdmittedIteration(
            admission=ForegroundAdmittedTurn(
                normalized=normalized,
                events=appended,
                turn_events=[turn_marker] if turn_marker is not None else [],
                tool_calls=calls,
            ),
            has_tool_calls=bool(calls),
            needs_follow_up=normalized.needs_follow_up,
        )

    async def publish_output(self, admission: ForegroundAdmittedTurn) -> None:
        """Deliver committed output before tool execution."""
        if self.execution.output_sink is not None:
            await self.execution.output_sink(
                admission.normalized, [*admission.events, *admission.turn_events]
            )

    async def execute_tools(
        self,
        prepared: ForegroundPreparedTurn[TNativeRequest],
        admission: ForegroundAdmittedTurn,
    ) -> IterationFinished[AgentRunStatus] | None:
        """Retain foreground parallel results, terminal tools and bridge polling."""
        execution = self.execution
        request = self.request
        try:
            terminal_completed = await execution._execute_tools(
                request.run_id,
                request.session_id,
                admission.tool_calls,
                tool_executor=prepared.call.tool_executor,
            )
        except _ToolExecutionUserInterrupted:
            marker = await execution.terminal.interrupt_after_tool_stop_if_running(
                session_id=request.session_id, run_id=request.run_id
            )
            if marker is not None and execution.output_sink is not None:
                await execution.output_sink(
                    NormalizedAdapterOutput(needs_follow_up=False, events=[]),
                    [marker],
                )
            return IterationFinished(AgentRunStatus.INTERRUPTED, "cancelled")
        if terminal_completed and await execution._complete_committed_terminal_run(
            request
        ):
            return IterationFinished(AgentRunStatus.COMPLETED, "completed")
        bridge = request.turn_action_bridge_boundary.consume()
        if bridge is not None:
            if self.poll_input_events is None:
                raise RuntimeError("TurnAction bridge admission requires input polling")
            polled = await self.poll_input_events(request.session_id)
            if polled.complete_run:
                await execution.terminal.complete_bridged_run(run_id=request.run_id)
                return IterationFinished(AgentRunStatus.COMPLETED, "completed")
            if polled.context_invalidated:
                return IterationFinished(AgentRunStatus.RUNNING, "completed")
        return None

    async def complete_turn(
        self, admission: ForegroundAdmittedTurn, *, include_output: bool
    ) -> AgentRunStatus:
        """Commit the original terminal operation before its output delivery."""
        execution = self.execution
        marker = await execution.terminal.complete_model_run(
            session_id=self.request.session_id,
            run_id=self.request.run_id,
            output_events=admission.events,
            completion=execution.model_operation_completion,
        )
        if execution.output_sink is not None:
            await execution.output_sink(
                admission.normalized
                if include_output
                else NormalizedAdapterOutput(needs_follow_up=False, events=[]),
                [*admission.events, *admission.turn_events, marker]
                if include_output
                else [marker],
            )
        return AgentRunStatus.COMPLETED

    async def finish_turn(
        self,
        prepared: ForegroundPreparedTurn[TNativeRequest],
        reason: IterationEndReason,
    ) -> None:
        """Keep once-only callback semantics, including callback failure."""
        if prepared.ended:
            return
        prepared.ended = True
        await _finish_turn(prepared.call.on_turn_end, reason)

    async def fail_turn(
        self, prepared: ForegroundPreparedTurn[TNativeRequest], error: Exception
    ) -> None:
        """Preserve ownership-loss propagation without failure hook side effects."""
        if not isinstance(error, CanonicalExecutionOwnerGenerationStaleError):
            await self.finish_turn(prepared, "error")

    async def close(self) -> None:
        """Close the foreground adapter after any core exit."""
        if isinstance(self.execution.model_adapter, AsyncClosableAdapter):
            await self.execution.model_adapter.close()

    async def limit_reached(self) -> AgentRunStatus:
        """Persist turn-limit interruption rather than successful completion."""
        await self.execution.terminal.interrupt_turn_limit(
            session_id=self.request.session_id, run_id=self.request.run_id
        )
        return AgentRunStatus.INTERRUPTED


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
        },
    )


def _is_user_stop_cancellation(exc: asyncio.CancelledError) -> bool:
    """Check whether CancelledError is user stop cancellation."""
    return any(arg == USER_STOP_CANCEL_MESSAGE for arg in exc.args)


def _enrich_client_tool_calls(
    normalized: NormalizedAdapterOutput,
    enrich_call: Callable[[ClientToolCallPayload], ClientToolCallPayload],
) -> NormalizedAdapterOutput:
    """Attach catalog-owned source snapshots before call events become durable."""
    events = [
        event.model_copy(update={"payload": enrich_call(event.payload)})
        if isinstance(event.payload, ClientToolCallPayload)
        else event
        for event in normalized.events
    ]
    return normalized.model_copy(update={"events": events})


def _assistant_content_is_non_empty(content: object) -> bool:
    """Check whether assistant content contains text to durabilize."""
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, Sequence):
        return bool(content)
    return False


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
