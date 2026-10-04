"""Agent run resolve tests."""

import dataclasses
import datetime
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import ClassVar, Literal
from unittest.mock import AsyncMock, Mock

import pytest
from azcommon.result import Failure, Success
from cryptography.fernet import Fernet
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import (
    BuiltinToolConfig,
    ModelParameters,
    SelectableModelSettings,
)
from azents.core.credentials import ApiKeySecrets
from azents.core.crypto import CredentialCipher
from azents.core.engine_tool_state import (
    AgentsAppendixDedupeState,
    ClaudeRulesAppendixDedupeState,
)
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentType,
    ExchangeFileOrigin,
    ExchangeFileProvenanceKind,
    ExchangeFileStatus,
    ExternalChannelResponseMode,
    LLMProvider,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_capability_contract import (
    ModelCapabilityFeature,
    ModelFeatureCondition,
    ModelRequestConstraints,
)
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_capability_projection import project_capabilities
from azents.core.model_catalog_source import CatalogFact
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.core.runtime_capabilities import RuntimeCapabilityResolver
from azents.core.tools import (
    ResolveContext,
    Toolkit,
    ToolkitContext,
    ToolkitExecutionMode,
    ToolkitProvider,
    TurnContext,
)
from azents.engine.events.openai_responses import OpenAIResponsesLowerer
from azents.engine.run.contracts import ToolkitBinding
from azents.engine.run.input import InputMessage, InvalidModelParameters, InvokeInput
from azents.engine.run.types import BuiltinToolSpec
from azents.engine.tools.builtin import BuiltinToolkitProvider
from azents.engine.tools.claude_rules import ClaudeRulesToolkitProvider
from azents.engine.tools.dynamic_worktree import (
    DynamicWorktreeToolkit,
    DynamicWorktreeToolkitProvider,
)
from azents.engine.tools.goal import GoalStateStore, GoalToolkitProvider
from azents.engine.tools.runtime_web import RuntimeWebToolkit, RuntimeWebToolkitProvider
from azents.engine.tools.scheduled import ScheduledToolkit, ScheduledToolkitProvider
from azents.engine.tools.subagent import SubagentToolkitProvider
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.engine_resolve import (
    get_engine_resolve_repositories,
)
from azents.repos.engine_tool_repositories import get_engine_tool_repositories
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.memory import MemoryRepository
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.data import (
    EffectiveToolkitConfig,
    EffectiveToolkitNamespaceMissing,
    EffectiveToolkitSource,
    ToolkitConfig,
)
from azents.runtime.types import RuntimeDomainConfig
from azents.services.engine_runtime_tokens import EngineRuntimeTokenResolver
from azents.services.historical_memory.context_snapshot import (
    MemoryContextSnapshotService,
)
from azents.services.image_generation_catalog import (
    ImageGenerationRuntimeConfigurationError,
)
from azents.services.oauth_runtime_clients import (
    create_runtime_oauth_client_factories,
)
from azents.services.runtime_web.service import RuntimeWebService
from azents.testing.model_metadata import make_test_model_metadata_service
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_options,
)
from azents.testing.types import require_instance

from . import resolve as resolve_module
from .resolve import (
    ExecutionOptionUnsupported,
    ModelTargetNotFound,
    ReasoningEffortUnsupported,
    resolve_agent_tools,
    resolve_invoke_input,
    resolve_invoke_input_with_profile,
    resolve_invoke_input_with_resolved_profile,
)

_NOW = datetime.datetime.now(datetime.timezone.utc)


def test_attachment_preview_does_not_advertise_withheld_resource_tools() -> None:
    """Team attachment metadata states the current Runtime content boundary."""
    file = ExchangeFile(
        id="file-1",
        workspace_id="ws-1",
        agent_id="agent-1",
        origin_type=ExchangeFileOrigin.UPLOAD,
        status=ExchangeFileStatus.AVAILABLE,
        object_key="ws-1/file-1",
        filename="notes.txt",
        media_type="text/plain",
        size_bytes=12,
        sha256="0" * 64,
        provenance_kind=ExchangeFileProvenanceKind.HUMAN,
        source_user_id="requester-1",
        source_agent_id=None,
        source_run_id=None,
        source_tool_name=None,
        source_provider=None,
        source_exchange_file_id=None,
        retention_root_session_id="session-1",
        retention_bound_at=_NOW,
        expires_at=_NOW + datetime.timedelta(hours=1),
        created_at=_NOW,
    )

    preview = resolve_module._attachment_text_preview(
        file,
        availability="available",
    )

    assert preview is not None
    assert "unavailable to Runtime tools in this run" in preview
    assert "import_file" not in preview
    assert "present_file" not in preview


def _session_manager_for(
    session: AsyncSession,
) -> SessionManager[AsyncSession]:
    """Return a session manager yielding one test session."""

    @asynccontextmanager
    async def manager() -> AsyncGenerator[AsyncSession, None]:
        yield session

    return manager


def _make_scheduled_provider() -> ScheduledToolkitProvider:
    """Create a provider whose collaborators are not exercised during resolution."""
    return ScheduledToolkitProvider(
        operations=AsyncMock(),
        terminal_service=AsyncMock(),
        channel_service=AsyncMock(),
        file_transfer_service=AsyncMock(),
    )


