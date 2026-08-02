"""External Channel Slack callback route tests."""

import logging
from unittest.mock import AsyncMock

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from azents.app import create_dummy_public_app
from azents.services.external_channel.discord_http import (
    DiscordHTTPAdmissionResult,
    DiscordHTTPAdmissionService,
)
from azents.services.external_channel.discord_interaction import (
    MAX_DISCORD_INTERACTION_BODY_BYTES,
    DiscordInteractionEnvelope,
    DiscordInteractionUnauthorized,
)
from azents.services.external_channel.http_admission import (
    SlackHTTPAdmissionResult,
    SlackHTTPAdmissionService,
)
from azents.services.external_channel.slack_http import (
    MAX_SLACK_HTTP_BODY_BYTES,
    SlackHTTPUnauthorized,
)
from azents.testing.external_channel import make_provider_effect_plan

from .route import router


def _client(service: AsyncMock) -> TestClient:
    app = create_dummy_public_app()
    app.dependency_overrides[SlackHTTPAdmissionService] = lambda: service
    return TestClient(app)


def _discord_client(service: AsyncMock) -> TestClient:
    app = create_dummy_public_app()
    app.dependency_overrides[DiscordHTTPAdmissionService] = lambda: service
    return TestClient(app)


@pytest.mark.parametrize(
    ("interaction_type", "expected_response_type"),
    [(2, 5), (3, 6), (4, 8), (5, 5)],
)
def test_discord_admission_returns_matching_initial_response(
    interaction_type: int,
    expected_response_type: int,
) -> None:
    """A successful durable admission receives its provider-native acknowledgement."""
    service = AsyncMock(spec=DiscordHTTPAdmissionService)
    service.handle.return_value = DiscordHTTPAdmissionResult(
        envelope=DiscordInteractionEnvelope(
            interaction_id="interaction-1",
            interaction_type=interaction_type,
            application_id="app-1",
            guild_id="guild-1",
            channel_id="channel-1",
            provider_parent_channel_id="channel-1",
            provider_thread_id=None,
            actor_user_id="user-1",
            command=None,
            message_command_source=None,
            component_custom_id=None,
            selected_value=None,
            modal_custom_id=None,
        ),
        admission=None,
    )

    response = _discord_client(service).post(
        "/external-channel/v1/discord/interactions/opaque-selector",
        content=b'{"token":"request-local-only"}',
        headers={
            "X-Signature-Ed25519": "signature",
            "X-Signature-Timestamp": "1784682000",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"type": expected_response_type}
    call = service.handle.await_args.kwargs
    assert call["selector"] == "opaque-selector"
    assert call["raw_body"] == b'{"token":"request-local-only"}'


def test_discord_control_plans_run_after_provider_response() -> None:
    """Attempt every committed direct plan after returning the response."""
    service = AsyncMock(spec=DiscordHTTPAdmissionService)
    first_plan = make_provider_effect_plan("discord-control-1")
    second_plan = make_provider_effect_plan("discord-control-2")
    service.handle.return_value = DiscordHTTPAdmissionResult(
        envelope=DiscordInteractionEnvelope(
            interaction_id="interaction-1",
            interaction_type=3,
            application_id="app-1",
            guild_id="guild-1",
            channel_id="channel-1",
            provider_parent_channel_id="channel-1",
            provider_thread_id=None,
            actor_user_id="user-1",
            command=None,
            message_command_source=None,
            component_custom_id="a:pc:interaction-1:setting-1:1:signature",
            selected_value=None,
            modal_custom_id=None,
        ),
        admission=None,
        response={"type": 7, "data": {"content": "Saved.", "components": []}},
        control_plans=(first_plan, second_plan),
        control_delivery_connection_id="connection-1",
    )

    response = _discord_client(service).post(
        "/external-channel/v1/discord/interactions/opaque-selector",
        content=b'{"token":"request-local-only"}',
        headers={
            "X-Signature-Ed25519": "signature",
            "X-Signature-Timestamp": "1784682000",
        },
    )

    assert response.status_code == 200
    assert service.attempt_control_delivery.await_count == 2
    assert service.attempt_control_delivery.await_args_list[0].kwargs == {
        "connection_id": "connection-1",
        "plan": first_plan,
    }
    assert service.attempt_control_delivery.await_args_list[1].kwargs == {
        "connection_id": "connection-1",
        "plan": second_plan,
    }


def test_discord_authentication_failure_uses_one_safe_response(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unknown selectors and invalid signatures remain indistinguishable."""
    service = AsyncMock(spec=DiscordHTTPAdmissionService)
    service.handle.side_effect = DiscordInteractionUnauthorized(
        "private detail",
        failure_code="discord_interaction_signature_invalid",
    )

    with caplog.at_level(logging.INFO):
        response = _discord_client(service).post(
            "/external-channel/v1/discord/interactions/opaque-selector",
            content=b"{}",
        )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Discord interaction could not be authenticated."
    }
    assert "private detail" not in response.text
    records = [
        record
        for record in caplog.records
        if record.message == "Rejected unauthenticated Discord interaction"
    ]
    assert len(records) == 1
    assert records[0].__dict__["authentication_failure_code"] == (
        "discord_interaction_signature_invalid"
    )


def test_oversized_discord_body_is_rejected_before_admission() -> None:
    """The Discord raw-body cap stops buffering before signature handling."""
    service = AsyncMock(spec=DiscordHTTPAdmissionService)

    response = _discord_client(service).post(
        "/external-channel/v1/discord/interactions/opaque-selector",
        content=b"x" * (MAX_DISCORD_INTERACTION_BODY_BYTES + 1),
    )

    assert response.status_code == 400
    service.handle.assert_not_awaited()


def test_url_verification_returns_challenge() -> None:
    """Return the verified Slack challenge without exposing a client operation."""
    service = AsyncMock(spec=SlackHTTPAdmissionService)
    service.handle.return_value = SlackHTTPAdmissionResult(
        challenge="challenge-1",
        event_id=None,
        interaction_id=None,
        created=None,
    )

    response = _client(service).post(
        "/external-channel/v1/slack/events",
        content=b'{"type":"url_verification"}',
        headers={
            "X-Slack-Request-Timestamp": "1784682000",
            "X-Slack-Signature": "v0=signature",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge-1"}
    call = service.handle.await_args.kwargs
    assert call["raw_body"] == b'{"type":"url_verification"}'


def test_slack_control_plan_runs_after_committed_admission() -> None:
    """Attempt one direct approval control after returning provider success."""
    service = AsyncMock(spec=SlackHTTPAdmissionService)
    plan = make_provider_effect_plan("slack-control")
    service.handle.return_value = SlackHTTPAdmissionResult(
        challenge=None,
        event_id="event-1",
        interaction_id=None,
        created=False,
        control_plan=plan,
        control_delivery_connection_id="connection-1",
    )

    response = _client(service).post(
        "/external-channel/v1/slack/events",
        content=b'{"type":"event_callback"}',
        headers={
            "X-Slack-Request-Timestamp": "1784682000",
            "X-Slack-Signature": "v0=signature",
        },
    )

    assert response.status_code == 200
    service.attempt_control_delivery.assert_awaited_once_with(
        connection_id="connection-1",
        plan=plan,
    )


def test_authentication_failure_uses_one_safe_response() -> None:
    """Do not distinguish unknown identities from invalid Slack signatures."""
    service = AsyncMock(spec=SlackHTTPAdmissionService)
    service.handle.side_effect = SlackHTTPUnauthorized("private detail")

    response = _client(service).post(
        "/external-channel/v1/slack/events",
        content=b"{}",
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Slack callback could not be authenticated."}
    assert "private detail" not in response.text


def test_database_failure_is_not_acknowledged_as_success() -> None:
    """Let unexpected admission failures propagate to the common server handler."""
    service = AsyncMock(spec=SlackHTTPAdmissionService)
    service.handle.side_effect = RuntimeError("database unavailable")
    client = _client(service)

    with pytest.raises(RuntimeError, match="database unavailable"):
        client.post(
            "/external-channel/v1/slack/events",
            content=b"{}",
        )


def test_oversized_body_is_rejected_before_service_admission() -> None:
    """Stop buffering and reject a callback beyond the provider inbox limit."""
    service = AsyncMock(spec=SlackHTTPAdmissionService)

    response = _client(service).post(
        "/external-channel/v1/slack/events",
        content=b"x" * (MAX_SLACK_HTTP_BODY_BYTES + 1),
    )

    assert response.status_code == 413
    service.handle.assert_not_awaited()


def test_callback_is_mounted_but_excluded_from_public_openapi() -> None:
    """Keep provider reachability outside generated authenticated clients."""
    paths = {route.path for route in router.routes if isinstance(route, APIRoute)}
    app = create_dummy_public_app()

    assert "/slack/events" in paths
    assert any(
        getattr(route, "path", None) == "/external-channel/v1/slack/events"
        for route in app.routes
    )
    assert "/external-channel/v1/slack/events" not in app.openapi()["paths"]
