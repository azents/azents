"""OpenAI Images SDK-backed client-tool tests."""

import base64
import json
from collections.abc import Callable
from io import BytesIO

import httpx
import pytest
from openai import AsyncOpenAI
from PIL import Image

from azents.engine.events.openai_responses import OpenAIResponsesClientConfig
from azents.engine.run.types import FunctionToolError, FunctionToolResult
from azents.engine.tools.openai_image_generation import (
    OPENAI_IMAGE_DEFAULT_MODEL,
    OpenAIImageGenerationExecutor,
    openai_images_client_factory,
)


def _image() -> bytes:
    image = Image.new("RGB", (2, 2), "blue")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _factory(
    transport: httpx.MockTransport,
    *,
    base_url: str = "https://api.openai.com/v1",
    headers: dict[str, str] | None = None,
) -> Callable[[], AsyncOpenAI]:
    """Create an SDK client backed by an in-memory provider transport."""

    def create() -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key="private-credential",
            base_url=base_url,
            default_headers=headers,
            http_client=httpx.AsyncClient(transport=transport),
            max_retries=0,
        )

    return create


@pytest.mark.parametrize(
    ("base_url", "model"),
    [
        ("https://api.openai.com/v1", "gpt-image-2.5-flare"),
        ("https://chatgpt.com/backend-api/codex", OPENAI_IMAGE_DEFAULT_MODEL),
    ],
)
async def test_generate_one_image_via_selected_endpoint_without_durable_base64(
    base_url: str,
    model: str,
) -> None:
    """Both credential modes use the SDK with model choice and account headers."""
    body = _image()
    encoded = base64.b64encode(body).decode()

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url == f"{base_url}/images/generations"
        assert request.headers["authorization"] == "Bearer private-credential"
        assert request.headers["chatgpt-account-id"] == "account-1"
        payload = json.loads(request.content)
        assert payload == {"model": model, "prompt": "Draw a blue square", "n": 1}
        return httpx.Response(200, json={"created": 1, "data": [{"b64_json": encoded}]})

    tool = OpenAIImageGenerationExecutor(
        model_identifier=model,
        client_factory=_factory(
            httpx.MockTransport(respond),
            base_url=base_url,
            headers={"ChatGPT-Account-Id": "account-1"},
        ),
        refresh_credential=None,
    ).make_tool()

    result = await tool.handler('{"prompt":"Draw a blue square"}')

    assert isinstance(result, FunctionToolResult)
    assert result.output == []
    assert result.generated_files is not None
    assert len(result.generated_files) == 1
    assert result.generated_files[0].body == body
    assert encoded not in result.model_dump_json()


@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (401, "valid integration credential"),
        (403, "not permitted"),
        (429, "rate limit"),
        (500, "HTTP 500"),
    ],
)
async def test_provider_failures_are_sanitized(
    status_code: int,
    message: str,
) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"error": {"message": "private credential must not leak"}},
        )

    tool = OpenAIImageGenerationExecutor(
        model_identifier=OPENAI_IMAGE_DEFAULT_MODEL,
        client_factory=_factory(httpx.MockTransport(respond)),
        refresh_credential=None,
    ).make_tool()

    with pytest.raises(FunctionToolError, match=message) as caught:
        await tool.handler('{"prompt":"Draw a blue square"}')
    assert "private credential must not leak" not in str(caught.value)


@pytest.mark.parametrize("data", [[], [{"b64_json": None}], [{"b64_json": "invalid"}]])
async def test_missing_or_invalid_image_fails_closed(
    data: list[dict[str, str | None]],
) -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"created": 1, "data": data})

    tool = OpenAIImageGenerationExecutor(
        model_identifier=OPENAI_IMAGE_DEFAULT_MODEL,
        client_factory=_factory(httpx.MockTransport(respond)),
        refresh_credential=None,
    ).make_tool()

    with pytest.raises(FunctionToolError, match="image"):
        await tool.handler('{"prompt":"Draw a blue square"}')


async def test_tool_schema_hides_credentials_and_rejects_oversized_prompt() -> None:
    calls = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    tool = OpenAIImageGenerationExecutor(
        model_identifier=OPENAI_IMAGE_DEFAULT_MODEL,
        client_factory=_factory(httpx.MockTransport(respond)),
        refresh_credential=None,
    ).make_tool()

    assert tool.spec.input_schema["type"] == "object"
    properties = tool.spec.input_schema["properties"]
    assert isinstance(properties, dict)
    assert set(properties) == {"prompt"}
    assert "private-credential" not in json.dumps(tool.spec.input_schema)
    assert OPENAI_IMAGE_DEFAULT_MODEL not in json.dumps(tool.spec.input_schema)
    with pytest.raises(FunctionToolError, match="at most 32000 characters"):
        await tool.handler(json.dumps({"prompt": "x" * 32_001}))
    assert calls == 0


async def test_subscription_refreshes_once_after_image_unauthorized() -> None:
    encoded = base64.b64encode(_image()).decode()
    credential = "expired-token"
    requests: list[str] = []
    refresh_count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.headers["authorization"])
        if request.headers["authorization"] == "Bearer expired-token":
            return httpx.Response(401, json={"error": {"message": "expired"}})
        return httpx.Response(200, json={"created": 1, "data": [{"b64_json": encoded}]})

    def create() -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=credential,
            base_url="https://chatgpt.com/backend-api/codex",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
            max_retries=0,
        )

    async def refresh() -> None:
        nonlocal credential, refresh_count
        credential = "refreshed-token"
        refresh_count += 1

    tool = OpenAIImageGenerationExecutor(
        model_identifier=OPENAI_IMAGE_DEFAULT_MODEL,
        client_factory=create,
        refresh_credential=refresh,
    ).make_tool()
    result = await tool.handler('{"prompt":"Draw an image"}')

    assert isinstance(result, FunctionToolResult)
    assert refresh_count == 1
    assert requests == ["Bearer expired-token", "Bearer refreshed-token"]


async def test_subscription_stops_after_second_unauthorized() -> None:
    refresh_count = 0
    requests = 0

    def respond(_request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(401, json={"error": {"message": "expired"}})

    async def refresh() -> None:
        nonlocal refresh_count
        refresh_count += 1

    tool = OpenAIImageGenerationExecutor(
        model_identifier=OPENAI_IMAGE_DEFAULT_MODEL,
        client_factory=_factory(httpx.MockTransport(respond)),
        refresh_credential=refresh,
    ).make_tool()
    with pytest.raises(FunctionToolError, match="reconnect"):
        await tool.handler('{"prompt":"Draw an image"}')

    assert requests == 2
    assert refresh_count == 1


def test_factory_preserves_subscription_endpoint_and_account_headers() -> None:
    factory = openai_images_client_factory(
        OpenAIResponsesClientConfig(
            api_key="private-credential",
            base_url="https://chatgpt.com/backend-api/codex",
            organization=None,
            project=None,
            default_headers={"ChatGPT-Account-Id": "account-1"},
        )
    )
    client = factory()
    assert str(client.base_url) == "https://chatgpt.com/backend-api/codex/"
