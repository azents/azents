"""Agent-owned Toolkit setup and OAuth authorization tests."""

import datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from azcommon.result import Failure, Success
from fastapi import HTTPException

import azents.api.public.toolkit.v1.oauth as oauth_module
from azents.api.public.toolkit.v1.oauth import (
    GitHubPlatformInstallationsRequest,
    OAuthExchangeRequest,
    _authorize_agent_management_or_error,
    connect_agent_oauth,
    disconnect_agent_oauth_connection,
    exchange_agent_oauth_connection,
    get_agent_github_platform_installations,
)
from azents.core.auth.deps import WorkspaceMember
from azents.core.config import Config
from azents.core.enums import WorkspaceUserRole
from azents.core.mcp_discovery import OAuthServerMetadata
from azents.core.oauth2 import (
    create_agent_github_platform_oauth_state,
    create_agent_toolkit_oauth_state,
)
from azents.core.system_setting import SystemSettingFieldSource
from azents.engine.tools.mcp import McpToolkitProvider
from azents.services.agent.data import NotAdmin
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
    ResolvedPlatformGitHubApp,
)
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.data import (
    AgentNotBelongToWorkspace,
    AgentToolkitOAuthContext,
    ToolkitOutput,
)


def _member(*, role: WorkspaceUserRole = WorkspaceUserRole.OWNER) -> WorkspaceMember:
    """Build an authenticated Workspace member context."""
    return WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=role,
        permissions=set(),
        session_id="session-1",
    )


def _agent_toolkit() -> ToolkitOutput:
    """Build an Agent-owned MCP OAuth Toolkit output."""
    now = datetime.datetime.now(datetime.UTC)
    return ToolkitOutput(
        id="toolkit-1",
        workspace_id="workspace-1",
        owner_agent_id="agent-1",
        toolkit_type="mcp",
        slug="private_mcp",
        name="Private MCP",
        config={
            "server_url": "https://mcp.test",
            "auth_type": "oauth2",
            "auth_url": "https://mcp.test/authorize",
            "token_url": "https://mcp.test/token",
        },
        credentials=(
            '{"type":"oauth2","client_id":"client-1","client_secret":"secret-1"}'
        ),
        enabled=True,
        always_expose_tools=False,
        revision=1,
        created_at=now,
        updated_at=now,
    )


def _config() -> Config:
    """Build the Config fields used by Agent OAuth routes."""
    return cast(
        Config,
        SimpleNamespace(
            web_url="https://app.test",
            mcp_proxy_url=None,
            credential_encryption=SimpleNamespace(key="state-secret"),
        ),
    )


async def test_agent_level_authorization_maps_missing_and_denied_separately() -> None:
    """Agent-level setup uses 404 for missing Agent and 403 for denied authority."""
    member = _member(role=WorkspaceUserRole.MANAGER)
    service = cast(Any, MagicMock(spec=ToolkitService))
    service.authorize_agent_management = AsyncMock(
        return_value=Failure(AgentNotBelongToWorkspace(agent_id="agent-1"))
    )

    with pytest.raises(HTTPException) as missing:
        await _authorize_agent_management_or_error(
            cast(ToolkitService, service),
            member,
            agent_id="agent-1",
        )

    assert missing.value.status_code == 404

    service.authorize_agent_management.return_value = Failure(
        NotAdmin(agent_id="agent-1")
    )
    with pytest.raises(HTTPException) as denied:
        await _authorize_agent_management_or_error(
            cast(ToolkitService, service),
            member,
            agent_id="agent-1",
        )

    assert denied.value.status_code == 403


async def test_agent_github_callback_rejects_cross_user_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A state issued to another User cannot populate the current User's access."""
    state = create_agent_github_platform_oauth_state(
        "state-secret",
        effective_generation="generation-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        user_id="user-other",
        redirect_uri="https://app.test/oauth/github/callback",
        callback_target="agent_github_installations",
    )
    service = cast(Any, MagicMock(spec=ToolkitService))
    service.authorize_agent_management = AsyncMock(return_value=Success(None))
    service.sync_agent_github_installations = AsyncMock()
    runtime = cast(Any, MagicMock(spec=PlatformGitHubAppRuntimeService))
    runtime.resolve = AsyncMock()
    exchange = AsyncMock()
    monkeypatch.setattr(oauth_module, "exchange_oauth_code", exchange)

    with pytest.raises(HTTPException) as raised:
        await get_agent_github_platform_installations(
            _member(),
            cast(ToolkitService, service),
            _config(),
            cast(PlatformGitHubAppRuntimeService, runtime),
            GitHubPlatformInstallationsRequest(code="code", state=state),
            handle="workspace",
            agent_id="agent-1",
        )

    assert raised.value.status_code == 400
    runtime.resolve.assert_not_awaited()
    exchange.assert_not_awaited()
    service.sync_agent_github_installations.assert_not_awaited()


