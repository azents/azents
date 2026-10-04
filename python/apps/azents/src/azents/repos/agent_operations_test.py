"""Completed Agent service operation tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentType,
    ExternalChannelResponseMode,
    WorkspaceUserRole,
)
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent, AgentCreate
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_admin.data import AgentAdminCreate
from azents.repos.agent_decommission import AgentDecommissionRepository
from azents.repos.agent_operations import (
    AgentOperationNotAdmin,
    AgentOperationsRepository,
)
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.runtime_profile.availability import (
    RuntimeProfileAvailabilityRepository,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.workspace_model_settings import WorkspaceModelSettingsRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_options,
)


def _agent() -> Agent:
    """Build one Agent operation result."""
    now = datetime.datetime.now(datetime.UTC)
    selection = make_test_model_selection()
    return Agent(
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
        runtime_capability=AgentRuntimeCapability.NONE,
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


async def test_agent_atomic_operations_close_before_returning() -> None:
    """Create, update, and admin removal finish their shared transactions."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    transaction_active = False

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        nonlocal transaction_active
        transaction_active = True
        try:
            yield session
        finally:
            transaction_active = False

    agent = _agent()
    agent_repository = AsyncMock(spec=AgentRepository)
    admin_repository = AsyncMock(spec=AgentAdminRepository)
    agent_session_repository = AsyncMock(spec=AgentSessionRepository)
    workspace_user_repository = AsyncMock(spec=WorkspaceUserRepository)
    availability_repository = AsyncMock(spec=RuntimeProfileAvailabilityRepository)
    agent_repository.get_by_id.return_value = agent
    workspace_user_repository.get.return_value = SimpleNamespace(
        workspace_id=agent.workspace_id,
        role=WorkspaceUserRole.OWNER,
    )

    async def create_agent(
        current_session: WriteSession,
        create: AgentCreate,
    ) -> Agent:
        assert transaction_active
        assert current_session is session
        assert create.name == "Agent"
        return agent

    async def create_admin(
        current_session: WriteSession,
        create: AgentAdminCreate,
    ) -> object:
        assert transaction_active
        assert current_session is session
        assert create.agent_id == agent.id
        return object()

    async def update_agent(
        current_session: WriteSession,
        agent_id: str,
        update: object,
    ) -> Success[Agent]:
        assert transaction_active
        assert current_session is session
        assert agent_id == agent.id
        assert update
        return Success(agent)

    async def replace_profiles(
        current_session: WriteSession,
        **kwargs: object,
    ) -> None:
        assert transaction_active
        assert current_session is session
        assert kwargs["agent_id"] == agent.id

    async def count_admins(
        current_session: WriteSession,
        agent_id: str,
    ) -> int:
        assert transaction_active
        assert current_session is session
        assert agent_id == agent.id
        return 2

    async def delete_admin(
        current_session: WriteSession,
        agent_id: str,
        workspace_user_id: str,
    ) -> bool:
        assert transaction_active
        assert current_session is session
        assert agent_id == agent.id
        assert workspace_user_id == "workspace-user-2"
        return True

    agent_repository.create.side_effect = create_agent
    agent_repository.update_by_id.side_effect = update_agent
    admin_repository.create.side_effect = create_admin
    admin_repository.count_by_agent.side_effect = count_admins
    admin_repository.delete.side_effect = delete_admin
    agent_session_repository.replace_stale_applied_inference_profiles.side_effect = (
        replace_profiles
    )
    repository = AgentOperationsRepository(
        session_manager=session_manager,
        agent_repository=agent_repository,
        admin_repository=admin_repository,
        workspace_model_settings_repository=AsyncMock(
            spec=WorkspaceModelSettingsRepository
        ),
        workspace_user_repository=workspace_user_repository,
        agent_decommission_repository=AsyncMock(spec=AgentDecommissionRepository),
        archived_session_retention_repository=AsyncMock(
            spec=ArchivedSessionRetentionRepository
        ),
        agent_session_repository=agent_session_repository,
        runtime_profile_repository=AsyncMock(spec=RuntimeProfileRepository),
        runtime_profile_availability_repository=availability_repository,
    )
    create = AgentCreate(
        workspace_id=agent.workspace_id,
        name=agent.name,
        model_selection=agent.model_selection,
        lightweight_model_selection=agent.lightweight_model_selection,
        selectable_model_options=agent.selectable_model_options,
        main_model_label=agent.main_model_label,
        lightweight_model_label=agent.lightweight_model_label,
        description=agent.description,
        model_parameters=agent.model_parameters,
        system_prompt=agent.system_prompt,
        enabled=agent.enabled,
        external_channel_default_response_mode=(
            agent.external_channel_default_response_mode
        ),
        type=agent.type,
        runtime_profile_id=None,
        runtime_capability=agent.runtime_capability,
        terminal_enabled=agent.terminal_enabled,
        memory_enabled=agent.memory_enabled,
        tool_search_enabled=agent.tool_search_enabled,
        max_turns=agent.max_turns,
        auto_archive_ttl_days=agent.auto_archive_ttl_days,
        subagent_settings=agent.subagent_settings,
    )

    create_result = await repository.create(
        create,
        creator_workspace_user_id="workspace-user-1",
    )
    assert create_result == Success(agent)
    assert not transaction_active

    update_result = await repository.update_by_id(
        agent_id=agent.id,
        workspace_id=agent.workspace_id,
        workspace_user_id="workspace-user-1",
        update={"name": "Updated"},
        runtime_profile_change=None,
        model_configuration_changed=True,
        valid_model_target_labels=["default"],
        model_target_label="default",
        reasoning_effort=None,
    )
    assert update_result == Success(agent)
    assert not transaction_active

    remove_result = await repository.remove_admin(
        agent_id=agent.id,
        workspace_user_id="workspace-user-2",
    )
    assert remove_result == Success(None)
    assert not transaction_active


