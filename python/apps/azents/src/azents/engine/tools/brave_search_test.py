"""Direct Brave Toolkit contract and fixed-host image admission tests."""

import json
from dataclasses import replace
from io import BytesIO

import httpx
import pytest
from PIL import Image

from azents.core.tools import BraveSearchToolkitConfig, ResolveContext, TurnContext
from azents.engine.run.types import FunctionToolError, FunctionToolResult
from azents.engine.tools.brave_search import (
    BraveSearchToolkit,
    BraveSearchToolkitProvider,
)
from azents.engine.tools.brave_search_api import BraveSearchApi


def _png() -> bytes:
    """Produce a valid deterministic small image fixture."""
    result = BytesIO()
    Image.new("RGB", (2, 2), color="red").save(result, format="PNG")
    return result.getvalue()


async def _publish(_event: object) -> None:
    """Keep the tool context free of event side effects."""


def _mock_client(handler: httpx.MockTransport) -> BraveSearchApi:
    """Construct a direct client with an isolated deterministic transport."""
    return BraveSearchApi(api_key="synthetic-key", timeout=2, transport=handler)


@pytest.mark.parametrize(
    ("kind", "path", "body"),
    [
        (
            "web",
            "/res/v1/web/search",
            {
                "web": {
                    "results": [
                        {
                            "title": "Web",
                            "url": "https://example.org/web",
                            "description": "Page",
                            "age": None,
                            "page_age": "2026-09-24",
                        }
                    ]
                }
            },
        ),
        (
            "context",
            "/res/v1/llm/context",
            {
                "grounding": {
                    "generic": [
                        {
                            "title": "Context",
                            "url": "https://example.org/context",
                            "snippets": ["Extracted text"],
                        }
                    ]
                }
            },
        ),
        (
            "news",
            "/res/v1/news/search",
            {
                "results": [
                    {
                        "title": "News",
                        "url": "https://example.org/news",
                        "description": "Story",
                        "page_age": "2026-09-24",
                        "profile": {"name": "Publisher"},
                    }
                ]
            },
        ),
        (
            "videos",
            "/res/v1/videos/search",
            {
                "results": [
                    {
                        "title": "Video",
                        "url": "https://example.org/video",
                        "description": "Clip",
                        "meta_url": {"hostname": "example.org"},
                    }
                ]
            },
        ),
    ],
)
async def test_search_maps_each_fixed_endpoint(
    kind: str,
    path: str,
    body: dict[str, object],
) -> None:
    """Preserve source links and use only the selected fixed API path."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=body)

    client = _mock_client(httpx.MockTransport(handler))
    if kind == "web":
        rows = await client.search("web", {"q": "sample"})
    elif kind == "context":
        rows = await client.search("context", {"q": "sample"})
    elif kind == "news":
        rows = await client.search("news", {"q": "sample"})
    else:
        rows = await client.search("videos", {"q": "sample"})
    assert len(rows) == 1
    assert rows[0].url.startswith("https://example.org/")
    if kind in {"web", "news"}:
        assert rows[0].age == "2026-09-24"
    if kind == "news":
        assert rows[0].source == "Publisher"
    if kind == "videos":
        assert rows[0].source == "example.org"
    assert requests[0].url.host == "api.search.brave.com"
    assert requests[0].url.path == path
    assert requests[0].headers["x-subscription-token"] == "synthetic-key"


async def test_web_all_country_is_omitted_and_null_results_are_empty() -> None:
    """Web does not accept ALL and a nullable Web section is not a provider error."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"type": "search", "web": None})

    toolkit = BraveSearchToolkit(
        config=BraveSearchToolkitConfig(country="ALL"),
        client=_mock_client(httpx.MockTransport(handler)),
    )
    state = await toolkit.update_context(
        TurnContext(
            workspace_id="workspace-1",
            model="test",
            run_id="run-1",
            publish_event=_publish,
        )
    )
    result = await state.tools[0].handler('{"q":"sample"}')
    assert isinstance(result, str)
    assert "no attributable results" in result
    assert "country" not in requests[0].url.params


async def test_long_web_results_preserve_whole_source_urls() -> None:
    """A text budget drops complete later entries instead of cutting a URL."""
    sources = [f"https://example.org/{'x' * 1700}-{rank}" for rank in range(20)]

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {"title": f"Web {rank}", "url": url, "description": "Summary"}
                        for rank, url in enumerate(sources)
                    ]
                }
            },
        )

    toolkit = BraveSearchToolkit(
        config=BraveSearchToolkitConfig(),
        client=_mock_client(httpx.MockTransport(handler)),
    )
    state = await toolkit.update_context(
        TurnContext(
            workspace_id="workspace-1",
            model="test",
            run_id="run-1",
            publish_event=_publish,
        )
    )
    result = await state.tools[0].handler('{"q":"sample","count":20}')
    assert isinstance(result, str)
    rendered_sources = [
        line.removeprefix("   Source: ")
        for line in result.splitlines()
        if line.startswith("   Source: ")
    ]
    assert rendered_sources == sources[: len(rendered_sources)]
    assert "further results omitted" in result
    assert len(result) < 18_000


