"""External Channel authenticated management API tests."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from azents.app import create_dummy_public_app
from azents.core.auth.deps import (
    CurrentUser,
    WorkspaceMember,
    get_current_user,
    get_workspace_member,
)
from azents.core.auth.permissions import Permissions
from azents.core.deps import get_config
from azents.core.enums import (
    ExternalChannelConnectionStatus,
    ExternalChannelProvider,
    ExternalChannelRouteStatus,
    ExternalChannelTransport,
    WorkspaceUserRole,
)
from azents.repos.external_channel.management_data import ManagedConnection
from azents.services.external_channel.management import (
    ExternalChannelManagementNotFound,
    ExternalChannelManagementService,
    ManagedConnectionSetup,
)


def _connection() -> ManagedConnection:
    return ManagedConnection(
        id="connection-1",
        route_id="route-1",
        agent_id="agent-1",
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        status=ExternalChannelConnectionStatus.CONFIGURING,
        route_status=ExternalChannelRouteStatus.ACTIVE,
        provider_app_id="A1",
        provider_tenant_id=None,
        provider_bot_user_id=None,
        credentials_configured=True,
        capabilities=None,
        last_verified_at=None,
        last_health_at=None,
        socket_gap_detected_at=None,
        socket_gap_reason=None,
        disconnected_at=None,
    )


def _client(service: AsyncMock) -> TestClient:
    app = create_dummy_public_app()
    app.dependency_overrides[ExternalChannelManagementService] = lambda: service
    app.dependency_overrides[get_workspace_member] = lambda: WorkspaceMember(
        user_id="user-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
        permissions={Permissions.ALL},
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


def test_opaque_approval_request_is_404_safe() -> None:
    """Unauthorized and missing opaque request IDs share one response."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.get_approval.side_effect = ExternalChannelManagementNotFound("request-1")

    response = _client(service).get("/external-channel/v1/approval-requests/request-1")

    assert response.status_code == 404
    assert response.json() == {"detail": "Approval request not found."}


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
    assert "/external-channel/v1/slack/events" not in paths
