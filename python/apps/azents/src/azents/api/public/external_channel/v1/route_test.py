"""External Channel Slack callback route tests."""

from unittest.mock import AsyncMock

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from azents.app import create_dummy_public_app
from azents.services.external_channel.http_admission import (
    SlackHTTPAdmissionResult,
    SlackHTTPAdmissionService,
)
from azents.services.external_channel.slack_http import (
    MAX_SLACK_HTTP_BODY_BYTES,
    SlackHTTPUnauthorized,
)

from .route import router


def _client(service: AsyncMock) -> TestClient:
    app = create_dummy_public_app()
    app.dependency_overrides[SlackHTTPAdmissionService] = lambda: service
    return TestClient(app)


def test_url_verification_returns_challenge() -> None:
    """Return the verified Slack challenge without exposing a client operation."""
    service = AsyncMock(spec=SlackHTTPAdmissionService)
    service.handle.return_value = SlackHTTPAdmissionResult(
        challenge="challenge-1",
        event_id=None,
        created=None,
    )

    response = _client(service).post(
        "/external-channel/v1/slack/events/selector-1",
        content=b'{"type":"url_verification"}',
        headers={
            "X-Slack-Request-Timestamp": "1784682000",
            "X-Slack-Signature": "v0=signature",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge-1"}
    call = service.handle.await_args.kwargs
    assert call["selector"] == "selector-1"
    assert call["raw_body"] == b'{"type":"url_verification"}'


def test_authentication_failure_uses_one_safe_response() -> None:
    """Do not distinguish unknown selectors from invalid Slack signatures."""
    service = AsyncMock(spec=SlackHTTPAdmissionService)
    service.handle.side_effect = SlackHTTPUnauthorized("private detail")

    response = _client(service).post(
        "/external-channel/v1/slack/events/unknown",
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
            "/external-channel/v1/slack/events/selector-1",
            content=b"{}",
        )


def test_oversized_body_is_rejected_before_service_admission() -> None:
    """Stop buffering and reject a callback beyond the provider inbox limit."""
    service = AsyncMock(spec=SlackHTTPAdmissionService)

    response = _client(service).post(
        "/external-channel/v1/slack/events/selector-1",
        content=b"x" * (MAX_SLACK_HTTP_BODY_BYTES + 1),
    )

    assert response.status_code == 413
    service.handle.assert_not_awaited()


def test_callback_is_mounted_but_excluded_from_public_openapi() -> None:
    """Keep provider reachability outside generated authenticated clients."""
    paths = {route.path for route in router.routes if isinstance(route, APIRoute)}
    app = create_dummy_public_app()

    assert "/slack/events/{selector}" in paths
    assert any(
        getattr(route, "path", None) == "/external-channel/v1/slack/events/{selector}"
        for route in app.routes
    )
    assert "/external-channel/v1/slack/events/{selector}" not in app.openapi()["paths"]
