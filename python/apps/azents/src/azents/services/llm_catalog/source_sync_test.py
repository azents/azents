"""LiteLLM source sync tests."""

import httpx
import pytest

from azents.services.llm_catalog import fetch_remote_litellm_model_cost_payload


@pytest.mark.asyncio
async def test_fetch_remote_litellm_model_cost_payload_reads_json_object() -> None:
    """Remote LiteLLM catalog fetch normalizes JSON object keys to strings."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "gpt-5.6": {
                    "litellm_provider": "openai",
                    "mode": "chat",
                }
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        payload = await fetch_remote_litellm_model_cost_payload(client)

    assert payload == {
        "gpt-5.6": {
            "litellm_provider": "openai",
            "mode": "chat",
        }
    }


@pytest.mark.asyncio
async def test_fetch_remote_litellm_model_cost_payload_rejects_non_object() -> None:
    """Remote LiteLLM catalog must remain an object keyed by model id."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["gpt-5.6"], request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="not a JSON object"):
            await fetch_remote_litellm_model_cost_payload(client)
