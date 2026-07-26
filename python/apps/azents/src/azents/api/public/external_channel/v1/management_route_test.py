"""External Channel authenticated management API tests."""

import datetime
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from azents.app import create_dummy_public_app
from azents.core.auth.deps import (
    CurrentUser,
    WorkspaceMember,
    get_current_user,
    get_workspace_member,
)
from azents.core.auth.roles import get_permissions_for_role
from azents.core.deps import get_config
from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelProvider,
    ExternalChannelTransport,
    WorkspaceUserRole,
)
from azents.repos.external_channel.data import ExternalChannelMultiConnectionImpact
from azents.repos.external_channel.management_data import (
    ManagedConnection,
    ManagedMultiConnection,
)
from azents.services.external_channel.connection import (
    ExternalChannelConnectionStateChanged,
)
from azents.services.external_channel.data import (
    ExternalChannelConnectionStatusSnapshot,
    ExternalChannelCredentialSnapshot,
)
from azents.services.external_channel.management import (
    ExternalChannelManagementGenerationChanged,
    ExternalChannelManagementNotFound,
    ExternalChannelManagementService,
    ManagedConnectionSetup,
    ManagedMultiConnectionSetup,
)


def _connection() -> ManagedConnection:
    return ManagedConnection(
        id="connection-1",
        route_id="route-1",
        agent_id="agent-1",
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        status=ExternalChannelConnectionStatus.CONFIGURING,
        provider_app_id="A1",
        provider_tenant_id=None,
        provider_bot_user_id=None,
        credentials_configured=True,
        capabilities=None,
        provider_config=None,
        last_verified_at=None,
        last_health_at=None,
        socket_gap_detected_at=None,
        socket_gap_reason=None,
        disconnected_at=None,
    )


def _multi_connection() -> ManagedMultiConnection:
    return ManagedMultiConnection(
        id="multi-connection-1",
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        app_mode=ExternalChannelAppMode.MULTI,
        status=ExternalChannelConnectionStatus.CONFIGURING,
        provider_app_id="A-MULTI",
        provider_tenant_id=None,
        provider_bot_user_id=None,
        credentials_configured=True,
        capabilities=None,
        provider_config=None,
        last_verified_at=None,
        last_health_at=None,
        socket_gap_detected_at=None,
        socket_gap_reason=None,
        disconnected_at=None,
        generation=datetime.datetime(2026, 7, 25, tzinfo=datetime.UTC),
        active_agent_count=2,
        configured_default_count=1,
    )


def _discord_status() -> ExternalChannelConnectionStatusSnapshot:
    return ExternalChannelConnectionStatusSnapshot(
        status=ExternalChannelConnectionStatus.ACTIVE,
        code="valid",
        message="Discord callback is configured.",
        action_hint=None,
        checked_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
        identity=None,
        credentials=ExternalChannelCredentialSnapshot(
            provider=ExternalChannelProvider.DISCORD,
            configured_fields=("bot_token",),
        ),
        capabilities=None,
    )


def _client(
    service: AsyncMock,
    *,
    role: WorkspaceUserRole = WorkspaceUserRole.OWNER,
    multi_app_enabled: bool = True,
    discord_enabled: bool = False,
) -> TestClient:
    app = create_dummy_public_app()
    app.dependency_overrides[ExternalChannelManagementService] = lambda: service
    app.dependency_overrides[get_workspace_member] = lambda: WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=role,
        permissions=get_permissions_for_role(role),
        session_id="auth-session-1",
    )
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="user-1",
        session_id="auth-session-1",
    )
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(
        external_channel_slack_callback_url=(
            "https://callbacks.example.test/external-channel/v1/slack/events"
        ),
        api_url="https://api.example.test",
        external_channel_multi_app_enabled=multi_app_enabled,
        external_channel_discord_enabled=discord_enabled,
    )
    return TestClient(app)


def test_setup_returns_redacted_connection_without_echoing_credentials() -> None:
    """Secrets are accepted as input but absent from every response field."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.setup_slack.return_value = ManagedConnectionSetup(connection=_connection())

    response = _client(service).post(
        "/external-channel/v1/workspaces/ws/agents/agent-1/external-channels/slack",
        json={
            "app_id": "A1",
            "transport": "http",
            "credentials": {
                "provider": "slack",
                "bot_token": "xoxb-secret",
                "signing_secret": "signing-secret",
                "app_token": None,
            },
        },
    )

    assert response.status_code == 201
    assert response.json()["connection"]["credentials_configured"] is True
    assert "xoxb-secret" not in response.text
    assert "signing-secret" not in response.text


def test_manifest_guidance_returns_fixed_callback_and_copy_ready_json() -> None:
    """Return a complete HTTP Manifest before a connection exists."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.list_connections.return_value = []

    response = _client(service).get(
        "/external-channel/v1/workspaces/ws/agents/agent-1/external-channels/manifest",
        params={"transport": "http", "app_name": "Incident Agent"},
    )

    assert response.status_code == 200
    payload = response.json()
    callback_url = "https://callbacks.example.test/external-channel/v1/slack/events"
    assert payload["callback_url"] == callback_url
    manifest = json.loads(payload["manifest_json"])
    assert manifest["settings"]["event_subscriptions"]["request_url"] == callback_url
    assert "{selector}" not in response.text
    assert "signing_secret" not in response.text