async def test_image_search_attaches_two_ranked_thumbnails_without_leaking_key() -> (
    None
):
    """Separate source/image/thumbnail URLs and use one search tool call."""
    image = _png()
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        if request.url.host == "api.search.brave.com":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": f"Image {rank}",
                            "url": f"https://example.org/page-{rank}",
                            "properties": {
                                "url": f"https://example.org/full-{rank}.png"
                            },
                            "thumbnail": {
                                "src": f"https://imgs.search.brave.com/thumb-{rank}"
                            },
                        }
                        for rank in (1, 2)
                    ]
                },
            )
        assert request.url.host == "imgs.search.brave.com"
        assert "x-subscription-token" not in request.headers
        return httpx.Response(200, content=image, headers={"content-type": "image/png"})

    client = _mock_client(httpx.MockTransport(handler))
    toolkit = BraveSearchToolkit(config=BraveSearchToolkitConfig(), client=client)
    state = await toolkit.update_context(
        TurnContext(
            workspace_id="workspace-1",
            model="test",
            run_id="run-1",
            publish_event=_publish,
        )
    )
    assert [tool.spec.name for tool in state.tools] == [
        "search_web",
        "search_context",
        "search_news",
        "search_images",
        "search_videos",
    ]
    result = await state.tools[3].handler(json.dumps({"q": "mountains"}))
    assert isinstance(result, FunctionToolResult)
    assert len(result.generated_files) == 2
    assert [image.output_index for image in result.generated_files] == [0, 1]
    assert isinstance(result.output, str)
    assert "https://example.org/full-1.png" in result.output
    assert "https://example.org/page-1" in result.output
    assert "synthetic-key" not in result.output
    assert [request.url.host for request in requested] == [
        "api.search.brave.com",
        "imgs.search.brave.com",
        "imgs.search.brave.com",
    ]


async def test_long_image_links_are_complete_for_every_attached_result() -> None:
    """Output budgets omit complete later entries, never truncate attached URLs."""
    image = _png()
    long_image = "https://example.org/" + "x" * 1850
    long_page = "https://example.org/page-" + "y" * 1850

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.search.brave.com":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": f"Image {rank}",
                            "url": f"{long_page}-{rank}",
                            "properties": {"url": f"{long_image}-{rank}"},
                            "thumbnail": {
                                "src": f"https://imgs.search.brave.com/{rank}"
                            },
                        }
                        for rank in range(20)
                    ]
                },
            )
        return httpx.Response(200, content=image, headers={"content-type": "image/png"})

    toolkit = BraveSearchToolkit(
        config=BraveSearchToolkitConfig(),
        client=_mock_client(httpx.MockTransport(handler)),
    )
    state = await toolkit.update_context(
        TurnContext(
            workspace_id="workspace-1",
            model="test",
            run_id="run-1",
            publish_event=_publish,
        )
    )
    result = await state.tools[3].handler('{"q":"mountains","count":20}')
    assert isinstance(result, FunctionToolResult)
    assert isinstance(result.output, str)
    assert len(result.generated_files) == 4
    for rank in range(4):
        assert f"{long_image}-{rank}" in result.output
        assert f"{long_page}-{rank}" in result.output
    assert "further results omitted" in result.output
    assert len(result.output) < 26_000


async def test_untrusted_thumbnail_url_is_text_only_and_never_fetched() -> None:
    """Do not follow an attacker-controlled result URL or a redirect."""
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Unsafe",
                        "url": "https://example.org/page",
                        "properties": {"url": "https://example.org/full.png"},
                        "thumbnail": {"src": "http://127.0.0.1/internal"},
                    }
                ]
            },
        )

    results = await _mock_client(httpx.MockTransport(handler)).search_images(
        {"q": "sample"}, attachment_count=2
    )
    assert len(results) == 1
    assert results[0].attachment is None
    assert results[0].unavailable_reason is not None
    assert len(requested) == 1


