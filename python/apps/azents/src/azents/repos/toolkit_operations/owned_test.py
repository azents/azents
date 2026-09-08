"""Agent-owned Toolkit operation authority and lock-order tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from azcommon.result import Failure
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentLifecycleStatus, WorkspaceUserRole
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.github_user_installation import GithubUserInstallationRepository
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.data import NotFound, ToolkitUpdate
from azents.repos.toolkit_operations import ToolkitOperationsRepository
from azents.repos.toolkit_operations.data import EffectiveSlugConflict
from azents.repos.toolkit_operations.owned import AgentToolkitOperationsRepository


async def test_owned_update_preserves_lock_order_and_rejects_namespace_conflict() -> (
    None
):
    """Lock Toolkit then Agent before checking the namespace in the same lifetime."""
    session = AsyncMock(spec=AsyncSession)
    active = False
    events: list[str] = []

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        nonlocal active
        active = True
        try:
            yield session
        finally:
            active = False

    toolkit_repo = AsyncMock(spec=ToolkitRepository)
    agent_repo = AsyncMock(spec=AgentRepository)

    async def load_toolkit(db: AsyncSession, toolkit_id: str) -> SimpleNamespace:
        assert active and db is session and toolkit_id == "toolkit-1"
        events.append("toolkit")
        return SimpleNamespace(
            owner_agent_id="agent-1",
            workspace_id="workspace-1",
            slug="old",
            enabled=True,
        )

    async def load_agent(db: AsyncSession, agent_id: str) -> SimpleNamespace:
        assert active and db is session and agent_id == "agent-1"
        events.append("agent")
        return SimpleNamespace(
            workspace_id="workspace-1",
            lifecycle_status=AgentLifecycleStatus.ACTIVE,
        )

    toolkit_repo.get_by_id_for_update.side_effect = load_toolkit
    agent_repo.lock_by_id.side_effect = load_agent
    toolkit_repo.has_effective_slug_conflict.return_value = True
    repository = AgentToolkitOperationsRepository(
        toolkit_repo=toolkit_repo,
        mcp_oauth_connection_repo=AsyncMock(spec=MCPOAuthConnectionRepository),
        agent_repo=agent_repo,
        agent_admin_repo=AsyncMock(spec=AgentAdminRepository),
        github_user_installation_repo=AsyncMock(spec=GithubUserInstallationRepository),
        session_manager=session_manager,
        shared_operations=AsyncMock(spec=ToolkitOperationsRepository),
    )
    result = await repository.update_agent_owned(
        "agent-1",
        "toolkit-1",
        ToolkitUpdate(slug="duplicate"),
        workspace_id="workspace-1",
        workspace_user_id="member-1",
        role=WorkspaceUserRole.OWNER,
        platform_authority=None,
    )
    assert result == Failure(EffectiveSlugConflict(slug="duplicate"))
    assert events == ["toolkit", "agent"]
    assert not active
    toolkit_repo.update_by_id.assert_not_awaited()

    toolkit_repo.get_by_id_for_update.side_effect = None
    toolkit_repo.get_by_id_for_update.return_value = SimpleNamespace(
        owner_agent_id="another-agent",
        workspace_id="workspace-1",
    )
    agent_repo.lock_by_id.reset_mock()
    result = await repository.update_agent_owned(
        "agent-1",
        "toolkit-1",
        ToolkitUpdate(slug="duplicate"),
        workspace_id="workspace-1",
        workspace_user_id="member-1",
        role=WorkspaceUserRole.OWNER,
        platform_authority=None,
    )
    assert result == Failure(NotFound(toolkit_id="toolkit-1"))
    agent_repo.lock_by_id.assert_not_awaited()
    toolkit_repo.update_by_id.assert_not_awaited()