def _make_agent(
    *,
    reasoning_supported: bool = False,
    effort_levels: list[ModelReasoningEffort] | None = None,
    tool_search_enabled: bool = False,
    fast_supported: bool = False,
) -> Agent:
    """Create Agent for tests."""
    selection = make_test_model_selection(integration_id="integ-1")
    selection.normalized_capabilities.reasoning.supported = reasoning_supported
    selection.normalized_capabilities.reasoning.effort_levels = (
        [] if effort_levels is None else effort_levels
    )
    selection.supported_execution_options = (
        [ModelExecutionOptionId.FAST] if fast_supported else []
    )
    return Agent(
        id="agent-1",
        workspace_id="ws-1",
        name="agent",
        description=None,
        model_selection=selection,
        lightweight_model_selection=selection,
        selectable_model_options=make_test_selectable_model_options(selection),
        main_model_label="default",
        lightweight_model_label="default",
        model_parameters=None,
        system_prompt="You are helpful.",
        enabled=True,
        external_channel_default_response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
        lifecycle_status=AgentLifecycleStatus.ACTIVE,
        type=AgentType.PUBLIC,
        runtime_profile_id=None,
        runtime_profile_selection_version=1,
        runtime_capability=AgentRuntimeCapability.MANAGED,
        runtime_capability_version=1,
        terminal_enabled=True,
        memory_enabled=True,
        tool_search_enabled=tool_search_enabled,
        max_turns=None,
        auto_archive_ttl_days=30,
        avatar=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_integration() -> LLMProviderIntegrationWithSecrets:
    """Create integration for tests."""
    return LLMProviderIntegrationWithSecrets(
        id="integ-1",
        workspace_id="ws-1",
        provider=LLMProvider.OPENAI,
        name="OpenAI",
        secrets=ApiKeySecrets(api_key="sk-test"),
        config=None,
        enabled=True,
        created_at=_NOW,
        updated_at=_NOW,
        catalog_configuration_version=1,
    )


def _make_image_generation_catalog_service() -> AsyncMock:
    """Create an image catalog service that accepts the selected settings."""
    service = AsyncMock()
    service.validate_runtime.return_value = None
    return service


class _FakeClaudeRulesAppendixDedupeStateStore:
    """Claude rules appendix dedupe state store for resolve tests."""

    async def load_appendix_dedupe(
        self, agent_id: str, session_id: str
    ) -> ClaudeRulesAppendixDedupeState:
        """Return empty dedupe state."""
        del agent_id, session_id
        return ClaudeRulesAppendixDedupeState()

    async def add_appendix_dedupe_paths(
        self,
        agent_id: str,
        session_id: str,
        appended_paths: Sequence[str],
    ) -> None:
        """Ignore dedupe updates."""
        del agent_id, session_id, appended_paths

    async def clear_appendix_dedupe(
        self,
        agent_id: str,
        session_id: str,
    ) -> None:
        """Ignore dedupe clear."""
        del agent_id, session_id


class _FakeAgentsAppendixDedupeStateStore:
    """AGENTS.md appendix dedupe state store for resolve tests."""

    async def load_appendix_dedupe(
        self, agent_id: str, session_id: str
    ) -> AgentsAppendixDedupeState:
        """Return empty AGENTS.md dedupe state."""
        del agent_id, session_id
        return AgentsAppendixDedupeState()

    async def replace_appendix_dedupe(
        self,
        agent_id: str,
        session_id: str,
        appended_paths: Sequence[str],
    ) -> None:
        """Ignore dedupe updates."""
        del agent_id, session_id, appended_paths


class _TestToolkitConfig(BaseModel):
    """Minimal registered Toolkit config for resolution failure tests."""

    value: str


class _FailingToolkitProvider(ToolkitProvider[_TestToolkitConfig]):
    """Registered Toolkit provider that raises the configured exception."""

    slug: ClassVar[str] = "test"
    name: ClassVar[str] = "Test"
    description: ClassVar[str] = "Test Toolkit"
    system_prompt: ClassVar[str] = ""
    config_model: ClassVar[type[BaseModel]] = _TestToolkitConfig

    def __init__(self, exception: Exception) -> None:
        self.exception = exception

    async def resolve(
        self,
        config: _TestToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[_TestToolkitConfig]:
        """Raise the configured resolution failure."""
        del config, context
        raise self.exception


class _SuccessfulToolkitProvider(ToolkitProvider[_TestToolkitConfig]):
    """Registered Toolkit provider that resolves a minimal Toolkit."""

    slug: ClassVar[str] = "test"
    name: ClassVar[str] = "Test"
    description: ClassVar[str] = "Test Toolkit"
    system_prompt: ClassVar[str] = ""
    config_model: ClassVar[type[BaseModel]] = _TestToolkitConfig

    async def resolve(
        self,
        config: _TestToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[_TestToolkitConfig]:
        """Return a resolved Toolkit instance."""
        del config, context
        return Toolkit()


def _make_toolkit_context() -> ToolkitContext:
    """Create ToolkitContext for resolve_agent_tools tests."""
    return ToolkitContext(
        session_id="session-1",
        workspace_id="ws-1",
        agent_id="agent-1",
        run_id="run-1",
        publish_event=AsyncMock(),
    )


def _runtime_capability_resolver(
    *,
    enabled: bool,
) -> RuntimeCapabilityResolver:
    """Create an explicit Runtime capability snapshot for Toolkit tests."""
    return RuntimeCapabilityResolver.from_agent(
        state=(
            AgentRuntimeCapability.MANAGED if enabled else AgentRuntimeCapability.NONE
        ),
        version=1,
    )


def _empty_toolkit_repository() -> AsyncMock:
    """Create a Toolkit repository without effective persisted Toolkits."""
    repository = AsyncMock()
    repository.list_effective_for_agent.return_value = []
    return repository


def test_auto_toolkit_revision_changes_with_canonical_scope() -> None:
    """Auto-bound Toolkits replace retained instances after scope changes."""
    config = _TestToolkitConfig(value="same")
    context = _make_toolkit_context()

    initial = resolve_module._auto_toolkit_source_revision(
        slug="skill",
        config=config,
        execution_mode=ToolkitExecutionMode.ROOT,
        context=context,
    )
    changed_workspace = resolve_module._auto_toolkit_source_revision(
        slug="skill",
        config=config,
        execution_mode=ToolkitExecutionMode.ROOT,
        context=dataclasses.replace(context, workspace_id="ws-2"),
    )
    changed_session = resolve_module._auto_toolkit_source_revision(
        slug="skill",
        config=config,
        execution_mode=ToolkitExecutionMode.ROOT,
        context=dataclasses.replace(context, session_id="session-2"),
    )

    assert initial != changed_workspace
    assert initial != changed_session


async def _resolve_failing_registered_toolkit(
    provider: ToolkitProvider[_TestToolkitConfig],
    *,
    toolkit_config: dict[str, object] | None = None,
    always_expose_tools: bool = False,
) -> list[ToolkitBinding]:
    """Resolve one registered Toolkit using the supplied provider."""
    toolkit_repository = AsyncMock()
    toolkit_repository.list_effective_for_agent.return_value = [
        EffectiveToolkitConfig(
            toolkit=ToolkitConfig(
                id="toolkit-1",
                workspace_id="ws-1",
                owner_agent_id=None,
                toolkit_type="test",
                slug="test",
                name="Test",
                description=None,
                config={"value": "valid"} if toolkit_config is None else toolkit_config,
                prompt=None,
                credentials=None,
                enabled=True,
                always_expose_tools=always_expose_tools,
                revision=1,
                created_at=_NOW,
                updated_at=_NOW,
            ),
            source=EffectiveToolkitSource.SHARED_ATTACHMENT,
            agent_toolkit_id="agent-toolkit-1",
            namespace="test_2",
        )
    ]
    return await resolve_agent_tools(
        "agent-1",
        _make_toolkit_context(),
        execution_mode=ToolkitExecutionMode.ROOT,
        toolkit_registry={"test": provider},
        web_url="https://example.test",
        oauth_secret_key="secret",
        mcp_proxy_url=None,
        runtime_domain_config=RuntimeDomainConfig(
            allowed_domains=(),
            denied_domains=(),
        ),
        memory_enabled=False,
        runtime_capability_resolver=_runtime_capability_resolver(enabled=False),
        repositories=get_engine_resolve_repositories(
            session_manager=_session_manager_for(AsyncMock(spec=AsyncSession)),
            agent_repository=AgentRepository(),
            integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
            toolkit_repository=toolkit_repository,
        ),
        workspace_handle=None,
    )


async def test_registered_toolkit_binding_captures_direct_exposure_policy() -> None:
    """Carry the persisted ToolkitConfig policy into the immutable binding."""
    bindings = await _resolve_failing_registered_toolkit(
        _SuccessfulToolkitProvider(),
        always_expose_tools=True,
    )

    assert len(bindings) == 1
    assert bindings[0].always_expose_tools is True
    assert bindings[0].slug == "test_2"
    assert bindings[0].base_slug == "test"
    assert bindings[0].toolkit.display_name == "Test"


async def test_registered_toolkit_missing_namespace_fails_before_resolution() -> None:
    """Fail missing Foundation namespace authority before provider resolution."""
    conflict = EffectiveToolkitNamespaceMissing(
        agent_id="agent-1",
        toolkit_id="toolkit-1",
    )
    toolkit_repository = AsyncMock()
    toolkit_repository.list_effective_for_agent.side_effect = conflict
    provider = AsyncMock()

    with pytest.raises(EffectiveToolkitNamespaceMissing) as exc_info:
        await resolve_agent_tools(
            "agent-1",
            _make_toolkit_context(),
            execution_mode=ToolkitExecutionMode.ROOT,
            toolkit_registry={"test": provider},
            web_url="https://example.test",
            oauth_secret_key="secret",
            mcp_proxy_url=None,
            runtime_domain_config=RuntimeDomainConfig(
                allowed_domains=(),
                denied_domains=(),
            ),
            memory_enabled=False,
            runtime_capability_resolver=_runtime_capability_resolver(enabled=False),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(AsyncMock(spec=AsyncSession)),
                agent_repository=AgentRepository(),
                integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
                toolkit_repository=toolkit_repository,
            ),
            workspace_handle=None,
        )

    assert exc_info.value is conflict
    provider.resolve.assert_not_awaited()


def _make_turn_context() -> TurnContext:
    """Create TurnContext for resolved Toolkit tests."""
    return TurnContext(
        workspace_id="ws-1",
        model="gpt-4o",
        run_id="run-1",
        publish_event=AsyncMock(),
        session_id="session-1",
    )


def _make_builtin_provider() -> BuiltinToolkitProvider:
    """Create BuiltinToolkitProvider for resolve_agent_tools tests."""
    session = AsyncMock(spec=AsyncSession)
    session.get = AsyncMock(return_value=None)
    memory = AsyncMock(spec=MemoryRepository)
    memory.list_summaries.return_value = []
    runtimes = AsyncMock(spec=AgentRuntimeRepository)
    runtimes.get_by_agent_id.return_value = None
    sessions = AsyncMock(spec=AgentSessionRepository)
    sessions.get_by_id.return_value = None
    projects = AsyncMock(spec=SessionWorkspaceProjectRepository)
    snapshots = Mock(spec=MemoryContextSnapshotService)
    snapshots.with_owner.return_value = snapshots
    snapshots.prompt_for_turn.return_value = ""
    snapshots.refresh_snapshot.return_value = False
    return BuiltinToolkitProvider(
        exchange_file_service=AsyncMock(),
        artifact_service=AsyncMock(),
        model_file_service=AsyncMock(),
        vfs_projection_service=None,
        vfs_read_router=AsyncMock(),
        agents_store=_FakeAgentsAppendixDedupeStateStore(),
        repositories=get_engine_tool_repositories(
            session_manager=_session_manager_for(session),
            cipher=CredentialCipher(Fernet.generate_key().decode()),
            memory_repository=require_instance(memory, MemoryRepository),
            agent_runtime_repository=require_instance(runtimes, AgentRuntimeRepository),
            agent_session_repository=require_instance(sessions, AgentSessionRepository),
            runtime_profile_repository=RuntimeProfileRepository(),
            project_repository=require_instance(
                projects, SessionWorkspaceProjectRepository
            ),
        ),
        memory_context_snapshot_service=require_instance(
            snapshots, MemoryContextSnapshotService
        ),
        agent_runtime_service=AsyncMock(),
        runner_operations=AsyncMock(),
        session_working_folder_binding_service=AsyncMock(),
        server_to_runtime_transfer_service=AsyncMock(),
        runtime_image_read_service=None,
        runtime_to_server_publication_service=AsyncMock(),
        runtime_to_provider_delivery_service=AsyncMock(),
        import_file_staging_configuration=AsyncMock(),
    )


def _make_subagent_provider() -> SubagentToolkitProvider:
    """Create SubagentToolkitProvider for resolve_agent_tools tests."""
    operations = AsyncMock()
    operations.get_agent.return_value = _make_agent()
    return SubagentToolkitProvider(
        operations=operations,
        broker=AsyncMock(),
    )


def _make_dynamic_worktree_provider() -> DynamicWorktreeToolkitProvider:
    """Create DynamicWorktreeToolkitProvider for resolution tests."""
    return DynamicWorktreeToolkitProvider(
        service=AsyncMock(),
        broker=AsyncMock(),
    )


class TestResolveInvokeInput:
    """resolve_invoke_input tests."""

    @pytest.mark.parametrize("builtin", ["web_search", "image_generation"])
    async def test_conditional_builtin_setting_reaches_existing_catalog_preparation(
        self,
        builtin: Literal["web_search", "image_generation"],
    ) -> None:
        agent = _make_agent(
            reasoning_supported=True, effort_levels=[ModelReasoningEffort.HIGH]
        )
        caps = project_capabilities(
            provider=LLMProvider.OPENAI,
            exact_model="gpt-4o",
            source_model=None,
            model_developer=None,
            evidence=ProviderCapabilityEvidence(
                reasoning=CatalogFact(state="value", value=True),
                reasoning_efforts=CatalogFact(
                    state="value", value=(ModelReasoningEffort.HIGH,)
                ),
            ),
        )
        caps.built_in_tools.supported = [builtin]
        caps.request_constraints = ModelRequestConstraints(
            feature_conditions=(
                ModelFeatureCondition(
                    feature=ModelCapabilityFeature.IMAGE_GENERATION
                    if builtin == "image_generation"
                    else ModelCapabilityFeature.WEB_SEARCH,
                    reasoning_efforts=("none",),
                    function_tools=None,
                ),
            )
        )
        agent.model_parameters = ModelParameters(
            reasoning_effort=ModelReasoningEffort.HIGH
        )
        agent.model_selection.normalized_capabilities = caps
        for option in agent.selectable_model_options:
            for candidate in option.candidates:
                candidate.model_selection.normalized_capabilities = caps
                candidate.settings.builtin_tools = [
                    BuiltinToolConfig(name=builtin, config={})
                ]
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = agent
        integration_repository = AsyncMock()
        integration_repository.get_by_id_with_secrets.return_value = _make_integration()
        result = await resolve_invoke_input(
            InvokeInput(agent_id="agent-1", session_id="session-1", messages=[]),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=(
                image_catalog_service := _make_image_generation_catalog_service()
            ),
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(AsyncMock(spec=AsyncSession)),
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )
        assert isinstance(result, Success)
        assert result.value.reasoning_effort == ModelReasoningEffort.HIGH
        image_catalog_service.validate_runtime.assert_awaited_once()
        catalog_args = image_catalog_service.validate_runtime.call_args.kwargs
        assert catalog_args["image_generation_supported"] is (
            builtin == "image_generation"
        )
        assert catalog_args["integration_enabled"] is True
        assert catalog_args["settings"].builtin_tools == [
            BuiltinToolConfig(name=builtin, config={})
        ]
        if builtin == "image_generation":
            # EngineAdapter's actual SDK-boundary test covers the subsequent
            # client-owned dispatch rejection without routing it as hosted.
            return
        lowerer = OpenAIResponsesLowerer(
            top_k=None,
            provider=LLMProvider.OPENAI,
            model=result.value.model,
            credential_kwargs={},
            model_capabilities=caps,
            supported_execution_options=[],
            enabled_execution_options=[],
            reasoning_effort=result.value.reasoning_effort,
            tools=None,
            hosted_tools=[BuiltinToolSpec(name="web_search", config={})],
        )
        with pytest.raises(ValueError, match="Required builtin tool is not supported"):
            lowerer.lower([], native_replay_context=None, model=result.value.model)

    async def test_v2_agent_effort_is_rejected_instead_of_silently_omitted(
        self,
    ) -> None:
        agent = _make_agent()
        caps = project_capabilities(
            provider=LLMProvider.OPENAI,
            exact_model="gpt-4o",
            source_model=None,
            model_developer=None,
            evidence=ProviderCapabilityEvidence(
                reasoning=CatalogFact(state="value", value=True),
                reasoning_efforts=CatalogFact(state="value", value=()),
            ),
        )
        agent.model_parameters = ModelParameters(
            reasoning_effort=ModelReasoningEffort.HIGH
        )
        agent.model_selection.normalized_capabilities = caps
        for option in agent.selectable_model_options:
            for candidate in option.candidates:
                candidate.model_selection.normalized_capabilities = caps
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = agent
        integration_repository = AsyncMock()
        integration_repository.get_by_id_with_secrets.return_value = _make_integration()
        result = await resolve_invoke_input(
            InvokeInput(agent_id="agent-1", session_id="session-1", messages=[]),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=_make_image_generation_catalog_service(),
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(AsyncMock(spec=AsyncSession)),
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )
        assert result == Failure(
            ReasoningEffortUnsupported(
                model_target_label="default", reasoning_effort=ModelReasoningEffort.HIGH
            )
        )
        assert agent.model_parameters.reasoning_effort is ModelReasoningEffort.HIGH

    async def test_v2_sampling_condition_is_checked_during_profile_preparation(
        self,
    ) -> None:
        agent = _make_agent(
            reasoning_supported=True, effort_levels=[ModelReasoningEffort.HIGH]
        )
        caps = project_capabilities(
            provider=LLMProvider.OPENAI,
            exact_model="gpt-4o",
            source_model=None,
            model_developer=None,
            evidence=ProviderCapabilityEvidence(
                reasoning=CatalogFact(state="value", value=True),
                reasoning_efforts=CatalogFact(
                    state="value", value=(ModelReasoningEffort.HIGH,)
                ),
            ),
        )
        caps.parameters.temperature = True
        caps.request_constraints = ModelRequestConstraints(
            feature_conditions=(
                ModelFeatureCondition(
                    feature=ModelCapabilityFeature.TEMPERATURE,
                    reasoning_efforts=("none",),
                    function_tools=None,
                ),
            )
        )
        agent.model_parameters = ModelParameters(temperature=0.3)
        agent.model_selection.normalized_capabilities = caps
        for option in agent.selectable_model_options:
            for candidate in option.candidates:
                candidate.model_selection.normalized_capabilities = caps
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = agent
        integration_repository = AsyncMock()
        integration_repository.get_by_id_with_secrets.return_value = _make_integration()
        result = await resolve_invoke_input_with_profile(
            InvokeInput(agent_id="agent-1", session_id="session-1", messages=[]),
            context_source=None,
            requested_profile=RequestedInferenceProfile(
                model_target_label="default",
                reasoning_effort=ModelReasoningEffort.HIGH,
                enabled_execution_options=[],
            ),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=_make_image_generation_catalog_service(),
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(AsyncMock(spec=AsyncSession)),
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )
        assert result == Failure(
            InvalidModelParameters(
                agent_id="agent-1",
                errors=[
                    "The selected request does not satisfy temperature conditions."
                ],
            )
        )

    async def test_resolves_run_request_from_agent_snapshot(self) -> None:
        """Build RunRequest from Agent snapshot and integration."""
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = _make_agent(tool_search_enabled=True)
        integration_repository = AsyncMock()
        integration_repository.get_by_id_with_secrets.return_value = _make_integration()

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            yield AsyncMock(spec=AsyncSession)

        result = await resolve_invoke_input(
            InvokeInput(
                agent_id="agent-1",
                session_id="session-1",
                messages=[
                    InputMessage(
                        text="hello",
                        headers=[],
                        metadata={},
                        attachments=[],
                    )
                ],
            ),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=_make_image_generation_catalog_service(),
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=session_manager,
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )

        assert isinstance(result, Success)
        run_request = result.value
        assert run_request.model == "gpt-4o"
        assert run_request.tool_search_enabled is True

    async def test_validates_maintained_default_before_provider_io(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Validate default image intent before refreshing provider credentials."""
        agent = _make_agent()
        selection = agent.selectable_model_options[0].candidates[0].model_selection
        selection.normalized_capabilities.built_in_tools.supported = [
            "image_generation"
        ]
        settings = SelectableModelSettings(
            context_window_tokens=None,
            max_output_tokens=None,
            builtin_tools=[BuiltinToolConfig(name="image_generation", config={})],
        )
        agent.selectable_model_options[0].candidates[0].settings = settings
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = agent
        integration_repository = AsyncMock()
        integration_repository.get_by_id_with_secrets.return_value = _make_integration()
        image_service = _make_image_generation_catalog_service()
        ensure_tokens = AsyncMock(return_value=Success(_make_integration()))
        monkeypatch.setattr(
            EngineRuntimeTokenResolver,
            "ensure",
            ensure_tokens,
        )

        result = await resolve_invoke_input(
            InvokeInput(
                agent_id="agent-1",
                session_id="session-1",
                messages=[],
            ),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=image_service,
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(AsyncMock(spec=AsyncSession)),
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )

        assert isinstance(result, Success)
        image_service.validate_runtime.assert_awaited_once_with(
            integration_id="integ-1",
            workspace_id="ws-1",
            provider=LLMProvider.OPENAI,
            integration_enabled=True,
            image_generation_supported=True,
            settings=settings,
        )
        ensure_tokens.assert_awaited()

    async def test_rejects_image_tool_when_conversation_capability_is_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pass current conversation capability into pre-dispatch validation."""
        agent = _make_agent()
        selection = agent.selectable_model_options[0].candidates[0].model_selection
        selection.normalized_capabilities.built_in_tools.supported = []
        settings = SelectableModelSettings(
            context_window_tokens=None,
            max_output_tokens=None,
            builtin_tools=[BuiltinToolConfig(name="image_generation", config={})],
        )
        agent.selectable_model_options[0].candidates[0].settings = settings
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = agent
        integration_repository = AsyncMock()
        integration_repository.get_by_id_with_secrets.return_value = _make_integration()
        error = ImageGenerationRuntimeConfigurationError(
            reason="model_unavailable",
            integration_id="integ-1",
            model_identifier=None,
        )
        image_service = _make_image_generation_catalog_service()
        image_service.validate_runtime.return_value = error
        ensure_tokens = AsyncMock()
        monkeypatch.setattr(
            EngineRuntimeTokenResolver,
            "ensure",
            ensure_tokens,
        )

        result = await resolve_invoke_input(
            InvokeInput(
                agent_id="agent-1",
                session_id="session-1",
                messages=[],
            ),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=image_service,
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(AsyncMock(spec=AsyncSession)),
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )

        assert result == Failure(error)
        image_service.validate_runtime.assert_awaited_once_with(
            integration_id="integ-1",
            workspace_id="ws-1",
            provider=LLMProvider.OPENAI,
            integration_enabled=True,
            image_generation_supported=False,
            settings=settings,
        )
        ensure_tokens.assert_not_awaited()

    async def test_rejects_invalid_image_pin_before_provider_io(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Reject stale explicit image intent before provider credential I/O."""
        agent = _make_agent()
        selection = agent.selectable_model_options[0].candidates[0].model_selection
        selection.normalized_capabilities.built_in_tools.supported = [
            "image_generation"
        ]
        settings = SelectableModelSettings(
            context_window_tokens=None,
            max_output_tokens=None,
            builtin_tools=[
                BuiltinToolConfig(
                    name="image_generation",
                    config={"model": "gpt-image-2.5-flare"},
                )
            ],
        )
        agent.selectable_model_options[0].candidates[0].settings = settings
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = agent
        integration_repository = AsyncMock()
        integration_repository.get_by_id_with_secrets.return_value = _make_integration()
        error = ImageGenerationRuntimeConfigurationError(
            reason="model_unavailable",
            integration_id="integ-1",
            model_identifier="gpt-image-2.5-flare",
        )
        image_service = _make_image_generation_catalog_service()
        image_service.validate_runtime.return_value = error
        ensure_tokens = AsyncMock()
        monkeypatch.setattr(
            EngineRuntimeTokenResolver,
            "ensure",
            ensure_tokens,
        )

        result = await resolve_invoke_input(
            InvokeInput(
                agent_id="agent-1",
                session_id="session-1",
                messages=[],
            ),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=image_service,
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(AsyncMock(spec=AsyncSession)),
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )

        assert result == Failure(error)
        ensure_tokens.assert_not_awaited()

    async def test_profile_revalidates_effective_image_settings(self) -> None:
        """Profile resolution validates the settings owned by its selected target."""
        agent = _make_agent()
        selection = agent.selectable_model_options[0].candidates[0].model_selection
        selection.normalized_capabilities.built_in_tools.supported = [
            "image_generation"
        ]
        settings = SelectableModelSettings(
            context_window_tokens=None,
            max_output_tokens=None,
            builtin_tools=[
                BuiltinToolConfig(
                    name="image_generation",
                    config={"model": "gpt-image-2.5-flare"},
                )
            ],
        )
        agent.selectable_model_options[0].candidates[0].settings = settings
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = agent
        integration_repository = AsyncMock()
        integration_repository.get_by_id_with_secrets.return_value = _make_integration()
        error = ImageGenerationRuntimeConfigurationError(
            reason="catalog_unusable",
            integration_id="integ-1",
            model_identifier="gpt-image-2.5-flare",
        )
        image_service = _make_image_generation_catalog_service()
        image_service.validate_runtime.return_value = error

        result = await resolve_invoke_input_with_profile(
            InvokeInput(
                agent_id="agent-1",
                session_id="session-1",
                messages=[],
            ),
            context_source=None,
            requested_profile=RequestedInferenceProfile(
                enabled_execution_options=[],
                model_target_label="default",
                reasoning_effort=None,
            ),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=image_service,
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(AsyncMock(spec=AsyncSession)),
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )

        assert result == Failure(error)
        image_service.validate_runtime.assert_awaited_once_with(
            integration_id="integ-1",
            workspace_id="ws-1",
            provider=LLMProvider.OPENAI,
            integration_enabled=True,
            image_generation_supported=True,
            settings=settings,
        )

    async def test_resolved_profile_revalidates_persisted_image_settings(self) -> None:
        """Recovered Session settings cannot bypass image catalog validation."""
        agent = _make_agent()
        selection = agent.selectable_model_options[0].candidates[0].model_selection
        selection.normalized_capabilities.built_in_tools.supported = [
            "image_generation"
        ]
        settings = SelectableModelSettings(
            context_window_tokens=None,
            max_output_tokens=None,
            builtin_tools=[
                BuiltinToolConfig(
                    name="image_generation",
                    config={"model": "gpt-image-2.5-flare"},
                )
            ],
        )
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = agent
        integration_repository = AsyncMock()
        integration_repository.get_by_id_with_secrets.return_value = _make_integration()
        error = ImageGenerationRuntimeConfigurationError(
            reason="provider_model_mismatch",
            integration_id="integ-1",
            model_identifier="gpt-image-2.5-flare",
        )
        image_service = _make_image_generation_catalog_service()
        image_service.validate_runtime.return_value = error

        result = await resolve_invoke_input_with_resolved_profile(
            InvokeInput(
                agent_id="agent-1",
                session_id="session-1",
                messages=[],
            ),
            context_source=None,
            resolved_model_selection=selection,
            resolved_model_settings=settings,
            resolved_reasoning_effort=None,
            resolved_enabled_execution_options=[],
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=image_service,
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(AsyncMock(spec=AsyncSession)),
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )

        assert result == Failure(error)

    async def test_applies_selected_model_settings_and_lightweight_cap(self) -> None:
        """Use option-owned output, tool, and context settings at runtime."""
        agent = _make_agent()
        main_option = agent.selectable_model_options[0]
        main_candidate = main_option.candidates[0]
        main_context = (
            main_candidate.model_selection.normalized_capabilities.context_window
        )
        main_context.max_input_tokens = 128_000
        main_context.max_output_tokens = 8_000
        main_capabilities = main_candidate.model_selection.normalized_capabilities
        main_capabilities.built_in_tools.supported = ["web_search"]
        main_capabilities.parameters.max_output_tokens = True
        main_candidate.settings = SelectableModelSettings(
            context_window_tokens=32_000,
            max_output_tokens=20_000,
            builtin_tools=[BuiltinToolConfig(name="web_search")],
        )
        lightweight_selection = make_test_model_selection(
            integration_id="integ-1",
            model_identifier="gpt-lightweight",
        )
        lightweight_context = (
            lightweight_selection.normalized_capabilities.context_window
        )
        lightweight_context.max_input_tokens = 64_000
        lightweight_option = make_test_selectable_model_options(
            lightweight_selection,
            label="lightweight",
        )[0]
        lightweight_option.candidates[0].settings = SelectableModelSettings(
            context_window_tokens=16_000,
            max_output_tokens=None,
            builtin_tools=[],
        )
        agent.selectable_model_options.append(lightweight_option)
        agent.lightweight_model_selection = lightweight_selection
        agent.lightweight_model_label = "lightweight"

        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = agent
        integration_repository = AsyncMock()
        integration_repository.get_by_id_with_secrets.return_value = _make_integration()

        result = await resolve_invoke_input(
            InvokeInput(
                agent_id="agent-1",
                session_id="session-1",
                messages=[],
            ),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=_make_image_generation_catalog_service(),
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(AsyncMock(spec=AsyncSession)),
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )

        assert isinstance(result, Success)
        request = result.value
        assert request.context_window_tokens == 32_000
        assert request.compaction_max_input_tokens == 16_000
        assert request.effective_max_input_tokens == 16_000
        assert request.max_output_tokens == 8_000
        assert [tool.name for tool in request.builtin_tools] == ["web_search"]

    async def test_rejects_stale_unsupported_model_settings(self) -> None:
        """Defensive runtime validation blocks unsupported persisted tool intent."""
        agent = _make_agent()
        candidate = agent.selectable_model_options[0].candidates[0]
        candidate.settings = SelectableModelSettings(
            context_window_tokens=None,
            max_output_tokens=None,
            builtin_tools=[BuiltinToolConfig(name="web_search")],
        )
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = agent
        integration_repository = AsyncMock()
        integration_repository.get_by_id_with_secrets.return_value = _make_integration()

        result = await resolve_invoke_input(
            InvokeInput(
                agent_id="agent-1",
                session_id="session-1",
                messages=[],
            ),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=_make_image_generation_catalog_service(),
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(AsyncMock(spec=AsyncSession)),
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )

        assert result == Failure(
            InvalidModelParameters(
                agent_id="agent-1",
                errors=["Model 'gpt-4o' does not support Web Search."],
            )
        )

    async def test_closes_snapshot_session_before_provider_refresh(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Provider token I/O starts only after Agent/Integration reads close."""
        active_sessions = 0
        agent_repository = AsyncMock()
        integration_repository = AsyncMock()

        async def get_agent(session: AsyncSession, agent_id: str) -> Agent:
            del session, agent_id
            assert active_sessions == 1
            return _make_agent()

        async def get_integration(
            session: AsyncSession, integration_id: str
        ) -> LLMProviderIntegrationWithSecrets:
            del session, integration_id
            assert active_sessions == 1
            return _make_integration()

        agent_repository.get_by_id.side_effect = get_agent
        integration_repository.get_by_id_with_secrets.side_effect = get_integration

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            nonlocal active_sessions
            active_sessions += 1
            try:
                yield AsyncMock(spec=AsyncSession)
            finally:
                active_sessions -= 1

        async def ensure_tokens(
            self: EngineRuntimeTokenResolver,
            integration: LLMProviderIntegrationWithSecrets,
        ) -> Success[LLMProviderIntegrationWithSecrets]:
            del self
            assert active_sessions == 0
            return Success(integration)

        monkeypatch.setattr(
            EngineRuntimeTokenResolver,
            "ensure",
            ensure_tokens,
        )

        result = await resolve_invoke_input(
            InvokeInput(
                agent_id="agent-1",
                session_id="session-1",
                messages=[],
            ),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=_make_image_generation_catalog_service(),
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=session_manager,
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )

        assert isinstance(result, Success)
        assert active_sessions == 0
        assert result.value.provider == LLMProvider.OPENAI
        assert result.value.agent_id == "agent-1"

    async def test_profile_resolution_preserves_explicit_default_effort(self) -> None:
        """Null effort remains visible model Default for the selected target."""
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = _make_agent()
        integration_repository = AsyncMock()
        integration_repository.get_by_id_with_secrets.return_value = _make_integration()

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            yield AsyncMock(spec=AsyncSession)

        result = await resolve_invoke_input_with_profile(
            InvokeInput(
                agent_id="agent-1",
                session_id="session-1",
                messages=[],
            ),
            context_source=None,
            requested_profile=RequestedInferenceProfile(
                enabled_execution_options=[],
                model_target_label="default",
                reasoning_effort=None,
            ),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=_make_image_generation_catalog_service(),
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=session_manager,
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )

        assert isinstance(result, Success)
        assert result.value.reasoning_effort is None
        assert result.value.run_request.reasoning_effort is None
        assert result.value.model_selection == _make_agent().model_selection
        assert agent_repository.get_by_id.await_count == 1

    async def test_profile_resolution_preserves_fast_intent(self) -> None:
        """Carry validated Fast intent into the immutable RunRequest."""
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = _make_agent(fast_supported=True)
        integration_repository = AsyncMock()
        integration_repository.get_by_id_with_secrets.return_value = _make_integration()

        result = await resolve_invoke_input_with_profile(
            InvokeInput(
                agent_id="agent-1",
                session_id="session-1",
                messages=[],
            ),
            context_source=None,
            requested_profile=RequestedInferenceProfile(
                model_target_label="default",
                reasoning_effort=None,
                enabled_execution_options=[ModelExecutionOptionId.FAST],
            ),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=_make_image_generation_catalog_service(),
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(AsyncMock(spec=AsyncSession)),
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )

        assert isinstance(result, Success)
        assert result.value.run_request.enabled_execution_options == [
            ModelExecutionOptionId.FAST
        ]

    async def test_profile_resolution_rejects_unsupported_fast(self) -> None:
        """Reject explicit unsupported intent through typed profile failure."""
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = _make_agent()
        integration_repository = AsyncMock()
        integration_repository.get_by_id_with_secrets.return_value = _make_integration()

        result = await resolve_invoke_input_with_profile(
            InvokeInput(
                agent_id="agent-1",
                session_id="session-1",
                messages=[],
            ),
            context_source=None,
            requested_profile=RequestedInferenceProfile(
                model_target_label="default",
                reasoning_effort=None,
                enabled_execution_options=[ModelExecutionOptionId.FAST],
            ),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=_make_image_generation_catalog_service(),
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(AsyncMock(spec=AsyncSession)),
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )

        assert result == Failure(
            ExecutionOptionUnsupported(
                model_target_label="default",
                enabled_execution_options=(ModelExecutionOptionId.FAST,),
            )
        )

    async def test_profile_resolution_rejects_missing_target(self) -> None:
        """Missing requested labels fail instead of using another target."""
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = _make_agent()

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            yield AsyncMock(spec=AsyncSession)

        result = await resolve_invoke_input_with_profile(
            InvokeInput(
                agent_id="agent-1",
                session_id="session-1",
                messages=[],
            ),
            context_source=None,
            requested_profile=RequestedInferenceProfile(
                enabled_execution_options=[],
                model_target_label="deleted",
                reasoning_effort=None,
            ),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=_make_image_generation_catalog_service(),
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=session_manager,
                agent_repository=agent_repository,
                integration_repository=AsyncMock(),
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )

        assert result == Failure(ModelTargetNotFound(model_target_label="deleted"))

    async def test_profile_resolution_rejects_effort_when_levels_are_empty(
        self,
    ) -> None:
        """Empty effort levels reject every explicit effort."""
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = _make_agent(
            reasoning_supported=True,
        )
        integration_repository = AsyncMock()
        integration_repository.get_by_id_with_secrets.return_value = _make_integration()

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            yield AsyncMock(spec=AsyncSession)

        result = await resolve_invoke_input_with_profile(
            InvokeInput(
                agent_id="agent-1",
                session_id="session-1",
                messages=[],
            ),
            context_source=None,
            requested_profile=RequestedInferenceProfile(
                enabled_execution_options=[],
                model_target_label="default",
                reasoning_effort=ModelReasoningEffort.HIGH,
            ),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=_make_image_generation_catalog_service(),
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=session_manager,
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )

        assert result == Failure(
            ReasoningEffortUnsupported(
                model_target_label="default",
                reasoning_effort=ModelReasoningEffort.HIGH,
            )
        )

    async def test_profile_resolution_rejects_effort_for_non_reasoning_model(
        self,
    ) -> None:
        """Explicit effort remains invalid when reasoning is unsupported."""
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = _make_agent()

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            yield AsyncMock(spec=AsyncSession)

        result = await resolve_invoke_input_with_profile(
            InvokeInput(
                agent_id="agent-1",
                session_id="session-1",
                messages=[],
            ),
            context_source=None,
            requested_profile=RequestedInferenceProfile(
                enabled_execution_options=[],
                model_target_label="default",
                reasoning_effort=ModelReasoningEffort.HIGH,
            ),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=_make_image_generation_catalog_service(),
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=session_manager,
                agent_repository=agent_repository,
                integration_repository=AsyncMock(),
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )

        assert result == Failure(
            ReasoningEffortUnsupported(
                model_target_label="default",
                reasoning_effort=ModelReasoningEffort.HIGH,
            )
        )

    async def test_profile_resolution_rejects_unsupported_effort(self) -> None:
        """Explicit effort is validated against the selected target snapshot."""
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = _make_agent(
            reasoning_supported=True,
            effort_levels=[ModelReasoningEffort.LOW],
        )

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            yield AsyncMock(spec=AsyncSession)

        result = await resolve_invoke_input_with_profile(
            InvokeInput(
                agent_id="agent-1",
                session_id="session-1",
                messages=[],
            ),
            context_source=None,
            requested_profile=RequestedInferenceProfile(
                enabled_execution_options=[],
                model_target_label="default",
                reasoning_effort=ModelReasoningEffort.HIGH,
            ),
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
            image_generation_catalog_service=_make_image_generation_catalog_service(),
            model_metadata_service=make_test_model_metadata_service(source=None),
            repositories=get_engine_resolve_repositories(
                session_manager=session_manager,
                agent_repository=agent_repository,
                integration_repository=AsyncMock(),
                toolkit_repository=ToolkitRepository(cipher=None),
            ),
            oauth_clients=create_runtime_oauth_client_factories(),
        )

        assert result == Failure(
            ReasoningEffortUnsupported(
                model_target_label="default",
                reasoning_effort=ModelReasoningEffort.HIGH,
            )
        )


class TestResolveAgentTools:
    """resolve_agent_tools auto-bound Toolkit tests."""

    @pytest.mark.parametrize(
        "execution_mode",
        [ToolkitExecutionMode.ROOT, ToolkitExecutionMode.SUBAGENT],
    )
    async def test_auto_binds_runtime_web_without_runtime_capability(
        self,
        execution_mode: ToolkitExecutionMode,
    ) -> None:
        """Runtime Web authority tools remain available before Runtime startup."""
        session = AsyncMock(spec=AsyncSession)
        session.get.return_value = None
        provider = RuntimeWebToolkitProvider(
            service=AsyncMock(spec=RuntimeWebService),
        )

        bindings = await resolve_agent_tools(
            "agent-1",
            _make_toolkit_context(),
            execution_mode=execution_mode,
            toolkit_registry={},
            web_url="https://example.test",
            oauth_secret_key="secret",
            mcp_proxy_url=None,
            runtime_domain_config=RuntimeDomainConfig(
                allowed_domains=(),
                denied_domains=(),
            ),
            runtime_web_toolkit_provider=provider,
            memory_enabled=False,
            runtime_capability_resolver=_runtime_capability_resolver(enabled=False),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(session),
                agent_repository=AgentRepository(),
                integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
                toolkit_repository=_empty_toolkit_repository(),
            ),
            workspace_handle=None,
        )

        assert [binding.slug for binding in bindings] == ["runtime_web"]
        assert isinstance(bindings[0].toolkit, RuntimeWebToolkit)

    @pytest.mark.parametrize(
        "execution_mode",
        [ToolkitExecutionMode.ROOT, ToolkitExecutionMode.SUBAGENT],
    )
    async def test_auto_binds_dynamic_worktree_in_shared_context_modes(
        self,
        execution_mode: ToolkitExecutionMode,
    ) -> None:
        """Root and subagent Runs resolve the shared-context worktree Toolkit."""
        session = AsyncMock(spec=AsyncSession)
        session.get.return_value = None

        bindings = await resolve_agent_tools(
            "agent-1",
            _make_toolkit_context(),
            execution_mode=execution_mode,
            toolkit_registry={},
            web_url="https://example.test",
            oauth_secret_key="secret",
            mcp_proxy_url=None,
            runtime_domain_config=RuntimeDomainConfig(
                allowed_domains=(),
                denied_domains=(),
            ),
            dynamic_worktree_toolkit_provider=_make_dynamic_worktree_provider(),
            memory_enabled=False,
            runtime_capability_resolver=_runtime_capability_resolver(enabled=False),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(session),
                agent_repository=AgentRepository(),
                integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
                toolkit_repository=_empty_toolkit_repository(),
            ),
            workspace_handle=None,
        )

        assert [binding.slug for binding in bindings] == ["dynamic_worktree"]
        assert isinstance(bindings[0].toolkit, DynamicWorktreeToolkit)

    async def test_skips_registered_toolkit_with_invalid_persisted_config(
        self,
    ) -> None:
        """Expected persisted config errors disable only that Toolkit."""
        bindings = await _resolve_failing_registered_toolkit(
            _FailingToolkitProvider(ValueError("invalid persisted credential"))
        )

        assert bindings == []

    async def test_skips_registered_toolkit_with_invalid_persisted_schema(
        self,
    ) -> None:
        """Schema-invalid persisted config disables only that Toolkit."""
        bindings = await _resolve_failing_registered_toolkit(
            _FailingToolkitProvider(RuntimeError("must not resolve")),
            toolkit_config={},
        )

        assert bindings == []

    async def test_propagates_unexpected_registered_toolkit_failure(self) -> None:
        """Unexpected provider bugs are not disguised as a missing Toolkit."""
        with pytest.raises(RuntimeError, match="provider bug"):
            await _resolve_failing_registered_toolkit(
                _FailingToolkitProvider(RuntimeError("provider bug"))
            )

    async def test_auto_binds_claude_rules_when_runtime_capability_allows(self) -> None:
        """Claude rules Toolkit is auto-bound after Runtime capability admission."""
        session = AsyncMock(spec=AsyncSession)
        session.get.return_value = None

        bindings = await resolve_agent_tools(
            "agent-1",
            _make_toolkit_context(),
            execution_mode=ToolkitExecutionMode.ROOT,
            toolkit_registry={},
            web_url="https://example.test",
            oauth_secret_key="secret",
            mcp_proxy_url=None,
            runtime_domain_config=RuntimeDomainConfig(
                allowed_domains=(),
                denied_domains=(),
            ),
            builtin_toolkit_provider=_make_builtin_provider(),
            claude_rules_toolkit_provider=ClaudeRulesToolkitProvider(
                store=_FakeClaudeRulesAppendixDedupeStateStore()
            ),
            memory_enabled=True,
            runtime_capability_resolver=_runtime_capability_resolver(enabled=True),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(session),
                agent_repository=AgentRepository(),
                integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
                toolkit_repository=_empty_toolkit_repository(),
            ),
            workspace_handle=None,
        )

        assert [binding.slug for binding in bindings] == [
            "memory_context",
            "memory_write",
            "readable_storage",
            "runtime",
            "claude_rules",
        ]
        memory_context_state = await bindings[0].toolkit.update_context(
            _make_turn_context()
        )
        memory_write_state = await bindings[1].toolkit.update_context(
            _make_turn_context()
        )
        memory_write_tools = {tool.spec.name for tool in memory_write_state.tools}
        assert memory_context_state.tools == []
        assert memory_write_tools == {"save_memory", "delete_memory"}

    async def test_does_not_auto_bind_claude_rules_when_capability_denies(
        self,
    ) -> None:
        """Claude rules Toolkit is not auto-bound without Runtime capability."""
        session = AsyncMock(spec=AsyncSession)
        session.get.return_value = None

        bindings = await resolve_agent_tools(
            "agent-1",
            _make_toolkit_context(),
            execution_mode=ToolkitExecutionMode.ROOT,
            toolkit_registry={},
            web_url="https://example.test",
            oauth_secret_key="secret",
            mcp_proxy_url=None,
            runtime_domain_config=RuntimeDomainConfig(
                allowed_domains=(),
                denied_domains=(),
            ),
            builtin_toolkit_provider=_make_builtin_provider(),
            claude_rules_toolkit_provider=ClaudeRulesToolkitProvider(
                store=_FakeClaudeRulesAppendixDedupeStateStore()
            ),
            memory_enabled=True,
            runtime_capability_resolver=_runtime_capability_resolver(enabled=False),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(session),
                agent_repository=AgentRepository(),
                integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
                toolkit_repository=_empty_toolkit_repository(),
            ),
            workspace_handle=None,
        )

        assert [binding.slug for binding in bindings] == [
            "memory_context",
            "memory_write",
            "readable_storage",
        ]

    async def test_auto_binds_subagent_toolkit_in_root_mode(self) -> None:
        """Root sessions receive the coherent subagent collaboration bundle."""
        session = AsyncMock(spec=AsyncSession)
        session.get.return_value = None

        bindings = await resolve_agent_tools(
            "agent-1",
            _make_toolkit_context(),
            execution_mode=ToolkitExecutionMode.ROOT,
            toolkit_registry={},
            web_url="https://example.test",
            oauth_secret_key="secret",
            mcp_proxy_url=None,
            runtime_domain_config=RuntimeDomainConfig(
                allowed_domains=(),
                denied_domains=(),
            ),
            subagent_toolkit_provider=_make_subagent_provider(),
            memory_enabled=False,
            runtime_capability_resolver=_runtime_capability_resolver(enabled=False),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(session),
                agent_repository=AgentRepository(),
                integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
                toolkit_repository=_empty_toolkit_repository(),
            ),
            workspace_handle=None,
        )

        assert [binding.slug for binding in bindings] == ["subagent"]
        state = await bindings[0].toolkit.update_context(_make_turn_context())
        assert {tool.spec.name for tool in state.tools} == {
            "spawn_agent",
            "send_message",
            "followup_task",
            "interrupt_agent",
            "list_agents",
        }

    async def test_subagent_mode_filters_root_only_auto_bound_toolkits(self) -> None:
        """Subagent mode keeps read/runtime capabilities and excludes root-only ones."""
        session = AsyncMock(spec=AsyncSession)
        session.get.return_value = None

        @asynccontextmanager
        async def goal_session_manager() -> AsyncGenerator[AsyncSession, None]:
            yield AsyncMock(spec=AsyncSession)

        bindings = await resolve_agent_tools(
            "agent-1",
            _make_toolkit_context(),
            execution_mode=ToolkitExecutionMode.SUBAGENT,
            toolkit_registry={},
            web_url="https://example.test",
            oauth_secret_key="secret",
            mcp_proxy_url=None,
            runtime_domain_config=RuntimeDomainConfig(
                allowed_domains=(),
                denied_domains=(),
            ),
            builtin_toolkit_provider=_make_builtin_provider(),
            claude_rules_toolkit_provider=ClaudeRulesToolkitProvider(
                store=_FakeClaudeRulesAppendixDedupeStateStore()
            ),
            goal_toolkit_provider=GoalToolkitProvider(
                store=GoalStateStore(session_manager=goal_session_manager)
            ),
            scheduled_toolkit_provider=_make_scheduled_provider(),
            memory_enabled=True,
            runtime_capability_resolver=_runtime_capability_resolver(enabled=True),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(session),
                agent_repository=AgentRepository(),
                integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
                toolkit_repository=_empty_toolkit_repository(),
            ),
            workspace_handle=None,
        )

        assert [binding.slug for binding in bindings] == [
            "memory_context",
            "readable_storage",
            "runtime",
            "claude_rules",
        ]

    async def test_scheduled_toolkit_is_unprefixed_and_root_only(self) -> None:
        """Scheduled auto-binding needs no attachment, config, or credentials."""
        session = AsyncMock(spec=AsyncSession)
        session.get.return_value = None
        provider = _make_scheduled_provider()

        root = await resolve_agent_tools(
            "agent-1",
            _make_toolkit_context(),
            execution_mode=ToolkitExecutionMode.ROOT,
            toolkit_registry={},
            web_url="https://example.test",
            oauth_secret_key="secret",
            mcp_proxy_url=None,
            runtime_domain_config=RuntimeDomainConfig(
                allowed_domains=(),
                denied_domains=(),
            ),
            builtin_toolkit_provider=_make_builtin_provider(),
            scheduled_toolkit_provider=provider,
            memory_enabled=False,
            runtime_capability_resolver=_runtime_capability_resolver(enabled=True),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(session),
                agent_repository=AgentRepository(),
                integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
                toolkit_repository=_empty_toolkit_repository(),
            ),
            workspace_handle=None,
        )
        subagent = await resolve_agent_tools(
            "agent-1",
            _make_toolkit_context(),
            execution_mode=ToolkitExecutionMode.SUBAGENT,
            toolkit_registry={},
            web_url="https://example.test",
            oauth_secret_key="secret",
            mcp_proxy_url=None,
            runtime_domain_config=RuntimeDomainConfig(
                allowed_domains=(),
                denied_domains=(),
            ),
            scheduled_toolkit_provider=provider,
            memory_enabled=False,
            runtime_capability_resolver=_runtime_capability_resolver(enabled=False),
            repositories=get_engine_resolve_repositories(
                session_manager=_session_manager_for(session),
                agent_repository=AgentRepository(),
                integration_repository=AsyncMock(spec=LLMProviderIntegrationRepository),
                toolkit_repository=_empty_toolkit_repository(),
            ),
            workspace_handle=None,
        )

        assert [binding.slug for binding in root] == [
            "readable_storage",
            "runtime",
            "scheduled",
        ]
        assert root[2].use_prefix is False
        assert root[2].toolkit_type is None
        assert root[2].toolkit_config_id is None
        assert root[2].source_revision is not None
        assert isinstance(root[2].toolkit, ScheduledToolkit)
        assert root[2].toolkit.runtime_context_store is not None
        assert subagent == []


