"""Event AgentEngineProtocol adapter assembly."""

import asyncio
import contextlib
import dataclasses
import logging
import math
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Annotated, Protocol

from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    EventKind,
    LLMProvider,
)
from azents.core.tools import TurnContext
from azents.engine.context.compaction import (
    SUMMARY_SYSTEM_PROMPT,
    SUMMARY_USER_TEMPLATE,
    CompactionSummaryBudget,
    SummaryModelCall,
    enforce_summary_char_budget,
    summarize_text_with_model,
)
from azents.engine.events.engine_events import (
    CompactionComplete,
    CompactionStarted,
    ContentDelta,
    FunctionCallDelta,
    ReasoningDelta,
    RunComplete,
    RunPhaseChanged,
    RunStopped,
)
from azents.engine.events.execution import (
    AgentRunExecution,
    AgentRunExecutionRequest,
    InputPoller,
    InputPollResult,
    ModelStreamTaskRegistry,
    ModelStreamTimeouts,
    PreparedModelCall,
)
from azents.engine.events.file_parts import RequestLocalModelFileResolver
from azents.engine.events.filters import (
    EventAttachmentAvailabilityFilter,
    EventAutoCompactionFilter,
    EventCompactor,
    EventFilePartPlaceholderFilter,
    EventPreLowerFilterPipeline,
    NativeRequestSizeGuard,
    PostLowerFilterPipeline,
)
from azents.engine.events.litellm_responses import (
    LiteLLMResponsesLowerer,
    LiteLLMResponsesModelAdapter,
    LiteLLMResponsesOutputNormalizer,
)
from azents.engine.events.model_file_materializer import ModelFileMaterializer
from azents.engine.events.output_parts import iter_output_parts
from azents.engine.events.protocols import (
    AgentRunCreateRepository,
    ClientToolExecutor,
    ManualCompactor,
    NormalizedAdapterOutput,
    SessionHeadRepository,
    StreamProjection,
    SummaryEnricher,
    SummaryGenerator,
    TranscriptRepository,
)
from azents.engine.events.system_prompt import build_system_prompt
from azents.engine.events.tools import (
    ToolCatalogClientToolExecutor,
    build_tool_catalog,
)
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionMarkerPayload,
    CompactionSummaryPayload,
    Event,
    InputTextPart,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolResultPayload,
    ReasoningPayload,
    SystemErrorPayload,
    UserMessagePayload,
)
from azents.engine.hooks.dispatcher import (
    RuntimeHookDispatcher,
    RuntimeHookProviderRef,
)
from azents.engine.hooks.types import (
    AfterToolCallHookContext,
    BeforeToolCallHookContext,
    CompactionSummaryHookContext,
    SessionCompactHookContext,
    ToolCallDeny,
    ToolOutputReplace,
    TurnEndHookContext,
    TurnEndReason,
    TurnStartHookContext,
)
from azents.engine.io.user_input import RunUserMessage
from azents.engine.run.contracts import RunContext, RunRequest, ToolkitBinding
from azents.engine.run.emit import Emit, durable, ephemeral
from azents.engine.run.types import (
    USER_STOP_CANCEL_MESSAGE,
    CheckStop,
    PollMessages,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.model_file_pin import ModelFilePinRepository
from azents.services.artifact import ArtifactService
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService

logger = logging.getLogger(__name__)


class RunExecution(Protocol):
    """Agent run execution protocol."""

    async def run(
        self,
        session: AsyncSession,
        request: AgentRunExecutionRequest,
        *,
        check_stop: CheckStop | None = None,
        poll_input_events: InputPoller | None = None,
    ) -> AgentRunStatus:
        """Run the run."""
        ...


RunExecutionFactory = Callable[..., RunExecution]


def _agent_run_execution_factory() -> RunExecutionFactory:
    """AgentRunExecution factory dependency."""
    return AgentRunExecution


def _summary_model_call() -> SummaryModelCall:
    """Summary model call dependency."""
    return summarize_text_with_model


@dataclasses.dataclass(frozen=True)
class EventEngineAdapterConfig:
    """Event engine adapter configuration."""

    native_request_max_input_chars: int = 16_000_000
    model_stream_first_event_timeout_seconds: float = 90.0
    model_stream_idle_timeout_seconds: float = 360.0
    model_stream_cancellation_cleanup_timeout_seconds: float = 5.0


def build_model_stream_timeouts(
    config: Annotated[
        EventEngineAdapterConfig,
        Depends(EventEngineAdapterConfig),
    ],
) -> ModelStreamTimeouts:
    """Validate and assemble model stream deadlines at composition time."""
    values = {
        "first event": config.model_stream_first_event_timeout_seconds,
        "idle": config.model_stream_idle_timeout_seconds,
        "cancellation cleanup": (
            config.model_stream_cancellation_cleanup_timeout_seconds
        ),
    }
    for name, value in values.items():
        if not math.isfinite(value) or value <= 0:
            raise ValueError(
                f"Model stream {name} timeout must be finite and greater than zero"
            )
    return ModelStreamTimeouts(
        first_event_seconds=config.model_stream_first_event_timeout_seconds,
        idle_seconds=config.model_stream_idle_timeout_seconds,
        cancellation_cleanup_seconds=(
            config.model_stream_cancellation_cleanup_timeout_seconds
        ),
    )


_SUMMARY_INPUT_OVERHEAD_TOKENS = 8_000
_SUMMARY_INPUT_CHAR_PER_TOKEN = 0.75
_MIN_SUMMARY_INPUT_CHARS = 24_000
_MAX_SUMMARY_INPUT_CHARS = 800_000
_SUMMARY_INPUT_OMISSION_MARKER = (
    "[Compaction input truncated: older raw events were omitted to fit the "
    "summary model context window.]"
)


@dataclasses.dataclass
class AgentEngineAdapter:
    """AgentEngineProtocol implementation based on event runtime.

    This adapter is the assembly boundary before worker dependency switch. It
    provides the `AgentEngineProtocol` surface required by the existing worker,
    while internal execution is performed by combining `AgentRunExecution` with
    event adapter/tool catalog.
    """

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    artifact_service: Annotated[ArtifactService, Depends(ArtifactService)]
    exchange_file_service: Annotated[ExchangeFileService, Depends(ExchangeFileService)]
    model_file_service: Annotated[ModelFileService, Depends(ModelFileService)]
    config: Annotated[EventEngineAdapterConfig, Depends(EventEngineAdapterConfig)]
    model_stream_timeouts: Annotated[
        ModelStreamTimeouts,
        Depends(build_model_stream_timeouts),
    ]
    model_stream_task_registry: Annotated[
        ModelStreamTaskRegistry,
        Depends(ModelStreamTaskRegistry),
    ]
    execution_factory: Annotated[
        RunExecutionFactory, Depends(_agent_run_execution_factory)
    ]
    run_repo: Annotated[AgentRunCreateRepository, Depends(AgentRunRepository)]
    agent_session_repo: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    session_head_repo: Annotated[SessionHeadRepository, Depends(AgentSessionRepository)]
    transcript_repo: Annotated[TranscriptRepository, Depends(EventTranscriptRepository)]
    model_file_pin_repo: Annotated[
        ModelFilePinRepository, Depends(ModelFilePinRepository)
    ]
    compactor: Annotated[ManualCompactor, Depends(EventCompactor)]
    summary_model_call: Annotated[SummaryModelCall, Depends(_summary_model_call)]

    async def save_error_message(self, session_id: str, content: str) -> Event:
        """Store Event system_error."""
        async with self.session_manager() as session:
            return await self.transcript_repo.append(
                session,
                EventCreate(
                    session_id=session_id,
                    kind=EventKind.SYSTEM_ERROR,
                    payload=SystemErrorPayload(
                        content=content,
                        severity="error",
                        recoverable=True,
                    ).model_dump(
                        mode="json",
                        exclude_none=True,
                    ),
                ),
            )

    async def compact(
        self, request: RunRequest, context: RunContext
    ) -> AsyncIterator[Emit]:
        """Run manual event compaction in append-only style."""
        yield ephemeral(CompactionStarted())
        async with self.session_manager() as session:
            await _ensure_agent_session(
                session,
                request.session_id,
                agent_session_repo=self.agent_session_repo,
            )
            transcript = await _current_model_input_transcript(
                session,
                request.session_id,
                session_repo=self.session_head_repo,
                transcript_repo=self.transcript_repo,
            )
            hook_dispatcher = RuntimeHookDispatcher()
            hook_providers = _runtime_hook_provider_refs(request.toolkits)
            await hook_dispatcher.dispatch_observation(
                hook_providers,
                "on_session_compact",
                SessionCompactHookContext(
                    workspace_id=request.workspace_id,
                    agent_id=request.agent_id,
                    session_id=request.session_id,
                    run_id=context.run_id,
                ),
            )
            await self.compactor.compact(
                session,
                session_id=request.session_id,
                transcript=transcript,
                compaction_id=uuid7().hex,
                summarize=_event_summary_generator(
                    request,
                    summarize=self.summary_model_call,
                ),
                summary_context_window_tokens=request.effective_max_input_tokens,
                reason="manual_command",
                summary_enricher=_compaction_summary_enricher(
                    request,
                    dispatcher=hook_dispatcher,
                    providers=hook_providers,
                    run_id=context.run_id,
                ),
            )
        yield ephemeral(CompactionComplete())

    async def run(
        self,
        request: RunRequest,
        context: RunContext,
        *,
        poll_messages: PollMessages | None = None,
        check_stop: CheckStop | None = None,
    ) -> AsyncIterator[Emit]:
        """Run Event AgentRunExecution and yield terminal event."""
        async with self.session_manager() as session:
            await _ensure_agent_session(
                session,
                request.session_id,
                agent_session_repo=self.agent_session_repo,
            )
            user_message_events = await _append_run_user_messages(
                session,
                request.session_id,
                request.user_messages,
                transcript_repo=self.transcript_repo,
            )
            run_state = await self.run_repo.get_by_id(session, context.run_id)
            if run_state is None or run_state.status is not AgentRunStatus.RUNNING:
                raise RuntimeError(
                    "AgentRun must be activated before engine invocation"
                )
            await session.commit()
        for event in user_message_events:
            yield durable(event)
        provider = _provider_name(request.provider)
        model_file_resolver = RequestLocalModelFileResolver()
        model_file_materializer = ModelFileMaterializer(
            model_file_service=self.model_file_service,
            resolver=model_file_resolver,
            user_id=context.user_id,
            agent_id=request.agent_id,
        )
        hook_dispatcher = RuntimeHookDispatcher()
        run_hook_providers = _runtime_hook_provider_refs(request.toolkits)
        emit_queue = _AsyncEventEmitQueue()

        async def prepare_model_call(
            *,
            transcript: Sequence[Event],
            model: str,
        ) -> PreparedModelCall:
            catalog = await build_tool_catalog(
                toolkit_bindings=request.toolkits,
                context=TurnContext(
                    user_id=context.user_id,
                    workspace_id=request.workspace_id,
                    model=model,
                    run_id=context.run_id,
                    session_id=request.session_id,
                    run_index=run_state.run_index,
                    publish_event=context.publish_event,
                    check_stop=check_stop,
                ),
            )
            hook_providers = _runtime_hook_provider_refs(
                catalog.active_toolkit_bindings
            )
            turn_start = await hook_dispatcher.dispatch_turn_start(
                hook_providers,
                TurnStartHookContext(
                    workspace_id=request.workspace_id,
                    agent_id=request.agent_id,
                    session_id=request.session_id,
                    run_id=context.run_id,
                    turn_index=None,
                ),
            )
            injected_prompts = [
                injected for injected in turn_start.injected_prompts if injected.text
            ]
            system_prompt_result = build_system_prompt(
                agent_prompt=request.agent_prompt,
                static_toolkit_prompts=catalog.static_prompt_fragment_inputs,
                dynamic_toolkit_prompts=catalog.dynamic_prompt_fragment_inputs,
                injected_prompts=injected_prompts,
            )
            lowerer = LiteLLMResponsesLowerer(
                provider=provider,
                model=model,
                tools=catalog.native_tools,
                provider_id=request.provider,
                credential_kwargs=request.credential_kwargs,
                temperature=request.temperature,
                max_output_tokens=request.max_output_tokens,
                top_p=request.top_p,
                stop=request.stop,
                reasoning_effort=request.reasoning_effort,
                hosted_tools=request.builtin_tools,
                prompt_cache_scope=request.session_id,
                model_developer=request.model_developer,
                model_capabilities=request.model_capabilities,
                model_file_resolver=model_file_resolver,
            )
            tool_executor = ToolCatalogClientToolExecutor(catalog)
            hooked_tool_executor = _HookedClientToolExecutor(
                inner=tool_executor,
                dispatcher=hook_dispatcher,
                providers=hook_providers,
                workspace_id=request.workspace_id,
                agent_id=request.agent_id,
                session_id=request.session_id,
                run_id=context.run_id,
            )

            async def on_turn_end(reason: TurnEndReason) -> None:
                await hook_dispatcher.dispatch_observation(
                    hook_providers,
                    "on_turn_end",
                    TurnEndHookContext(
                        workspace_id=request.workspace_id,
                        agent_id=request.agent_id,
                        session_id=request.session_id,
                        run_id=context.run_id,
                        reason=reason,
                        turn_index=None,
                    ),
                )

            try:
                native_request = lowerer.lower(
                    transcript,
                    model=model,
                    system_prompt=system_prompt_result.prompt,
                )
            except asyncio.CancelledError:
                await on_turn_end("cancelled")
                raise
            except Exception:
                await on_turn_end("error")
                raise
            return PreparedModelCall(
                native_request=native_request,
                inference_state=request.inference_state,
                system_prompt_analysis=system_prompt_result.analysis,
                tool_executor=hooked_tool_executor,
                on_turn_end=on_turn_end,
            )

        async def on_auto_compaction_started() -> None:
            await emit_queue.put(ephemeral(CompactionStarted(continuing=True)))
            await hook_dispatcher.dispatch_observation(
                run_hook_providers,
                "on_session_compact",
                SessionCompactHookContext(
                    workspace_id=request.workspace_id,
                    agent_id=request.agent_id,
                    session_id=request.session_id,
                    run_id=context.run_id,
                ),
            )

        pre_lower_filter = EventPreLowerFilterPipeline(
            [
                EventAttachmentAvailabilityFilter(),
                EventFilePartPlaceholderFilter(session_id=request.session_id),
                EventAutoCompactionFilter(
                    session_id=request.session_id,
                    compactor=self.compactor,
                    summarize=_event_summary_generator(
                        request,
                        summarize=self.summary_model_call,
                    ),
                    max_input_tokens=request.effective_max_input_tokens,
                    auto_compaction_threshold_tokens=(
                        request.auto_compaction_threshold_tokens
                    ),
                    compaction_id_factory=lambda: uuid7().hex,
                    on_compaction_started=on_auto_compaction_started,
                    summary_enricher=_compaction_summary_enricher(
                        request,
                        dispatcher=hook_dispatcher,
                        providers=run_hook_providers,
                        run_id=context.run_id,
                    ),
                ),
            ]
        )
        execution = self.execution_factory(
            post_lower_filter=PostLowerFilterPipeline(
                [
                    NativeRequestSizeGuard(
                        max_input_chars=self.config.native_request_max_input_chars,
                    ),
                ]
            ),
            model_adapter=LiteLLMResponsesModelAdapter(),
            output_normalizer=LiteLLMResponsesOutputNormalizer(
                provider=provider,
                model=request.model,
            ),
            pre_lower_filter=pre_lower_filter,
            model_call_preparer=prepare_model_call,
            output_sink=emit_queue.extend_from_output,
            phase_sink=lambda phase: _emit_phase_change(
                emit_queue,
                run_id=context.run_id,
                phase=phase,
                pre_lower_filter=pre_lower_filter,
            ),
            pre_model_lower_hook=model_file_materializer.materialize,
            model_file_pin_repo=self.model_file_pin_repo,
            model_stream_timeouts=self.model_stream_timeouts,
            model_stream_task_registry=self.model_stream_task_registry,
            run_repo=self.run_repo,
            transcript_repo=self.transcript_repo,
            session_repo=self.session_head_repo,
        )

        async def execute_run() -> AgentRunStatus:
            async with self.session_manager() as session:
                return await execution.run(
                    session,
                    AgentRunExecutionRequest(
                        run_id=context.run_id,
                        session_id=request.session_id,
                        owner_generation=context.owner_generation,
                        tool_admission_barrier=context.tool_admission_barrier,
                        run_index=run_state.run_index,
                        model=request.model,
                        max_turns=request.max_turns,
                    ),
                    check_stop=check_stop,
                    poll_input_events=_make_input_poller(
                        poll_messages,
                        transcript_repo=self.transcript_repo,
                    ),
                )

        run_task = asyncio.create_task(execute_run())
        cancel_args: tuple[object, ...] | None = None
        try:
            try:
                while True:
                    if run_task.done() and emit_queue.empty():
                        break
                    get_task = asyncio.create_task(emit_queue.get())
                    done, pending = await asyncio.wait(
                        {run_task, get_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if get_task in pending:
                        get_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await get_task
                    if get_task in done:
                        yield get_task.result()
                    elif run_task in done and emit_queue.empty():
                        break
                status = run_task.result()
            except asyncio.CancelledError as exc:
                cancel_args = exc.args
                raise
        finally:
            if not run_task.done():
                _cancel_run_task(run_task, cancel_args)
                with contextlib.suppress(asyncio.CancelledError):
                    await run_task

        if status in {AgentRunStatus.COMPLETED, AgentRunStatus.FAILED}:
            yield ephemeral(RunComplete(run_id=context.run_id))
        elif status in {AgentRunStatus.RUNNING, AgentRunStatus.CANCELLED}:
            return
        else:
            yield ephemeral(RunStopped(run_id=context.run_id))


def _cancel_run_task(
    run_task: asyncio.Task[AgentRunStatus],
    cancel_args: tuple[object, ...] | None,
) -> None:
    """Pass adapter consumer cancellation reason to execution task."""
    if cancel_args and USER_STOP_CANCEL_MESSAGE in cancel_args:
        run_task.cancel(USER_STOP_CANCEL_MESSAGE)
        return
    run_task.cancel()


async def _current_model_input_transcript(
    session: AsyncSession,
    session_id: str,
    *,
    session_repo: SessionHeadRepository,
    transcript_repo: TranscriptRepository,
) -> list[Event]:
    """Return model input transcript based on current event session head."""
    session_state = await session_repo.get_by_id(session, session_id)
    head_event_id = (
        session_state.model_input_head_event_id if session_state is not None else None
    )
    return await transcript_repo.list_for_model_input(
        session,
        session_id,
        head_event_id=head_event_id,
    )


async def _emit_phase_change(
    queue: "_AsyncEventEmitQueue",
    *,
    run_id: str,
    phase: AgentRunPhase,
    pre_lower_filter: EventPreLowerFilterPipeline,
) -> None:
    """Reflect run phase and auto compaction lifecycle in legacy stream."""
    if phase == AgentRunPhase.PREPARING_INPUT:
        pre_lower_filter.was_compacted = False
    if phase == AgentRunPhase.WAITING_FOR_MODEL and pre_lower_filter.was_compacted:
        await queue.put(ephemeral(CompactionComplete(continuing=True)))
        pre_lower_filter.was_compacted = False
    await queue.put(ephemeral(RunPhaseChanged(run_id=run_id, phase=phase)))


def _runtime_hook_provider_refs(
    toolkits: Sequence[ToolkitBinding],
) -> list[RuntimeHookProviderRef]:
    """Convert Toolkit binding list to runtime hook provider refs."""
    refs: list[RuntimeHookProviderRef] = []
    for binding in toolkits:
        refs.append(RuntimeHookProviderRef(slug=binding.slug, toolkit=binding.toolkit))
    return refs


class _HookedClientToolExecutor:
    """Apply runtime hook dispatch to Event tool executor."""

    def __init__(
        self,
        *,
        inner: ClientToolExecutor,
        dispatcher: RuntimeHookDispatcher,
        providers: Sequence[RuntimeHookProviderRef],
        workspace_id: str,
        agent_id: str,
        session_id: str,
        run_id: str,
    ) -> None:
        self._inner = inner
        self._dispatcher = dispatcher
        self._providers = list(providers)
        self._workspace_id = workspace_id
        self._agent_id = agent_id
        self._session_id = session_id
        self._run_id = run_id

    def request_cancel(self, call: ClientToolCallPayload) -> None:
        """Forward running inner tool cancellation request."""
        self._inner.request_cancel(call)

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Run tool after applying before/after tool hooks."""
        toolkit_slug = _toolkit_slug_from_tool_name(call.name)
        before = await self._dispatcher.dispatch_before_tool_call(
            self._providers,
            BeforeToolCallHookContext(
                tool_name=call.name,
                toolkit_slug=toolkit_slug,
                args_json=call.arguments,
                workspace_id=self._workspace_id,
                agent_id=self._agent_id,
                session_id=self._session_id,
                run_id=self._run_id,
            ),
        )
        if isinstance(before, ToolCallDeny):
            return ClientToolResultPayload(
                call_id=call.call_id,
                name=call.name,
                status="failed",
                output=[OutputTextPart(text=before.message)],
            )

        result = await self._inner.execute(call)
        output_text = _tool_result_text(result)
        after = await self._dispatcher.dispatch_after_tool_call(
            self._providers,
            AfterToolCallHookContext(
                tool_name=call.name,
                toolkit_slug=toolkit_slug,
                args_json=call.arguments,
                workspace_id=self._workspace_id,
                agent_id=self._agent_id,
                session_id=self._session_id,
                run_id=self._run_id,
                output_text=output_text,
                error_message=output_text if result.status == "failed" else None,
            ),
        )
        if isinstance(after, ToolOutputReplace):
            return result.model_copy(
                update={
                    "status": "completed",
                    "output": [OutputTextPart(text=after.output_text)],
                }
            )
        return result


def _toolkit_slug_from_tool_name(name: str) -> str:
    """Extract toolkit slug from prefixed tool name."""
    if "__" not in name:
        return ""
    return name.split("__", 1)[0]


def _tool_result_text(result: ClientToolResultPayload) -> str | None:
    """Join Tool output text parts."""
    texts = [
        part.text
        for part in iter_output_parts(result.output)
        if isinstance(part, OutputTextPart) and part.text
    ]
    if not texts:
        return None
    return "\n".join(texts)


def _provider_name(provider: LLMProvider) -> str:
    """Convert provider enum to string for native compat key."""
    return provider.value


def _make_input_poller(
    poll_messages: PollMessages | None,
    *,
    transcript_repo: TranscriptRepository,
) -> Callable[[AsyncSession, str], Awaitable[InputPollResult]] | None:
    """Convert boundary poll to event transcript append callback."""
    if poll_messages is None:
        return None

    async def poll(
        session: AsyncSession,
        session_id: str,
    ) -> InputPollResult:
        result = await poll_messages()
        if not result.user_messages:
            return InputPollResult(
                events=[],
                context_invalidated=result.context_invalidated,
                complete_run=result.complete_run,
            )
        events = await _append_run_user_messages(
            session,
            session_id,
            result.user_messages,
            transcript_repo=transcript_repo,
        )
        return InputPollResult(
            events=events,
            context_invalidated=result.context_invalidated,
            complete_run=result.complete_run,
        )

    return poll


def _compaction_summary_enricher(
    request: RunRequest,
    *,
    dispatcher: RuntimeHookDispatcher,
    providers: Sequence[RuntimeHookProviderRef],
    run_id: str | None,
) -> SummaryEnricher:
    """Create compaction summary enrichment hook pipeline bound to request."""

    async def enrich(
        *,
        summary: str,
        continuity_history: str,
        compaction_id: str,
        reason: str | None,
        covered_until_event_id: str,
    ) -> str:
        return await dispatcher.dispatch_compaction_summary(
            providers,
            CompactionSummaryHookContext(
                workspace_id=request.workspace_id,
                agent_id=request.agent_id,
                session_id=request.session_id,
                run_id=run_id,
                compaction_id=compaction_id,
                reason=reason,
                covered_until_event_id=covered_until_event_id,
                summary=summary,
                continuity_history=continuity_history,
            ),
        )

    return enrich


def _event_summary_generator(
    request: RunRequest,
    *,
    summarize: SummaryModelCall,
) -> SummaryGenerator:
    """Create event summary generator bound to RunRequest."""

    async def generate(
        events: Sequence[Event],
        summary_budget: CompactionSummaryBudget,
    ) -> str:
        input_char_budget = _summary_input_char_budget(
            request.effective_max_input_tokens,
            summary_budget,
        )
        conversation_text = _render_events_for_summary(
            events,
            max_chars=input_char_budget,
        )
        if not conversation_text.strip():
            return ""
        provider = request.compaction_provider or request.provider
        model = request.compaction_model or request.model
        credential_kwargs = (
            request.compaction_credential_kwargs or request.credential_kwargs
        )
        summary = await summarize(
            provider=provider,
            model=model,
            credential_kwargs=dict(credential_kwargs),
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            user_prompt=SUMMARY_USER_TEMPLATE,
            conversation_text=conversation_text,
            max_output_tokens=summary_budget.max_output_tokens,
            session_id=request.session_id,
        )
        return enforce_summary_char_budget(summary, summary_budget)

    return generate


def _render_events_for_summary(
    events: Sequence[Event],
    *,
    max_chars: int | None = None,
) -> str:
    """Render events as compaction summary input text."""
    lines = [
        rendered
        for rendered in (_render_event_for_summary(event) for event in events)
        if rendered.strip()
    ]
    full_text = "\n".join(lines)
    if max_chars is None or len(full_text) <= max_chars:
        return full_text
    return _trim_summary_input(lines, max_chars)


def _render_event_for_summary(event: Event) -> str:
    """Render one Event as compaction summary input text."""
    payload = event.payload
    match payload:
        case UserMessagePayload(content=content):
            return f"[User]: {_event_text_content(content)}"
        case AssistantMessagePayload(content=content):
            return f"[Assistant]: {_event_text_content(content)}"
        case ReasoningPayload(text=text, summary=summary):
            if summary:
                return f"[Reasoning summary]: {summary}"
            if text:
                return f"[Reasoning]: {text}"
        case ClientToolCallPayload(name=name, arguments=arguments):
            return f"[Client tool call: {name}({arguments})]"
        case ClientToolResultPayload(name=name, status=status, output=output):
            return (
                f"[Client tool result: {name or 'unknown'} {status}] "
                f"{_event_text_content(output)}"
            )
        case ProviderToolCallPayload(name=name, arguments=arguments):
            rendered_arguments = arguments or ""
            return f"[Provider tool call: {name}({rendered_arguments})]"
        case ProviderToolResultPayload(name=name, status=status, output=output):
            return (
                f"[Provider tool result: {name or 'unknown'} {status}] "
                f"{_event_text_content(output)}"
            )
        case CompactionSummaryPayload(content=content):
            return f"[Existing Checkpoint]: {content}"
        case CompactionMarkerPayload():
            return ""
        case SystemErrorPayload(content=content):
            return f"[System error]: {content}"
        case _:
            return ""
    return ""


def _trim_summary_input(lines: Sequence[str], max_chars: int) -> str:
    """Limit summary input around checkpoint plus recent raw events."""
    marker_budget = len(_SUMMARY_INPUT_OMISSION_MARKER) + 2
    remaining = max(0, max_chars - marker_budget)
    selected: dict[int, str] = {}

    checkpoint_index = _latest_checkpoint_index(lines)
    if checkpoint_index is not None and remaining > 0:
        checkpoint = lines[checkpoint_index]
        selected[checkpoint_index] = _fit_summary_line(checkpoint, remaining)
        remaining -= len(selected[checkpoint_index]) + 1

    for index in range(len(lines) - 1, -1, -1):
        if index in selected:
            continue
        line = lines[index]
        line_cost = len(line) + 1
        if line_cost <= remaining:
            selected[index] = line
            remaining -= line_cost
            continue
        if not selected and remaining > 0:
            selected[index] = _fit_summary_line(line, remaining)
        break

    rendered = [text for _, text in sorted(selected.items()) if text.strip()]
    if not rendered:
        return _SUMMARY_INPUT_OMISSION_MARKER[:max_chars]
    if len(rendered) == len(lines):
        return "\n".join(rendered)

    if checkpoint_index is not None and checkpoint_index in selected:
        checkpoint = selected[checkpoint_index]
        tail = [
            text
            for index, text in sorted(selected.items())
            if index != checkpoint_index and text.strip()
        ]
        return "\n".join([checkpoint, _SUMMARY_INPUT_OMISSION_MARKER, *tail])
    return "\n".join([_SUMMARY_INPUT_OMISSION_MARKER, *rendered])


def _latest_checkpoint_index(lines: Sequence[str]) -> int | None:
    """Find latest checkpoint index in rendered line list."""
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].startswith("[Existing Checkpoint]:"):
            return index
    return None


def _fit_summary_line(line: str, max_chars: int) -> str:
    """Keep suffix of long line to fit summary input budget."""
    if max_chars <= 0:
        return ""
    if len(line) <= max_chars:
        return line
    note = "[Leading content omitted to fit summary context.]\n"
    if max_chars <= len(note):
        return line[-max_chars:]
    return note + line[-(max_chars - len(note)) :]


def _summary_input_char_budget(
    max_input_tokens: int,
    summary_budget: CompactionSummaryBudget,
) -> int:
    """Conservatively calculate summary model input char budget."""
    usable_tokens = max(
        0,
        max_input_tokens
        - summary_budget.max_output_tokens
        - _SUMMARY_INPUT_OVERHEAD_TOKENS,
    )
    budget = int(usable_tokens * _SUMMARY_INPUT_CHAR_PER_TOKEN)
    return max(
        _MIN_SUMMARY_INPUT_CHARS,
        min(_MAX_SUMMARY_INPUT_CHARS, budget),
    )


def _event_text_content(content: object) -> str:
    """Extract only text from Event content/output part array."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    texts: list[str] = []
    for part in content:
        if isinstance(part, InputTextPart | OutputTextPart):
            texts.append(part.text)
    return "\n".join(texts)


class _AsyncEventEmitQueue:
    """Forward execution output to publishable emit async queue."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Emit] = asyncio.Queue()

    async def extend_from_output(
        self,
        normalized: NormalizedAdapterOutput,
        appended: Sequence[Event],
    ) -> None:
        """Put normalizer output into publish queue."""
        for projection in normalized.projections:
            emit = _stream_projection_emit(projection)
            if emit is not None:
                await self._queue.put(emit)
        for event in appended:
            await self._queue.put(durable(event))

    async def get(self) -> Emit:
        """Return next emit."""
        return await self._queue.get()

    async def put(self, emit: Emit) -> None:
        """Put one emit into queue."""
        await self._queue.put(emit)

    def empty(self) -> bool:
        """Return whether queue is empty."""
        return self._queue.empty()


def _stream_projection_emit(projection: StreamProjection) -> Emit | None:
    """Convert UI stream projection to ephemeral emit."""
    if projection.type == "content_delta":
        return ephemeral(
            ContentDelta(
                delta=projection.delta or "",
                content_index=projection.index or 0,
            )
        )
    if projection.type == "function_call_delta":
        return ephemeral(
            FunctionCallDelta(
                index=projection.index or 0,
                id=projection.call_id,
                name=projection.name,
                arguments_delta=projection.delta or "",
            )
        )
    if projection.type == "reasoning_delta":
        return ephemeral(ReasoningDelta(delta=projection.delta or ""))
    return None


async def _append_run_user_messages(
    session: AsyncSession,
    session_id: str,
    user_messages: Sequence[RunUserMessage],
    *,
    transcript_repo: TranscriptRepository,
) -> list[Event]:
    """Append RunRequest event user_message input to transcript."""
    appended: list[Event] = []
    for user_message in user_messages:
        existing = await transcript_repo.get_by_external_id(
            session,
            session_id,
            user_message.external_id,
        )
        if existing is not None:
            continue
        appended.append(
            await transcript_repo.append(
                session,
                EventCreate(
                    session_id=session_id,
                    kind=EventKind.USER_MESSAGE,
                    payload=user_message.payload.model_dump(
                        mode="json",
                        exclude_none=True,
                    ),
                    external_id=user_message.external_id,
                ),
            )
        )
    return appended


async def _ensure_agent_session(
    session: AsyncSession,
    session_id: str,
    *,
    agent_session_repo: AgentSessionRepository,
) -> None:
    """Ensure AgentSession row exists before event processing."""
    agent_session = await agent_session_repo.get_by_id(session, session_id)
    if agent_session is None:
        raise ValueError("AgentSession not found")