def test_agent_connection_list_includes_read_only_associated_multi_apps() -> None:
    """Agent visibility includes sanitized Multi App context without mutations."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.list_connections.return_value = [_connection()]
    service.list_agent_multi_connections.return_value = [_multi_connection()]

    response = _client(service, role=WorkspaceUserRole.MEMBER).get(
        "/external-channel/v1/workspaces/ws/agents/agent-1/external-channels"
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "connection-1"
    associated = response.json()["associated_multi_apps"]
    assert associated == [
        {
            "id": "multi-connection-1",
            "provider": "slack",
            "transport": "http",
            "app_mode": "multi",
            "status": "configuring",
            "provider_app_id": "A-MULTI",
            "provider_tenant_id": None,
            "provider_bot_user_id": None,
            "credentials_configured": True,
            "capabilities": None,
            "provider_config": None,
            "last_verified_at": None,
            "last_health_at": None,
            "socket_gap_detected_at": None,
            "socket_gap_reason": None,
            "disconnected_at": None,
            "generation": "2026-07-25T00:00:00Z",
            "active_agent_count": 2,
            "configured_default_count": 1,
        }
    ]
    service.list_agent_multi_connections.assert_awaited_once_with(
        workspace_id="workspace-1",
        agent_id="agent-1",
        workspace_user_id="workspace-user-1",
    )


def test_validate_returns_conflict_when_connection_changes_in_flight() -> None:
    """A stale provider validation result cannot overwrite newer local state."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.validate_connection.side_effect = ExternalChannelConnectionStateChanged(
        "The connection changed during validation. Retry the operation."
    )

    response = _client(service).post(
        "/external-channel/v1/workspaces/ws/agents/agent-1/"
        "external-channels/connection-1/validate"
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "The connection changed during validation. Retry the operation."
    }


def test_opaque_approval_request_is_404_safe() -> None:
    """Unauthorized and missing opaque request IDs share one response."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.get_approval.side_effect = ExternalChannelManagementNotFound("request-1")

    response = _client(service).get("/external-channel/v1/approval-requests/request-1")

    assert response.status_code == 404
    assert response.json() == {"detail": "Approval request not found."}


def test_manager_can_create_redacted_multi_app_without_an_agent() -> None:
    """Workspace Managers can create a zero-Agent Multi App without secret echo."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.setup_multi_slack.return_value = ManagedMultiConnectionSetup(
        connection=_multi_connection()
    )

    response = _client(service, role=WorkspaceUserRole.MANAGER).post(
        "/external-channel/v1/workspaces/ws/external-channels/slack/multi",
        json={
            "app_id": "A-MULTI",
            "transport": "http",
            "credentials": {
                "provider": "slack",
                "bot_token": "xoxb-multi-secret",
                "signing_secret": "multi-signing-secret",
                "app_token": None,
            },
        },
    )

    assert response.status_code == 201
    assert response.json()["connection"]["app_mode"] == "multi"
    assert "xoxb-multi-secret" not in response.text
    assert "multi-signing-secret" not in response.text
    service.setup_multi_slack.assert_awaited_once()


