"""Event AgentEngineProtocol adapter assembly."""

import asyncio
import contextlib
import dataclasses
import datetime
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Annotated, Protocol, assert_never

import httpx
from azcommon.result import Failure, Success
from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import XaiOAuthSecrets
from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    EventKind,
    LLMProvider,
)
from azents.core.tools import TurnContext
from azents.core.xai import resolve_xai_api_base_url
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
    ProviderToolActivityChanged,
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
from azents.engine.events.openai_responses import (
    OpenAIResponsesLowerer,
    OpenAIResponsesModelAdapter,
    OpenAIResponsesOutputNormalizer,
    OpenAIResponsesRequest,
    create_openai_responses_client,
    openai_responses_client_config,
    openai_responses_websocket_endpoint_eligible,
)
from azents.engine.events.output_parts import iter_output_parts
from azents.engine.events.protocols import (
    AgentRunCreateRepository,
    ClientToolExecutor,
    ContentDeltaProjection,
    FunctionCallDeltaProjection,
    ManualCompactor,
    NativeModelRequest,
    NormalizedAdapterOutput,
    ProviderToolActivityProjection,
    ReasoningDeltaProjection,
    SessionHeadRepository,
    StreamProjection,
    SummaryEnricher,
    SummaryGenerator,
    TranscriptRepository,
)
from azents.engine.events.provider_output import ProviderOutputMaterializer
from azents.engine.events.provider_tool_rendering import render_provider_tool_semantic
from azents.engine.events.responses_continuation import ResponsesContinuationPlanner
from azents.engine.events.system_prompt import build_system_prompt
from azents.engine.events.tools import (
    ToolCatalogClientToolExecutor,
    build_tool_catalog,
    extend_prepared_tool_catalog_with_json_functions,
    extend_tool_catalog_candidates,
    project_tool_catalog_for_client_compatibility,
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
from azents.engine.model_stream import ModelStreamWatchdog, get_model_stream_watchdog
from azents.engine.run.builtin_tools import (
    ClientBuiltinToolImplementationUnavailableError,
    resolve_builtin_tools,
)
from azents.engine.run.client_tool_compatibility import (
    ClientToolRoute,
    resolve_client_tool_adapter_profile,
    resolve_client_tool_model_profiles,
)
from azents.engine.run.contracts import RunContext, RunRequest, ToolkitBinding
from azents.engine.run.emit import Emit, durable, ephemeral
from azents.engine.run.model_transport import ModelTransportKey
from azents.engine.run.tool_budget import (
    ProviderHostedToolDeclarationCounts,
    ToolRequestCompatibilityKey,
    build_default_tool_request_compatibility_registry,
    resolve_tool_declaration_budget,
)
from azents.engine.run.types import (
    USER_STOP_CANCEL_MESSAGE,
    CheckStop,
    FunctionTool,
    FunctionToolError,
    PollMessages,
)
from azents.engine.tooling.tool_search import (
    DeferredToolSearchIndex,
    ToolWorkingSetStore,
    make_tool_search_tool,
    project_tool_catalog,
)
from azents.engine.tools.xai_image_generation import (
    XaiImageGenerationExecutor,
    XaiImagineClientFactory,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)
from azents.repos.model_file_pin import ModelFilePinRepository
from azents.services.artifact import ArtifactService
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService
from azents.services.xai_imagine import XaiImagineClient
from azents.services.xai_oauth.data import (
    ProviderEntitlementDenied,
    ProviderRejected,
    ProviderUnavailable,
)
from azents.services.xai_oauth.runtime import refresh_runtime_tokens

logger = logging.getLogger(__name__)


class RunExecution(Protocol):
    """Agent run execution protocol."""

    async def run(
        self,
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


def _xai_imagine_client_factory() -> XaiImagineClientFactory:
    """Build operation-scoped xAI Imagine clients."""

    @contextlib.asynccontextmanager
    async def create() -> AsyncIterator[XaiImagineClient]:
        timeout = httpx.Timeout(60.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as http_client:
            yield XaiImagineClient(
                http_client,
                base_url=resolve_xai_api_base_url(),
            )

    return create


def _tool_working_set_store(
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ],
) -> ToolWorkingSetStore:
    """Build the session-scoped deferred-tool working-set store."""
    return ToolWorkingSetStore(session_manager=session_manager)


def _summary_model_call(
    watchdog: Annotated[ModelStreamWatchdog, Depends(get_model_stream_watchdog)],
) -> SummaryModelCall:
    """Bind the process-owned watchdog to compaction model calls."""

    async def call_summary(
        *,
        provider: LLMProvider,
        provider_integration_id: str | None,
        model: str,
        credential_kwargs: dict[str, object],
        system_prompt: str,
        user_prompt: str,
        conversation_text: str,
        max_output_tokens: int,
        session_id: str | None = None,
    ) -> str:
        return await summarize_text_with_model(
            watchdog=watchdog,
            provider=provider,
            provider_integration_id=provider_integration_id,
            model=model,
            credential_kwargs=credential_kwargs,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            conversation_text=conversation_text,
            max_output_tokens=max_output_tokens,
            session_id=session_id,
        )

    return call_summary


@dataclasses.dataclass(frozen=True)
class EventEngineAdapterConfig:
    """Event engine adapter configuration."""

    native_request_max_input_chars: int = 16_000_000


@dataclasses.dataclass
class _CompactionLiveState:
    """Track legacy compaction events from the durable Run phase."""

    active: bool = False


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
    tool_working_set_store: Annotated[
        ToolWorkingSetStore,
        Depends(_tool_working_set_store),
    ]
    artifact_service: Annotated[ArtifactService, Depends(ArtifactService)]
    exchange_file_service: Annotated[ExchangeFileService, Depends(ExchangeFileService)]
    model_file_service: Annotated[ModelFileService, Depends(ModelFileService)]
    integration_repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]
    xai_imagine_client_factory: Annotated[
        XaiImagineClientFactory,
        Depends(_xai_imagine_client_factory),
    ]
    config: Annotated[EventEngineAdapterConfig, Depends(EventEngineAdapterConfig)]
    model_stream_watchdog: Annotated[
        ModelStreamWatchdog,
        Depends(get_model_stream_watchdog),
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

    def _xai_image_generation_tool(self, request: RunRequest) -> FunctionTool:
        """Build the auto-bound Imagine tool from the selected xAI integration."""
        access_token = request.credential_kwargs.get("api_key")
        if not isinstance(access_token, str) or not access_token:
            raise ClientBuiltinToolImplementationUnavailableError(
                "xAI image generation requires an integration credential."
            )
        integration_id = (
            request.inference_state.model_selection.llm_provider_integration_id
            if request.inference_state is not None
            else None
        )

        async def refresh_access_token() -> str:
            if integration_id is None:
                raise FunctionToolError(
                    "xAI OAuth reconnect is required for image generation."
                )
            async with self.session_manager() as session:
                integration = await self.integration_repository.get_by_id_with_secrets(
                    session,
                    integration_id,
                )
            if (
                integration is None
                or integration.workspace_id != request.workspace_id
                or integration.provider != LLMProvider.XAI_OAUTH
            ):
                raise FunctionToolError(
                    "xAI OAuth reconnect is required for image generation."
                )
            refresh_result = await refresh_runtime_tokens(
                integration=integration,
                integration_repository=self.integration_repository,
                session_manager=self.session_manager,
            )
            match refresh_result:
                case Failure(error):
                    match error:
                        case ProviderRejected():
                            message = (
                                "xAI OAuth reconnect is required for image generation."
                            )
                        case ProviderEntitlementDenied():
                            message = (
                                "xAI Imagine access is not permitted for this account."
                            )
                        case ProviderUnavailable():
                            message = (
                                "xAI OAuth is temporarily unavailable. Try again later."
                            )
                        case _ as unreachable:
                            assert_never(unreachable)
                    raise FunctionToolError(message)
                case Success(refreshed):
                    if not isinstance(refreshed.secrets, XaiOAuthSecrets):
                        raise FunctionToolError(
                            "xAI OAuth reconnect is required for image generation."
                        )
                    access_token = refreshed.secrets.access_token
                    request.credential_kwargs["api_key"] = access_token
                    return access_token

        return XaiImageGenerationExecutor(
            provider=request.provider,
            access_token=access_token,
            client_factory=self.xai_imagine_client_factory,
            refresh_access_token=(
                refresh_access_token
                if request.provider == LLMProvider.XAI_OAUTH
                else None
            ),
        ).make_tool()

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

        async def on_compaction_started() -> None:
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

        async def clear_tool_working_set(session: AsyncSession) -> None:
            await self.tool_working_set_store.clear_in_session(
                session,
                request.agent_id,
                request.session_id,
            )

        await self.compactor.compact(
            session_id=request.session_id,
            transcript=transcript,
            compaction_id=uuid7().hex,
            summarize=_event_summary_generator(
                request,
                summarize=self.summary_model_call,
            ),
            on_started=on_compaction_started,
            summary_context_window_tokens=request.effective_max_input_tokens,
            reason="manual_command",
            summary_enricher=_compaction_summary_enricher(
                request,
                dispatcher=hook_dispatcher,
                providers=hook_providers,
                run_id=context.run_id,
            ),
            on_committing=clear_tool_working_set,
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
        compaction_live_state = _CompactionLiveState()

        async def prepare_model_call(
            *,
            transcript: Sequence[Event],
            model: str,
        ) -> PreparedModelCall[NativeModelRequest | OpenAIResponsesRequest]:
            model_selection = (
                request.inference_state.model_selection
                if request.inference_state is not None
                else None
            )
            model_family = (
                model_selection.model_family if model_selection is not None else None
            )
            model_developer = (
                model_selection.model_developer
                if model_selection is not None
                else request.model_developer
            )
            lowerer_type = (
                OpenAIResponsesLowerer
                if _uses_openai_sdk(request.provider)
                else LiteLLMResponsesLowerer
            )
            client_tool_route = ClientToolRoute(
                provider=request.provider,
                adapter=lowerer_type.adapter,
                native_format=lowerer_type.native_format,
            )
            client_tool_model_profiles = resolve_client_tool_model_profiles(
                model_identifier=(
                    model_selection.model_identifier
                    if model_selection is not None
                    else model
                ),
                model_developer=model_developer,
                model_family=model_family,
            )
            client_tool_adapter_profile = resolve_client_tool_adapter_profile(
                route=client_tool_route,
            )
            historical_plaintext_custom_supported = (
                client_tool_adapter_profile is not None
                and client_tool_adapter_profile.supports_wire_dialect(
                    "plaintext_custom"
                )
            )
            candidate_catalog = await build_tool_catalog(
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
            catalog = project_tool_catalog_for_client_compatibility(
                candidate_catalog,
                client_tool_model_profiles,
                client_tool_adapter_profile,
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
            resolved_builtin_tools = resolve_builtin_tools(
                selected=request.builtin_tools,
                provider=request.provider,
                supported=request.model_capabilities.built_in_tools.supported,
            )
            client_builtin_tools: list[FunctionTool] = []
            for tool in resolved_builtin_tools.client_executed:
                if tool.name == "image_generation" and request.provider in {
                    LLMProvider.XAI,
                    LLMProvider.XAI_OAUTH,
                }:
                    client_builtin_tools.append(
                        self._xai_image_generation_tool(request)
                    )
                    continue
                raise ClientBuiltinToolImplementationUnavailableError(
                    f"Client builtin tool implementation is unavailable: {tool.name}"
                )
            if client_builtin_tools:
                candidate_catalog = extend_tool_catalog_candidates(
                    candidate_catalog,
                    client_builtin_tools,
                )
                catalog = project_tool_catalog_for_client_compatibility(
                    candidate_catalog,
                    client_tool_model_profiles,
                    client_tool_adapter_profile,
                )
            logger.info(
                "Projected client tools for model compatibility",
                extra={
                    "session_id": request.session_id,
                    "run_id": context.run_id,
                    "model_developer": (
                        model_developer.value if model_developer is not None else None
                    ),
                    "model_family": model_family,
                    "client_tool_model_profiles": sorted(
                        profile.value for profile in client_tool_model_profiles
                    ),
                    "client_tool_adapter_profile": (
                        client_tool_adapter_profile.profile_id
                        if client_tool_adapter_profile is not None
                        else None
                    ),
                    "client_tool_adapter_default_wire_dialects": (
                        list(client_tool_adapter_profile.default_wire_dialects)
                        if client_tool_adapter_profile is not None
                        else []
                    ),
                    "client_tool_adapter_model_profile_wire_dialects": (
                        {
                            preference.model_profile.value: list(
                                preference.wire_dialects
                            )
                            for preference in (
                                client_tool_adapter_profile.model_profile_preferences
                            )
                        }
                        if client_tool_adapter_profile is not None
                        else {}
                    ),
                    "candidate_tool_count": len(candidate_catalog.tools),
                    "projected_tool_count": len(catalog.tools),
                },
            )

            provider_visible_tool_names: tuple[str, ...]
            deferred_tool_names: frozenset[str]
            if request.tool_search_enabled:
                budget = resolve_tool_declaration_budget(
                    registry=build_default_tool_request_compatibility_registry(),
                    key=ToolRequestCompatibilityKey(
                        provider=request.provider,
                        adapter=lowerer_type.adapter,
                        native_format=lowerer_type.native_format,
                        model_identifier=model,
                        model_developer=model_developer,
                        model_family=model_family,
                    ),
                    provider_hosted=ProviderHostedToolDeclarationCounts(
                        total_tools=len(resolved_builtin_tools.provider_hosted),
                        function_declarations=0,
                    ),
                )
                search_index = DeferredToolSearchIndex(list(catalog.entries.values()))
                if search_index.entries:
                    direct_count_with_search = len(catalog.direct_tool_names) + 1
                    if budget.client_function_capacity is None:
                        activation_capacity = None
                    else:
                        activation_capacity = max(
                            0,
                            budget.client_function_capacity - direct_count_with_search,
                        )
                    search_tool = make_tool_search_tool(
                        index=search_index,
                        store=self.tool_working_set_store,
                        agent_id=request.agent_id,
                        session_id=request.session_id,
                        activation_capacity=activation_capacity,
                    )
                    catalog = extend_prepared_tool_catalog_with_json_functions(
                        catalog,
                        [search_tool],
                    )

                working_set = await self.tool_working_set_store.load(
                    request.agent_id,
                    request.session_id,
                )
                projection = project_tool_catalog(
                    entries=catalog.entries,
                    working_set=working_set,
                    budget=budget,
                )
                provider_visible_tool_names = projection.provider_visible_tool_names
                deferred_tool_names = frozenset(catalog.deferred_tool_names)
                logger.info(
                    "Prepared model tool projection",
                    extra={
                        "session_id": request.session_id,
                        "run_id": context.run_id,
                        "provider": request.provider.value,
                        "model": model,
                        "tool_budget_rule_id": (
                            budget.rule.rule_id if budget.rule is not None else None
                        ),
                        "resolved_tool_limit": budget.maximum_declarations,
                        "counted_provider_hosted_tools": (
                            budget.counted_provider_hosted_declarations
                        ),
                        "direct_tool_count": len(projection.direct_tool_names),
                        "active_deferred_tool_count": len(
                            projection.active_deferred_tool_names
                        ),
                        "visible_deferred_tool_count": len(
                            projection.visible_deferred_tool_names
                        ),
                    },
                )
            else:
                provider_visible_tool_names = tuple(catalog.tools)
                deferred_tool_names = frozenset()
                logger.info(
                    "Prepared complete model tool catalog",
                    extra={
                        "session_id": request.session_id,
                        "run_id": context.run_id,
                        "provider": request.provider.value,
                        "model": model,
                        "tool_count": len(provider_visible_tool_names),
                    },
                )
            system_prompt_result = build_system_prompt(
                agent_prompt=request.agent_prompt,
                static_toolkit_prompts=catalog.static_prompt_fragment_inputs_for(
                    provider_visible_tool_names
                ),
                dynamic_toolkit_prompts=catalog.dynamic_prompt_fragment_inputs,
                injected_prompts=injected_prompts,
            )
            lowerer = lowerer_type(
                provider=provider,
                model=model,
                tools=catalog.native_tools_for(provider_visible_tool_names),
                provider_id=request.provider,
                credential_kwargs=(
                    {}
                    if _uses_openai_sdk(request.provider)
                    else request.credential_kwargs
                ),
                temperature=request.temperature,
                max_output_tokens=request.max_output_tokens,
                top_p=request.top_p,
                stop=request.stop,
                reasoning_effort=request.reasoning_effort,
                hosted_tools=resolved_builtin_tools.provider_hosted,
                prompt_cache_scope=request.session_id,
                model_developer=request.model_developer,
                model_capabilities=request.model_capabilities,
                model_file_resolver=model_file_resolver,
                historical_plaintext_custom_supported=(
                    historical_plaintext_custom_supported
                ),
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
            prepared_tool_executor: ClientToolExecutor = hooked_tool_executor
            if request.tool_search_enabled:
                prepared_tool_executor = _WorkingSetClientToolExecutor(
                    inner=hooked_tool_executor,
                    deferred_tool_names=deferred_tool_names,
                    store=self.tool_working_set_store,
                    agent_id=request.agent_id,
                    session_id=request.session_id,
                )
                prepared_tool_executor = _PreparedToolAllowlistExecutor(
                    inner=prepared_tool_executor,
                    allowed_tool_names=frozenset(provider_visible_tool_names),
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
                tool_executor=prepared_tool_executor,
                enrich_client_tool_call=catalog.enrich_client_tool_call,
                on_turn_end=on_turn_end,
            )

        async def on_auto_compaction_started() -> None:
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

        async def clear_tool_working_set(session: AsyncSession) -> None:
            await self.tool_working_set_store.clear_in_session(
                session,
                request.agent_id,
                request.session_id,
            )

        pre_lower_filter = EventPreLowerFilterPipeline(
            [
                EventAttachmentAvailabilityFilter(),
                EventFilePartPlaceholderFilter(session_id=request.session_id),
            ]
        )
        auto_compaction_filter = EventAutoCompactionFilter(
            session_id=request.session_id,
            compactor=self.compactor,
            summarize=_event_summary_generator(
                request,
                summarize=self.summary_model_call,
            ),
            max_input_tokens=request.effective_max_input_tokens,
            auto_compaction_threshold_tokens=request.auto_compaction_threshold_tokens,
            compaction_id_factory=lambda: uuid7().hex,
            on_compaction_started=on_auto_compaction_started,
            summary_enricher=_compaction_summary_enricher(
                request,
                dispatcher=hook_dispatcher,
                providers=run_hook_providers,
                run_id=context.run_id,
            ),
            on_committing=clear_tool_working_set,
        )
        integration_id = (
            request.inference_state.model_selection.llm_provider_integration_id
            if request.inference_state is not None
            else None
        )
        if _uses_openai_sdk(request.provider):
            client_config = openai_responses_client_config(
                provider=request.provider,
                credential_kwargs=request.credential_kwargs,
            )
            model_adapter = OpenAIResponsesModelAdapter(
                client=create_openai_responses_client(config=client_config),
                continuation_planner=(
                    ResponsesContinuationPlanner()
                    if request.provider == LLMProvider.OPENAI
                    else None
                ),
                transport_state=context.model_transport_state,
                transport_key=ModelTransportKey(
                    family="openai_responses",
                    provider=request.provider.value,
                    provider_integration_id=integration_id,
                ),
                websocket_endpoint_eligible=(
                    openai_responses_websocket_endpoint_eligible(
                        provider=request.provider,
                        config=client_config,
                    )
                ),
            )
            output_normalizer = OpenAIResponsesOutputNormalizer(
                provider=provider,
                model=request.model,
                operation="sampling",
                integration=integration_id,
            )
        else:
            model_adapter = LiteLLMResponsesModelAdapter(None)
            output_normalizer = LiteLLMResponsesOutputNormalizer(
                provider=provider,
                model=request.model,
                operation="sampling",
                integration=integration_id,
            )

        generated_output_materializer = ProviderOutputMaterializer(
            exchange_file_service=self.exchange_file_service,
            model_file_service=self.model_file_service,
            workspace_id=request.workspace_id,
            agent_id=request.agent_id,
            session_id=request.session_id,
            user_id=context.user_id,
            run_id=context.run_id,
            run_index=run_state.run_index,
        )
        execution = self.execution_factory(
            session_manager=self.session_manager,
            post_lower_filter=PostLowerFilterPipeline(
                [
                    NativeRequestSizeGuard(
                        max_input_chars=self.config.native_request_max_input_chars,
                    ),
                ]
            ),
            model_adapter=model_adapter,
            model_stream_watchdog=self.model_stream_watchdog,
            model_stream_provider=provider,
            model_stream_provider_integration_id=integration_id,
            model_stream_inference_profile=(
                request.inference_state.model_target_label
                if request.inference_state is not None
                else None
            ),
            output_normalizer=output_normalizer,
            pre_lower_filter=pre_lower_filter,
            auto_compaction_filter=auto_compaction_filter,
            model_call_preparer=prepare_model_call,
            output_sink=emit_queue.extend_from_output,
            phase_sink=lambda phase, model_call_started_at: _emit_phase_change(
                emit_queue,
                run_id=context.run_id,
                phase=phase,
                model_call_started_at=model_call_started_at,
                compaction_state=compaction_live_state,
            ),
            provider_output_materializer=generated_output_materializer,
            client_tool_output_materializer=generated_output_materializer,
            pre_model_lower_hook=model_file_materializer.materialize,
            model_file_pin_repo=self.model_file_pin_repo,
            run_repo=self.run_repo,
            transcript_repo=self.transcript_repo,
            session_repo=self.session_head_repo,
        )

        async def execute_run() -> AgentRunStatus:
            return await execution.run(
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
                    session_manager=self.session_manager,
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
    model_call_started_at: datetime.datetime | None,
    compaction_state: _CompactionLiveState,
) -> None:
    """Reflect durable Run phase and auto compaction in the legacy stream."""
    if phase == AgentRunPhase.COMPACTING and not compaction_state.active:
        compaction_state.active = True
        await queue.put(ephemeral(CompactionStarted(continuing=True)))
    elif phase != AgentRunPhase.COMPACTING and compaction_state.active:
        compaction_state.active = False
        await queue.put(ephemeral(CompactionComplete(continuing=True)))
    await queue.put(
        ephemeral(
            RunPhaseChanged(
                run_id=run_id,
                phase=phase,
                model_call_started_at=model_call_started_at,
            )
        )
    )


def _runtime_hook_provider_refs(
    toolkits: Sequence[ToolkitBinding],
) -> list[RuntimeHookProviderRef]:
    """Convert Toolkit binding list to runtime hook provider refs."""
    refs: list[RuntimeHookProviderRef] = []
    for binding in toolkits:
        refs.append(RuntimeHookProviderRef(slug=binding.slug, toolkit=binding.toolkit))
    return refs


class _PreparedToolAllowlistExecutor:
    """Reject client tool calls outside one prepared provider projection."""

    def __init__(
        self,
        *,
        inner: ClientToolExecutor,
        allowed_tool_names: frozenset[str],
    ) -> None:
        self.inner = inner
        self.allowed_tool_names = allowed_tool_names

    def request_cancel(self, call: ClientToolCallPayload) -> None:
        """Forward cancellation only for tools admitted to this prepared call."""
        if call.name in self.allowed_tool_names:
            self.inner.request_cancel(call)

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Execute only tools whose schemas were sent to the provider."""
        if call.name not in self.allowed_tool_names:
            return ClientToolResultPayload(
                call_id=call.call_id,
                name=call.name,
                wire_dialect=call.wire_dialect,
                status="failed",
                output=[OutputTextPart(text=f"Tool not found: {call.name}")],
            )
        return await self.inner.execute(call)


class _WorkingSetClientToolExecutor:
    """Refresh deferred-tool recency before every admitted invocation."""

    def __init__(
        self,
        *,
        inner: ClientToolExecutor,
        deferred_tool_names: frozenset[str],
        store: ToolWorkingSetStore,
        agent_id: str,
        session_id: str,
    ) -> None:
        self.inner = inner
        self.deferred_tool_names = deferred_tool_names
        self.store = store
        self.agent_id = agent_id
        self.session_id = session_id

    def request_cancel(self, call: ClientToolCallPayload) -> None:
        """Forward running inner tool cancellation request."""
        self.inner.request_cancel(call)

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Touch deferred recency before hooks or handler execution."""
        if call.name in self.deferred_tool_names:
            await self.store.touch(self.agent_id, self.session_id, call.name)
        return await self.inner.execute(call)


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
        self.inner = inner
        self.dispatcher = dispatcher
        self._providers = list(providers)
        self._workspace_id = workspace_id
        self._agent_id = agent_id
        self._session_id = session_id
        self._run_id = run_id

    def request_cancel(self, call: ClientToolCallPayload) -> None:
        """Forward running inner tool cancellation request."""
        self.inner.request_cancel(call)

    async def execute(self, call: ClientToolCallPayload) -> ClientToolResultPayload:
        """Run tool after applying before/after tool hooks."""
        toolkit_slug = _toolkit_slug_from_tool_name(call.name)
        before = await self.dispatcher.dispatch_before_tool_call(
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
                wire_dialect=call.wire_dialect,
                status="failed",
                output=[OutputTextPart(text=before.message)],
            )

        result = await self.inner.execute(call)
        output_text = _tool_result_text(result)
        after = await self.dispatcher.dispatch_after_tool_call(
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


def _uses_openai_sdk(provider: LLMProvider) -> bool:
    """Return whether the provider uses the official OpenAI HTTP adapter."""
    return provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}


def _make_input_poller(
    poll_messages: PollMessages | None,
    *,
    session_manager: SessionManager[AsyncSession],
    transcript_repo: TranscriptRepository,
) -> Callable[[str], Awaitable[InputPollResult]] | None:
    """Convert boundary poll to event transcript append callback."""
    if poll_messages is None:
        return None

    async def poll(
        session_id: str,
    ) -> InputPollResult:
        result = await poll_messages()
        if not result.user_messages:
            return InputPollResult(
                events=[],
                context_invalidated=result.context_invalidated,
                complete_run=result.complete_run,
            )
        async with session_manager() as session:
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
        provider_integration_id = request.compaction_provider_integration_id
        if request.compaction_provider is None and request.inference_state is not None:
            provider_integration_id = (
                request.inference_state.model_selection.llm_provider_integration_id
            )
        summary = await summarize(
            provider=provider,
            provider_integration_id=provider_integration_id,
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
        case ClientToolCallPayload(
            name=name,
            wire_dialect="plaintext_custom",
        ):
            return f"[Client tool call: {name} (plaintext custom input omitted)]"
        case ClientToolCallPayload(name=name, arguments=arguments):
            return f"[Client tool call: {name}({arguments})]"
        case ClientToolResultPayload(name=name, status=status, output=output):
            return (
                f"[Client tool result: {name or 'unknown'} {status}] "
                f"{_event_text_content(output)}"
            )
        case ProviderToolCallPayload() as payload:
            return render_provider_tool_semantic(payload)
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
            await self._queue.put(_stream_projection_emit(projection))
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


def _stream_projection_emit(projection: StreamProjection) -> Emit:
    """Convert one canonical stream projection to an ephemeral emit."""
    match projection:
        case ContentDeltaProjection(delta=delta, content_index=content_index):
            return ephemeral(ContentDelta(delta=delta, content_index=content_index))
        case FunctionCallDeltaProjection(
            index=index,
            call_id=call_id,
            name=name,
            delta=arguments_delta,
        ):
            return ephemeral(
                FunctionCallDelta(
                    index=index,
                    id=call_id,
                    name=name,
                    arguments_delta=arguments_delta,
                )
            )
        case ReasoningDeltaProjection(
            delta=delta,
            item_id=item_id,
            output_index=output_index,
            summary_index=summary_index,
        ):
            return ephemeral(
                ReasoningDelta(
                    delta=delta,
                    item_id=item_id,
                    output_index=output_index,
                    summary_index=summary_index,
                )
            )
        case ProviderToolActivityProjection(
            call_id=call_id,
            name=name,
            status=status,
            arguments=arguments,
        ):
            return ephemeral(
                ProviderToolActivityChanged(
                    call_id=call_id,
                    name=name,
                    status=status,
                    arguments=arguments,
                )
            )
        case _:
            assert_never(projection)


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