async def test_update_rejects_revoked_admin_before_mutation() -> None:
    """Final Agent mutation rechecks current authority in its transaction."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        yield session

    agent = _agent()
    agent_repository = AsyncMock(spec=AgentRepository)
    admin_repository = AsyncMock(spec=AgentAdminRepository)
    workspace_user_repository = AsyncMock(spec=WorkspaceUserRepository)
    agent_repository.get_by_id.return_value = agent
    workspace_user_repository.get.return_value = SimpleNamespace(
        workspace_id=agent.workspace_id,
        role=WorkspaceUserRole.MEMBER,
    )
    admin_repository.is_admin.return_value = False
    repository = AgentOperationsRepository(
        session_manager=session_manager,
        agent_repository=agent_repository,
        admin_repository=admin_repository,
        workspace_model_settings_repository=AsyncMock(
            spec=WorkspaceModelSettingsRepository
        ),
        workspace_user_repository=workspace_user_repository,
        agent_decommission_repository=AsyncMock(spec=AgentDecommissionRepository),
        archived_session_retention_repository=AsyncMock(
            spec=ArchivedSessionRetentionRepository
        ),
        agent_session_repository=AsyncMock(spec=AgentSessionRepository),
        runtime_profile_repository=AsyncMock(spec=RuntimeProfileRepository),
        runtime_profile_availability_repository=AsyncMock(
            spec=RuntimeProfileAvailabilityRepository
        ),
    )

    result = await repository.update_by_id(
        agent_id=agent.id,
        workspace_id=agent.workspace_id,
        workspace_user_id="workspace-user-1",
        update={"name": "Rejected"},
        runtime_profile_change=None,
        model_configuration_changed=False,
        valid_model_target_labels=["default"],
        model_target_label="default",
        reasoning_effort=None,
    )

    assert result.failure
    assert isinstance(result.error, AgentOperationNotAdmin)
    agent_repository.update_by_id.assert_not_awaited()
