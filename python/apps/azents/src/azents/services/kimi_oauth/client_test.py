"""Kimi OAuth client tests."""

import datetime
from urllib.parse import parse_qs

import httpx
from azcommon.result import Failure, Success

from azents.core.kimi_oauth import KIMI_OAUTH_CLIENT_ID, KimiOAuthConnectionMethod

from .client import KimiOAuthClient
from .data import (
    ProviderPending,
    ProviderRejected,
    ProviderSlowDown,
    ProviderUnavailable,
)

_DEVICE_ID = "device-id-123"


def _make_client(transport: httpx.AsyncBaseTransport) -> KimiOAuthClient:
    """Create a client using a mock transport."""
    return KimiOAuthClient(httpx.AsyncClient(transport=transport))


def _assert_compatibility_headers(request: httpx.Request) -> None:
    """Assert the stable Kimi CLI-compatible request identity."""
    assert request.headers["X-Msh-Platform"] == "kimi_cli"
    assert request.headers["X-Msh-Device-Name"] == "Azents"
    assert request.headers["X-Msh-Device-Model"] == "Azents Server"
    assert request.headers["X-Msh-Device-Id"] == _DEVICE_ID


class TestKimiOAuthClient:
    """KimiOAuthClient tests."""

    async def test_request_device_user_code(self) -> None:
        """Parse the Kimi device authorization response."""
        assert KIMI_OAUTH_CLIENT_ID == "17e5f671-d194-4dfb-9706-5516cb48c098"

        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/oauth/device_authorization"
            body = parse_qs(request.content.decode())
            assert body == {"client_id": [KIMI_OAUTH_CLIENT_ID]}
            _assert_compatibility_headers(request)
            return httpx.Response(
                200,
                json={
                    "device_code": "device-code-123",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://auth.kimi.com/device",
                    "verification_uri_complete": (
                        "https://auth.kimi.com/device?user_code=ABCD-EFGH"
                    ),
                    "interval": 7,
                    "expires_in": 900,
                },
            )

        result = await _make_client(
            httpx.MockTransport(handler)
        ).request_device_user_code(device_id=_DEVICE_ID)

        assert isinstance(result, Success)
        assert result.value.device_code == "device-code-123"
        assert result.value.user_code == "ABCD-EFGH"
        assert result.value.verification_uri == (
            "https://auth.kimi.com/device?user_code=ABCD-EFGH"
        )
        assert result.value.interval_seconds == 7
        assert result.value.expires_in_seconds == 900

    async def test_poll_device_tokens_pending(self) -> None:
        """Classify a pending device grant response as pending."""

        async def handler(request: httpx.Request) -> httpx.Response:
            _assert_compatibility_headers(request)
            return httpx.Response(400, json={"error": "authorization_pending"})

        result = await _make_client(httpx.MockTransport(handler)).poll_device_tokens(
            device_code="device-code-123",
            device_id=_DEVICE_ID,
            connection_method=KimiOAuthConnectionMethod.DEVICE,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProviderPending)

    async def test_poll_device_tokens_slow_down(self) -> None:
        """Preserve a provider request to increase the polling interval."""

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "slow_down"})

        result = await _make_client(httpx.MockTransport(handler)).poll_device_tokens(
            device_code="device-code-123",
            device_id=_DEVICE_ID,
            connection_method=KimiOAuthConnectionMethod.DEVICE,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProviderSlowDown)

    async def test_poll_device_tokens_success(self) -> None:
        """Convert a device grant response to a token set."""

        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/oauth/token"
            body = parse_qs(request.content.decode())
            assert body["grant_type"] == [
                "urn:ietf:params:oauth:grant-type:device_code"
            ]
            assert body["client_id"] == [KIMI_OAUTH_CLIENT_ID]
            assert body["device_code"] == ["device-code-123"]
            _assert_compatibility_headers(request)
            return httpx.Response(
                200,
                json={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 3600,
                },
            )

        result = await _make_client(httpx.MockTransport(handler)).poll_device_tokens(
            device_code="device-code-123",
            device_id=_DEVICE_ID,
            connection_method=KimiOAuthConnectionMethod.DEVICE,
        )

        assert isinstance(result, Success)
        assert result.value.access_token == "access-token"
        assert result.value.refresh_token == "refresh-token"
        assert result.value.expires_at > datetime.datetime.now(datetime.UTC)
        assert result.value.connection_method == KimiOAuthConnectionMethod.DEVICE

    async def test_refresh_uses_existing_refresh_token_when_not_rotated(self) -> None:
        """Keep the old refresh token when Kimi does not rotate it."""

        async def handler(request: httpx.Request) -> httpx.Response:
            body = parse_qs(request.content.decode())
            assert body["grant_type"] == ["refresh_token"]
            assert body["refresh_token"] == ["old-refresh-token"]
            assert body["client_id"] == [KIMI_OAUTH_CLIENT_ID]
            _assert_compatibility_headers(request)
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access-token",
                    "expires_in": 3600,
                },
            )

        result = await _make_client(httpx.MockTransport(handler)).refresh_tokens(
            refresh_token="old-refresh-token",
            device_id=_DEVICE_ID,
            connection_method=KimiOAuthConnectionMethod.DEVICE,
        )

        assert isinstance(result, Success)
        assert result.value.access_token == "new-access-token"
        assert result.value.refresh_token == "old-refresh-token"

    async def test_provider_403_is_rejected(self) -> None:
        """Classify HTTP 403 as a permanent credential rejection."""

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "access_denied"})

        result = await _make_client(httpx.MockTransport(handler)).refresh_tokens(
            refresh_token="refresh-token",
            device_id=_DEVICE_ID,
            connection_method=KimiOAuthConnectionMethod.DEVICE,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProviderRejected)

    async def test_provider_rate_limit_is_unavailable(self) -> None:
        """Classify HTTP 429 as temporary provider unavailability."""

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate_limited"})

        result = await _make_client(httpx.MockTransport(handler)).refresh_tokens(
            refresh_token="refresh-token",
            device_id=_DEVICE_ID,
            connection_method=KimiOAuthConnectionMethod.DEVICE,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProviderUnavailable)

    async def test_provider_4xx_is_rejected(self) -> None:
        """Classify other 4xx responses as provider rejection."""

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "invalid_grant"})

        result = await _make_client(httpx.MockTransport(handler)).refresh_tokens(
            refresh_token="refresh-token",
            device_id=_DEVICE_ID,
            connection_method=KimiOAuthConnectionMethod.DEVICE,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProviderRejected)
