"""Agent-owned Toolkit setup and OAuth authorization tests."""

import datetime
from collections.abc import Sequence
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Result, Success
from fastapi import HTTPException

import azents.api.public.toolkit.v1.oauth as oauth_module
import azents.services.toolkit_oauth.helpers as oauth_helpers
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
from azents.core.github_installation import GitHubInstallationSnapshot
from azents.core.mcp_discovery import OAuthServerMetadata
from azents.core.oauth2 import (
    create_agent_github_platform_oauth_state,
    create_agent_toolkit_oauth_state,
)
from azents.core.system_setting import SystemSettingFieldSource
from azents.core.toolkit_errors import NotFound
from azents.engine.tools.mcp import McpToolkitProvider
from azents.services.agent.data import NotAdmin
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
    ResolvedPlatformGitHubApp,
)
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.data import (
    AgentNotBelongToWorkspace,
    AgentToolkitOAuthConnectionInput,
    AgentToolkitOAuthContext,
    ToolkitOutput,
)


class _ToolkitService(ToolkitService):
    """Typed service boundary with explicit async observation handles."""

    def __init__(self) -> None:
        self.authorize_agent_management_call = AsyncMock(
            side_effect=AssertionError("Unexpected authorization call")
        )
        self.sync_agent_github_installations_call = AsyncMock(
            side_effect=AssertionError("Unexpected installation sync")
        )
        self.get_agent_oauth_context_call = AsyncMock(
            side_effect=AssertionError("Unexpected OAuth context lookup")
        )
        self.store_agent_oauth_connection_call = AsyncMock(
            side_effect=AssertionError("Unexpected OAuth connection write")
        )
        self.delete_agent_oauth_connection_call = AsyncMock(
            side_effect=AssertionError("Unexpected OAuth connection deletion")
        )

    async def authorize_agent_management(
        self,
        agent_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[None, AgentNotBelongToWorkspace | NotAdmin]:
        return await self.authorize_agent_management_call(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )

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
        return await self.sync_agent_github_installations_call(
            agent_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            user_id=user_id,
            role=role,
            platform_app_id=platform_app_id,
            installations=installations,
        )

    async def get_agent_oauth_context(
        self,
        agent_id: str,
        toolkit_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        AgentToolkitOAuthContext, AgentNotBelongToWorkspace | NotAdmin | NotFound
    ]:
        return await self.get_agent_oauth_context_call(
            agent_id,
            toolkit_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )

    async def store_agent_oauth_connection(
        self,
        agent_id: str,
        toolkit_id: str,
        connection: AgentToolkitOAuthConnectionInput,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
        connected: bool,
    ) -> Result[None, AgentNotBelongToWorkspace | NotAdmin | NotFound]:
        return await self.store_agent_oauth_connection_call(
            agent_id,
            toolkit_id,
            connection,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
            connected=connected,
        )

    async def delete_agent_oauth_connection(
        self,
        agent_id: str,
        toolkit_id: str,
        *,
        workspace_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[None, AgentNotBelongToWorkspace | NotAdmin | NotFound]:
        return await self.delete_agent_oauth_connection_call(
            agent_id,
            toolkit_id,
            workspace_id=workspace_id,
            workspace_user_id=workspace_user_id,
            role=role,
        )


class _PlatformRuntime(PlatformGitHubAppRuntimeService):
    """Resolve through the real runtime interface, observing unexpected calls."""

    def __init__(self) -> None:
        self.resolve_call = AsyncMock(
            side_effect=AssertionError("Unexpected platform runtime resolution")
        )

    async def resolve(self) -> ResolvedPlatformGitHubApp:
        return await self.resolve_call()


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
    """Validate a complete synthetic Config without environment lookups."""
    return Config.model_validate(
        {
            "runtime_env": "local",
            "sentry_dsn": None,
            "rdb": {
                "host": "localhost",
                "port": 5432,
                "user": "test",
                "password": None,
                "db_name": "oauth_tests",
            },
            "auth": {
                "jwt": {"secret_key": "synthetic-jwt-key"},
                "refresh_token": {},
                "signup_token": {},
            },
            "system_bootstrap": {"setup_token": None},
            "runtime_provider_bootstrap": {
                "source_key": None,
                "source_path": None,
                "poll_interval_seconds": 60.0,
            },
            "email": None,
            "credential_encryption": {"key": "state-secret"},
            "redis": {"url": "redis://localhost:6379/0"},
            "runtime_transfer_coordinator": {
                "endpoint": None,
                "tls_ca_file": None,
                "allow_insecure": False,
                "credential_lifetime_seconds": 60.0,
            },
            "model_stream_timeout": {
                "connect_timeout_seconds": 1.0,
                "parsed_event_idle_timeout_seconds": 1.0,
                "absolute_attempt_timeout_seconds": 30.0,
                "close_grace_seconds": 1.0,
            },
            "openai_responses_websocket_enabled": False,
            "workspace_s3": {"bucket": "oauth-tests"},
            "web_url": "https://app.test",
            "mcp_proxy_url": None,
        }
    )


async def test_agent_level_authorization_maps_missing_and_denied_separately() -> None:
    """Agent-level setup uses 404 for missing Agent and 403 for denied authority."""
    member = _member(role=WorkspaceUserRole.MANAGER)
    service = _ToolkitService()
    service.authorize_agent_management_call = AsyncMock(
        return_value=Failure(AgentNotBelongToWorkspace(agent_id="agent-1"))
    )

    with pytest.raises(HTTPException) as missing:
        await _authorize_agent_management_or_error(
            service,
            member,
            agent_id="agent-1",
        )

    assert missing.value.status_code == 404

    service.authorize_agent_management_call.return_value = Failure(
        NotAdmin(agent_id="agent-1")
    )
    with pytest.raises(HTTPException) as denied:
        await _authorize_agent_management_or_error(
            service,
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
    service = _ToolkitService()
    service.authorize_agent_management_call = AsyncMock(return_value=Success(None))
    service.sync_agent_github_installations_call = AsyncMock()
    runtime = _PlatformRuntime()
    runtime.resolve_call = AsyncMock()
    exchange = AsyncMock()
    monkeypatch.setattr(oauth_module, "exchange_oauth_code", exchange)

    with pytest.raises(HTTPException) as raised:
        await get_agent_github_platform_installations(
            _member(),
            service,
            _config(),
            runtime,
            GitHubPlatformInstallationsRequest(code="code", state=state),
            handle="workspace",
            agent_id="agent-1",
        )

    assert raised.value.status_code == 400
    runtime.resolve_call.assert_not_awaited()
    exchange.assert_not_awaited()
    service.sync_agent_github_installations_call.assert_not_awaited()


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
    service = _ToolkitService()
    service.authorize_agent_management_call = AsyncMock(return_value=Success(None))
    service.sync_agent_github_installations_call = AsyncMock(return_value=Success(None))
    runtime = _PlatformRuntime()
    runtime.resolve_call = AsyncMock(
        return_value=ResolvedPlatformGitHubApp(
            app_id="123",
            client_id="client-id",
            private_key="private-key",
            client_secret="client-secret",
            effective_generation="generation-1",
            app_id_source=SystemSettingFieldSource.ADMIN,
        )
    )
    installations = (
        GitHubInstallationSnapshot(
            installation_id=42,
            app_id=None,
            account_login="azents",
            account_type="Organization",
            account_avatar_url="https://example.test/avatar.png",
        ),
    )
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
        service,
        _config(),
        runtime,
        GitHubPlatformInstallationsRequest(code="code", state=state),
        handle="workspace",
        agent_id="agent-1",
    )

    assert [item.id for item in response.installations] == [42]
    sync_args = service.sync_agent_github_installations_call.await_args
    assert sync_args is not None
    assert sync_args.args == ("agent-1",)
    assert sync_args.kwargs["user_id"] == "user-1"
    assert sync_args.kwargs["installations"] == installations
    revoke.assert_awaited_once_with("client-id", "client-secret", "user-token")


async def test_new_agent_oauth_connect_remains_authorization_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starting OAuth without a token does not project a ready connection."""
    service = _ToolkitService()
    service.get_agent_oauth_context_call = AsyncMock(
        return_value=Success(
            AgentToolkitOAuthContext(
                toolkit=_agent_toolkit(),
                connection=None,
            )
        )
    )
    service.store_agent_oauth_connection_call = AsyncMock(return_value=Success(None))
    monkeypatch.setattr(
        oauth_helpers,
        "discover_required_metadata",
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
        service,
        _config(),
        {"mcp": McpToolkitProvider()},
        handle="workspace",
        agent_id="agent-1",
        toolkit_config_id="toolkit-1",
    )

    assert response.authorization_url.startswith("https://mcp.test/authorize?")
    store_args = service.store_agent_oauth_connection_call.await_args
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
    service = _ToolkitService()
    service.get_agent_oauth_context_call = AsyncMock()

    with pytest.raises(HTTPException) as raised:
        await exchange_agent_oauth_connection(
            _member(),
            service,
            config,
            {"mcp": McpToolkitProvider()},
            OAuthExchangeRequest(code="code", state=state),
            handle="workspace",
            agent_id="agent-1",
            toolkit_config_id="toolkit-1",
        )

    assert raised.value.status_code == 400
    service.get_agent_oauth_context_call.assert_not_awaited()


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
    service = _ToolkitService()
    service.get_agent_oauth_context_call = AsyncMock(
        return_value=Failure(NotAdmin(agent_id="agent-1"))
    )
    exchange = AsyncMock()
    monkeypatch.setattr(oauth_helpers, "exchange_and_handle_errors", exchange)

    with pytest.raises(HTTPException) as raised:
        await exchange_agent_oauth_connection(
            _member(role=WorkspaceUserRole.MANAGER),
            service,
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
    service = _ToolkitService()
    service.delete_agent_oauth_connection_call = AsyncMock(
        return_value=Failure(NotAdmin(agent_id="agent-1"))
    )

    with pytest.raises(HTTPException) as raised:
        await disconnect_agent_oauth_connection(
            _member(role=WorkspaceUserRole.MANAGER),
            service,
            handle="workspace",
            agent_id="agent-1",
            toolkit_config_id="toolkit-1",
        )

    assert raised.value.status_code == 404