async def test_agent_github_callback_syncs_through_authorized_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid Agent state revalidates and stores installations through the service."""
    state = create_agent_github_platform_oauth_state(
        "state-secret",
        effective_generation="generation-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        user_id="user-1",
        redirect_uri="https://app.test/oauth/github/callback",
        callback_target="agent_github_installations",
    )
    service = cast(Any, MagicMock(spec=ToolkitService))
    service.authorize_agent_management = AsyncMock(return_value=Success(None))
    service.sync_agent_github_installations = AsyncMock(return_value=Success(None))
    runtime = cast(Any, MagicMock(spec=PlatformGitHubAppRuntimeService))
    runtime.resolve = AsyncMock(
        return_value=ResolvedPlatformGitHubApp(
            app_id="123",
            client_id="client-id",
            private_key="private-key",
            client_secret="client-secret",
            effective_generation="generation-1",
            app_id_source=SystemSettingFieldSource.ADMIN,
        )
    )
    installations = [
        {
            "id": 42,
            "account": {
                "login": "azents",
                "type": "Organization",
                "avatar_url": "https://example.test/avatar.png",
            },
        }
    ]
    monkeypatch.setattr(
        oauth_module,
        "exchange_oauth_code",
        AsyncMock(return_value="user-token"),
    )
    monkeypatch.setattr(
        oauth_module,
        "list_user_installations",
        AsyncMock(return_value=installations),
    )
    revoke = AsyncMock()
    monkeypatch.setattr(oauth_module, "revoke_oauth_token", revoke)

    response = await get_agent_github_platform_installations(
        _member(),
        cast(ToolkitService, service),
        _config(),
        cast(PlatformGitHubAppRuntimeService, runtime),
        GitHubPlatformInstallationsRequest(code="code", state=state),
        handle="workspace",
        agent_id="agent-1",
    )

    assert [item.id for item in response.installations] == [42]
    sync_args = service.sync_agent_github_installations.await_args
    assert sync_args is not None
    assert sync_args.args == ("agent-1",)
    assert sync_args.kwargs["user_id"] == "user-1"
    assert sync_args.kwargs["installations"] == installations
    revoke.assert_awaited_once_with("client-id", "client-secret", "user-token")


async def test_new_agent_oauth_connect_remains_authorization_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starting OAuth without a token does not project a ready connection."""
    service = cast(Any, MagicMock(spec=ToolkitService))
    service.get_agent_oauth_context = AsyncMock(
        return_value=Success(
            AgentToolkitOAuthContext(
                toolkit=_agent_toolkit(),
                connection=None,
            )
        )
    )
    service.store_agent_oauth_connection = AsyncMock(return_value=Success(None))
    monkeypatch.setattr(
        oauth_module,
        "_discover_required_metadata",
        AsyncMock(
            return_value=OAuthServerMetadata(
                authorization_endpoint="https://mcp.test/authorize",
                token_endpoint="https://mcp.test/token",
                registration_endpoint=None,
                scopes_supported=[],
                issuer="https://mcp.test",
            )
        ),
    )
    response = await connect_agent_oauth(
        _member(),
        cast(ToolkitService, service),
        _config(),
        {"mcp": McpToolkitProvider()},
        handle="workspace",
        agent_id="agent-1",
        toolkit_config_id="toolkit-1",
    )

    assert response.authorization_url.startswith("https://mcp.test/authorize?")
    store_args = service.store_agent_oauth_connection.await_args
    assert store_args is not None
    assert store_args.kwargs["connected"] is False


async def test_agent_oauth_exchange_rejects_redirect_context_mismatch() -> None:
    """The exchange path must match the exact redirect URI bound at connect time."""
    config = _config()
    state = create_agent_toolkit_oauth_state(
        toolkit_id="toolkit-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        user_id="user-1",
        redirect_uri=(
            "https://app.test/oauth/mcp/callback?handle=other"
            "&agent_id=agent-1&toolkit_config_id=toolkit-1"
        ),
        code_verifier="verifier-1",
        callback_target="agent_toolkits",
        secret_key="state-secret",
    )
    service = cast(Any, MagicMock(spec=ToolkitService))
    service.get_agent_oauth_context = AsyncMock()

    with pytest.raises(HTTPException) as raised:
        await exchange_agent_oauth_connection(
            _member(),
            cast(ToolkitService, service),
            config,
            {"mcp": McpToolkitProvider()},
            OAuthExchangeRequest(code="code", state=state),
            handle="workspace",
            agent_id="agent-1",
            toolkit_config_id="toolkit-1",
        )

    assert raised.value.status_code == 400
    service.get_agent_oauth_context.assert_not_awaited()


async def test_agent_oauth_exchange_revalidates_current_item_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A removed Agent administrator cannot complete a previously started flow."""
    state = create_agent_toolkit_oauth_state(
        toolkit_id="toolkit-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        user_id="user-1",
        redirect_uri=(
            "https://app.test/oauth/mcp/callback?handle=workspace"
            "&agent_id=agent-1&toolkit_config_id=toolkit-1"
        ),
        code_verifier="verifier-1",
        callback_target="agent_toolkits",
        secret_key="state-secret",
    )
    service = cast(Any, MagicMock(spec=ToolkitService))
    service.get_agent_oauth_context = AsyncMock(
        return_value=Failure(NotAdmin(agent_id="agent-1"))
    )
    exchange = AsyncMock()
    monkeypatch.setattr(oauth_module, "_exchange_and_handle_errors", exchange)

    with pytest.raises(HTTPException) as raised:
        await exchange_agent_oauth_connection(
            _member(role=WorkspaceUserRole.MANAGER),
            cast(ToolkitService, service),
            _config(),
            {"mcp": McpToolkitProvider()},
            OAuthExchangeRequest(code="code", state=state),
            handle="workspace",
            agent_id="agent-1",
            toolkit_config_id="toolkit-1",
        )

    assert raised.value.status_code == 404
    exchange.assert_not_awaited()


async def test_agent_oauth_disconnect_hides_unauthorized_item() -> None:
    """Disconnect performs the same current authority and ownership lookup."""
    service = cast(Any, MagicMock(spec=ToolkitService))
    service.delete_agent_oauth_connection = AsyncMock(
        return_value=Failure(NotAdmin(agent_id="agent-1"))
    )

    with pytest.raises(HTTPException) as raised:
        await disconnect_agent_oauth_connection(
            _member(role=WorkspaceUserRole.MANAGER),
            cast(ToolkitService, service),
            handle="workspace",
            agent_id="agent-1",
            toolkit_config_id="toolkit-1",
        )

    assert raised.value.status_code == 404
