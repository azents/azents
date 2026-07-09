"""xAI OAuth client tests."""

import base64
import datetime
import json
from urllib.parse import parse_qs

import httpx
from azcommon.result import Failure, Success

from azents.core.xai_oauth import XAI_OAUTH_SCOPE, XaiOAuthConnectionMethod

from .client import XaiOAuthClient
from .data import (
    ProviderEntitlementDenied,
    ProviderPending,
    ProviderRejected,
    ProviderUnavailable,
)


def _jwt_payload(payload: dict[str, object]) -> str:
    """Create unsigned JWT payload for tests."""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}."


def _make_client(transport: httpx.AsyncBaseTransport) -> XaiOAuthClient:
    """Create client using Mock transport."""
    return XaiOAuthClient(
        httpx.AsyncClient(transport=transport), client_id="client-123"
    )


class TestXaiOAuthClient:
    """XaiOAuthClient tests."""

    async def test_request_device_user_code(self) -> None:
        """Parse Device user-code response."""

        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/oauth2/device/code"
            body = parse_qs(request.content.decode())
            assert body["client_id"] == ["client-123"]
            assert body["scope"] == [XAI_OAUTH_SCOPE]
            return httpx.Response(
                200,
                json={
                    "device_code": "device-code-123",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://auth.x.ai/activate",
                    "interval": 7,
                    "expires_in": 900,
                },
            )

        result = await _make_client(
            httpx.MockTransport(handler)
        ).request_device_user_code()

        assert isinstance(result, Success)
        assert result.value.device_code == "device-code-123"
        assert result.value.user_code == "ABCD-EFGH"
        assert result.value.verification_uri == "https://auth.x.ai/activate"
        assert result.value.interval_seconds == 7
        assert result.value.expires_in_seconds == 900

    async def test_poll_device_tokens_pending(self) -> None:
        """Classify pending device grant response as pending."""

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "authorization_pending"})

        result = await _make_client(httpx.MockTransport(handler)).poll_device_tokens(
            device_code="device-code-123",
            connection_method=XaiOAuthConnectionMethod.DEVICE,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProviderPending)

    async def test_poll_device_tokens_success(self) -> None:
        """Convert device grant response to token set."""
        id_token = _jwt_payload({"sub": "account-123", "email": "user@example.com"})

        async def handler(request: httpx.Request) -> httpx.Response:
            body = parse_qs(request.content.decode())
            assert body["grant_type"] == [
                "urn:ietf:params:oauth:grant-type:device_code"
            ]
            assert body["client_id"] == ["client-123"]
            assert body["device_code"] == ["device-code-123"]
            return httpx.Response(
                200,
                json={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "id_token": id_token,
                    "expires_in": 3600,
                },
            )

        result = await _make_client(httpx.MockTransport(handler)).poll_device_tokens(
            device_code="device-code-123",
            connection_method=XaiOAuthConnectionMethod.DEVICE,
        )

        assert isinstance(result, Success)
        assert result.value.access_token == "access-token"
        assert result.value.refresh_token == "refresh-token"
        assert result.value.id_token == id_token
        assert result.value.account_id == "account-123"
        assert result.value.email == "user@example.com"
        assert result.value.expires_at > datetime.datetime.now(datetime.UTC)

    async def test_refresh_uses_existing_refresh_token_when_not_rotated(self) -> None:
        """Keep the old refresh token when xAI does not rotate it."""

        async def handler(request: httpx.Request) -> httpx.Response:
            body = parse_qs(request.content.decode())
            assert body["grant_type"] == ["refresh_token"]
            assert body["refresh_token"] == ["old-refresh-token"]
            assert body["client_id"] == ["client-123"]
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access-token",
                    "expires_in": 3600,
                },
            )

        result = await _make_client(httpx.MockTransport(handler)).refresh_tokens(
            refresh_token="old-refresh-token",
            connection_method=XaiOAuthConnectionMethod.DEVICE,
        )

        assert isinstance(result, Success)
        assert result.value.access_token == "new-access-token"
        assert result.value.refresh_token == "old-refresh-token"

    async def test_provider_403_is_entitlement_denied(self) -> None:
        """Classify HTTP 403 as entitlement denial instead of token expiry."""

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "access_denied"})

        result = await _make_client(httpx.MockTransport(handler)).refresh_tokens(
            refresh_token="refresh-token",
            connection_method=XaiOAuthConnectionMethod.DEVICE,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProviderEntitlementDenied)

    async def test_provider_rate_limit_is_unavailable(self) -> None:
        """Classify HTTP 429 as temporary provider unavailability."""

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate_limited"})

        result = await _make_client(httpx.MockTransport(handler)).refresh_tokens(
            refresh_token="refresh-token",
            connection_method=XaiOAuthConnectionMethod.DEVICE,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProviderUnavailable)

    async def test_provider_4xx_is_rejected(self) -> None:
        """Classify non-entitlement 4xx as provider rejection."""

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "invalid_grant"})

        result = await _make_client(httpx.MockTransport(handler)).refresh_tokens(
            refresh_token="refresh-token",
            connection_method=XaiOAuthConnectionMethod.DEVICE,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProviderRejected)