@pytest.mark.parametrize(
    ("country", "expected_country"),
    [("ALL", None), ("US", "US")],
)
async def test_connection_test_uses_supported_web_country(
    country: str, expected_country: str | None
) -> None:
    """Omit the ALL sentinel while preserving explicit Web country filters."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"web": {"results": []}})

    provider = BraveSearchToolkitProvider(transport=httpx.MockTransport(handler))
    result = await provider.test_connection(
        BraveSearchToolkitConfig(country=country), '{"api_key":"synthetic-key"}'
    )

    assert result.success
    assert len(requests) == 1
    assert requests[0].url.path == "/res/v1/web/search"
    assert requests[0].url.params.get("country") == expected_country


async def test_provider_errors_and_connection_test_do_not_echo_key() -> None:
    """Return actionable key/rate failures without raw upstream material."""
    provider = BraveSearchToolkitProvider(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(403, text="synthetic-key")
        )
    )
    assert await provider.validate_credentials({"api_key": "synthetic-key"}) is None
    result = await provider.test_connection(
        BraveSearchToolkitConfig(), '{"api_key":"synthetic-key"}'
    )
    assert not result.success
    assert "synthetic-key" not in result.message
    assert "subscription" in result.message
    with pytest.raises(FunctionToolError, match="key is invalid"):
        await _mock_client(httpx.MockTransport(lambda _: httpx.Response(401))).search(
            "web", {"q": "sample"}
        )


async def test_provider_resolves_only_configured_key_and_exposes_no_key_arguments() -> (
    None
):
    """Build five functions from a key that remains outside tool schemas."""
    provider = BraveSearchToolkitProvider(transport=None)
    context = ResolveContext(
        toolkit_id="toolkit-1",
        toolkit_name="Brave Search",
        credentials_json='{"api_key":"synthetic-key"}',
        agent_id="agent-1",
        session_id="session-1",
        session=None,
        web_url="https://example.org",
        oauth_secret_key="unused",
        workspace_id="workspace-1",
        workspace_handle="workspace",
    )
    toolkit = await provider.resolve(BraveSearchToolkitConfig(), context)
    state = await toolkit.update_context(
        TurnContext(
            workspace_id="workspace-1",
            model="test",
            run_id="run-1",
            publish_event=_publish,
        )
    )
    assert len(state.tools) == 5
    for tool in state.tools:
        schema = json.dumps(tool.spec.input_schema)
        assert "api_key" not in schema
        assert "synthetic-key" not in schema

    with pytest.raises(ValueError, match="required"):
        await provider.resolve(
            BraveSearchToolkitConfig(),
            replace(context, credentials_json=None),
        )


@pytest.mark.parametrize(
    ("thumbnail_status", "media_type", "body"),
    [
        (302, "image/png", b""),
        (200, "text/html", b"<html>not an image</html>"),
        (200, "image/png", b"not a png"),
    ],
)
async def test_thumbnail_failure_never_publishes_a_broken_attachment(
    thumbnail_status: int,
    media_type: str,
    body: bytes,
) -> None:
    """Reject redirects, non-images, and images that fail decoded verification."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.search.brave.com":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Example",
                            "url": "https://example.org/page",
                            "properties": {"url": "https://example.org/full.png"},
                            "thumbnail": {"src": "https://imgs.search.brave.com/thumb"},
                        }
                    ]
                },
            )
        return httpx.Response(
            thumbnail_status,
            headers={"content-type": media_type, "location": "http://127.0.0.1/"},
            content=body,
        )

    results = await _mock_client(httpx.MockTransport(handler)).search_images(
        {"q": "sample"}, attachment_count=2
    )
    assert len(results) == 1
    assert results[0].attachment is None
    assert results[0].unavailable_reason is not None


async def test_rate_limit_and_oversized_json_fail_closed() -> None:
    """Bound provider errors and response size before JSON parsing."""
    quota = _mock_client(
        httpx.MockTransport(lambda _: httpx.Response(429, text="secret"))
    )
    with pytest.raises(FunctionToolError, match="quota limit"):
        await quota.search("web", {"q": "sample"})

    oversized = _mock_client(
        httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))
        )
    )
    with pytest.raises(FunctionToolError, match="size limit"):
        await oversized.search("web", {"q": "sample"})


async def test_image_input_rejects_provider_unsupported_parameters() -> None:
    """Use separate image schema: no offset and no excessive result count."""
    client = _mock_client(
        httpx.MockTransport(lambda _: httpx.Response(200, json={"results": []}))
    )
    toolkit = BraveSearchToolkit(config=BraveSearchToolkitConfig(), client=client)
    state = await toolkit.update_context(
        TurnContext(
            workspace_id="workspace-1",
            model="test",
            run_id="run-1",
            publish_event=_publish,
        )
    )
    with pytest.raises(FunctionToolError, match="less than or equal to 20"):
        await state.tools[3].handler('{"q":"sample","count":201}')
    properties = state.tools[3].spec.input_schema["properties"]
    assert isinstance(properties, dict)
    assert "offset" not in properties
