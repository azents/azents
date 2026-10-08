"""SDK fixture routing stays explicit, local and preserves public request paths."""

from unittest.mock import AsyncMock

import httpx
import pytest

from azents.core.config import Config
from azents.core.github_auth import create_github_client
from azents.core.github_user_testenv import GitHubUserTestenvTransport
from azents.services.github_user_oauth.provider import get_github_user_provider


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/login/oauth/access_token", "/login/oauth/access_token"),
        ("https://api.github.com/app", "/app"),
        (
            "https://api.github.com/user/installations?page=2",
            "/user/installations?page=2",
        ),
    ],
)
async def test_sdk_fixture_rewrite_preserves_path_without_spurious_query(
    monkeypatch: pytest.MonkeyPatch, url: str, expected: str
) -> None:
    transport = GitHubUserTestenvTransport("http://127.0.0.1:8082")
    boundary = AsyncMock(return_value=httpx.Response(200, json={"fixture": True}))
    monkeypatch.setattr(transport.transport, "handle_async_request", boundary)
    request = httpx.Request("POST", url, json={"synthetic": True})
    try:
        await transport.handle_async_request(request)
        assert str(request.url) == "http://127.0.0.1:8082" + expected
        assert request.headers["Host"] == "127.0.0.1:8082"
        boundary.assert_awaited_once_with(request)
    finally:
        await transport.aclose()


async def test_sdk_fixture_rejects_unexpected_hosts_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = GitHubUserTestenvTransport("http://127.0.0.1:8082")
    boundary = AsyncMock()
    monkeypatch.setattr(transport.transport, "handle_async_request", boundary)
    try:
        with pytest.raises(ValueError, match="Unexpected host"):
            await transport.handle_async_request(
                httpx.Request("GET", "https://other.test/private")
            )
        boundary.assert_not_awaited()
    finally:
        await transport.aclose()


@pytest.mark.parametrize("enabled", [False, True])
def test_fixture_url_is_used_only_in_explicit_testenv_composition(
    enabled: bool,
) -> None:
    config = Config.model_construct(
        testenv_api_enabled=enabled,
        testenv_github_platform_validation_base_url="http://127.0.0.1:8082",
    )
    provider = get_github_user_provider(config)
    assert (provider.client_factory is create_github_client) is not enabled