def test_multi_app_creation_is_blocked_before_mode_aware_enablement() -> None:
    """Operators must explicitly enable Multi data after the runtime rollout."""
    service = AsyncMock(spec=ExternalChannelManagementService)

    response = _client(
        service,
        role=WorkspaceUserRole.MANAGER,
        multi_app_enabled=False,
    ).post(
        "/external-channel/v1/workspaces/ws/external-channels/slack/multi",
        json={
            "app_id": "A-MULTI",
            "transport": "http",
            "credentials": {
                "provider": "slack",
                "bot_token": "xoxb-multi-secret",
                "signing_secret": "multi-signing-secret",
                "app_token": None,
            },
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Slack Multi App creation is not enabled for this deployment."
    }
    service.setup_multi_slack.assert_not_awaited()


@pytest.mark.parametrize(
    "path",
    [
        "/external-channel/v1/workspaces/ws/agents/agent-1/external-channels/discord",
        "/external-channel/v1/workspaces/ws/external-channels/discord/multi",
    ],
)
def test_discord_creation_is_blocked_until_full_provider_rollout(path: str) -> None:
    """Discord setup cannot create provider state before required later phases."""
    service = AsyncMock(spec=ExternalChannelManagementService)

    response = _client(service).post(
        path,
        json={
            "app_id": "discord-app-1",
            "configuration": {
                "provider": "discord",
                "target_guild_id": "guild-1",
            },
            "credentials": {
                "provider": "discord",
                "bot_token": "discord-bot-token",
            },
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": (
            "Discord External Channel creation is not enabled for this deployment."
        )
    }
    service.setup_discord.assert_not_awaited()
    service.setup_multi_discord.assert_not_awaited()


@pytest.mark.parametrize(
    ("path", "service_method"),
    [
        (
            "/external-channel/v1/workspaces/ws/agents/agent-1/"
            "external-channels/connection-1/discord",
            "update_discord",
        ),
        (
            "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
            "connection-1",
            "update_multi_discord",
        ),
    ],
)
def test_discord_replacement_is_blocked_until_full_provider_rollout(
    path: str,
    service_method: str,
) -> None:
    """Discord replacement fails closed before it can persist a new secret."""
    service = AsyncMock(spec=ExternalChannelManagementService)

    response = _client(service).put(
        path,
        json={
            "app_id": "discord-app-1",
            "configuration": {
                "provider": "discord",
                "target_guild_id": "guild-1",
            },
            "credentials": {
                "provider": "discord",
                "bot_token": "discord-bot-token",
            },
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": (
            "Discord External Channel creation is not enabled for this deployment."
        )
    }
    getattr(service, service_method).assert_not_awaited()


@pytest.mark.parametrize(
    ("path", "service_method"),
    [
        (
            "/external-channel/v1/workspaces/ws/agents/agent-1/"
            "external-channels/connection-1/discord",
            "update_discord",
        ),
        (
            "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
            "connection-1",
            "update_multi_discord",
        ),
    ],
)
def test_discord_replacement_returns_redacted_status(
    path: str,
    service_method: str,
) -> None:
    """Successful replacement never echoes the supplied Discord Bot Token."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    getattr(service, service_method).return_value = _discord_status()

    response = _client(service, discord_enabled=True).put(
        path,
        json={
            "app_id": "discord-app-1",
            "configuration": {
                "provider": "discord",
                "target_guild_id": "guild-1",
            },
            "credentials": {
                "provider": "discord",
                "bot_token": "discord-bot-token",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["credentials"] == {
        "provider": "discord",
        "configured_fields": ["bot_token"],
    }
    assert "discord-bot-token" not in response.text
    getattr(service, service_method).assert_awaited_once()


def test_member_cannot_replace_workspace_discord_multi_app() -> None:
    """Workspace Multi credential rotation retains Manager-or-Owner authority."""
    service = AsyncMock(spec=ExternalChannelManagementService)

    response = _client(
        service,
        role=WorkspaceUserRole.MEMBER,
        discord_enabled=True,
    ).put(
        "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
        "connection-1",
        json={
            "app_id": "discord-app-1",
            "configuration": {
                "provider": "discord",
                "target_guild_id": "guild-1",
            },
            "credentials": {
                "provider": "discord",
                "bot_token": "discord-bot-token",
            },
        },
    )

    assert response.status_code == 403
    service.update_multi_discord.assert_not_awaited()


@pytest.mark.parametrize(
    ("path", "payload", "service_method"),
    [
        (
            "/external-channel/v1/workspaces/ws/external-channels/slack/multi/"
            "multi-connection-1/agents",
            {"agent_id": "agent-1"},
            "add_multi_route",
        ),
        (
            "/external-channel/v1/workspaces/ws/external-channels/slack/multi/"
            "multi-connection-1/agents/route-1/reenable",
            None,
            "reenable_multi_route",
        ),
    ],
)
def test_multi_route_growth_is_blocked_before_mode_aware_enablement(
    path: str,
    payload: dict[str, str] | None,
    service_method: str,
) -> None:
    """The rollout gate also prevents adding or reviving Multi routes."""
    service = AsyncMock(spec=ExternalChannelManagementService)

    response = _client(service, multi_app_enabled=False).post(path, json=payload)

    assert response.status_code == 503
    getattr(service, service_method).assert_not_awaited()


def test_member_cannot_read_workspace_multi_apps() -> None:
    """Ordinary members never gain Workspace Multi App management authority."""
    service = AsyncMock(spec=ExternalChannelManagementService)

    response = _client(service, role=WorkspaceUserRole.MEMBER).get(
        "/external-channel/v1/workspaces/ws/external-channels/slack/multi"
    )

    assert response.status_code == 403
    service.list_multi_connections.assert_not_awaited()


def test_multi_route_removal_rejects_stale_generation() -> None:
    """Stale destructive Multi mutations surface one conflict response."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.remove_multi_route.side_effect = ExternalChannelManagementGenerationChanged(
        "The Multi App changed. Reload it before retrying the operation."
    )

    response = _client(service).request(
        "DELETE",
        "/external-channel/v1/workspaces/ws/external-channels/slack/multi/"
        "multi-connection-1/agents/route-1",
        json={"expected_generation": "2026-07-25T00:00:00Z"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "The Multi App changed. Reload it before retrying the operation."
    }


def test_multi_catalog_pagination_and_cross_workspace_not_found() -> None:
    """Catalog pages preserve parameters and foreign Multi Apps remain opaque."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.list_multi_routes.side_effect = ExternalChannelManagementNotFound(
        "foreign-connection"
    )

    response = _client(service, role=WorkspaceUserRole.MANAGER).get(
        "/external-channel/v1/workspaces/ws/external-channels/slack/multi/"
        "foreign-connection/agents",
        params={"offset": 10, "limit": 25},
    )

    assert response.status_code == 404
    service.list_multi_routes.assert_awaited_once_with(
        workspace_id="workspace-1",
        connection_id="foreign-connection",
        offset=10,
        limit=25,
    )


def test_multi_connection_impact_returns_generation_fenced_preview() -> None:
    """Whole-App confirmation receives its generation and affected identities."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    generation = datetime.datetime(2026, 7, 25, tzinfo=datetime.UTC)
    service.get_multi_connection_impact.return_value = (
        ExternalChannelMultiConnectionImpact(
            connection_id="multi-connection-1",
            generation=generation,
            active_route_count=2,
            active_default_count=0,
            active_binding_count=0,
            bound_resource_count=0,
            open_admission_count=0,
            pending_access_request_count=0,
            pending_context_count=0,
            affected_defaults=(),
            affected_bindings=(),
        )
    )

    response = _client(service, role=WorkspaceUserRole.MANAGER).get(
        "/external-channel/v1/workspaces/ws/external-channels/slack/multi/"
        "multi-connection-1/impact"
    )

    assert response.status_code == 200
    assert response.json()["generation"] == "2026-07-25T00:00:00Z"
    assert response.json()["active_route_count"] == 2
    service.get_multi_connection_impact.assert_awaited_once_with(
        workspace_id="workspace-1",
        connection_id="multi-connection-1",
    )


def test_openapi_includes_management_but_excludes_provider_callback() -> None:
    """Generated clients receive management operations, never raw callbacks."""
    paths = create_dummy_public_app().openapi()["paths"]
    connection_path = (
        "/external-channel/v1/workspaces/{handle}/agents/{agent_id}/"
        "external-channels/{connection_id}"
    )

    assert (
        "/external-channel/v1/workspaces/{handle}/agents/{agent_id}/external-channels"
        in paths
    )
    assert f"{connection_path}/slack" in paths
    assert "put" in paths[f"{connection_path}/slack"]
    assert f"{connection_path}/transport" not in paths
    assert f"{connection_path}/reconnect" not in paths
    assert "/external-channel/v1/approval-requests/{access_request_id}" in paths
    multi_path = (
        "/external-channel/v1/workspaces/{handle}/external-channels/slack/multi"
    )
    assert multi_path in paths
    assert "post" in paths[multi_path]
    assert f"{multi_path}/{{connection_id}}/impact" in paths
    assert f"{multi_path}/{{connection_id}}/agents/{{route_id}}/impact" in paths
    discord_single_path = (
        "/external-channel/v1/workspaces/{handle}/agents/{agent_id}/"
        "external-channels/discord"
    )
    discord_multi_path = (
        "/external-channel/v1/workspaces/{handle}/external-channels/discord/multi"
    )
    assert discord_single_path in paths
    assert "post" in paths[discord_single_path]
    assert discord_multi_path in paths
    assert "post" in paths[discord_multi_path]
    discord_single_update_path = f"{connection_path}/discord"
    assert discord_single_update_path in paths
    assert "put" in paths[discord_single_update_path]
    discord_multi_update_path = f"{discord_multi_path}/{{connection_id}}"
    assert discord_multi_update_path in paths
    assert "put" in paths[discord_multi_update_path]
    assert not any(
        "multi" in path and "/agents/{agent_id}/external-channels" in path
        for path in paths
    )
    assert "/external-channel/v1/slack/events" not in paths
