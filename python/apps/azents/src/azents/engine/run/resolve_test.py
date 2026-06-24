"""Agent run resolve tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import ApiKeySecrets
from azents.core.enums import AgentRole, AgentType, LLMProvider
from azents.engine.run.input import InputMessage, InvokeInput
from azents.repos.agent.data import Agent
from azents.repos.agent_subagent.data import SubagentToolkitInheritMode
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.testing.model_selection import make_test_model_selection

from .resolve import resolve_invoke_input

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
        role=AgentRole.AGENT,
        runtime_provider_id=None,
        shell_enabled=True,
        memory_enabled=True,
        max_turns=None,
        toolkit_inherit_mode=SubagentToolkitInheritMode.ALL,
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
