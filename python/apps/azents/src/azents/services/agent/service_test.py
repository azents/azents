"""AgentService model snapshot behavior tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast
from unittest.mock import AsyncMock

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import (
    DEFAULT_MAIN_MODEL_OPTION_LABEL,
    AgentModelSelectionInput,
    SelectableModelOption,
)
from azents.core.enums import AgentLifecycleStatus, AgentType
from azents.repos.agent.data import Agent
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)

from . import AgentService
from .data import AgentCreateInput, ModelRequired

_NOW = datetime.datetime.now(datetime.timezone.utc)


def _make_agent(agent_id: str = "agent-1") -> Agent:
    """Create Agent for tests."""
    selection = make_test_model_selection()
    return Agent(
        id=agent_id,
        workspace_id="ws-1",
        name="Test agent",
        description=None,
        model_selection=selection,
        lightweight_model_selection=selection,
        selectable_model_options=[
            SelectableModelOption(
                label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
                model_selection=selection,
                settings=make_test_model_settings(),
            )
        ],
        main_model_label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
        lightweight_model_label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
        model_parameters=None,
        system_prompt=None,
        enabled=True,
        lifecycle_status=AgentLifecycleStatus.ACTIVE,
        type=AgentType.PUBLIC,
        runtime_provider_id=None,
        shell_enabled=True,
        memory_enabled=True,
        tool_search_enabled=False,
        max_turns=None,
        avatar=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_service() -> AgentService:
    """Create AgentService with mock dependencies."""
    repository = AsyncMock()
    admin_repository = AsyncMock()
    workspace_model_settings_repository = AsyncMock()
    model_catalog_read_service = AsyncMock()
    workspace_user_repository = AsyncMock()
    agent_decommission_repository = AsyncMock()
    archived_session_retention_repository = AsyncMock()
    upload_service = AsyncMock()
    avatar_handler = AsyncMock()
    s3_service = AsyncMock()

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield AsyncMock(spec=AsyncSession)

    return AgentService(
        repository=repository,
        admin_repository=admin_repository,
        workspace_model_settings_repository=workspace_model_settings_repository,
        model_catalog_read_service=model_catalog_read_service,
        workspace_user_repository=workspace_user_repository,
        agent_decommission_repository=agent_decommission_repository,
        archived_session_retention_repository=archived_session_retention_repository,
        upload_service=upload_service,
        avatar_handler=avatar_handler,
        s3_service=s3_service,
        workspace_s3_bucket="bucket",
        avatar_cdn_base_url=None,
        session_manager=session_manager,
    )


class TestAgentServiceModelSelection:
    """Agent model selection copy behavior tests."""

    async def test_create_requires_model_when_workspace_default_absent(self) -> None:
        """Creation without model selection fails when workspace default is absent."""
        service = _make_service()
        settings = AsyncMock()
        settings.default_model_selection = None
        settings.default_lightweight_model_selection = None
        settings.default_selectable_model_options = None
        settings.default_main_model_label = None
        settings.default_lightweight_model_label = None
        settings_repo = cast(Any, service.workspace_model_settings_repository)
        settings_repo.get_or_create.return_value = settings

        result = await service.create(
            AgentCreateInput(workspace_id="ws-1", name="agent"),
            creator_workspace_user_id="wu-1",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ModelRequired)

    async def test_create_bootstraps_default_from_explicit_model(self) -> None:
        """Explicit model creation sets workspace default."""
        service = _make_service()
        selection = make_test_model_selection()
        settings = AsyncMock()
        settings.default_model_selection = None
        settings.default_lightweight_model_selection = None
        settings.default_selectable_model_options = None
        settings.default_main_model_label = None
        settings.default_lightweight_model_label = None
        settings_repo = cast(Any, service.workspace_model_settings_repository)
        catalog_read_service = cast(Any, service.model_catalog_read_service)
        agent_repo = cast(Any, service.repository)
        admin_repo = cast(Any, service.admin_repository)
        settings_repo.get_or_create.return_value = settings
        catalog_read_service.resolve_agent_model_selection.return_value = Success(
            selection
        )
        agent_repo.create.return_value = _make_agent()
        admin_repo.create.return_value = AsyncMock()

        result = await service.create(
            AgentCreateInput(
                workspace_id="ws-1",
                name="agent",
                model_selection=AgentModelSelectionInput(
                    llm_provider_integration_id="integ-1",
                    model_identifier="gpt-4o",
                ),
            ),
            creator_workspace_user_id="wu-1",
        )

        assert isinstance(result, Success)
        settings_repo.set_default_model_if_empty.assert_awaited_once()
        repository_create = agent_repo.create.await_args.args[1]
        assert repository_create.runtime_provider_id is None
        assert repository_create.tool_search_enabled is True

    async def test_create_preserves_explicit_tool_search_opt_out(self) -> None:
        """Creation forwards an explicit Tool Search opt-out to the repository."""
        service = _make_service()
        selection = make_test_model_selection()
        settings = AsyncMock()
        settings.default_model_selection = None
        settings.default_lightweight_model_selection = None
        settings.default_selectable_model_options = None
        settings.default_main_model_label = None
        settings.default_lightweight_model_label = None
        settings_repo = cast(Any, service.workspace_model_settings_repository)
        catalog_read_service = cast(Any, service.model_catalog_read_service)
        agent_repo = cast(Any, service.repository)
        admin_repo = cast(Any, service.admin_repository)
        settings_repo.get_or_create.return_value = settings
        catalog_read_service.resolve_agent_model_selection.return_value = Success(
            selection
        )
        agent_repo.create.return_value = _make_agent()
        admin_repo.create.return_value = AsyncMock()

        result = await service.create(
            AgentCreateInput(
                workspace_id="ws-1",
                name="agent",
                model_selection=AgentModelSelectionInput(
                    llm_provider_integration_id="integ-1",
                    model_identifier="gpt-4o",
                ),
                tool_search_enabled=False,
            ),
            creator_workspace_user_id="wu-1",
        )

        assert isinstance(result, Success)
        repository_create = agent_repo.create.await_args.args[1]
        assert repository_create.tool_search_enabled is False
