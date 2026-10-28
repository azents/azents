"""Observed cache/reasoning subsets survive the real provider-to-Responses path."""

import pytest
from azents_llm_contract.authority import ApiKeyCredential
from pydantic import SecretStr

from azents_llm_proxy.authority_test import binding
from azents_llm_proxy.proxy_test import RESULT
from azents_llm_proxy.tool_wire_test import google_result, invoke

pytestmark = pytest.mark.usefixtures("protected_provider_clients")


async def test_native_usage_subsets_and_observed_tier_are_not_double_counted() -> None:
    model = "gpt-4o-mini"
    usage = {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
        "input_tokens_details": {"cached_tokens": 40},
        "output_tokens_details": {"reasoning_tokens": 10},
    }
    observed = await invoke(
        binding(),
        model=model,
        endpoint="https://api.openai.com/v1/responses",
        result={**RESULT, "model": model, "usage": usage, "service_tier": "priority"},
        functions=False,
        controls=None,
    )
    result = observed.response.json()
    observed_usage = result["usage"]
    assert observed_usage["input_tokens"] == 100
    assert observed_usage["output_tokens"] == 20
    assert observed_usage["total_tokens"] == 120
    assert observed_usage["input_tokens_details"]["cached_tokens"] == 40
    assert observed_usage["output_tokens_details"]["reasoning_tokens"] == 10
    assert observed_usage["cost"] is None
    assert result["service_tier"] == "priority"


async def test_anthropic_uncached_and_cache_read_write_usage_are_preserved() -> None:
    original = binding()
    value = original.model_copy(
        update={
            "credential": ApiKeyCredential(
                kind="api_key",
                provider="anthropic",
                api_key=SecretStr("usage-fixture-key"),
            ),
            "configuration": original.configuration.model_copy(
                update={"protocol": "anthropic"}
            ),
        }
    )
    model = "claude-sonnet-4-5"
    result = {
        "id": "msg_usage",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "reply"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "cache_read_input_tokens": 40,
            "cache_creation_input_tokens": 10,
        },
    }
    observed = await invoke(
        value,
        model=model,
        endpoint="https://api.anthropic.com/v1/messages",
        result=result,
        functions=False,
        controls=None,
    )
    usage = observed.response.json()["usage"]
    assert usage["input_tokens"] == 150, usage
    assert usage["output_tokens"] == 20 and usage["total_tokens"] == 170
    assert usage["input_tokens_details"]["cached_tokens"] == 40
    assert usage["input_tokens_details"]["cache_write_tokens"] == 10


async def test_google_reasoning_and_cached_input_subsets_are_not_lost() -> None:
    original = binding()
    value = original.model_copy(
        update={
            "credential": ApiKeyCredential(
                kind="api_key",
                provider="google_gemini",
                api_key=SecretStr("usage-fixture-key"),
            ),
            "configuration": original.configuration.model_copy(
                update={"protocol": "google"}
            ),
        }
    )
    model = "gemini-3.1-pro-preview"
    result = google_result(image=False)
    result["usageMetadata"] = {
        "promptTokenCount": 100,
        "cachedContentTokenCount": 40,
        "candidatesTokenCount": 20,
        "thoughtsTokenCount": 10,
        "totalTokenCount": 130,
    }
    observed = await invoke(
        value,
        model=model,
        endpoint=f"https://generativelanguage.googleapis.com/v1alpha/models/{model}:generateContent",
        result=result,
        functions=False,
        controls=None,
    )
    usage = observed.response.json()["usage"]
    assert usage["input_tokens"] == 100, usage
    assert usage["output_tokens"] == 30 and usage["total_tokens"] == 130
    assert usage["input_tokens_details"]["cached_tokens"] == 40
    assert usage["output_tokens_details"]["reasoning_tokens"] == 10
