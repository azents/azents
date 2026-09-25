"""Contract coverage for the testenv-only Brave Search transport."""

from typing import Literal

import httpx
import pytest

from azents.engine.run.types import FunctionToolError
from azents.engine.tools.brave_search_api import BraveSearchApi
from azents.engine.tools.brave_search_testenv import make_brave_testenv_transport


@pytest.mark.parametrize("kind", ["web", "context", "news", "videos"])
async def test_fixture_supports_fixed_search_operations(
    kind: Literal["web", "context", "news", "videos"],
) -> None:
    """Resolve each tool path without paid network access."""
    client = BraveSearchApi(
        api_key="brave-e2e-valid",
        timeout=2,
        transport=make_brave_testenv_transport(),
    )
    results = await client.search(kind, {"q": "test", "count": 1})
    assert len(results) == 1
    assert results[0].url == f"https://example.org/brave/{kind}"


async def test_fixture_serves_two_bounded_proxy_images() -> None:
    """Both attached previews preserve image/page URLs and valid PNG bytes."""
    client = BraveSearchApi(
        api_key="brave-e2e-valid",
        timeout=2,
        transport=make_brave_testenv_transport(),
    )
    results = await client.search_images({"q": "test", "count": 2}, attachment_count=2)
    assert len(results) == 2
    assert [result.rank for result in results] == [0, 1]
    assert all(result.attachment is not None for result in results)
    assert [result.page_url for result in results] == [
        "https://example.org/brave/image-page-1",
        "https://example.org/brave/image-page-2",
    ]
    assert [result.image_url for result in results] == [
        "https://example.org/brave/original-1.png",
        "https://example.org/brave/original-2.png",
    ]


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("brave-e2e-revoked", "key is invalid"),
        ("brave-e2e-limited", "rate or quota limit"),
    ],
)
async def test_fixture_rejects_revoked_or_limited_key(key: str, expected: str) -> None:
    """Deterministic auth and quota failures remain secret-free."""
    client = BraveSearchApi(
        api_key=key,
        timeout=2,
        transport=make_brave_testenv_transport(),
    )
    with pytest.raises(FunctionToolError, match=expected):
        await client.search("web", {"q": "test"})


async def test_fixture_rejects_unknown_hosts_and_never_forwards_keys() -> None:
    """The thumbnail fixture refuses an unexpected host and an API token."""
    async with httpx.AsyncClient(transport=make_brave_testenv_transport()) as client:
        response = await client.get("https://example.org/brave-e2e-one.png")
        assert response.status_code == 404
        response = await client.get(
            "https://imgs.search.brave.com/brave-e2e-one.png",
            headers={"X-Subscription-Token": "brave-e2e-valid"},
        )
        assert response.status_code == 500
