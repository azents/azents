"""Agent run resolve tests."""

import datetime
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import ApiKeySecrets
from azents.core.enums import AgentType, LLMProvider
from azents.core.tools import (
    SessionType,
    ToolkitContext,
    ToolkitExecutionMode,
    TurnContext,
)
from azents.engine.run.input import InputMessage, InvokeInput
from azents.engine.tools.builtin import BuiltinToolkitProvider
from azents.engine.tools.builtin_agents import AgentsAppendixDedupeState
from azents.engine.tools.claude_rules import (
    ClaudeRulesAppendixDedupeState,
    ClaudeRulesToolkitProvider,
)
from azents.engine.tools.goal import GoalStateStore, GoalToolkitProvider
from azents.engine.tools.subagent import SubagentToolkitProvider
from azents.repos.agent.data import Agent
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.runtime.types import RuntimeDomainConfig
from azents.testing.model_selection import make_test_model_selection

from .resolve import resolve_agent_tools, resolve_invoke_input

_NOW = datetime.datetime.now(datetime.timezone.utc)


def _make_agent() -> Agent:
    """Create Agent for tests."""
    selection = make_test_model_selection(integration_id="integ-1")
    return Agent(
        id="agent-1",
        workspace_id="ws-1",
        name="agent",
        description=None,
        model_selection=selection,
        lightweight_model_selection=selection,
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
        mutator: Callable[
            [ClaudeRulesAppendixDedupeState], ClaudeRulesAppendixDedupeState
        ],
    ) -> None:
        """Ignore dedupe updates."""
        del agent_id, session_id, mutator


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
        mutator: Callable[[AgentsAppendixDedupeState], AgentsAppendixDedupeState],
    ) -> None:
        """Ignore dedupe updates."""
        del agent_id, session_id, mutator


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


def _make_subagent_provider() -> SubagentToolkitProvider:
    """Create SubagentToolkitProvider for resolve_agent_tools tests."""
    return SubagentToolkitProvider(
        session_manager=AsyncMock(),
        broker=AsyncMock(),
        input_buffer_service=AsyncMock(),
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


class TestResolveAgentTools:
    """resolve_agent_tools auto-bound Toolkit tests."""

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
            session=session,
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
            session=session,
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
            runtime_tools_enabled=False,
        )

        assert [binding.slug for binding in bindings] == ["memory_read", "memory_write"]

    async def test_auto_binds_subagent_toolkit_in_root_mode(self) -> None:
        """Root sessions receive the coherent subagent collaboration bundle."""
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
            session=session,
            web_url="https://example.test",
            oauth_secret_key="secret",
            mcp_proxy_url=None,
            runtime_domain_config=RuntimeDomainConfig(
                allowed_domains=(),
                denied_domains=(),
            ),
            subagent_toolkit_provider=_make_subagent_provider(),
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
            session=session,
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
            memory_enabled=True,
            runtime_tools_enabled=True,
        )

        assert [binding.slug for binding in bindings] == [
            "memory_read",
            "runtime",
            "claude_rules",
        ]
