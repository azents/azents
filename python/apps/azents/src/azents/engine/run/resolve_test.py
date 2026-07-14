"""Agent run resolve tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import ApiKeySecrets
from azents.core.enums import (
    AgentType,
    ExchangeFileOrigin,
    ExchangeFileStatus,
    LLMProvider,
    ModelFileStatus,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.tools import (
    ResolveContext,
    SessionType,
    Toolkit,
    ToolkitContext,
    ToolkitExecutionMode,
    TurnContext,
)
from azents.engine.run.input import InputMessage, InvokeInput
from azents.engine.run.types import OWNERSHIP_LOST_CANCEL_MESSAGE
from azents.engine.tools.builtin import BuiltinToolkitProvider
from azents.engine.tools.builtin_agents import AgentsAppendixDedupeState
from azents.engine.tools.claude_rules import (
    ClaudeRulesAppendixDedupeState,
    ClaudeRulesToolkitProvider,
)
from azents.engine.tools.envvar import EnvVarToolkitConfig, EnvVarToolkitProvider
from azents.engine.tools.goal import GoalStateStore, GoalToolkitProvider
from azents.engine.tools.subagent import SubagentToolkitProvider
from azents.rdb.session import SessionManager
from azents.repos.agent.data import Agent
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.model_file.data import ModelFile
from azents.repos.toolkit.data import AgentToolkit, ToolkitConfig
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.runtime.types import RuntimeDomainConfig
from azents.services.exchange_file import ExchangeFileDownload
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_options,
)

from .resolve import (
    ModelTargetNotFound,
    ReasoningEffortUnsupported,
    materialize_user_input_exchange_file_attachments,
    resolve_agent_tools,
    resolve_invoke_input,
    resolve_invoke_input_with_profile,
)

_NOW = datetime.datetime.now(datetime.timezone.utc)


def _make_agent(
    *,
    reasoning_supported: bool = False,
    effort_levels: list[ModelReasoningEffort] | None = None,
) -> Agent:
    """Create Agent for tests."""
    selection = make_test_model_selection(integration_id="integ-1")
    selection.normalized_capabilities.reasoning.supported = reasoning_supported
    selection.normalized_capabilities.reasoning.effort_levels = (
        [] if effort_levels is None else effort_levels
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
        type=AgentType.PUBLIC,
        runtime_provider_id=None,
        shell_enabled=True,
        memory_enabled=True,
        max_turns=None,
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
    )


def _make_exchange_file(*, file_id: str) -> ExchangeFile:
    """Create one available ExchangeFile attachment."""
    return ExchangeFile(
        id=file_id,
        workspace_id="ws-1",
        agent_id="agent-1",
        origin_type=ExchangeFileOrigin.UPLOAD,
        status=ExchangeFileStatus.AVAILABLE,
        object_key=f"exchange/ws-1/files/{file_id}/original",
        filename=f"{file_id}.txt",
        media_type="text/plain",
        size_bytes=4,
        sha256="sha256",
        created_by_user_id="user-1",
        expires_at=_NOW + datetime.timedelta(days=30),
        created_at=_NOW,
    )


def _make_model_file(*, model_file_id: str) -> ModelFile:
    """Create one ModelFile produced from an Exchange attachment."""
    return ModelFile(
        id=model_file_id,
        workspace_id="ws-1",
        session_id="session-1",
        agent_id="agent-1",
        name=f"{model_file_id}.txt",
        media_type="text/plain",
        kind="text",
        size_bytes=4,
        created_run_index=1,
        storage_key=f"model-files/ws-1/session-1/{model_file_id}",
        status=ModelFileStatus.AVAILABLE,
        normalized_format="text/plain",
        sha256="sha256",
        created_at=_NOW,
    )


class _FakeClaudeRulesAppendixDedupeStateStore:
    """Claude rules appendix dedupe state store for resolve tests."""

    async def load_appendix_dedupe(
        self, agent_id: str, session_id: str
    ) -> ClaudeRulesAppendixDedupeState:
        """Return empty dedupe state."""
        del agent_id, session_id
        return ClaudeRulesAppendixDedupeState()

    async def update_appendix_dedupe(
        self,
        agent_id: str,
        session_id: str,
        *,
        run_id: str,
        owner_generation: int,
        mutator: Callable[
            [ClaudeRulesAppendixDedupeState], ClaudeRulesAppendixDedupeState
        ],
    ) -> None:
        """Ignore dedupe updates."""
        del agent_id, session_id, run_id, owner_generation, mutator


class _FakeAgentsAppendixDedupeStateStore:
    """AGENTS.md appendix dedupe state store for resolve tests."""

    async def load_appendix_dedupe(
        self, agent_id: str, session_id: str
    ) -> AgentsAppendixDedupeState:
        """Return empty AGENTS.md dedupe state."""
        del agent_id, session_id
        return AgentsAppendixDedupeState()

    async def update_appendix_dedupe(
        self,
        agent_id: str,
        session_id: str,
        *,
        run_id: str,
        owner_generation: int,
        mutator: Callable[[AgentsAppendixDedupeState], AgentsAppendixDedupeState],
    ) -> None:
        """Ignore dedupe updates."""
        del agent_id, session_id, run_id, owner_generation, mutator


class _SessionBoundaryEnvVarToolkitProvider(EnvVarToolkitProvider):
    """Assert registered Toolkit resolution runs without an active DB session."""

    def __init__(self, session_active: Callable[[], bool]) -> None:
        self.session_active = session_active

    async def resolve(
        self,
        config: EnvVarToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[EnvVarToolkitConfig]:
        """Delegate after checking the DB snapshot boundary."""
        assert not self.session_active()
        return await super().resolve(config, context)


class _FailingEnvVarToolkitProvider(EnvVarToolkitProvider):
    """Registered provider that exposes an implementation failure."""

    async def resolve(
        self,
        config: EnvVarToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[EnvVarToolkitConfig]:
        """Raise a programming error instead of silently removing the Toolkit."""
        del config, context
        raise AssertionError("registered provider bug")


def _make_toolkit_context() -> ToolkitContext:
    """Create ToolkitContext for resolve_agent_tools tests."""
    return ToolkitContext(
        session_id="session-1",
        workspace_id="ws-1",
        agent_id="agent-1",
        user_id="user-1",
        run_id="run-1",
        publish_event=AsyncMock(),
        session_type=SessionType.USER,
        interface_type=None,
        interface_channel_id=None,
    )


def _make_turn_context() -> TurnContext:
    """Create TurnContext for resolved Toolkit tests."""
    return TurnContext(
        user_id="user-1",
        workspace_id="ws-1",
        model="gpt-4o",
        run_id="run-1",
        owner_generation=1,
        publish_event=AsyncMock(),
        session_id="session-1",
    )


def _make_builtin_provider() -> BuiltinToolkitProvider:
    """Create BuiltinToolkitProvider for resolve_agent_tools tests."""
    return BuiltinToolkitProvider(
        exchange_file_service=AsyncMock(),
        artifact_service=AsyncMock(),
        model_file_service=AsyncMock(),
        agents_store=_FakeAgentsAppendixDedupeStateStore(),
        session_manager=AsyncMock(),
        memory_repo=AsyncMock(),
        agent_runtime_repo=AsyncMock(),
        runner_operations=AsyncMock(),
        project_repo=AsyncMock(),
    )


def _make_session_manager(
    session: AsyncSession,
) -> SessionManager[AsyncSession]:
    """Create a reusable session manager around one mock session."""

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield session

    return session_manager


def _make_subagent_provider(
    session_manager: SessionManager[AsyncSession],
) -> SubagentToolkitProvider:
    """Create SubagentToolkitProvider for resolve_agent_tools tests."""
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = _make_agent()
    return SubagentToolkitProvider(
        session_manager=session_manager,
        broker=AsyncMock(),
        input_buffer_service=AsyncMock(),
        agent_repository=agent_repository,
    )


class TestResolveInvokeInput:
    """resolve_invoke_input tests."""

    async def test_resolves_run_request_from_agent_snapshot(self) -> None:
        """Build RunRequest from Agent snapshot and integration."""
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = _make_agent()
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
                        user_id=None,
                        headers=[],
                        metadata={},
                        attachments=[],
                    )
                ],
            ),
            agent_repository=agent_repository,
            integration_repository=integration_repository,
            session_manager=session_manager,
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
        )

        assert isinstance(result, Success)
        run_request = result.value
        assert run_request.model == "gpt-4o"
        assert run_request.provider == LLMProvider.OPENAI
        assert run_request.agent_id == "agent-1"

    async def test_releases_read_session_before_runtime_token_refresh(self) -> None:
        """OAuth refresh starts only after the Agent/Integration snapshot closes."""
        agent_repository = AsyncMock()
        agent_repository.get_by_id.return_value = _make_agent()
        integration_repository = AsyncMock()
        integration_repository.get_by_id_with_secrets.return_value = _make_integration()
        active_sessions = 0

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            nonlocal active_sessions
            active_sessions += 1
            try:
                yield AsyncMock(spec=AsyncSession)
            finally:
                active_sessions -= 1

        async def ensure_runtime_tokens(**kwargs: object) -> object:
            assert active_sessions == 0
            return Success(kwargs["integration"])

        with patch(
            "azents.engine.run.resolve._ensure_provider_runtime_tokens",
            side_effect=ensure_runtime_tokens,
        ):
            result = await resolve_invoke_input(
                InvokeInput(
                    agent_id="agent-1",
                    session_id="session-1",
                    messages=[],
                ),
                agent_repository=agent_repository,
                integration_repository=integration_repository,
                session_manager=session_manager,
                exchange_file_service=AsyncMock(),
                model_file_service=AsyncMock(),
            )

        assert isinstance(result, Success)
        assert active_sessions == 0

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
            requested_profile=RequestedInferenceProfile(
                model_target_label="default",
                reasoning_effort=None,
            ),
            agent_repository=agent_repository,
            integration_repository=integration_repository,
            session_manager=session_manager,
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
        )

        assert isinstance(result, Success)
        assert result.value.reasoning_effort is None
        assert result.value.run_request.reasoning_effort is None
        assert result.value.model_selection == _make_agent().model_selection
        assert agent_repository.get_by_id.await_count == 1

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
            requested_profile=RequestedInferenceProfile(
                model_target_label="deleted",
                reasoning_effort=None,
            ),
            agent_repository=agent_repository,
            integration_repository=AsyncMock(),
            session_manager=session_manager,
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
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
            requested_profile=RequestedInferenceProfile(
                model_target_label="default",
                reasoning_effort=ModelReasoningEffort.HIGH,
            ),
            agent_repository=agent_repository,
            integration_repository=integration_repository,
            session_manager=session_manager,
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
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
            requested_profile=RequestedInferenceProfile(
                model_target_label="default",
                reasoning_effort=ModelReasoningEffort.HIGH,
            ),
            agent_repository=agent_repository,
            integration_repository=AsyncMock(),
            session_manager=session_manager,
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
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
            requested_profile=RequestedInferenceProfile(
                model_target_label="default",
                reasoning_effort=ModelReasoningEffort.HIGH,
            ),
            agent_repository=agent_repository,
            integration_repository=AsyncMock(),
            session_manager=session_manager,
            exchange_file_service=AsyncMock(),
            model_file_service=AsyncMock(),
        )

        assert result == Failure(
            ReasoningEffortUnsupported(
                model_target_label="default",
                reasoning_effort=ModelReasoningEffort.HIGH,
            )
        )


class TestMaterializeUserInputExchangeFileAttachments:
    """Exchange attachment materialization compensation tests."""

    async def test_discards_created_model_file_when_next_attachment_raises(
        self,
    ) -> None:
        """An exception after partial creation compensates every created ModelFile."""
        exchange_file = _make_exchange_file(file_id="exchange-1")
        model_file = _make_model_file(model_file_id="model-file-1")
        exchange_file_service = AsyncMock()
        exchange_file_service.resolve_attachment_metadata_for_agent.side_effect = [
            Success(exchange_file),
            RuntimeError("metadata resolve failed"),
        ]
        exchange_file_service.resolve_attachment_for_agent.return_value = Success(
            ExchangeFileDownload(file=exchange_file, body=b"body")
        )
        model_file_service = AsyncMock()
        model_file_service.create_for_agent_pending_input.return_value = Success(
            model_file
        )

        with pytest.raises(RuntimeError, match="metadata resolve failed"):
            await materialize_user_input_exchange_file_attachments(
                ["exchange://first", "exchange://second"],
                agent_id="agent-1",
                session_id="session-1",
                exchange_file_service=exchange_file_service,
                model_file_service=model_file_service,
                user_id="user-1",
            )

        model_file_service.discard_unreferenced.assert_awaited_once_with(
            agent_id="agent-1",
            session_id="session-1",
            model_file_ids=["model-file-1"],
        )

    async def test_discards_created_model_file_when_next_attachment_is_cancelled(
        self,
    ) -> None:
        """Cancellation after partial creation compensates before propagating."""
        exchange_file = _make_exchange_file(file_id="exchange-1")
        model_file = _make_model_file(model_file_id="model-file-1")
        exchange_file_service = AsyncMock()
        exchange_file_service.resolve_attachment_metadata_for_agent.side_effect = [
            Success(exchange_file),
            asyncio.CancelledError("cancelled"),
        ]
        exchange_file_service.resolve_attachment_for_agent.return_value = Success(
            ExchangeFileDownload(file=exchange_file, body=b"body")
        )
        model_file_service = AsyncMock()
        model_file_service.create_for_agent_pending_input.return_value = Success(
            model_file
        )

        with pytest.raises(asyncio.CancelledError):
            await materialize_user_input_exchange_file_attachments(
                ["exchange://first", "exchange://second"],
                agent_id="agent-1",
                session_id="session-1",
                exchange_file_service=exchange_file_service,
                model_file_service=model_file_service,
                user_id="user-1",
            )

        model_file_service.discard_unreferenced.assert_awaited_once_with(
            agent_id="agent-1",
            session_id="session-1",
            model_file_ids=["model-file-1"],
        )

    async def test_ownership_loss_does_not_run_stale_model_file_cleanup(
        self,
    ) -> None:
        """Ownership handoff propagates without stale-worker compensation writes."""
        exchange_file = _make_exchange_file(file_id="exchange-1")
        model_file = _make_model_file(model_file_id="model-file-1")
        exchange_file_service = AsyncMock()
        exchange_file_service.resolve_attachment_metadata_for_agent.side_effect = [
            Success(exchange_file),
            asyncio.CancelledError(OWNERSHIP_LOST_CANCEL_MESSAGE),
        ]
        exchange_file_service.resolve_attachment_for_agent.return_value = Success(
            ExchangeFileDownload(file=exchange_file, body=b"body")
        )
        model_file_service = AsyncMock()
        model_file_service.create_for_agent_pending_input.return_value = Success(
            model_file
        )

        with pytest.raises(asyncio.CancelledError) as cancelled:
            await materialize_user_input_exchange_file_attachments(
                ["exchange://first", "exchange://second"],
                agent_id="agent-1",
                session_id="session-1",
                exchange_file_service=exchange_file_service,
                model_file_service=model_file_service,
                user_id="user-1",
            )

        assert cancelled.value.args == (OWNERSHIP_LOST_CANCEL_MESSAGE,)
        model_file_service.discard_unreferenced.assert_not_awaited()


class TestResolveAgentTools:
    """resolve_agent_tools auto-bound Toolkit tests."""

    async def test_releases_config_session_before_provider_resolution(self) -> None:
        """Registered providers resolve only after DB configuration reads finish."""
        session = AsyncMock(spec=AsyncSession)
        active_sessions = 0

        @asynccontextmanager
        async def session_manager() -> AsyncGenerator[AsyncSession, None]:
            nonlocal active_sessions
            active_sessions += 1
            try:
                yield session
            finally:
                active_sessions -= 1

        agent_toolkit_repository = AsyncMock()
        agent_toolkit_repository.list_by_agent.return_value = [
            AgentToolkit(
                id="agent-toolkit-1",
                agent_id="agent-1",
                toolkit_id="toolkit-1",
                toolkit_type="envvar",
                created_at=_NOW,
            )
        ]
        toolkit_repository = AsyncMock()
        toolkit_repository.get_by_id.return_value = ToolkitConfig(
            id="toolkit-1",
            workspace_id="ws-1",
            toolkit_type="envvar",
            slug="environment",
            name="Environment",
            description=None,
            config={"entries": []},
            prompt=None,
            credentials=None,
            enabled=True,
            created_at=_NOW,
            updated_at=_NOW,
        )
        provider = _SessionBoundaryEnvVarToolkitProvider(lambda: active_sessions > 0)

        bindings = await resolve_agent_tools(
            "agent-1",
            _make_toolkit_context(),
            execution_mode=ToolkitExecutionMode.ROOT,
            toolkit_registry={"envvar": provider},
            agent_toolkit_repository=agent_toolkit_repository,
            toolkit_repository=toolkit_repository,
            session_manager=session_manager,
            web_url="https://example.test",
            oauth_secret_key="secret",
            mcp_proxy_url=None,
            workspace_handle="workspace",
            runtime_domain_config=RuntimeDomainConfig(
                allowed_domains=(),
                denied_domains=(),
            ),
            memory_enabled=False,
            runtime_tools_enabled=False,
        )

        assert [binding.slug for binding in bindings] == ["environment"]
        assert active_sessions == 0

    async def test_registered_provider_failure_is_not_silently_omitted(self) -> None:
        """A configured Toolkit implementation bug fails resolution visibly."""
        session = AsyncMock(spec=AsyncSession)
        agent_toolkit_repository = AsyncMock()
        agent_toolkit_repository.list_by_agent.return_value = [
            AgentToolkit(
                id="agent-toolkit-1",
                agent_id="agent-1",
                toolkit_id="toolkit-1",
                toolkit_type="envvar",
                created_at=_NOW,
            )
        ]
        toolkit_repository = AsyncMock()
        toolkit_repository.get_by_id.return_value = ToolkitConfig(
            id="toolkit-1",
            workspace_id="ws-1",
            toolkit_type="envvar",
            slug="environment",
            name="Environment",
            description=None,
            config={"entries": []},
            prompt=None,
            credentials=None,
            enabled=True,
            created_at=_NOW,
            updated_at=_NOW,
        )

        with pytest.raises(AssertionError, match="registered provider bug"):
            await resolve_agent_tools(
                "agent-1",
                _make_toolkit_context(),
                execution_mode=ToolkitExecutionMode.ROOT,
                toolkit_registry={"envvar": _FailingEnvVarToolkitProvider()},
                agent_toolkit_repository=agent_toolkit_repository,
                toolkit_repository=toolkit_repository,
                session_manager=_make_session_manager(session),
                web_url="https://example.test",
                oauth_secret_key="secret",
                mcp_proxy_url=None,
                workspace_handle="workspace",
                runtime_domain_config=RuntimeDomainConfig(
                    allowed_domains=(),
                    denied_domains=(),
                ),
                memory_enabled=False,
                runtime_tools_enabled=False,
            )

    async def test_auto_binds_claude_rules_when_runtime_tools_enabled(self) -> None:
        """Claude rules Toolkit is auto-bound after runtime shell Toolkit."""
        session = AsyncMock(spec=AsyncSession)
        session.get.return_value = None
        agent_toolkit_repository = AsyncMock()
        agent_toolkit_repository.list_by_agent.return_value = []

        bindings = await resolve_agent_tools(
            "agent-1",
            _make_toolkit_context(),
            execution_mode=ToolkitExecutionMode.ROOT,
            toolkit_registry={},
            agent_toolkit_repository=agent_toolkit_repository,
            toolkit_repository=AsyncMock(),
            session_manager=_make_session_manager(session),
            web_url="https://example.test",
            oauth_secret_key="secret",
            mcp_proxy_url=None,
            workspace_handle="workspace",
            runtime_domain_config=RuntimeDomainConfig(
                allowed_domains=(),
                denied_domains=(),
            ),
            builtin_toolkit_provider=_make_builtin_provider(),
            claude_rules_toolkit_provider=ClaudeRulesToolkitProvider(
                store=_FakeClaudeRulesAppendixDedupeStateStore()
            ),
            memory_enabled=True,
            runtime_tools_enabled=True,
        )

        assert [binding.slug for binding in bindings] == [
            "memory_read",
            "memory_write",
            "runtime",
            "claude_rules",
        ]
        memory_read_state = await bindings[0].toolkit.update_context(
            _make_turn_context()
        )
        memory_write_state = await bindings[1].toolkit.update_context(
            _make_turn_context()
        )
        memory_read_tools = {tool.spec.name for tool in memory_read_state.tools}
        memory_write_tools = {tool.spec.name for tool in memory_write_state.tools}
        assert memory_read_tools == {
            "list_memories",
            "get_memory",
            "search_memories",
        }
        assert memory_write_tools == {"save_memory", "delete_memory"}

    async def test_does_not_auto_bind_claude_rules_when_runtime_tools_disabled(
        self,
    ) -> None:
        """Claude rules Toolkit is not auto-bound without runtime tools."""
        session = AsyncMock(spec=AsyncSession)
        session.get.return_value = None
        agent_toolkit_repository = AsyncMock()
        agent_toolkit_repository.list_by_agent.return_value = []

        bindings = await resolve_agent_tools(
            "agent-1",
            _make_toolkit_context(),
            execution_mode=ToolkitExecutionMode.ROOT,
            toolkit_registry={},
            agent_toolkit_repository=agent_toolkit_repository,
            toolkit_repository=AsyncMock(),
            session_manager=_make_session_manager(session),
            web_url="https://example.test",
            oauth_secret_key="secret",
            mcp_proxy_url=None,
            workspace_handle="workspace",
            runtime_domain_config=RuntimeDomainConfig(
                allowed_domains=(),
                denied_domains=(),
            ),
            builtin_toolkit_provider=_make_builtin_provider(),
            claude_rules_toolkit_provider=ClaudeRulesToolkitProvider(
                store=_FakeClaudeRulesAppendixDedupeStateStore()
            ),
            memory_enabled=True,
            runtime_tools_enabled=False,
        )

        assert [binding.slug for binding in bindings] == ["memory_read", "memory_write"]

    async def test_auto_binds_subagent_toolkit_in_root_mode(self) -> None:
        """Root sessions receive the coherent subagent collaboration bundle."""
        session = AsyncMock(spec=AsyncSession)
        session.get.return_value = None
        agent_toolkit_repository = AsyncMock()
        agent_toolkit_repository.list_by_agent.return_value = []

        session_manager = _make_session_manager(session)
        bindings = await resolve_agent_tools(
            "agent-1",
            _make_toolkit_context(),
            execution_mode=ToolkitExecutionMode.ROOT,
            toolkit_registry={},
            agent_toolkit_repository=agent_toolkit_repository,
            toolkit_repository=AsyncMock(),
            session_manager=session_manager,
            web_url="https://example.test",
            oauth_secret_key="secret",
            mcp_proxy_url=None,
            workspace_handle="workspace",
            runtime_domain_config=RuntimeDomainConfig(
                allowed_domains=(),
                denied_domains=(),
            ),
            subagent_toolkit_provider=_make_subagent_provider(session_manager),
            memory_enabled=False,
            runtime_tools_enabled=False,
        )

        assert [binding.slug for binding in bindings] == ["subagent"]
        state = await bindings[0].toolkit.update_context(_make_turn_context())
        assert {tool.spec.name for tool in state.tools} == {
            "spawn_agent",
            "send_message",
            "followup_task",
            "wait_agent",
            "interrupt_agent",
            "list_agents",
        }

    async def test_subagent_mode_filters_root_only_auto_bound_toolkits(self) -> None:
        """Subagent mode keeps read/runtime capabilities and excludes root-only ones."""
        session = AsyncMock(spec=AsyncSession)
        session.get.return_value = None
        agent_toolkit_repository = AsyncMock()
        agent_toolkit_repository.list_by_agent.return_value = []

        @asynccontextmanager
        async def goal_session_manager() -> AsyncGenerator[AsyncSession, None]:
            yield AsyncMock(spec=AsyncSession)

        bindings = await resolve_agent_tools(
            "agent-1",
            _make_toolkit_context(),
            execution_mode=ToolkitExecutionMode.SUBAGENT,
            toolkit_registry={},
            agent_toolkit_repository=agent_toolkit_repository,
            toolkit_repository=AsyncMock(),
            session_manager=_make_session_manager(session),
            web_url="https://example.test",
            oauth_secret_key="secret",
            mcp_proxy_url=None,
            workspace_handle="workspace",
            runtime_domain_config=RuntimeDomainConfig(
                allowed_domains=(),
                denied_domains=(),
            ),
            builtin_toolkit_provider=_make_builtin_provider(),
            claude_rules_toolkit_provider=ClaudeRulesToolkitProvider(
                store=_FakeClaudeRulesAppendixDedupeStateStore()
            ),
            goal_toolkit_provider=GoalToolkitProvider(
                store=GoalStateStore(
                    session_manager=goal_session_manager,
                    agent_run_repository=AgentRunRepository(),
                    agent_session_repository=AgentSessionRepository(),
                    event_transcript_repository=EventTranscriptRepository(),
                    toolkit_state_repository=ToolkitStateRepository(),
                )
            ),
            memory_enabled=True,
            runtime_tools_enabled=True,
        )

        assert [binding.slug for binding in bindings] == [
            "memory_read",
            "runtime",
            "claude_rules",
        ]
