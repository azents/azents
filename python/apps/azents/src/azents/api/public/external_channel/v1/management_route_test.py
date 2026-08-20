"""External Channel authenticated management API tests."""

import datetime
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.public.external_channel.v1 import (
    management_route as management_route_module,
)
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
    ExternalChannelConversationLocation,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelTransport,
    WorkspaceUserRole,
)
from azents.repos.external_channel.data import ExternalChannelMultiConnectionImpact
from azents.repos.external_channel.management_data import (
    ManagedBinding,
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
from azents.services.external_channel.discord_api import (
    DiscordAPIConfigurationInvalid,
    DiscordAPICredentialsInvalid,
    DiscordAPIUnavailable,
)
from azents.services.external_channel.management import (
    ExternalChannelManagementGenerationChanged,
    ExternalChannelManagementNotFound,
    ExternalChannelManagementService,
    ExternalChannelResponseModeSetting,
    ManagedConnectionSetup,
    ManagedMultiConnectionSetup,
)


def _create_route_app() -> FastAPI:
    """Create the External Channel management route app once."""
    app = FastAPI()
    app.include_router(
        management_route_module.router,
        prefix="/external-channel/v1",
    )
    return app


_ROUTE_APP = _create_route_app()


@pytest.fixture(autouse=True)
def _reset_dependency_overrides() -> None:
    """Prevent dependency overrides from leaking between tests."""
    _ROUTE_APP.dependency_overrides.clear()


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
        open_access_enabled=True,
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


def _binding(
    response_mode: ExternalChannelResponseMode = (
        ExternalChannelResponseMode.MENTION_ONLY
    ),
) -> ManagedBinding:
    now = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    return ManagedBinding(
        id="binding-1",
        agent_session_id="session-1",
        provider=ExternalChannelProvider.SLACK,
        response_mode=response_mode,
        resource_type=ExternalChannelResourceType.THREAD,
        conversation_location=ExternalChannelConversationLocation.THREADS,
        resource_label="Channel thread",
        connected_at=now,
        disconnected_at=None,
        disconnect_reason=None,
        latest_activity_at=now,
        work=None,
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
) -> TestClient:
    app = _ROUTE_APP
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
    service.get_default_response_mode.return_value = ExternalChannelResponseModeSetting(
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES
    )

    response = _client(service, role=WorkspaceUserRole.MEMBER).get(
        "/external-channel/v1/workspaces/ws/agents/agent-1/external-channels"
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "connection-1"
    assert response.json()["default_response_mode"] == "all_messages"
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
            "last_health_code": None,
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


def test_agent_admin_can_replace_default_response_mode() -> None:
    """The Agent-scoped setting accepts one required concrete mode."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.update_default_response_mode.return_value = (
        ExternalChannelResponseModeSetting(
            response_mode=ExternalChannelResponseMode.MENTION_ONLY
        )
    )

    response = _client(service).put(
        "/external-channel/v1/workspaces/ws/agents/agent-1/"
        "external-channels/default-response-mode",
        json={"response_mode": "mention_only"},
    )

    assert response.status_code == 200
    assert response.json() == {"response_mode": "mention_only"}
    service.update_default_response_mode.assert_awaited_once_with(
        workspace_id="workspace-1",
        agent_id="agent-1",
        workspace_user_id="workspace-user-1",
        setting=management_route_module.ResponseModeRequest(
            response_mode=ExternalChannelResponseMode.MENTION_ONLY
        ),
    )


def test_default_response_mode_rejects_unknown_values() -> None:
    """The API cannot create nullable, inherited, or unknown policy state."""
    service = AsyncMock(spec=ExternalChannelManagementService)

    response = _client(service).put(
        "/external-channel/v1/workspaces/ws/agents/agent-1/"
        "external-channels/default-response-mode",
        json={"response_mode": "use_agent_default"},
    )

    assert response.status_code == 422
    service.update_default_response_mode.assert_not_awaited()


def test_agent_admin_can_replace_connected_binding_response_mode() -> None:
    """A session binding update returns the concrete projected mode."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.update_binding_response_mode.return_value = _binding()

    response = _client(service).put(
        "/external-channel/v1/workspaces/ws/agents/agent-1/sessions/session-1/"
        "external-channels/binding-1/response-mode",
        json={"response_mode": "mention_only"},
    )

    assert response.status_code == 200
    assert response.json()["response_mode"] == "mention_only"
    service.update_binding_response_mode.assert_awaited_once_with(
        workspace_id="workspace-1",
        agent_id="agent-1",
        workspace_user_id="workspace-user-1",
        user_id="user-1",
        agent_session_id="session-1",
        binding_id="binding-1",
        setting=management_route_module.ResponseModeRequest(
            response_mode=ExternalChannelResponseMode.MENTION_ONLY
        ),
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
        "detail": "Multi App creation is not enabled for this deployment."
    }
    service.setup_multi_slack.assert_not_awaited()


@pytest.mark.parametrize(
    ("path", "service_method"),
    [
        (
            "/external-channel/v1/workspaces/ws/agents/agent-1/external-channels/discord",
            "setup_discord",
        )
    ],
)
def test_discord_creation_is_available_without_a_rollout_flag(
    path: str,
    service_method: str,
) -> None:
    """Discord setup is available without deployment-scoped feature gates."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.setup_discord.return_value = ManagedConnectionSetup(
        connection=_connection()
    )
    service.setup_multi_discord.return_value = ManagedMultiConnectionSetup(
        connection=_multi_connection()
    )

    response = _client(service).post(
        path,
        json={
            "app_id": "discord-app-1",
            "configuration": {
                "provider": "discord",
                "target_guild_id": "guild-1",
                "thread_auto_archive_duration_minutes": 1440,
            },
            "credentials": {
                "provider": "discord",
                "bot_token": "discord-bot-token",
            },
        },
    )

    assert response.status_code == 201
    getattr(service, service_method).assert_awaited_once()


def test_discord_multi_app_creation_is_blocked_before_mode_aware_enablement() -> None:
    """Discord Multi creation obeys the same deployment rollout gate as Slack."""
    service = AsyncMock(spec=ExternalChannelManagementService)

    response = _client(
        service,
        role=WorkspaceUserRole.MANAGER,
        multi_app_enabled=False,
    ).post(
        "/external-channel/v1/workspaces/ws/external-channels/discord/multi",
        json={
            "app_id": "discord-app-1",
            "configuration": {
                "provider": "discord",
                "target_guild_id": "guild-1",
                "thread_auto_archive_duration_minutes": 1440,
            },
            "credentials": {
                "provider": "discord",
                "bot_token": "discord-bot-token",
            },
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Multi App creation is not enabled for this deployment."
    }
    service.setup_multi_discord.assert_not_awaited()


def test_discord_multi_app_creation_succeeds_after_mode_aware_enablement() -> None:
    """Discord Multi creation reaches the provider-correct service after rollout."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.setup_multi_discord.return_value = ManagedMultiConnectionSetup(
        connection=_multi_connection()
    )

    response = _client(service, role=WorkspaceUserRole.MANAGER).post(
        "/external-channel/v1/workspaces/ws/external-channels/discord/multi",
        json={
            "app_id": "discord-app-1",
            "configuration": {
                "provider": "discord",
                "target_guild_id": "guild-1",
                "thread_auto_archive_duration_minutes": 1440,
            },
            "credentials": {
                "provider": "discord",
                "bot_token": "discord-bot-token",
            },
        },
    )

    assert response.status_code == 201
    service.setup_multi_discord.assert_awaited_once()


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
def test_discord_replacement_is_available_without_a_rollout_flag(
    path: str,
    service_method: str,
) -> None:
    """Discord replacement is available without deployment-scoped feature gates."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    getattr(service, service_method).return_value = _discord_status()

    response = _client(service).put(
        path,
        json={
            "app_id": "discord-app-1",
            "configuration": {
                "provider": "discord",
                "target_guild_id": "guild-1",
                "thread_auto_archive_duration_minutes": 1440,
            },
            "credentials": {
                "provider": "discord",
                "bot_token": "discord-bot-token",
            },
        },
    )

    assert response.status_code == 200
    getattr(service, service_method).assert_awaited_once()


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

    response = _client(service).put(
        path,
        json={
            "app_id": "discord-app-1",
            "configuration": {
                "provider": "discord",
                "target_guild_id": "guild-1",
                "thread_auto_archive_duration_minutes": 1440,
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


@pytest.mark.parametrize(
    ("error", "expected_detail", "failure_stage", "failure_code"),
    [
        (
            DiscordAPICredentialsInvalid(),
            {
                "code": "discord_credentials_invalid",
                "message": "Discord rejected the Bot Token.",
                "action_hint": "Replace the Bot Token and try again.",
            },
            "provider_authentication",
            "credentials_invalid",
        ),
        (
            DiscordAPIConfigurationInvalid(),
            {
                "code": "discord_callback_configuration_invalid",
                "message": (
                    "Discord rejected the automatically configured interaction "
                    "endpoint."
                ),
                "action_hint": (
                    "Validate again. If it still fails, ask an administrator to "
                    "check the public callback URL; no manual Discord endpoint setup "
                    "is required."
                ),
            },
            "provider_callback",
            "callback_configuration_invalid",
        ),
        (
            DiscordAPIUnavailable(),
            {
                "code": "discord_api_unavailable",
                "message": "Discord is temporarily unavailable.",
                "action_hint": "Try again later.",
            },
            "provider_api",
            "api_unavailable",
        ),
        (
            ValueError("Discord callback URL is not configured."),
            {
                "code": "discord_configuration_invalid",
                "message": "Discord connection configuration is invalid.",
                "action_hint": "Check the App settings and try again.",
            },
            "configuration",
            "configuration_invalid",
        ),
    ],
)
def test_discord_setup_returns_safe_structured_provider_errors(
    error: DiscordAPIConfigurationInvalid
    | DiscordAPICredentialsInvalid
    | DiscordAPIUnavailable
    | ValueError,
    expected_detail: dict[str, str],
    failure_stage: str,
    failure_code: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Provider failures expose an actionable redacted error without Bot Token data."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.setup_discord.side_effect = error

    with caplog.at_level(
        logging.ERROR,
        logger=management_route_module.logger.name,
    ):
        response = _client(service).post(
            "/external-channel/v1/workspaces/ws/agents/agent-1/"
            "external-channels/discord",
            json={
                "app_id": "discord-app-1",
                "configuration": {
                    "provider": "discord",
                    "target_guild_id": "guild-1",
                    "thread_auto_archive_duration_minutes": 1440,
                },
                "credentials": {
                    "provider": "discord",
                    "bot_token": "discord-bot-token",
                },
            },
        )

    assert response.status_code == 400
    assert response.json() == {"detail": expected_detail}
    assert "discord-bot-token" not in response.text
    record = next(
        record
        for record in caplog.records
        if record.message == "Discord External Channel activation failed"
    )
    assert record.__dict__["operation"] == "setup_dedicated"
    assert record.__dict__["connection_id"] is None
    assert record.__dict__["failure_stage"] == failure_stage
    assert record.__dict__["failure_code"] == failure_code
    assert record.__dict__["error_type"] == type(error).__name__
    assert record.exc_info is None
    assert "discord-bot-token" not in caplog.text


def test_discord_setup_failure_log_never_serializes_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Generic setup errors keep diagnostics structured and secret-free."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.setup_discord.side_effect = ValueError(
        "discord-bot-token must never reach diagnostics"
    )

    with caplog.at_level(
        logging.ERROR,
        logger=management_route_module.logger.name,
    ):
        response = _client(service).post(
            "/external-channel/v1/workspaces/ws/agents/agent-1/"
            "external-channels/discord",
            json={
                "app_id": "discord-app-1",
                "configuration": {
                    "provider": "discord",
                    "target_guild_id": "guild-1",
                    "thread_auto_archive_duration_minutes": 1440,
                },
                "credentials": {
                    "provider": "discord",
                    "bot_token": "discord-bot-token",
                },
            },
        )

    assert response.status_code == 400
    record = next(
        record
        for record in caplog.records
        if record.message == "Discord External Channel activation failed"
    )
    assert record.__dict__["failure_stage"] == "configuration"
    assert record.__dict__["failure_code"] == "configuration_invalid"
    assert record.__dict__["error_type"] == "ValueError"
    assert "discord-bot-token" not in caplog.text
    assert "must never reach diagnostics" not in caplog.text


def test_member_cannot_replace_workspace_discord_multi_app() -> None:
    """Workspace Multi credential rotation retains Manager-or-Owner authority."""
    service = AsyncMock(spec=ExternalChannelManagementService)

    response = _client(
        service,
        role=WorkspaceUserRole.MEMBER,
    ).put(
        "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
        "connection-1",
        json={
            "app_id": "discord-app-1",
            "configuration": {
                "provider": "discord",
                "target_guild_id": "guild-1",
                "thread_auto_archive_duration_minutes": 1440,
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


@pytest.mark.parametrize(
    ("path", "method", "payload", "service_method"),
    [
        (
            "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
            "connection-1",
            "GET",
            None,
            "get_multi_connection",
        ),
        (
            "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
            "connection-1/impact",
            "GET",
            None,
            "get_multi_connection_impact",
        ),
        (
            "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
            "connection-1/validate",
            "POST",
            None,
            "validate_multi_connection",
        ),
        (
            "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
            "connection-1",
            "DELETE",
            {"expected_generation": "2026-07-25T00:00:00Z"},
            "disconnect_multi_connection",
        ),
        (
            "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
            "connection-1/agents",
            "GET",
            None,
            "list_multi_routes",
        ),
        (
            "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
            "connection-1/agents",
            "POST",
            {"agent_id": "agent-1"},
            "add_multi_route",
        ),
        (
            "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
            "connection-1/agents/route-1/impact",
            "GET",
            None,
            "get_multi_route_impact",
        ),
        (
            "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
            "connection-1/agents/route-1",
            "DELETE",
            {"expected_generation": "2026-07-25T00:00:00Z"},
            "remove_multi_route",
        ),
        (
            "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
            "connection-1/agents/route-1/reenable",
            "POST",
            None,
            "reenable_multi_route",
        ),
        (
            "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
            "connection-1/channel-defaults",
            "GET",
            None,
            "list_multi_channel_defaults",
        ),
        (
            "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
            "connection-1/channel-defaults/channel-1",
            "PUT",
            {
                "route_id": "route-1",
                "expected_generation": "2026-07-25T00:00:00Z",
            },
            "replace_multi_channel_default",
        ),
        (
            "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
            "connection-1/channel-defaults/channel-1",
            "DELETE",
            {"expected_generation": "2026-07-25T00:00:00Z"},
            "clear_multi_channel_default",
        ),
    ],
)
def test_discord_multi_operations_keep_provider_ids_opaque(
    path: str,
    method: str,
    payload: dict[str, str] | None,
    service_method: str,
) -> None:
    """Every Discord management operation passes the provider fence to the service."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    getattr(service, service_method).side_effect = ExternalChannelManagementNotFound(
        "connection-1"
    )

    response = _client(service, role=WorkspaceUserRole.MANAGER).request(
        method,
        path,
        json=payload,
    )

    assert response.status_code == 404
    assert getattr(service, service_method).await_args.kwargs["provider"] is (
        ExternalChannelProvider.DISCORD
    )