@pytest.mark.parametrize("top_k", [None, 37])
async def test_existing_agent_top_k_reaches_run_and_retry_carrier(
    top_k: int | None,
) -> None:
    agent = _make_agent()
    agent.model_parameters = ModelParameters(top_k=top_k)
    for option in agent.selectable_model_options:
        for candidate in option.candidates:
            candidate.model_selection.normalized_capabilities.parameters.top_k = True
    before = agent.model_parameters.model_dump_json()
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = agent
    integration_repository = AsyncMock()
    integration_repository.get_by_id_with_secrets.return_value = _make_integration()
    session_manager = _session_manager_for(AsyncMock(spec=AsyncSession))
    result = await resolve_invoke_input(
        InvokeInput(agent_id="agent-1", session_id="session-1", messages=[]),
        repositories=get_engine_resolve_repositories(
            agent_repository=agent_repository,
            integration_repository=integration_repository,
            session_manager=session_manager,
            toolkit_repository=ToolkitRepository(cipher=None),
        ),
        oauth_clients=create_runtime_oauth_client_factories(),
        exchange_file_service=AsyncMock(),
        model_file_service=AsyncMock(),
        image_generation_catalog_service=_make_image_generation_catalog_service(),
        model_metadata_service=make_test_model_metadata_service(source=None),
    )
    assert isinstance(result, Success)
    assert result.value.top_k == top_k
    assert dataclasses.replace(result.value, user_messages=[]).top_k == top_k
    assert agent.model_parameters.model_dump_json() == before
