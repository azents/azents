"""Real Proxy ingress and SDK provider wires for selected hosted-tool settings."""

import json
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
import pytest
import respx
from azents_llm_contract.authority import ApiKeyCredential, TargetBinding
from pydantic import SecretStr

from azents_llm_proxy import bootstrap
from azents_llm_proxy.authority import AuthorityClient
from azents_llm_proxy.authority_test import AGENT, SERVICE
from azents_llm_proxy.history_test import PNG
from azents_llm_proxy.proxy_test import RESULT, setup_proxy
from azents_llm_proxy.tools_test import FUNCTION, selected

pytestmark = pytest.mark.usefixtures("protected_provider_clients")


@dataclass(frozen=True, repr=False)
class WireObservation:
    response: httpx.Response
    request: httpx.Request
    physical_calls: int


async def invoke(
    value: TargetBinding,
    *,
    model: str,
    endpoint: str,
    result: object,
    functions: bool,
    controls: dict[str, object] | None,
) -> WireObservation:
    value = value.model_copy(update={"public_model": model, "model_identifier": model})

    def authority(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=value.protected_json())

    body: dict[str, object] = {
        "model": model,
        "input": "synthetic-tool-prompt",
        "metadata": {"azents_target_id": value.target_id},
    }
    if functions:
        body["tools"] = [FUNCTION]
    if controls is not None:
        body.update(controls)
    location = urlsplit(endpoint)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        with respx.mock(assert_all_called=False) as router:
            upstream = router.route(
                method="POST", scheme="https", host=location.hostname
            ).mock(return_value=httpx.Response(200, json=result))
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://proxy"
            ) as client:
                response = await client.post(
                    "/v1/responses",
                    headers={"Authorization": f"Bearer {AGENT}"},
                    json=body,
                )
            assert response.status_code == 200, response.text
            assert upstream.call_count == 1
            sent = upstream.calls[0].request
            assert sent.url.path == location.path
            return WireObservation(
                response=response, request=sent, physical_calls=upstream.call_count
            )


@pytest.mark.parametrize("xai", [False, True])
async def test_native_hosted_search_restrictions_survive_provider_transform(
    xai: bool,
) -> None:
    if xai:
        value = selected(
            "responses",
            "web_search",
            {
                "blocked_domains": ["blocked.example"],
                "external_web_access": False,
                "user_location": {"city": "Seoul"},
            },
        )
        value = value.model_copy(
            update={
                "credential": ApiKeyCredential(
                    kind="api_key",
                    provider="xai",
                    api_key=SecretStr("provider-sentinel"),
                )
            }
        )
        model, endpoint = "grok-4", "https://api.x.ai/v1/responses"
    else:
        value = selected(
            "native_responses",
            "web_search",
            {
                "filters": {"blocked_domains": ["blocked.example"]},
                "external_web_access": False,
                "user_location": {"type": "approximate", "city": "Seoul"},
            },
        )
        model, endpoint = "gpt-4o-mini", "https://api.openai.com/v1/responses"
    observed = await invoke(
        value,
        model=model,
        endpoint=endpoint,
        result={**RESULT, "model": model},
        functions=True,
        controls=None,
    )
    tools = json.loads(observed.request.content)["tools"]
    assert tools[0] == FUNCTION
    assert tools[1]["type"] == "web_search"
    assert tools[1]["filters"]["blocked_domains"] == ["blocked.example"]
    assert tools[1]["external_web_access"] is False
    assert tools[1]["user_location"]["city"] == "Seoul"
    assert observed.response.json()["usage"]["total_tokens"] == 3


async def test_anthropic_selected_search_coexists_with_functions_and_restrictions() -> (
    None
):
    value = selected(
        "anthropic",
        "web_search",
        {
            "allowed_domains": ["example.com"],
            "max_uses": 2,
            "user_location": {"country": "KR"},
        },
    )
    model = "claude-sonnet-4-5"
    result = {
        "id": "msg_offline",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "reply"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 2, "output_tokens": 1},
    }
    observed = await invoke(
        value,
        model=model,
        endpoint="https://api.anthropic.com/v1/messages",
        result=result,
        functions=True,
        controls=None,
    )
    tools = json.loads(observed.request.content)["tools"]
    assert len(tools) == 2
    assert tools[0]["name"] == "image_generation"
    assert tools[1] == {
        "type": "web_search_20250305",
        "name": "web_search",
        "allowed_domains": ["example.com"],
        "max_uses": 2,
        "user_location": {"type": "approximate", "country": "KR"},
    }
    assert observed.response.json()["usage"]["total_tokens"] == 3


def google_result(*, image: bool) -> dict[str, object]:
    parts: list[dict[str, object]] = [{"text": "reply"}]
    if image:
        parts.append({"inlineData": {"mimeType": "image/png", "data": PNG}})
    return {
        "candidates": [
            {"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}
        ],
        "usageMetadata": {
            "promptTokenCount": 2,
            "candidatesTokenCount": 1,
            "totalTokenCount": 3,
        },
        "modelVersion": "gemini-fixture",
    }


async def test_google_search_keeps_function_coexistence_when_current_facts_allow() -> (
    None
):
    value = selected("google", "web_search", {})
    model = "gemini-3.1-pro-preview"
    observed = await invoke(
        value,
        model=model,
        endpoint=f"https://generativelanguage.googleapis.com/v1alpha/models/{model}:generateContent",
        result=google_result(image=False),
        functions=True,
        controls=None,
    )
    tools = json.loads(observed.request.content)["tools"]
    assert "googleSearch" in json.dumps(tools)
    assert "function_declarations" in json.dumps(tools)
    assert "image_generation" in json.dumps(tools)
    assert observed.response.json()["usage"]["total_tokens"] == 3


async def test_google_hosted_image_preserves_controls_output_bytes_and_usage() -> None:
    value = selected(
        "google", "image_generation", {"size": "2K", "aspect_ratio": "16:9"}
    )
    model = "gemini-3.1-flash-image-preview"
    observed = await invoke(
        value,
        model=model,
        endpoint=f"https://generativelanguage.googleapis.com/v1alpha/models/{model}:generateContent",
        result=google_result(image=True),
        functions=False,
        controls=None,
    )
    config = json.loads(observed.request.content)["generationConfig"]
    assert config["responseModalities"] == ["TEXT", "IMAGE"]
    assert config["imageConfig"] == {"imageSize": "2K", "aspectRatio": "16:9"}
    assert any(
        item["type"] == "image_generation_call" and item["result"] == PNG
        for item in observed.response.json()["output"]
    )
    assert observed.response.json()["usage"]["total_tokens"] == 3
