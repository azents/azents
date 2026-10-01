"""Completed Engine read operation tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.credentials import ApiKeySecrets
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentType,
    ExternalChannelResponseMode,
    LLMProvider,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.engine_read import (
    EngineInvokeReadRepository,
    EngineModelReadRepository,
    EngineToolkitReadRepository,
)
from azents.repos.llm_provider_integration import LLMProviderIntegrationRepository
from azents.repos.llm_provider_integration.data import LLMProviderIntegrationWithSecrets
from azents.repos.toolkit import ToolkitRepository
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_options,
)


async def test_engine_reads_complete_their_sessions_before_returning() -> None:
    """Engine snapshots return only after their repository transactions close."""
    session = AsyncMock(spec=AsyncSession)
    transaction_active = False

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        nonlocal transaction_active
        transaction_active = True
        try:
            yield session
        finally:
            transaction_active = False

    selection = make_test_model_selection(integration_id="integration-1")
    now = datetime.datetime.now(datetime.UTC)
    agent = Agent(
        id="agent-1",
        workspace_id="workspace-1",
        name="Agent",
        description=None,
        model_selection=selection,
        lightweight_model_selection=selection,
        selectable_model_options=make_test_selectable_model_options(selection),
        main_model_label="default",
        lightweight_model_label="default",
        model_parameters=None,
        system_prompt=None,
        enabled=True,
        external_channel_default_response_mode=(
            ExternalChannelResponseMode.ALL_MESSAGES
        ),
        lifecycle_status=AgentLifecycleStatus.ACTIVE,
        type=AgentType.PUBLIC,
        runtime_profile_id=None,
        runtime_profile_selection_version=1,
        runtime_capability=AgentRuntimeCapability.MANAGED,
        runtime_capability_version=1,
        terminal_enabled=True,
        memory_enabled=True,
        tool_search_enabled=True,
        max_turns=None,
        auto_archive_ttl_days=30,
        avatar=None,
        created_at=now,
        updated_at=now,
    )
    integration = LLMProviderIntegrationWithSecrets(
        id="integration-1",
        workspace_id="workspace-1",
        provider=LLMProvider.OPENAI,
        name="OpenAI",
        secrets=ApiKeySecrets(api_key="test"),
        config=None,
        enabled=True,
        created_at=now,
        updated_at=now,
        catalog_configuration_version=1,
    )
    agent_repository = AsyncMock(spec=AgentRepository)
    integration_repository = AsyncMock(spec=LLMProviderIntegrationRepository)
    toolkit_repository = AsyncMock(spec=ToolkitRepository)

    async def get_agent(
        current_session: AsyncSession,
        agent_id: str,
    ) -> Agent:
        assert transaction_active
        assert current_session is session
        assert agent_id == "agent-1"
        return agent

    async def get_integration(
        current_session: AsyncSession,
        integration_id: str,
    ) -> LLMProviderIntegrationWithSecrets:
        assert transaction_active
        assert current_session is session
        assert integration_id == "integration-1"
        return integration

    async def list_toolkits(
        current_session: AsyncSession,
        agent_id: str,
        *,
        workspace_id: str,
    ) -> list[object]:
        assert transaction_active
        assert current_session is session
        assert agent_id == "agent-1"
        assert workspace_id == "workspace-1"
        return []

    agent_repository.get_by_id.side_effect = get_agent
    integration_repository.get_by_id_with_secrets.side_effect = get_integration
    toolkit_repository.list_effective_for_agent.side_effect = list_toolkits

    invoke_result = await EngineInvokeReadRepository(
        session_manager=session_manager,
        agent_repository=agent_repository,
        integration_repository=integration_repository,
    ).load_model_source(
        agent_id="agent-1",
        model_source_agent_id="agent-1",
        requested_profile=None,
        resolved_model_selection=None,
        resolved_model_settings=None,
    )

    assert isinstance(invoke_result, Success)
    assert invoke_result.value.agent == agent
    assert not transaction_active

    loaded_integration = await EngineModelReadRepository(
        session_manager=session_manager,
        integration_repository=integration_repository,
    ).get_integration("integration-1")

    assert loaded_integration == integration
    assert not transaction_active

    toolkits = await EngineToolkitReadRepository(
        session_manager=session_manager,
        toolkit_repository=toolkit_repository,
    ).list_effective_for_agent(
        "agent-1",
        workspace_id="workspace-1",
    )

    assert toolkits == []
    assert not transaction_active