@pytest.mark.parametrize(
    ("provider", "path"),
    [
        (
            ExternalChannelProvider.SLACK,
            "/external-channel/v1/workspaces/ws/external-channels/slack/multi",
        ),
        (
            ExternalChannelProvider.DISCORD,
            "/external-channel/v1/workspaces/ws/external-channels/discord/multi",
        ),
    ],
)
def test_multi_lists_are_provider_scoped(
    provider: ExternalChannelProvider,
    path: str,
) -> None:
    """Slack and Discord lists cannot enumerate each other's Multi Apps."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.list_multi_connections.return_value = []

    response = _client(service, role=WorkspaceUserRole.MANAGER).get(path)

    assert response.status_code == 200
    service.list_multi_connections.assert_awaited_once_with(
        workspace_id="workspace-1",
        provider=provider,
        offset=0,
        limit=50,
    )


def test_multi_list_uses_one_provider_neutral_page() -> None:
    """Workspace integrations receive one stable page across Slack and Discord."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.list_multi_connections.return_value = []

    response = _client(service, role=WorkspaceUserRole.MANAGER).get(
        "/external-channel/v1/workspaces/ws/external-channels/multi"
    )

    assert response.status_code == 200
    service.list_multi_connections.assert_awaited_once_with(
        workspace_id="workspace-1",
        provider=None,
        offset=0,
        limit=50,
    )


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
        provider=ExternalChannelProvider.SLACK,
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
            active_participation_setting_count=0,
            nonterminal_setup_claim_count=0,
            active_binding_count=0,
            connected_parent_binding_count=0,
            bound_resource_count=0,
            open_admission_count=0,
            pending_access_request_count=0,
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
        provider=ExternalChannelProvider.SLACK,
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
    assert (
        "/external-channel/v1/workspaces/{handle}/agents/{agent_id}/"
        "external-channels/default-response-mode" in paths
    )
    assert (
        "/external-channel/v1/workspaces/{handle}/agents/{agent_id}/sessions/"
        "{session_id}/external-channels/{binding_id}/response-mode" in paths
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
    assert "get" in paths[discord_multi_path]
    discord_single_update_path = f"{connection_path}/discord"
    assert discord_single_update_path in paths
    assert "put" in paths[discord_single_update_path]
    discord_multi_update_path = f"{discord_multi_path}/{{connection_id}}"
    assert discord_multi_update_path in paths
    assert "put" in paths[discord_multi_update_path]
    assert "get" in paths[discord_multi_update_path]
    assert f"{discord_multi_update_path}/validate" in paths
    assert f"{discord_multi_update_path}/impact" in paths
    assert f"{discord_multi_update_path}/agents" in paths
    assert f"{discord_multi_update_path}/agents/{{route_id}}/impact" in paths
    assert f"{discord_multi_update_path}/channel-defaults" in paths
    assert (
        f"{discord_multi_update_path}/channel-defaults/{{provider_channel_id}}" in paths
    )
    assert not any(
        "multi" in path and "/agents/{agent_id}/external-channels" in path
        for path in paths
    )
    assert "/external-channel/v1/slack/events" not in paths


def test_update_dedicated_discord_thread_duration() -> None:
    """The dedicated policy route forwards one validated non-secret value."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.update_discord_thread_auto_archive_duration.return_value = _connection()

    response = _client(service).put(
        "/external-channel/v1/workspaces/ws/agents/agent-1/"
        "external-channels/connection-1/discord/thread-auto-archive-duration",
        json={"thread_auto_archive_duration_minutes": 10080},
    )

    assert response.status_code == 200
    call = service.update_discord_thread_auto_archive_duration.await_args
    assert call.kwargs["connection_id"] == "connection-1"
    assert call.kwargs["setting"].thread_auto_archive_duration_minutes == 10080


def test_update_multi_discord_thread_duration_uses_generation_fence() -> None:
    """The Workspace policy route forwards the management generation."""
    service = AsyncMock(spec=ExternalChannelManagementService)
    service.update_multi_discord_thread_auto_archive_duration.return_value = (
        _multi_connection()
    )

    response = _client(service, role=WorkspaceUserRole.MANAGER).put(
        "/external-channel/v1/workspaces/ws/external-channels/discord/multi/"
        "connection-1/thread-auto-archive-duration",
        json={
            "thread_auto_archive_duration_minutes": 4320,
            "expected_generation": "2026-08-20T00:00:00Z",
        },
    )

    assert response.status_code == 200
    call = service.update_multi_discord_thread_auto_archive_duration.await_args
    assert call.kwargs["connection_id"] == "connection-1"
    assert call.kwargs["expected_generation"] == datetime.datetime(
        2026, 8, 20, tzinfo=datetime.UTC
    )
    assert call.kwargs["setting"].thread_auto_archive_duration_minutes == 4320


@pytest.mark.parametrize("duration", [0, 59, 61, 2880, 10081])
def test_discord_thread_duration_rejects_unsupported_values(duration: int) -> None:
    """The policy route rejects values outside Discord's closed set."""
    service = AsyncMock(spec=ExternalChannelManagementService)

    response = _client(service).put(
        "/external-channel/v1/workspaces/ws/agents/agent-1/"
        "external-channels/connection-1/discord/thread-auto-archive-duration",
        json={"thread_auto_archive_duration_minutes": duration},
    )

    assert response.status_code == 422
    service.update_discord_thread_auto_archive_duration.assert_not_awaited()
