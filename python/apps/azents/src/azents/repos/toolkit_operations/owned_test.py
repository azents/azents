"""Agent-owned Toolkit operation authority and lock-order tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentLifecycleStatus, WorkspaceUserRole
from azents.core.toolkit_errors import NotFound
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.github_user_installation import GithubUserInstallationRepository
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.data import ToolkitUpdate
from azents.repos.toolkit_namespace import ToolkitNamespaceRepository
from azents.repos.toolkit_operations import ToolkitOperationsRepository
from azents.repos.toolkit_operations.owned import AgentToolkitOperationsRepository


async def test_owned_update_preserves_lock_order_and_allows_duplicate_slug() -> None:
    """Lock Toolkit then Agent before updating and reallocating the namespace."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    active = False
    events: list[str] = []

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        nonlocal active
        active = True
        try:
            yield session
        finally:
            active = False

    toolkit_repo = AsyncMock(spec=ToolkitRepository)
    agent_repo = AsyncMock(spec=AgentRepository)
    namespace_repo = AsyncMock(spec=ToolkitNamespaceRepository)

    async def load_toolkit(db: WriteSession, toolkit_id: str) -> SimpleNamespace:
        assert active and db is session and toolkit_id == "toolkit-1"
        events.append("toolkit")
        return SimpleNamespace(
            owner_agent_id="agent-1",
            workspace_id="workspace-1",
            slug="old",
            enabled=True,
        )

    async def load_agent(db: WriteSession, agent_id: str) -> SimpleNamespace:
        assert active and db is session and agent_id == "agent-1"
        events.append("agent")
        return SimpleNamespace(
            workspace_id="workspace-1",
            lifecycle_status=AgentLifecycleStatus.ACTIVE,
        )

    updated = SimpleNamespace(slug="duplicate")
    toolkit_repo.get_by_id.side_effect = load_toolkit
    toolkit_repo.update_by_id.return_value = Success(updated)
    agent_repo.get_by_id.side_effect = load_agent
    repository = AgentToolkitOperationsRepository(
        toolkit_repo=toolkit_repo,
        mcp_oauth_connection_repo=AsyncMock(spec=MCPOAuthConnectionRepository),
        agent_repo=agent_repo,
        namespace_repo=namespace_repo,
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
        slug_reset_canonical_name=None,
        platform_authority=None,
    )

    assert result == Success(updated)
    assert events == ["toolkit", "agent"]
    assert not active
    toolkit_repo.update_by_id.assert_awaited_once()
    namespace_repo.ensure_active.assert_awaited_once_with(
        session,
        agent_id="agent-1",
        toolkit_id="toolkit-1",
        base_slug="duplicate",
    )

    toolkit_repo.get_by_id.side_effect = None
    toolkit_repo.get_by_id.return_value = SimpleNamespace(
        owner_agent_id="another-agent",
        workspace_id="workspace-1",
    )
    agent_repo.get_by_id.reset_mock()
    toolkit_repo.update_by_id.reset_mock()
    result = await repository.update_agent_owned(
        "agent-1",
        "toolkit-1",
        ToolkitUpdate(slug="duplicate"),
        workspace_id="workspace-1",
        workspace_user_id="member-1",
        role=WorkspaceUserRole.OWNER,
        slug_reset_canonical_name=None,
        platform_authority=None,
    )

    assert result == Failure(NotFound(toolkit_id="toolkit-1"))
    agent_repo.get_by_id.assert_not_awaited()
    toolkit_repo.update_by_id.assert_not_awaited()


async def test_owned_blank_slug_reset_uses_locked_current_name() -> None:
    """Derive an Agent-owned reset Slug from the locked Toolkit Name."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        yield session

    toolkit = SimpleNamespace(
        owner_agent_id="agent-1",
        workspace_id="workspace-1",
        name="Current Production",
        slug="old",
    )
    toolkit_repo = AsyncMock(spec=ToolkitRepository)
    toolkit_repo.get_by_id.return_value = toolkit
    toolkit_repo.update_by_id.return_value = Success(
        SimpleNamespace(slug="current_production")
    )
    agent_repo = AsyncMock(spec=AgentRepository)
    agent_repo.get_by_id.return_value = SimpleNamespace(
        workspace_id="workspace-1",
        lifecycle_status=AgentLifecycleStatus.ACTIVE,
    )
    repository = AgentToolkitOperationsRepository(
        toolkit_repo=toolkit_repo,
        mcp_oauth_connection_repo=AsyncMock(spec=MCPOAuthConnectionRepository),
        agent_repo=agent_repo,
        namespace_repo=AsyncMock(spec=ToolkitNamespaceRepository),
        agent_admin_repo=AsyncMock(spec=AgentAdminRepository),
        github_user_installation_repo=AsyncMock(spec=GithubUserInstallationRepository),
        session_manager=session_manager,
        shared_operations=AsyncMock(spec=ToolkitOperationsRepository),
    )

    result = await repository.update_agent_owned(
        "agent-1",
        "toolkit-1",
        ToolkitUpdate(),
        workspace_id="workspace-1",
        workspace_user_id="member-1",
        role=WorkspaceUserRole.OWNER,
        slug_reset_canonical_name="MCP",
        platform_authority=None,
    )

    assert isinstance(result, Success)
    call = toolkit_repo.update_by_id.await_args
    assert call is not None
    assert call.args[2]["slug"] == "current_production"
