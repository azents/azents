"""Public Authlib boundary contracts with the established HTTP backend."""

import asyncio
import gzip
import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from authlib.integrations.httpx_client import AsyncOAuth2Client
from pydantic import ValidationError

from azents.core.oauth2 import (
    OAuthTokenError,
    OAuthTokenResponse,
    build_authorization_url,
    exchange_authorization_code,
    refresh_access_token,
)


async def _grant(operation: str, secret: str | None) -> OAuthTokenResponse:
    if operation == "exchange":
        return await exchange_authorization_code(
            "https://provider.test/token",
            "client",
            secret,
            "code",
            "https://app.test/callback",
            code_verifier="verifier",
            resource="https://mcp.test",
            proxy_url="http://proxy.test:3128",
        )
    return await refresh_access_token(
        "https://provider.test/token",
        "client",
        secret,
        "old-refresh",
        proxy_url="http://proxy.test:3128",
    )


@pytest.mark.parametrize("operation", ["exchange", "refresh"])
@pytest.mark.parametrize("secret", [None, "secret", ""])
async def test_public_sdk_owns_grant_forms(operation: str, secret: str | None) -> None:
    """SDK grant/auth encoding retains PKCE, resource and proxy contracts."""
    requests: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    if operation == "exchange":
        method = "fetch_token"
        implementation = AsyncOAuth2Client.fetch_token
    else:
        method = "refresh_token"
        implementation = AsyncOAuth2Client.refresh_token
    with (
        patch(
            "azents.core.oauth2.httpx.AsyncClient", return_value=http_client
        ) as factory,
        patch.object(
            AsyncOAuth2Client,
            method,
            autospec=True,
            side_effect=implementation,
        ) as sdk,
    ):
        token = await _grant(operation, secret)
    factory.assert_called_once_with(proxy="http://proxy.test:3128")
    sdk.assert_called_once()
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.headers["accept"] == "application/json"
    assert "authorization" not in request.headers
    form = parse_qs(request.content.decode(), keep_blank_values=True)
    expected = {"client_id": ["client"]}
    if secret is not None:
        expected["client_secret"] = [secret]
    if operation == "exchange":
        expected.update(
            {
                "grant_type": ["authorization_code"],
                "code": ["code"],
                "redirect_uri": ["https://app.test/callback"],
                "code_verifier": ["verifier"],
                "resource": ["https://mcp.test"],
            }
        )
    else:
        expected.update(
            {"grant_type": ["refresh_token"], "refresh_token": ["old-refresh"]}
        )
    assert form == expected
    assert token.access_token == "access"
    assert token.refresh_token is None
    assert token.expires_at is not None
    assert http_client.is_closed


@pytest.mark.parametrize("operation", ["exchange", "refresh"])
@pytest.mark.parametrize("status", [302, 400, 503])
async def test_http_status_contract_is_unchanged(operation: str, status: int) -> None:
    """Non-success responses remain original httpx status failures."""
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(status, json={"error": "invalid_grant"})
        )
    )
    with patch("azents.core.oauth2.httpx.AsyncClient", return_value=http_client):
        with pytest.raises(httpx.HTTPStatusError) as raised:
            await _grant(operation, None)
    assert raised.value.response.status_code == status
    assert raised.value.response.json() == {"error": "invalid_grant"}
    assert str(raised.value.request.url) == "https://provider.test/token"


@pytest.mark.parametrize("operation", ["exchange", "refresh"])
async def test_http_200_provider_error_contract(operation: str) -> None:
    """Non-standard error bodies keep OAuthTokenError instead of SDK exceptions."""
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "ok": False,
                    "error": "invalid_grant",
                    "error_description": "expired",
                },
            )
        )
    )
    with patch("azents.core.oauth2.httpx.AsyncClient", return_value=http_client):
        with pytest.raises(OAuthTokenError, match="invalid_grant: expired"):
            await _grant(operation, None)


@pytest.mark.parametrize("payload", [[], {"unknown": "field"}, {"access_token": None}])
async def test_malformed_success_keeps_validation_failure(payload: object) -> None:
    """The existing Pydantic token boundary rejects malformed success."""
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    )
    with patch("azents.core.oauth2.httpx.AsyncClient", return_value=http_client):
        with pytest.raises(ValidationError):
            await _grant("exchange", None)


async def test_malformed_json_keeps_decode_failure() -> None:
    """Invalid JSON still fails before SDK token normalization."""
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=b"not-json")
        )
    )
    with patch("azents.core.oauth2.httpx.AsyncClient", return_value=http_client):
        with pytest.raises(json.JSONDecodeError):
            await _grant("refresh", None)


@pytest.mark.parametrize("refresh", [None, "rotated"])
async def test_refresh_retains_original_nullable_fields(refresh: str | None) -> None:
    """SDK fallback state does not overwrite provider token omission/null semantics."""
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "access_token": "new",
                    "refresh_token": refresh,
                    "expires_at": None,
                },
            )
        )
    )
    with patch("azents.core.oauth2.httpx.AsyncClient", return_value=http_client):
        result = await _grant("refresh", "secret")
    assert result.refresh_token == refresh
    assert result.expires_at is None


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connection failed"),
        httpx.ReadTimeout("timeout"),
        RuntimeError("unexpected"),
        asyncio.CancelledError(),
    ],
)
async def test_transport_failures_and_cancellation_propagate(
    error: BaseException,
) -> None:
    """The public transport adapter preserves exact exceptions without fallback."""

    def provider(request: httpx.Request) -> httpx.Response:
        raise error

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    with patch("azents.core.oauth2.httpx.AsyncClient", return_value=http_client):
        with pytest.raises(type(error)) as raised:
            await _grant("exchange", None)
    assert raised.value is error
    assert http_client.is_closed


def test_public_authorization_url_preserves_protocol_fields() -> None:
    """Authlib authorization URL retains explicit state, scope, PKCE and resource."""
    url = build_authorization_url(
        "https://provider.test/authorize",
        "client",
        "https://app.test/callback",
        ["read", "write"],
        "state",
        code_challenge="challenge",
        resource="https://mcp.test",
    )
    assert parse_qs(urlparse(url).query) == {
        "client_id": ["client"],
        "response_type": ["code"],
        "redirect_uri": ["https://app.test/callback"],
        "state": ["state"],
        "scope": ["read write"],
        "code_challenge": ["challenge"],
        "code_challenge_method": ["S256"],
        "resource": ["https://mcp.test"],
    }


async def test_compressed_provider_response_is_decoded_once() -> None:
    """Bridge decoded bytes without replaying provider content encodings."""
    content = gzip.compress(b'{"access_token":"compressed"}')
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={
                    "content-encoding": "gzip",
                    "content-length": str(len(content)),
                },
                content=content,
            )
        )
    )
    with patch("azents.core.oauth2.httpx.AsyncClient", return_value=http_client):
        result = await _grant("exchange", None)
    assert result.access_token == "compressed"


def test_optional_authorization_fields_remain_absent() -> None:
    """Absent scope, PKCE and resource are not replaced by SDK defaults."""
    url = build_authorization_url(
        "https://provider.test/authorize",
        "client",
        "https://app.test/callback",
        [],
        "state",
    )
    assert parse_qs(urlparse(url).query) == {
        "client_id": ["client"],
        "response_type": ["code"],
        "redirect_uri": ["https://app.test/callback"],
        "state": ["state"],
    }
