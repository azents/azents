"""Event AgentEngineProtocol adapter assembly."""

import asyncio
import contextlib
import dataclasses
import datetime
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from typing import Annotated, Protocol, assert_never

import httpx
from azcommon.result import Failure, Success
from azcommon.uuid import uuid7
from fastapi import Depends
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.builtin_tools import builtin_tool_configurable
from azents.core.credentials import ChatGPTOAuthSecrets, XaiOAuthSecrets
from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    LLMProvider,
)
from azents.core.image_generation_config import (
    ExplicitImageGenerationModel,
    decode_image_generation_model_config,
)
from azents.core.model_pricing import (
    CapturedModelPricing,
    normalize_model_pricing,
)
from azents.core.openai_client_config import openai_responses_client_config
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
from azents.engine.events.external_channel_rendering import (
    render_external_channel_message,
)
from azents.engine.events.file_parts import RequestLocalModelFileResolver
from azents.engine.events.filters import (
    EventAutoCompactionFilter,
    EventCompactor,
    NativeRequestSizeGuard,
    PostLowerFilterPipeline,
)
from azents.engine.events.model_file_materializer import ModelFileMaterializer
from azents.engine.events.model_support_contract import (
    resolve_model_support_context,
    saved_builtin_tool_allowed,
)
from azents.engine.events.openai_responses import (
    OpenAIResponsesLowerer,
    OpenAIResponsesModelAdapter,
    OpenAIResponsesOutputNormalizer,
    OpenAIResponsesRequest,
    openai_responses_websocket_endpoint_eligible,
)
from azents.engine.events.output_parts import (
    enforce_tool_output_text_hard_cap,
    iter_output_parts,
)
from azents.engine.events.protocols import (
    ClientToolExecutor,
    ContentDeltaProjection,
    FunctionCallDeltaProjection,
    ManualCompactor,
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
from azents.engine.events.pydantic_ai_adapter import PydanticAIModelAdapter
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.pydantic_ai_output import PydanticAIOutputNormalizer
from azents.engine.events.pydantic_ai_types import PydanticAIRequest
from azents.engine.events.responses_continuation import ResponsesContinuationPlanner
from azents.engine.events.responses_lowering import resolve_openai_service_tier
from azents.engine.events.system_prompt import build_system_prompt
from azents.engine.events.tool_invocation import (
    ClientToolInvoker,
    PreparedClientToolInvocation,
    UnboundedClientToolResult,
)
from azents.engine.events.tools import (
    CappedClientToolExecutor,
    ToolCatalogClientToolInvoker,
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
    ExternalChannelMessagePayload,
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
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.model_factories import get_model_sdk_factories
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.model_stream import ModelStreamWatchdog, get_model_stream_watchdog
from azents.engine.run.builtin_tools import (
    ClientBuiltinToolImplementationUnavailableError,
    UnsupportedRequiredBuiltinToolError,
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
    BuiltinToolSpec,
    CheckStop,
    FunctionTool,
    FunctionToolError,
    PollMessages,
)
from azents.engine.tooling.tool_search import (
    DeferredToolSearchIndex,
    make_tool_search_tool,
    project_tool_catalog,
)
from azents.engine.tools.openai_image_generation import (
    OPENAI_IMAGE_DEFAULT_MODEL,
    OpenAIImageGenerationExecutor,
    openai_images_client_factory,
)
from azents.engine.tools.run_tool_to_file import (
    RUN_TOOL_TO_FILE_NAME,
    LateBoundClientToolInvoker,
    RunToolToFileToolkitProvider,
)
from azents.engine.tools.xai_image_generation import (
    XaiImageGenerationExecutor,
    XaiImagineClientFactory,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session_system_prompt_snapshot import (
    AgentSessionSystemPromptSnapshotRepository,
)
from azents.repos.chatgpt_oauth_runtime import ChatGPTOAuthRuntimeRepository
from azents.repos.compaction_operation import CompactionCommitContext
from azents.repos.engine_event_mutation import EngineEventMutationRepository
from azents.repos.engine_event_operation import EngineEventOperationRepository
from azents.repos.engine_execution_operation import EngineExecutionOperationRepository
from azents.repos.engine_input_projection import EngineInputProjectionRepository
from azents.repos.engine_model_input_operation import (
    EngineModelInputOperationRepository,
)
from azents.repos.engine_output_operation import (
    EngineOutputOperationRepository,
    EngineRunRepository,
)
from azents.repos.engine_run_finalization_operation import (
    EngineRunFinalizationOperationRepository,
)
from azents.repos.engine_tool_result_operation import (
    EngineToolResultOperationRepository,
)
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.deps import (
    get_llm_provider_integration_repository,
)
from azents.repos.model_file import ModelFileRepository
from azents.repos.model_file_pin import ModelFilePinRepository
from azents.repos.model_operation_completion import ModelOperationCompletionRepository
from azents.repos.provider_output_operation import ProviderOutputOperationRepository
from azents.repos.session_execution.ownership import OwnerBoundSessionManager
from azents.repos.terminal_finalization import TerminalRunFinalizationRepository
from azents.repos.toolkit_state.engine import ToolWorkingSetStore
from azents.repos.xai_oauth_runtime import XaiOAuthRuntimeRepository
from azents.services.artifact import ArtifactService
from azents.services.chatgpt_oauth.data import (
    ProviderRejected as ChatGPTProviderRejected,
)
from azents.services.chatgpt_oauth.data import (
    ProviderUnavailable as ChatGPTProviderUnavailable,
)
from azents.services.chatgpt_oauth.runtime import (
    refresh_runtime_tokens as refresh_chatgpt_runtime_tokens,
)
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService
from azents.services.model_metadata import ModelMetadataService
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
    sdk_factories: Annotated[ModelSDKFactories, Depends(get_model_sdk_factories)],
) -> SummaryModelCall:
    """Bind the process-owned watchdog to compaction model calls."""

    async def call_summary(
        *,
        provider: LLMProvider,
        provider_integration_id: str | None,
        model: str,
        credential_kwargs: dict[str, object],
        assembly_metadata: ModelAssemblyMetadata | None,
        system_prompt: str,
        user_prompt: str,
        conversation_text: str,
        max_output_tokens: int,
        session_id: str | None = None,
    ) -> str:
        return await summarize_text_with_model(
            sdk_factories=sdk_factories,
            watchdog=watchdog,
            provider=provider,
            provider_integration_id=provider_integration_id,
            model=model,
            credential_kwargs=credential_kwargs,
            assembly_metadata=assembly_metadata,
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
    provider_output_operation_repository: Annotated[
        ProviderOutputOperationRepository,
        Depends(ProviderOutputOperationRepository),
    ]
    integration_repository: Annotated[
        LLMProviderIntegrationRepository,
        Depends(get_llm_provider_integration_repository),
    ]
    metadata_service: Annotated[ModelMetadataService, Depends(ModelMetadataService)]
    sdk_factories: Annotated[ModelSDKFactories, Depends(get_model_sdk_factories)]
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
    run_repo: Annotated[EngineRunRepository, Depends(AgentRunRepository)]
    agent_session_repo: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    session_head_repo: Annotated[SessionHeadRepository, Depends(AgentSessionRepository)]
    transcript_repo: Annotated[TranscriptRepository, Depends(EventTranscriptRepository)]
    system_prompt_snapshot_repo: Annotated[
        AgentSessionSystemPromptSnapshotRepository,
        Depends(AgentSessionSystemPromptSnapshotRepository),
    ]
    model_file_pin_repo: Annotated[
        ModelFilePinRepository, Depends(ModelFilePinRepository)
    ]
    model_operation_completion_repository: Annotated[
        ModelOperationCompletionRepository, Depends(ModelOperationCompletionRepository)
    ]
    terminal_finalization_repository: Annotated[
        TerminalRunFinalizationRepository,
        Depends(TerminalRunFinalizationRepository),
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
            persistence_repository = XaiOAuthRuntimeRepository(
                integration_repository=self.integration_repository,
                session_manager=self.session_manager,
            )
            integration = await persistence_repository.load_integration(
                integration_id=integration_id
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
                persistence_repository=persistence_repository,
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
                            assert_never(unreachable)  # ty: ignore[type-assertion-failure] — Result's runtime error union is closed, but ty does not narrow this generic match to Never.
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

    def _openai_image_generation_tool(
        self, request: RunRequest, selection: BuiltinToolSpec
    ) -> FunctionTool:
        """Bind the selected OpenAI integration to a client image tool."""
        access_token = request.credential_kwargs.get("api_key")
        if not isinstance(access_token, str) or not access_token:
            raise ClientBuiltinToolImplementationUnavailableError(
                "OpenAI image generation requires an integration credential."
            )
        model_choice = decode_image_generation_model_config(selection.config)
        model_identifier = (
            model_choice.model_identifier
            if isinstance(model_choice, ExplicitImageGenerationModel)
            else OPENAI_IMAGE_DEFAULT_MODEL
        )
        integration_id = (
            request.inference_state.model_selection.llm_provider_integration_id
            if request.inference_state is not None
            else None
        )

        async def refresh_credential() -> None:
            if integration_id is None:
                raise FunctionToolError(
                    "ChatGPT OAuth reconnect is required for image generation."
                )
            persistence_repository = ChatGPTOAuthRuntimeRepository(
                integration_repository=self.integration_repository,
                session_manager=self.session_manager,
            )
            integration = await persistence_repository.load_integration(
                integration_id=integration_id
            )
            if (
                integration is None
                or integration.workspace_id != request.workspace_id
                or integration.provider != LLMProvider.CHATGPT_OAUTH
            ):
                raise FunctionToolError(
                    "ChatGPT OAuth reconnect is required for image generation."
                )
            refreshed = await refresh_chatgpt_runtime_tokens(
                integration=integration,
                persistence_repository=persistence_repository,
            )
            match refreshed:
                case Success(updated):
                    if not isinstance(updated.secrets, ChatGPTOAuthSecrets):
                        raise FunctionToolError(
                            "ChatGPT OAuth reconnect is required for image generation."
                        )
                    request.credential_kwargs["api_key"] = updated.secrets.access_token
                case Failure(error):
                    match error:
                        case ChatGPTProviderRejected():
                            message = (
                                "ChatGPT OAuth reconnect is required for "
                                "image generation."
                            )
                        case ChatGPTProviderUnavailable():
                            message = (
                                "ChatGPT OAuth is temporarily unavailable. "
                                "Try again later."
                            )
                        case _ as unreachable:
                            assert_never(unreachable)
                    raise FunctionToolError(message)

        def client_factory() -> AsyncOpenAI:
            config = openai_responses_client_config(
                provider=request.provider,
                credential_kwargs=request.credential_kwargs,
            )
            return openai_images_client_factory(config)()

        return OpenAIImageGenerationExecutor(
            model_identifier=model_identifier,
            client_factory=client_factory,
            refresh_credential=(
                refresh_credential
                if request.provider == LLMProvider.CHATGPT_OAUTH
                else None
            ),
        ).make_tool()

    async def save_error_message(
        self,
        session_id: str,
        content: str,
        *,
        owner_generation: int,
    ) -> Event:
        """Store Event system_error under the current Session owner generation."""
        owner_session_manager = OwnerBoundSessionManager(
            session_manager=self.session_manager,
            session_id=session_id,
            owner_generation=owner_generation,
        )
        return await self._event_operation_repository(
            owner_session_manager
        ).append_system_error(
            session_id=session_id,
            content=content,
        )

    async def compact(
        self, request: RunRequest, context: RunContext
    ) -> AsyncIterator[Emit]:
        """Run manual event compaction in append-only style."""
        compaction_request = request
        owner_session_manager = OwnerBoundSessionManager(
            session_manager=self.session_manager,
            session_id=request.session_id,
            owner_generation=context.owner_generation,
        )
        compactor = self.compactor.with_session_manager(owner_session_manager)
        yield ephemeral(CompactionStarted())
        transcript = await self._event_operation_repository(
            owner_session_manager
        ).prepare_compaction(session_id=request.session_id)

        hook_dispatcher = RuntimeHookDispatcher()
        hook_providers = _runtime_hook_provider_refs(request.toolkits)

        async def on_compaction_started() -> None:
            nonlocal compaction_request
            if context.prepare_compaction_request is not None:
                compaction_request = await context.prepare_compaction_request(
                    compaction_request
                )
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

        await compactor.compact(
            session_id=request.session_id,
            transcript=transcript,
            compaction_id=uuid7().hex,
            summarize=_event_summary_generator(
                lambda: compaction_request,
                summarize=self.summary_model_call,
            ),
            on_started=on_compaction_started,
            summary_context_window_tokens=(
                lambda: compaction_request.effective_max_input_tokens
            ),
            reason="manual_command",
            summary_enricher=_compaction_summary_enricher(
                request,
                dispatcher=hook_dispatcher,
                providers=hook_providers,
                run_id=context.run_id,
            ),
            commit_context=CompactionCommitContext(
                workspace_id=request.workspace_id,
                agent_id=request.agent_id,
                run_id=context.run_id,
                owner_generation=context.owner_generation,
                settle_model_operation=(context.model_operation_completion is not None),
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
        owner_session_manager = OwnerBoundSessionManager(
            session_manager=self.session_manager,
            session_id=request.session_id,
            owner_generation=context.owner_generation,
        )
        tool_working_set_store = self.tool_working_set_store.with_session_manager(
            owner_session_manager
        )
        compactor = self.compactor.with_session_manager(owner_session_manager)
        event_operation_repository = self._event_operation_repository(
            owner_session_manager
        )
        preparation = await event_operation_repository.prepare_run(
            session_id=request.session_id,
            run_id=context.run_id,
            user_messages=request.user_messages,
        )
        run_state = preparation.run_state
        for event in preparation.user_message_events:
            yield durable(event)
        provider = _provider_name(request.provider)
        model_file_resolver = RequestLocalModelFileResolver()
        model_file_materializer = ModelFileMaterializer(
            model_file_service=self.model_file_service,
            resolver=model_file_resolver,
            authority=context.resource_authority,
        )
        hook_dispatcher = RuntimeHookDispatcher()
        run_hook_providers = _runtime_hook_provider_refs(request.toolkits)
        emit_queue = _AsyncEventEmitQueue()
        compaction_live_state = _CompactionLiveState()

        async def prepare_model_call(
            *,
            transcript: Sequence[Event],
            model: str,
        ) -> PreparedModelCall[PydanticAIRequest | OpenAIResponsesRequest]:
            await owner_session_manager.assert_current()
            model_selection = (
                request.inference_state.model_selection
                if request.inference_state is not None
                else None
            )
            output_normalizer.pricing = await _capture_model_pricing(
                metadata_service=self.metadata_service,
                provider=request.provider,
                model_identifier=(
                    model_selection.model_identifier
                    if model_selection is not None
                    else model
                ),
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
                else PydanticAILowerer
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
                    workspace_id=request.workspace_id,
                    model=model,
                    run_id=context.run_id,
                    session_id=request.session_id,
                    run_index=run_state.run_index,
                    tool_search_enabled=request.tool_search_enabled,
                    resource_authority=context.resource_authority,
                    publish_event=context.publish_event,
                    check_stop=check_stop,
                    mailbox_activity_observer=context.mailbox_activity_observer,
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
                supported=[
                    tool.name
                    for tool in request.builtin_tools
                    if builtin_tool_configurable(
                        request.model_capabilities, tool=tool.name
                    )
                ],
            )
            client_builtin_tools: list[FunctionTool] = []
            for tool in resolved_builtin_tools.client_executed:
                if tool.name == "image_generation" and request.provider in {
                    LLMProvider.OPENAI,
                    LLMProvider.CHATGPT_OAUTH,
                }:
                    client_builtin_tools.append(
                        self._openai_image_generation_tool(request, tool)
                    )
                    continue
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

            run_tool_binding: LateBoundClientToolInvoker | None = None
            runtime_toolkit = next(
                (
                    binding.toolkit
                    for binding in catalog.active_toolkit_bindings
                    if isinstance(binding.toolkit, RunToolToFileToolkitProvider)
                ),
                None,
            )
            if runtime_toolkit is not None:
                candidate_binding = LateBoundClientToolInvoker()
                run_tool = runtime_toolkit.make_run_tool_to_file(candidate_binding)
                if run_tool is not None:
                    catalog = extend_prepared_tool_catalog_with_json_functions(
                        catalog,
                        [run_tool],
                    )
                    run_tool_binding = candidate_binding

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
                        store=tool_working_set_store,
                        agent_id=request.agent_id,
                        session_id=request.session_id,
                        activation_capacity=activation_capacity,
                    )
                    catalog = extend_prepared_tool_catalog_with_json_functions(
                        catalog,
                        [search_tool],
                    )

                working_set = await tool_working_set_store.load(
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
                        "supported_execution_options": [
                            option.value
                            for option in (
                                model_selection.supported_execution_options
                                if model_selection is not None
                                else []
                            )
                        ],
                        "enabled_execution_options": [
                            option.value for option in request.enabled_execution_options
                        ],
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
            if request.model_capabilities.semantic_contract is not None:
                builtin_context = resolve_model_support_context(
                    request.model_capabilities,
                    requested_effort=request.reasoning_effort,
                    function_tools=any(
                        catalog.wire_dialects[name] == "json_function"
                        for name in provider_visible_tool_names
                    ),
                )
                for tool in resolved_builtin_tools.client_executed:
                    # The saved row is projected for this provider's execution
                    # owner; hosted image denial cannot override a client row.
                    if not saved_builtin_tool_allowed(
                        request.model_capabilities,
                        tool=tool.name,
                        context=builtin_context,
                    ):
                        raise UnsupportedRequiredBuiltinToolError(
                            f"Required builtin tool is not supported: {tool.name}"
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
                temperature=request.temperature,
                max_output_tokens=request.max_output_tokens,
                top_p=request.top_p,
                top_k=request.top_k,
                stop=request.stop,
                reasoning_effort=request.reasoning_effort,
                supported_execution_options=(
                    model_selection.supported_execution_options
                    if model_selection is not None
                    else []
                ),
                enabled_execution_options=request.enabled_execution_options,
                hosted_tools=resolved_builtin_tools.provider_hosted,
                prompt_cache_scope=request.session_id,
                model_developer=request.model_developer,
                model_capabilities=request.model_capabilities,
                model_file_resolver=model_file_resolver,
                historical_plaintext_custom_supported=(
                    historical_plaintext_custom_supported
                ),
            )
            shared_tool_invoker: ClientToolInvoker = ToolCatalogClientToolInvoker(
                catalog
            )
            shared_tool_invoker = _OwnerBoundClientToolInvoker(
                inner=shared_tool_invoker,
                owner=owner_session_manager,
            )
            shared_tool_invoker = _HookedClientToolInvoker(
                inner=shared_tool_invoker,
                dispatcher=hook_dispatcher,
                providers=hook_providers,
                toolkit_namespaces={
                    name: entry.source.namespace
                    for name, entry in catalog.entries.items()
                    if entry.source.toolkit_config_id is not None
                },
                workspace_id=request.workspace_id,
                agent_id=request.agent_id,
                session_id=request.session_id,
                run_id=context.run_id,
            )
            if request.tool_search_enabled:
                shared_tool_invoker = _WorkingSetClientToolInvoker(
                    inner=shared_tool_invoker,
                    deferred_tool_names=deferred_tool_names,
                    store=tool_working_set_store,
                    agent_id=request.agent_id,
                    session_id=request.session_id,
                )
            visible_tool_names = frozenset(provider_visible_tool_names)
            tool_invoker: ClientToolInvoker = _PreparedToolAllowlistInvoker(
                inner=shared_tool_invoker,
                allowed_tool_names=visible_tool_names,
            )
            if run_tool_binding is not None:
                target_names = visible_tool_names - {RUN_TOOL_TO_FILE_NAME}
                run_tool_binding.bind(
                    invoker=_PreparedToolAllowlistInvoker(
                        inner=shared_tool_invoker,
                        allowed_tool_names=target_names,
                    ),
                    wire_dialects={
                        name: catalog.wire_dialects[name] for name in target_names
                    },
                )
            prepared_tool_executor: ClientToolExecutor = CappedClientToolExecutor(
                tool_invoker
            )

            async def on_turn_end(reason: TurnEndReason) -> None:
                await owner_session_manager.assert_current()
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
                if isinstance(native_request, PydanticAIRequest):
                    native_request = dataclasses.replace(
                        native_request,
                        assembly_metadata=(
                            ModelAssemblyMetadata.from_selection(model_selection)
                            if model_selection is not None
                            else request.model_assembly_metadata
                        ),
                    )
            except asyncio.CancelledError:
                await on_turn_end("cancelled")
                raise
            except Exception:
                await on_turn_end("error")
                raise
            requested_service_tier = (
                native_request.options.get("service_tier")
                if isinstance(native_request, OpenAIResponsesRequest)
                else native_request.settings.get("service_tier")
            )
            output_normalizer.service_tier = (
                requested_service_tier
                if isinstance(requested_service_tier, str)
                else None
            )
            return PreparedModelCall(
                native_request=native_request,
                inference_state=request.inference_state,
                system_prompt_analysis=system_prompt_result.analysis,
                tool_executor=prepared_tool_executor,
                enrich_client_tool_call=catalog.enrich_client_tool_call,
                on_turn_end=on_turn_end,
            )

        compaction_request = request

        async def on_auto_compaction_started() -> None:
            nonlocal compaction_request
            if context.prepare_compaction_request is not None:
                compaction_request = await context.prepare_compaction_request(
                    compaction_request
                )
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

        input_projection_repository = EngineInputProjectionRepository(
            exchange_file_repository=ExchangeFileRepository(),
            model_file_repository=ModelFileRepository(),
            transcript_repository=EventTranscriptRepository(),
        )
        auto_compaction_filter = EventAutoCompactionFilter(
            session_id=request.session_id,
            compactor=compactor,
            summarize=_event_summary_generator(
                lambda: compaction_request,
                summarize=self.summary_model_call,
            ),
            max_input_tokens=lambda: compaction_request.effective_max_input_tokens,
            auto_compaction_threshold_tokens=request.auto_compaction_threshold_tokens,
            compaction_id_factory=lambda: uuid7().hex,
            on_compaction_started=on_auto_compaction_started,
            summary_enricher=_compaction_summary_enricher(
                request,
                dispatcher=hook_dispatcher,
                providers=run_hook_providers,
                run_id=context.run_id,
            ),
            commit_context=CompactionCommitContext(
                workspace_id=request.workspace_id,
                agent_id=request.agent_id,
                run_id=context.run_id,
                owner_generation=context.owner_generation,
                settle_model_operation=(context.model_operation_completion is not None),
            ),
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
                client=self.sdk_factories.openai_responses(config=client_config),
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
                pricing=None,
                operation="sampling",
                integration=integration_id,
                requested_service_tier=resolve_openai_service_tier(
                    provider=request.provider,
                    supported=(
                        request.inference_state.model_selection.supported_execution_options
                        if request.inference_state is not None
                        else []
                    ),
                    enabled=request.enabled_execution_options,
                ),
            )
        else:
            model_adapter = PydanticAIModelAdapter(
                factory=self.sdk_factories.provider_model(
                    provider=request.provider,
                    credential_kwargs=request.credential_kwargs,
                )
            )
            output_normalizer = PydanticAIOutputNormalizer(
                provider=provider,
                model=request.model,
                pricing=None,
                operation="sampling",
                integration=integration_id,
            )

        generated_output_materializer = (
            ProviderOutputMaterializer(
                exchange_file_service=self.exchange_file_service,
                model_file_service=self.model_file_service,
                operation_repository=self.provider_output_operation_repository,
                authority=context.resource_authority,
                provider_name=provider,
            )
            if context.resource_authority is not None
            else None
        )
        event_mutation_repository = EngineEventMutationRepository(
            transcript_repository=self.transcript_repo
        )
        tool_result_operation_repository = EngineToolResultOperationRepository(
            session_manager=owner_session_manager,
            run_repository=self.run_repo,
            transcript_repository=self.transcript_repo,
        )
        execution = self.execution_factory(
            execution_operation_repository=EngineExecutionOperationRepository(
                session_manager=owner_session_manager,
                run_repository=self.run_repo,
                model_file_pin_repository=self.model_file_pin_repo,
            ),
            model_input_operation_repository=EngineModelInputOperationRepository(
                session_manager=owner_session_manager,
                run_repository=self.run_repo,
                transcript_repository=self.transcript_repo,
                session_head_repository=self.session_head_repo,
                tool_result_repository=tool_result_operation_repository,
                input_projection_repository=input_projection_repository,
            ),
            tool_result_operation_repository=tool_result_operation_repository,
            output_operation_repository=EngineOutputOperationRepository(
                session_manager=owner_session_manager,
                run_repository=self.run_repo,
                event_mutation_repository=event_mutation_repository,
                metadata_repository=self.provider_output_operation_repository,
                tool_result_repository=tool_result_operation_repository,
                system_prompt_repository=self.system_prompt_snapshot_repo,
            ),
            run_finalization_operation_repository=EngineRunFinalizationOperationRepository(
                session_manager=owner_session_manager,
                run_repository=self.run_repo,
                event_mutation_repository=event_mutation_repository,
                model_operation_repository=self.model_operation_completion_repository,
                terminal_finalization_repository=self.terminal_finalization_repository,
                model_file_pin_repository=self.model_file_pin_repo,
            ),
            model_operation_completion=context.model_operation_completion,
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
        )

        async def execute_run() -> AgentRunStatus:
            return await execution.run(
                AgentRunExecutionRequest(
                    run_id=context.run_id,
                    session_id=request.session_id,
                    owner_generation=context.owner_generation,
                    tool_admission_barrier=context.tool_admission_barrier,
                    turn_action_bridge_boundary=(context.turn_action_bridge_boundary),
                    run_index=run_state.run_index,
                    model=request.model,
                    max_turns=request.max_turns,
                ),
                check_stop=check_stop,
                poll_input_events=_make_input_poller(
                    poll_messages,
                    event_operation_repository=event_operation_repository,
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

    def _event_operation_repository(
        self,
        session_manager: SessionManager[AsyncSession],
    ) -> EngineEventOperationRepository:
        """Bind completed Event operations to one transaction authority."""
        return EngineEventOperationRepository(
            session_manager=session_manager,
            run_repository=self.run_repo,
            agent_session_repository=self.agent_session_repo,
            session_head_repository=self.session_head_repo,
            transcript_repository=self.transcript_repo,
        )


def _cancel_run_task(
    run_task: asyncio.Task[AgentRunStatus],
    cancel_args: tuple[object, ...] | None,
) -> None:
    """Pass adapter consumer cancellation reason to execution task."""
    if cancel_args and USER_STOP_CANCEL_MESSAGE in cancel_args:
        run_task.cancel(USER_STOP_CANCEL_MESSAGE)
        return
    run_task.cancel()


async def _capture_model_pricing(
    *,
    metadata_service: ModelMetadataService,
    provider: LLMProvider,
    model_identifier: str,
) -> CapturedModelPricing:
    """Capture validated price authority before one physical model dispatch.

    :param metadata_service: injected local validated-source reader
    :param provider: authoritative selected provider identity
    :param model_identifier: exact semantic model selection
    :returns: immutable source pricing, including explicit unavailable evidence
    """
    snapshot = await metadata_service.capture()
    metadata = metadata_service.lookup(
        snapshot,
        provider=provider,
        model_identifier=model_identifier,
    )
    return normalize_model_pricing(
        provider=provider,
        model_identifier=model_identifier,
        source_snapshot_id=snapshot.id if snapshot is not None else None,
        source_hash=snapshot.source_hash if snapshot is not None else None,
        source_model=metadata,
        request_timestamp=datetime.datetime.now(datetime.UTC),
    )


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


class _PreparedToolAllowlistInvoker:
    """Reject client tool calls outside one prepared provider projection."""

    def __init__(
        self,
        *,
        inner: ClientToolInvoker,
        allowed_tool_names: frozenset[str],
    ) -> None:
        self.inner = inner
        self.allowed_tool_names = allowed_tool_names

    def request_cancel(self, call: PreparedClientToolInvocation) -> None:
        """Forward cancellation only for tools admitted to this prepared call."""
        if call.name in self.allowed_tool_names:
            self.inner.request_cancel(call)

    async def invoke(
        self,
        call: PreparedClientToolInvocation,
    ) -> UnboundedClientToolResult:
        """Execute only tools whose schemas were sent to the provider."""
        if call.name not in self.allowed_tool_names:
            return UnboundedClientToolResult(
                call_id=call.call_id,
                name=call.name,
                wire_dialect=call.wire_dialect,
                status="failed",
                execution_succeeded=False,
                output=[OutputTextPart(text=f"Tool not found: {call.name}")],
                metadata={},
                pending_generated_files=(),
                terminal_run=False,
            )
        return await self.inner.invoke(call)


class _OwnerBoundClientToolInvoker:
    """Admit external tool work only after a database-only owner check."""

    def __init__(
        self, *, inner: ClientToolInvoker, owner: OwnerBoundSessionManager
    ) -> None:
        self.inner = inner
        self.owner = owner

    def request_cancel(self, call: PreparedClientToolInvocation) -> None:
        """Forward best-effort cancellation for an already admitted effect."""
        self.inner.request_cancel(call)

    async def invoke(
        self, call: PreparedClientToolInvocation
    ) -> UnboundedClientToolResult:
        """Release the authority transaction before executing the handler."""
        await self.owner.assert_current()
        return await self.inner.invoke(call)


class _WorkingSetClientToolInvoker:
    """Refresh deferred-tool recency before every admitted invocation."""

    def __init__(
        self,
        *,
        inner: ClientToolInvoker,
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

    def request_cancel(self, call: PreparedClientToolInvocation) -> None:
        """Forward running inner tool cancellation request."""
        self.inner.request_cancel(call)

    async def invoke(
        self,
        call: PreparedClientToolInvocation,
    ) -> UnboundedClientToolResult:
        """Touch deferred recency before hooks or handler execution."""
        if call.name in self.deferred_tool_names:
            await self.store.touch(self.agent_id, self.session_id, call.name)
        return await self.inner.invoke(call)


class _HookedClientToolInvoker:
    """Apply runtime hook dispatch to Event tool executor."""

    def __init__(
        self,
        *,
        inner: ClientToolInvoker,
        dispatcher: RuntimeHookDispatcher,
        providers: Sequence[RuntimeHookProviderRef],
        toolkit_namespaces: Mapping[str, str],
        workspace_id: str,
        agent_id: str,
        session_id: str,
        run_id: str,
    ) -> None:
        self.inner = inner
        self.dispatcher = dispatcher
        self._providers = list(providers)
        self._toolkit_namespaces = dict(toolkit_namespaces)
        self._workspace_id = workspace_id
        self._agent_id = agent_id
        self._session_id = session_id
        self._run_id = run_id

    def request_cancel(self, call: PreparedClientToolInvocation) -> None:
        """Forward running inner tool cancellation request."""
        self.inner.request_cancel(call)

    async def invoke(
        self,
        call: PreparedClientToolInvocation,
    ) -> UnboundedClientToolResult:
        """Run tool after applying before/after tool hooks."""
        toolkit_slug = self._toolkit_namespaces.get(call.name, "")
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
            return UnboundedClientToolResult(
                call_id=call.call_id,
                name=call.name,
                wire_dialect=call.wire_dialect,
                status="failed",
                execution_succeeded=False,
                output=[OutputTextPart(text=before.message)],
                metadata={},
                pending_generated_files=(),
                terminal_run=False,
            )

        result = await self.inner.invoke(call)
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
            return dataclasses.replace(
                result,
                status="completed",
                output=[OutputTextPart(text=after.output_text)],
            )
        return result


def _tool_result_text(result: UnboundedClientToolResult) -> str | None:
    """Join the ordinary capped Tool output text observed by hooks."""
    texts = [
        part.text
        for part in iter_output_parts(enforce_tool_output_text_hard_cap(result.output))
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
    event_operation_repository: EngineEventOperationRepository,
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
                suppress_parent_result=result.suppress_parent_result,
            )
        events = await event_operation_repository.append_user_messages(
            session_id=session_id,
            user_messages=result.user_messages,
        )
        return InputPollResult(
            events=events,
            context_invalidated=result.context_invalidated,
            complete_run=result.complete_run,
            suppress_parent_result=result.suppress_parent_result,
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
    request_provider: Callable[[], RunRequest],
    *,
    summarize: SummaryModelCall,
) -> SummaryGenerator:
    """Create an event summary generator bound to the latest compaction request."""

    async def generate(
        events: Sequence[Event],
        summary_budget: CompactionSummaryBudget,
    ) -> str:
        request = request_provider()
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
            assembly_metadata=(
                request.compaction_assembly_metadata
                if request.compaction_provider is not None
                else request.model_assembly_metadata
            ),
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
        case ExternalChannelMessagePayload(prompt_role="invocation") as payload:
            return render_external_channel_message(payload)
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
