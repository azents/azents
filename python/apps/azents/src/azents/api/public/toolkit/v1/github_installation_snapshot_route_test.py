"""Typed GitHub installation snapshots retain the Agent callback wire policy."""

from collections.abc import Sequence
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Result, Success

import azents.api.public.toolkit.v1.oauth as oauth_module
from azents.api.public.toolkit.v1.oauth import (
    GitHubPlatformInstallationsRequest,
    get_agent_github_platform_installations,
)
from azents.api.public.toolkit.v1.oauth_agent_test import _config, _member
from azents.core.enums import WorkspaceUserRole
from azents.core.github_installation import GitHubInstallationSnapshot
from azents.core.oauth2 import create_agent_github_platform_oauth_state
from azents.core.system_setting import SystemSettingFieldSource
from azents.services.agent.data import NotAdmin
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
    ResolvedPlatformGitHubApp,
)
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.data import AgentNotBelongToWorkspace


class _InstallationService(ToolkitService):
    """Assert the exact authorized call and retain every installation in order."""

    def __init__(self) -> None:
        self.synced: tuple[GitHubInstallationSnapshot, ...] | None = None

    async def authorize_agent_management(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[None, AgentNotBelongToWorkspace | NotAdmin]:
        assert (agent_id, workspace_id, workspace_user_id, role) == (
            "agent-1",
            "workspace-1",
            "workspace-user-1",
            WorkspaceUserRole.OWNER,
        )
        return Success(None)

    async def sync_agent_github_installations(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        user_id: str,
        role: WorkspaceUserRole,
        platform_app_id: str,
        installations: Sequence[GitHubInstallationSnapshot],
    ) -> Result[None, AgentNotBelongToWorkspace | NotAdmin]:
        assert (
            agent_id,
            workspace_id,
            workspace_user_id,
            user_id,
            role,
            platform_app_id,
        ) == (
            "agent-1",
            "workspace-1",
            "workspace-user-1",
            "user-1",
            WorkspaceUserRole.OWNER,
            "123",
        )
        self.synced = tuple(installations)
        return Success(None)


class _InstallationRuntime(PlatformGitHubAppRuntimeService):
    def __init__(self) -> None:
        """This fixture resolves its explicit synthetic credential snapshot."""
        pass

    async def resolve(self) -> ResolvedPlatformGitHubApp:
        return ResolvedPlatformGitHubApp(
            app_id="123",
            client_id="client-id",
            private_key="private-key",
            client_secret="client-secret",
            effective_generation="generation-1",
            app_id_source=SystemSettingFieldSource.ADMIN,
        )


async def test_agent_installation_snapshots_preserve_order_duplicates_and_avatar_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshots = (
        GitHubInstallationSnapshot(
            42, None, "first", "Organization", "https://example.test/a"
        ),
        GitHubInstallationSnapshot(7, None, "no-avatar", "User", None),
        GitHubInstallationSnapshot(True, None, "bool-id", "User", ""),
        GitHubInstallationSnapshot(
            42, None, "duplicate", "Organization", "https://example.test/b"
        ),
    )
    monkeypatch.setattr(
        oauth_module, "exchange_oauth_code", AsyncMock(return_value="user-token")
    )
    monkeypatch.setattr(
        oauth_module, "list_user_installations", AsyncMock(return_value=snapshots)
    )
    revoke = AsyncMock()
    monkeypatch.setattr(oauth_module, "revoke_oauth_token", revoke)
    service = _InstallationService()
    state = create_agent_github_platform_oauth_state(
        "state-secret",
        effective_generation="generation-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        user_id="user-1",
        redirect_uri="https://app.test/oauth/github/callback",
        callback_target="agent_github_installations",
    )
    response = await get_agent_github_platform_installations(
        _member(),
        service,
        _config(),
        _InstallationRuntime(),
        GitHubPlatformInstallationsRequest(code="code", state=state),
        handle="workspace",
        agent_id="agent-1",
    )
    assert service.synced == snapshots
    assert [item.id for item in response.installations] == [42, 1, 42]
    assert [item.account_login for item in response.installations] == [
        "first",
        "bool-id",
        "duplicate",
    ]
    assert [item.account_avatar_url for item in response.installations] == [
        "https://example.test/a",
        "",
        "https://example.test/b",
    ]
    revoke.assert_awaited_once_with("client-id", "client-secret", "user-token")
