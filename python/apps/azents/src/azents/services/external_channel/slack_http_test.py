"""Slack HTTP signature, parsing, and identity validation tests."""

import datetime
import hashlib
import hmac
import json

import httpx
import pytest

from azents.core.enums import ExternalChannelTransport
from azents.services.external_channel.slack_http import (
    MAX_SLACK_HTTP_BODY_BYTES,
    SlackEventCallback,
    SlackHTTPPayloadTooLarge,
    SlackHTTPUnauthorized,
    SlackURLVerification,
    SlackWebAPIClient,
    parse_slack_callback,
    verify_slack_signature,
)

_NOW = datetime.datetime(2026, 7, 22, 1, 0, tzinfo=datetime.UTC)
_SECRET = "signing-secret"


def _signature(body: bytes, timestamp: int | None = None) -> tuple[str, str]:
    request_timestamp = timestamp if timestamp is not None else int(_NOW.timestamp())
    timestamp_header = str(request_timestamp)
    base = b"v0:" + timestamp_header.encode() + b":" + body
    signature = "v0=" + hmac.new(_SECRET.encode(), base, hashlib.sha256).hexdigest()
    return timestamp_header, signature


def _event_body() -> bytes:
    return json.dumps(
        {
            "type": "event_callback",
            "event_id": "Ev-1",
            "event_time": int(_NOW.timestamp()),
            "api_app_id": "A-1",
            "team_id": "T-1",
            "enterprise_id": "E-1",
            "token": "deprecated-token-must-not-be-stored",
            "event": {
                "type": "app_mention",
                "channel": "C-1",
                "user": "U-1",
                "text": "Please investigate",
                "ts": "100.0002",
                "thread_ts": "100.0001",
                "unexpected": "not retained",
            },
        }
    ).encode()


def test_signature_verification_uses_exact_raw_body() -> None:
    """Accept the signed bytes and reject a semantically equal reserialization."""
    body = b'{"type":"url_verification","challenge":"abc"}'
    timestamp, signature = _signature(body)

    verify_slack_signature(
        raw_body=body,
        timestamp_header=timestamp,
        signature_header=signature,
        signing_secret=_SECRET,
        now=_NOW,
    )

    with pytest.raises(SlackHTTPUnauthorized):
        verify_slack_signature(
            raw_body=b'{"challenge":"abc","type":"url_verification"}',
            timestamp_header=timestamp,
            signature_header=signature,
            signing_secret=_SECRET,
            now=_NOW,
        )


@pytest.mark.parametrize("offset_seconds", [-301, 301])
def test_signature_verification_rejects_replay_window(offset_seconds: int) -> None:
    """Reject both stale and excessively future-dated requests."""
    body = b"{}"
    timestamp, signature = _signature(
        body,
        int(_NOW.timestamp()) + offset_seconds,
    )

    with pytest.raises(SlackHTTPUnauthorized):
        verify_slack_signature(
            raw_body=body,
            timestamp_header=timestamp,
            signature_header=signature,
            signing_secret=_SECRET,
            now=_NOW,
        )


def test_url_verification_does_not_require_app_identity() -> None:
    """Return the challenge because Slack omits ``api_app_id`` from this shape."""
    result = parse_slack_callback(
        connection_id="connection-1",
        raw_body=json.dumps(
            {"type": "url_verification", "challenge": "challenge-1"}
        ).encode(),
        received_at=_NOW,
    )

    assert result == SlackURLVerification(challenge="challenge-1")


def test_event_callback_projects_bounded_routing_and_message_fields() -> None:
    """Normalize identity and correlation while dropping unrelated top-level data."""
    result = parse_slack_callback(
        connection_id="connection-1",
        raw_body=_event_body(),
        received_at=_NOW,
    )

    assert isinstance(result, SlackEventCallback)
    assert result.app_id == "A-1"
    assert result.tenant_id == "T-1"
    assert result.event.provider_event_id == "Ev-1"
    assert result.event.event_type == "app_mention"
    assert result.event.resource_correlation_key == "C-1:100.0001"
    assert result.event.provider_enterprise_id == "E-1"
    assert "token" not in result.event.envelope
    event = result.event.envelope["event"]
    assert isinstance(event, dict)
    assert event["text"] == "Please investigate"
    assert "unexpected" not in event


def test_event_callback_rejects_oversized_body() -> None:
    """Bound the provider inbox before JSON normalization."""
    with pytest.raises(SlackHTTPPayloadTooLarge):
        parse_slack_callback(
            connection_id="connection-1",
            raw_body=b"x" * (MAX_SLACK_HTTP_BODY_BYTES + 1),
            received_at=_NOW,
        )


@pytest.mark.asyncio
async def test_auth_test_returns_sanitized_identity() -> None:
    """Expose only provider identity and capabilities from ``auth.test``."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer xoxb-secret"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "team_id": "T-1",
                "user_id": "U-BOT",
                "bot_id": "B-1",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SlackWebAPIClient(client).validate_connection(
            bot_token="xoxb-secret",
            app_id="A-1",
            transport=ExternalChannelTransport.HTTP,
        )

    assert result.status == "valid"
    assert result.identity is not None
    assert result.identity.app_id == "A-1"
    assert result.identity.tenant_id == "T-1"
    assert result.identity.bot_user_id == "B-1"
    assert result.capabilities is not None
    assert "xoxb-secret" not in repr(result)


@pytest.mark.asyncio
async def test_auth_test_distinguishes_invalid_and_unavailable() -> None:
    """Map rejected credentials separately from transient provider failure."""

    def invalid_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(invalid_handler)
    ) as client:
        invalid = await SlackWebAPIClient(client).validate_connection(
            bot_token="xoxb-invalid",
            app_id="A-1",
            transport=ExternalChannelTransport.HTTP,
        )

    def unavailable_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(unavailable_handler)
    ) as client:
        unavailable = await SlackWebAPIClient(client).validate_connection(
            bot_token="xoxb-secret",
            app_id="A-1",
            transport=ExternalChannelTransport.HTTP,
        )

    assert invalid.status == "invalid"
    assert invalid.code == "slack_credentials_invalid"
    assert unavailable.status == "unavailable"
    assert unavailable.code == "slack_unavailable"
