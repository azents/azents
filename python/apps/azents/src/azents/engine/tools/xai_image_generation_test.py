"""xAI image-generation client tool tests."""

import base64
import contextlib
import json
from collections.abc import AsyncIterator
from io import BytesIO

import httpx
import pytest
from PIL import Image

from azents.core.enums import LLMProvider
from azents.engine.run.types import FunctionToolError, FunctionToolResult
from azents.engine.tools.xai_image_generation import (
    XaiImageGenerationExecutor,
    XaiImagineClientFactory,
)
from azents.services.xai_imagine import XaiImagineClient


def _png_base64() -> str:
    body = BytesIO()
    Image.new("RGB", (1, 1), color=(255, 0, 0)).save(body, format="PNG")
    return base64.b64encode(body.getvalue()).decode()


def _factory(
    transport: httpx.AsyncBaseTransport,
) -> XaiImagineClientFactory:
    @contextlib.asynccontextmanager
    async def create() -> AsyncIterator[XaiImagineClient]:
        async with httpx.AsyncClient(transport=transport) as http_client:
            yield XaiImagineClient(
                http_client,
                base_url="https://api.x.ai/v1",
            )

    return create


async def test_api_key_tool_returns_transient_validated_image() -> None:
    """Generate with the selected API key and keep bytes out of serialization."""
    encoded = _png_base64()

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer api-key-secret"
        return httpx.Response(200, json={"data": [{"b64_json": encoded}]})

    tool = XaiImageGenerationExecutor(
        provider=LLMProvider.XAI,
        access_token="api-key-secret",
        client_factory=_factory(httpx.MockTransport(respond)),
        refresh_access_token=None,
    ).make_tool()

    result = await tool.handler(
        json.dumps(
            {
                "prompt": "A small red pixel",
                "aspect_ratio": "1:1",
                "resolution": "1k",
            }
        )
    )

    assert isinstance(result, FunctionToolResult)
    assert result.output == []
    assert result.metadata == {
        "provider": "xai",
        "operation": "image_generation",
    }
    assert len(result.generated_files) == 1
    assert result.generated_files[0].body.startswith(b"\x89PNG")
    serialized = result.model_dump_json()
    assert encoded not in serialized
    assert "api-key-secret" not in serialized


async def test_tool_rejects_prompt_above_imagine_limit() -> None:
    """Reject oversized prompts before sending an Imagine request."""
    calls = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    tool = XaiImageGenerationExecutor(
        provider=LLMProvider.XAI,
        access_token="api-key-secret",
        client_factory=_factory(httpx.MockTransport(respond)),
        refresh_access_token=None,
    ).make_tool()

    with pytest.raises(FunctionToolError, match="at most 1024 characters"):
        await tool.handler(json.dumps({"prompt": "x" * 1_025}))

    assert calls == 0


async def test_oauth_tool_refreshes_once_after_unauthorized() -> None:
    """Force one OAuth refresh and retry the same Imagine request once."""
    encoded = _png_base64()
    tokens: list[str] = []
    refresh_calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        token = request.headers["authorization"].removeprefix("Bearer ")
        tokens.append(token)
        if token == "old-access-token":
            return httpx.Response(401)
        return httpx.Response(200, json={"data": [{"b64_json": encoded}]})

    async def refresh() -> str:
        nonlocal refresh_calls
        refresh_calls += 1
        return "new-access-token"

    tool = XaiImageGenerationExecutor(
        provider=LLMProvider.XAI_OAUTH,
        access_token="old-access-token",
        client_factory=_factory(httpx.MockTransport(respond)),
        refresh_access_token=refresh,
    ).make_tool()

    result = await tool.handler('{"prompt":"A refreshed image"}')

    assert isinstance(result, FunctionToolResult)
    assert len(result.generated_files) == 1
    assert refresh_calls == 1
    assert tokens == ["old-access-token", "new-access-token"]


async def test_oauth_tool_requires_reconnect_after_second_unauthorized() -> None:
    """Stop after the single forced OAuth refresh retry."""
    tokens: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        tokens.append(request.headers["authorization"])
        return httpx.Response(401)

    async def refresh() -> str:
        return "new-access-token"

    tool = XaiImageGenerationExecutor(
        provider=LLMProvider.XAI_OAUTH,
        access_token="old-access-token",
        client_factory=_factory(httpx.MockTransport(respond)),
        refresh_access_token=refresh,
    ).make_tool()

    with pytest.raises(FunctionToolError, match="reconnect is required"):
        await tool.handler('{"prompt":"A rejected image"}')

    assert tokens == ["Bearer old-access-token", "Bearer new-access-token"]


@pytest.mark.parametrize(
    ("retry_status", "error_message"),
    [
        (403, "access is not permitted"),
        (429, "rate limit was exceeded"),
    ],
)
async def test_oauth_tool_classifies_error_after_refresh(
    retry_status: int,
    error_message: str,
) -> None:
    """Preserve safe Imagine error classification after the OAuth retry."""
    tokens: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        tokens.append(request.headers["authorization"])
        status = 401 if len(tokens) == 1 else retry_status
        return httpx.Response(status)

    async def refresh() -> str:
        return "new-access-token"

    tool = XaiImageGenerationExecutor(
        provider=LLMProvider.XAI_OAUTH,
        access_token="old-access-token",
        client_factory=_factory(httpx.MockTransport(respond)),
        refresh_access_token=refresh,
    ).make_tool()

    with pytest.raises(FunctionToolError, match=error_message):
        await tool.handler('{"prompt":"A rejected image"}')

    assert tokens == ["Bearer old-access-token", "Bearer new-access-token"]


async def test_api_key_tool_does_not_refresh_unauthorized() -> None:
    """Classify an API-key 401 without invoking OAuth behavior."""

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    tool = XaiImageGenerationExecutor(
        provider=LLMProvider.XAI,
        access_token="invalid-api-key",
        client_factory=_factory(httpx.MockTransport(respond)),
        refresh_access_token=None,
    ).make_tool()

    with pytest.raises(FunctionToolError, match="integration credential"):
        await tool.handler('{"prompt":"A rejected image"}')
