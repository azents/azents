"""Supported GitHub SDK boundaries with deterministic intercepted provider traffic."""

import asyncio
import base64
import json
import logging
from collections.abc import Callable

import httpx
import pytest
from githubkit import BaseAuthStrategy, GitHub, UnauthAuthStrategy
from pydantic import ValidationError

from azents.core.github_auth import (
    GitHubClientFactory,
    create_github_client,
    exchange_installation_token,
    exchange_oauth_code,
    get_app_slug,
    get_installation,
    list_installations,
    list_user_installations,
    revoke_oauth_token,
)
from azents.core.github_installation import decode_github_installations


def _factory(handler: Callable[[httpx.Request], httpx.Response]) -> GitHubClientFactory:
    def create(auth: BaseAuthStrategy | None) -> GitHub[BaseAuthStrategy]:
        return GitHub[BaseAuthStrategy](
            auth=auth if auth is not None else UnauthAuthStrategy(),
            async_transport=httpx.MockTransport(handler),
            auto_retry=False,
            http_cache=False,
            follow_redirects=False,
            timeout=5.0,
        )

    return create


def _installation(
    installation_id: object = 7, avatar: object = None
) -> dict[str, object]:
    return {
        "id": installation_id,
        "app_id": 11,
        "account": {"login": "owner", "type": "User", "avatar_url": avatar},
        "extension": {"opaque": True},
    }


def test_native_sdk_factory_retains_default_accept_and_disabled_retry_cache() -> None:
    client = create_github_client(None)
    assert client.config.accept == "application/vnd.github+json"
    assert client.config.auto_retry is None and client.config.http_cache is False
    assert client.config.timeout.read == 5.0
    assert client.config.follow_redirects is False


@pytest.mark.asyncio
async def test_public_app_operations_preserve_endpoints_and_bearer_contract() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer current-jwt"
        assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
        assert request.url.host == "api.github.com"
        if request.url.path == "/app":
            return httpx.Response(200, json={"slug": "example-app", "extension": True})
        if request.url.path == "/app/installations":
            assert request.url.params["per_page"] == "100"
            return httpx.Response(200, json=[_installation(), _installation()])
        if request.url.path == "/app/installations/7":
            return httpx.Response(200, json=_installation())
        assert request.url.path == "/app/installations/7/access_tokens"
        assert request.method == "POST"
        return httpx.Response(
            201, json={"token": "issued-token", "expires_at": "opaque-expiration"}
        )

    factory = _factory(handle)
    assert await get_app_slug("current-jwt", client_factory=factory) == "example-app"
    records = await list_installations("current-jwt", client_factory=factory)
    assert len(records) == 2 and records[0] == records[1]
    record = await get_installation("current-jwt", "7", client_factory=factory)
    assert record.installation_id == 7 and record.app_id == 11
    assert (
        await exchange_installation_token("current-jwt", "7", client_factory=factory)
        == "issued-token"
    )
    assert len(requests) == 4


@pytest.mark.asyncio
async def test_user_installations_preserve_skips_and_avatar_presence() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/user/installations"
        assert request.headers["Authorization"] == "Bearer oauth-user-token"
        return httpx.Response(
            200,
            json={
                "installations": [
                    _installation(True, ""),
                    _installation(7),
                    _installation(7, 3),
                    {"id": 8, "account": None},
                    {"id": "9", "account": {"login": "x", "type": "User"}},
                ]
            },
        )

    records = await list_user_installations(
        "oauth-user-token", client_factory=_factory(handle)
    )
    assert [record.installation_id for record in records] == [True, 7, 7]
    assert records[0].installation_id is True
    assert [record.account_avatar_url for record in records] == ["", None, None]
    assert decode_github_installations([_installation(), "invalid outer record"]) == ()


@pytest.mark.asyncio
async def test_oauth_exchange_and_revoke_use_public_sdk_auth_operations() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "github.com":
            assert request.url.path == "/login/oauth/access_token"
            assert json.loads(request.content) == {
                "client_id": "client",
                "client_secret": "secret",
                "code": "code",
            }
            return httpx.Response(200, json={"access_token": "oauth-token"})
        assert request.method == "DELETE"
        assert request.url.path == "/applications/client/token"
        assert (
            request.headers["Authorization"]
            == "Basic " + base64.b64encode(b"client:secret").decode()
        )
        assert json.loads(request.content) == {"access_token": "oauth-token"}
        assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"
        return httpx.Response(204)

    factory = _factory(handle)
    assert (
        await exchange_oauth_code("client", "secret", "code", client_factory=factory)
        == "oauth-token"
    )
    await revoke_oauth_token("client", "secret", "oauth-token", client_factory=factory)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_expected_oauth_and_http_errors_preserve_caller_contracts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"error": "bad_code", "error_description": "Rejected"}
        )

    with pytest.raises(
        ValueError, match="OAuth token exchange failed: bad_code - Rejected"
    ):
        await exchange_oauth_code(
            "client", "secret", "code", client_factory=_factory(rejected)
        )

    def failure(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "unavailable"})

    with pytest.raises(httpx.HTTPStatusError):
        await get_app_slug("token", client_factory=_factory(failure))
    with caplog.at_level(logging.WARNING):
        await revoke_oauth_token(
            "client",
            "sentinel-secret-never-log",
            "sentinel-token-never-log",
            client_factory=_factory(failure),
        )
    assert "Failed to revoke GitHub OAuth token" in caplog.text
    assert "sentinel-secret-never-log" not in caplog.text
    assert "sentinel-token-never-log" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [RuntimeError("programming defect"), asyncio.CancelledError()]
)
async def test_revocation_never_handles_unexpected_failures_or_cancellation(
    failure: BaseException,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        raise failure

    with pytest.raises(type(failure)):
        await revoke_oauth_token(
            "client", "secret", "token", client_factory=_factory(handle)
        )


@pytest.mark.asyncio
async def test_malformed_outer_payloads_fail_without_exposing_token_inputs() -> None:
    def wrong_outer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["invalid-envelope"])

    with pytest.raises(ValidationError):
        await list_user_installations("token", client_factory=_factory(wrong_outer))

    def wrong_token(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201, json={"token": 3, "refresh_token": "sentinel-private-token"}
        )

    with pytest.raises(ValidationError) as caught:
        await exchange_installation_token(
            "jwt", "7", client_factory=_factory(wrong_token)
        )
    assert "sentinel-private-token" not in str(caught.value)
