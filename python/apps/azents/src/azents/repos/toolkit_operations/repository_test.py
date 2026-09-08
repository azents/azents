"""Toolkit operation repository transaction tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import MCPOAuthConnectionStatus, ToolkitScopeType
from azents.core.system_setting import SystemSettingFieldSource
from azents.repos.agent import AgentRepository
from azents.repos.github_user_installation import GithubUserInstallationRepository
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.mcp_oauth_connection.data import MCPOAuthConnectionSummary
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.repos.toolkit import (
    AgentToolkitRepository,
    ToolkitRepository,
    ToolkitScopeRepository,
)
from azents.repos.toolkit.data import (
    ToolkitConfig,
    ToolkitCreate,
    ToolkitScope,
    ToolkitUpdate,
)
from azents.repos.workspace_user import WorkspaceUserRepository

from . import ToolkitOperationsRepository
from .data import (
    PlatformAuthorityRejected,
    PlatformToolkitAuthority,
    ToolkitWorkspaceMismatch,
)


class _OAuthAttachFailure(RuntimeError):
    """Stop create while the response OAuth summary is being attached."""


class _TrackedSessionManager:
    """Deterministic commit/rollback probe for one repository operation."""

    def __init__(self) -> None:
        self.session = AsyncMock(spec=AsyncSession)
        self.active = False
        self.committed = False
        self.rolled_back = False

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        self.active = True
        try:
            yield self.session
        except Exception:
            self.rolled_back = True
            raise
        else:
            self.committed = True
        finally:
            self.active = False


def _toolkit(*, workspace_id: str = "workspace-1") -> ToolkitConfig:
    now = datetime.datetime.now(datetime.UTC)
    return ToolkitConfig(
        id="toolkit-1",
        workspace_id=workspace_id,
        toolkit_type="mcp",
        slug="toolkit",
        name="Toolkit",
        config={"url": "https://example.test", "auth_type": "oauth2"},
        credentials=None,
        enabled=True,
        always_expose_tools=False,
        revision=1,
        created_at=now,
        updated_at=now,
    )


def _scope() -> ToolkitScope:
    return ToolkitScope(
        id="scope-1",
        toolkit_id="toolkit-1",
        scope_type=ToolkitScopeType.WORKSPACE,
        scope_id="workspace-1",
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _create() -> ToolkitCreate:
    return ToolkitCreate(
        workspace_id="workspace-1",
        toolkit_type="mcp",
        slug="toolkit",
        name="Toolkit",
        config={"url": "https://example.test", "auth_type": "oauth2"},
        credentials=None,
        always_expose_tools=False,
    )


def _repository(
    session_manager: _TrackedSessionManager,
) -> tuple[
    ToolkitOperationsRepository,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
]:
    toolkit_repository = AsyncMock(spec=ToolkitRepository)
    scope_repository = AsyncMock(spec=ToolkitScopeRepository)
    oauth_repository = AsyncMock(spec=MCPOAuthConnectionRepository)
    github_repository = AsyncMock(spec=GithubUserInstallationRepository)
    system_setting_repository = AsyncMock(spec=SystemSettingRepository)
    agent_toolkit_repository = AsyncMock(spec=AgentToolkitRepository)
    repository = ToolkitOperationsRepository(
        toolkit_repository=toolkit_repository,
        scope_repository=scope_repository,
        agent_toolkit_repository=agent_toolkit_repository,
        agent_repository=AsyncMock(spec=AgentRepository),
        workspace_user_repository=AsyncMock(spec=WorkspaceUserRepository),
        github_installation_repository=github_repository,
        oauth_connection_repository=oauth_repository,
        system_setting_repository=system_setting_repository,
        session_manager=session_manager,
    )
    return (
        repository,
        toolkit_repository,
        scope_repository,
        oauth_repository,
        github_repository,
        system_setting_repository,
    )


def _platform_authority() -> PlatformToolkitAuthority:
    return PlatformToolkitAuthority(
        app_id="123",
        app_id_source=SystemSettingFieldSource.ADMIN,
        user_id="user-1",
        installation_ids=frozenset({456}),
    )


async def test_create_composes_scope_and_oauth_summary_in_one_transaction() -> None:
    """Create, default Scope, and OAuth projection share one DB lifetime."""
    session_manager = _TrackedSessionManager()
    repository, toolkit_repo, scope_repo, oauth_repo, _, _ = _repository(
        session_manager
    )
    toolkit_repo.create.return_value = Success(_toolkit())
    scope_repo.create.return_value = Success(_scope())
    summary = MCPOAuthConnectionSummary(
        status=MCPOAuthConnectionStatus.CONNECTED,
        issuer="https://issuer.example",
        resource=None,
        scope="read",
        expires_at=None,
    )
    oauth_repo.get_summary_by_toolkit_id.return_value = summary

    result = await repository.create(_create(), platform_authority=None)

    assert isinstance(result, Success)
    assert result.value.oauth_connection == summary
    create_session = toolkit_repo.create.await_args.args[0]
    scope_session = scope_repo.create.await_args.args[0]
    oauth_session = oauth_repo.get_summary_by_toolkit_id.await_args.args[0]
    assert create_session is session_manager.session
    assert scope_session is session_manager.session
    assert oauth_session is session_manager.session
    assert session_manager.committed is True
    assert session_manager.rolled_back is False


async def test_create_rolls_back_when_oauth_attach_fails() -> None:
    """OAuth projection failure cannot commit Toolkit without its Scope."""
    session_manager = _TrackedSessionManager()
    repository, toolkit_repo, scope_repo, oauth_repo, _, _ = _repository(
        session_manager
    )
    toolkit_repo.create.return_value = Success(_toolkit())
    scope_repo.create.return_value = Success(_scope())
    oauth_repo.get_summary_by_toolkit_id.side_effect = _OAuthAttachFailure

    with pytest.raises(_OAuthAttachFailure):
        await repository.create(_create(), platform_authority=None)

    assert session_manager.rolled_back is True
    assert session_manager.committed is False
    toolkit_repo.create.assert_awaited_once()
    scope_repo.create.assert_awaited_once()


@pytest.mark.parametrize(
    ("locked_toolkit", "error_type"),
    [
        (None, type(None)),
        (_toolkit(workspace_id="workspace-2"), ToolkitWorkspaceMismatch),
    ],
)
async def test_update_revalidates_current_toolkit_and_workspace(
    locked_toolkit: ToolkitConfig | None,
    error_type: type[object],
) -> None:
    """A stale preflight cannot authorize a deleted or moved Toolkit mutation."""
    session_manager = _TrackedSessionManager()
    repository, toolkit_repo, _, _, _, _ = _repository(session_manager)
    toolkit_repo.get_by_id.return_value = locked_toolkit

    result = await repository.update(
        "toolkit-1",
        ToolkitUpdate(name="Updated"),
        workspace_id="workspace-1",
        expected_toolkit_type="mcp",
        platform_authority=None,
    )

    assert isinstance(result, Failure)
    if error_type is type(None):
        assert result.error.__class__.__name__ == "NotFound"
    else:
        assert isinstance(result.error, error_type)
    toolkit_repo.update_by_id.assert_not_awaited()


async def test_update_rejects_platform_reconnect_race_before_mutation() -> None:
    """A changed effective App identity invalidates prepared credentials."""
    session_manager = _TrackedSessionManager()
    repository, toolkit_repo, _, _, github_repo, setting_repo = _repository(
        session_manager
    )
    setting_repo.get_current.return_value = SimpleNamespace(config={"app_id": "999"})

    result = await repository.update(
        "toolkit-1",
        ToolkitUpdate(name="Updated"),
        workspace_id="workspace-1",
        expected_toolkit_type="github",
        platform_authority=_platform_authority(),
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, PlatformAuthorityRejected)
    assert result.error.detail == "GitHub Platform App reconnect is required."
    toolkit_repo.get_by_id.assert_not_awaited()
    toolkit_repo.update_by_id.assert_not_awaited()
    github_repo.list_accessible_installation_ids.assert_not_awaited()


async def test_update_rejects_revoked_installation_before_mutation() -> None:
    """Final validation rejects access revoked after provider preparation."""
    session_manager = _TrackedSessionManager()
    repository, toolkit_repo, _, _, github_repo, setting_repo = _repository(
        session_manager
    )
    setting_repo.get_current.return_value = SimpleNamespace(config={"app_id": "123"})
    github_repo.list_accessible_installation_ids.return_value = frozenset()

    result = await repository.update(
        "toolkit-1",
        ToolkitUpdate(name="Updated"),
        workspace_id="workspace-1",
        expected_toolkit_type="github",
        platform_authority=_platform_authority(),
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, PlatformAuthorityRejected)
    assert result.error.detail == (
        "GitHub installation is not accessible to this user."
    )
    toolkit_repo.get_by_id.assert_not_awaited()
    toolkit_repo.update_by_id.assert_not_awaited()
