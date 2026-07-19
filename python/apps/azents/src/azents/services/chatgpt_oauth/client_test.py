"""ChatGPTOAuthClient tests."""

import base64
import datetime
import json

import httpx
from azcommon.result import Failure, Success

from azents.core.chatgpt_oauth import (
    CHATGPT_OAUTH_TOKEN_URL,
    ChatGPTOAuthConnectionMethod,
)

from .client import ChatGPTOAuthClient
from .data import ProviderPending, ProviderRejected, ProviderUnavailable


def _jwt_payload(payload: dict[str, object]) -> str:
    """Create unsigned JWT payload for tests."""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"{header}.{body}."


def _make_client(
    transport: httpx.AsyncBaseTransport,
    *,
    token_url: str = CHATGPT_OAUTH_TOKEN_URL,
) -> ChatGPTOAuthClient:
    """Create client using Mock transport."""
    return ChatGPTOAuthClient(
        httpx.AsyncClient(transport=transport),
        token_url=token_url,
    )


class TestChatGPTOAuthClient:
    """ChatGPTOAuthClient tests."""

    async def test_request_device_user_code(self) -> None:
        """Parse Device user-code response."""

        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/accounts/deviceauth/usercode"
            return httpx.Response(
                200,
                json={
                    "device_auth_id": "device-auth-123",
                    "user_code": "ABCD-EFGH",
                    "interval": "7",
                },
            )

        result = await _make_client(
            httpx.MockTransport(handler)
        ).request_device_user_code()

        assert isinstance(result, Success)
        assert result.value.device_auth_id == "device-auth-123"
        assert result.value.user_code == "ABCD-EFGH"
        assert result.value.interval_seconds == 7

    async def test_poll_device_authorization_code_pending(self) -> None:
        """Classify Provider pending status as pending result."""

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "authorization_pending"})

        result = await _make_client(
            httpx.MockTransport(handler)
        ).poll_device_authorization_code(
            device_auth_id="device-auth-123", user_code="ABCD-EFGH"
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProviderPending)

    async def test_exchange_authorization_code_success(self) -> None:
        """Convert Authorization code exchange response to token set."""
        id_token = _jwt_payload(
            {
                "sub": "account-123",
                "email": "user@example.com",
                "plan_type": "plus",
            }
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            body = request.content.decode()
            assert "grant_type=authorization_code" in body
            assert "code=auth-code" in body
            assert "code_verifier=verifier" in body
            return httpx.Response(
                200,
                json={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "id_token": id_token,
                    "expires_in": 3600,
                },
            )

        result = await _make_client(
            httpx.MockTransport(handler)
        ).exchange_authorization_code(
            code="auth-code",
            code_verifier="verifier",
            redirect_uri="https://api.example.com/callback",
            connection_method=ChatGPTOAuthConnectionMethod.CALLBACK,
        )

        assert isinstance(result, Success)
        assert result.value.access_token == "access-token"
        assert result.value.refresh_token == "refresh-token"
        assert result.value.id_token == id_token
        assert result.value.account_id == "account-123"
        assert result.value.email == "user@example.com"
        assert result.value.plan_type == "plus"
        assert result.value.expires_at > datetime.datetime.now(datetime.UTC)

    async def test_exchange_authorization_code_rejected(self) -> None:
        """Classify 4xx token endpoint response as provider rejected."""

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "invalid_grant"})

        result = await _make_client(
            httpx.MockTransport(handler)
        ).exchange_authorization_code(
            code="auth-code",
            code_verifier="verifier",
            redirect_uri="https://api.example.com/callback",
            connection_method=ChatGPTOAuthConnectionMethod.CALLBACK,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProviderRejected)

    async def test_exchange_authorization_code_rate_limited(self) -> None:
        """Classify 429 token endpoint response as provider unavailable."""

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate_limited"})

        result = await _make_client(
            httpx.MockTransport(handler)
        ).exchange_authorization_code(
            code="auth-code",
            code_verifier="verifier",
            redirect_uri="https://api.example.com/callback",
            connection_method=ChatGPTOAuthConnectionMethod.CALLBACK,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProviderUnavailable)

    async def test_exchange_authorization_code_unavailable(self) -> None:
        """Classify 5xx token endpoint response as provider unavailable."""

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "unavailable"})

        result = await _make_client(
            httpx.MockTransport(handler)
        ).exchange_authorization_code(
            code="auth-code",
            code_verifier="verifier",
            redirect_uri="https://api.example.com/callback",
            connection_method=ChatGPTOAuthConnectionMethod.CALLBACK,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProviderUnavailable)

    async def test_exchange_authorization_code_invalid_success_body(self) -> None:
        """Classify invalid provider success body as provider unavailable."""

        async def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        result = await _make_client(
            httpx.MockTransport(handler)
        ).exchange_authorization_code(
            code="auth-code",
            code_verifier="verifier",
            redirect_uri="https://api.example.com/callback",
            connection_method=ChatGPTOAuthConnectionMethod.CALLBACK,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProviderUnavailable)

    async def test_refresh_tokens_uses_injected_token_url(self) -> None:
        """Use the configured token endpoint without changing provider defaults."""

        async def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "https://oauth.example.test/custom/token"
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access-token",
                    "refresh_token": "new-refresh-token",
                    "expires_in": 3600,
                },
            )

        result = await _make_client(
            httpx.MockTransport(handler),
            token_url="https://oauth.example.test/custom/token",
        ).refresh_tokens(
            refresh_token="refresh-token",
            connection_method=ChatGPTOAuthConnectionMethod.DEVICE,
        )

        assert isinstance(result, Success)

    async def test_refresh_tokens_success(self) -> None:
        """Convert Refresh token grant response to token set."""

        async def handler(request: httpx.Request) -> httpx.Response:
            body = request.content.decode()
            assert "grant_type=refresh_token" in body
            assert "refresh_token=refresh-token" in body
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access-token",
                    "refresh_token": "new-refresh-token",
                    "expires_in": 3600,
                },
            )

        result = await _make_client(httpx.MockTransport(handler)).refresh_tokens(
            refresh_token="refresh-token",
            connection_method=ChatGPTOAuthConnectionMethod.DEVICE,
        )

        assert isinstance(result, Success)
        assert result.value.access_token == "new-access-token"
        assert result.value.refresh_token == "new-refresh-token"
        assert result.value.connection_method == ChatGPTOAuthConnectionMethod.DEVICE
