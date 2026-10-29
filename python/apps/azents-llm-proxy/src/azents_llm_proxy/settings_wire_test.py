"""Saved generation controls reach physical provider serialization unchanged."""

import json

import pytest
from azents_llm_contract.authority import ApiKeyCredential, TargetBinding
from azents_llm_contract.settings import GenerationSettings
from pydantic import SecretStr

from azents_llm_proxy.authority_test import binding
from azents_llm_proxy.proxy_test import RESULT
from azents_llm_proxy.tool_wire_test import google_result, invoke

pytestmark = pytest.mark.usefixtures("protected_provider_clients")


def configured(*, provider: str, protocol: str, generic: bool) -> TargetBinding:
    original = binding()
    return original.model_copy(
        update={
            "credential": ApiKeyCredential.model_validate(
                {
                    "kind": "api_key",
                    "provider": provider,
                    "api_key": SecretStr("provider-setting-sentinel"),
                }
            ),
            "configuration": original.configuration.model_copy(
                update={
                    "protocol": protocol,
                    "parameters": GenerationSettings(
                        temperature=0.4,
                        top_p=0.8,
                        top_k=20 if generic else None,
                        stop_sequences=("END",) if generic else None,
                        reasoning_effort=None,
                    ),
                    "max_output_tokens": 100,
                    "supported_features": (
                        "input:text",
                        "temperature",
                        "top_p",
                        "top_k",
                        "stop_sequences",
                        "max_output_tokens",
                        "function_calling",
                        "strict_function_schema",
                        "structured_response",
                        "parallel_function_calls",
                    ),
                }
            ),
        }
    )


async def test_native_controls_keep_strict_tools_schema_sampling_and_smaller_cap() -> (
    None
):
    model = "gpt-4o-mini"
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    tool = {"type": "function", "name": "answer", "parameters": schema, "strict": True}
    text = {
        "format": {
            "type": "json_schema",
            "name": "answer",
            "schema": schema,
            "strict": True,
        }
    }
    observed = await invoke(
        configured(provider="openai", protocol="native_responses", generic=False),
        model=model,
        endpoint="https://api.openai.com/v1/responses",
        result={**RESULT, "model": model},
        functions=False,
        controls={
            "tools": [tool],
            "text": text,
            "parallel_tool_calls": True,
            "max_output_tokens": 50,
        },
    )
    wire = json.loads(observed.request.content)
    assert wire["temperature"] == 0.4 and wire["top_p"] == 0.8
    assert wire["max_output_tokens"] == 50
    assert wire["text"] == text and wire["tools"] == [tool]
    assert wire["parallel_tool_calls"] is True
    assert wire["store"] is False


async def test_anthropic_generic_sampling_stop_and_saved_cap_are_not_dropped() -> None:
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
        configured(provider="anthropic", protocol="anthropic", generic=True),
        model=model,
        endpoint="https://api.anthropic.com/v1/messages",
        result=result,
        functions=False,
        controls=None,
    )
    wire = json.loads(observed.request.content)
    assert wire["temperature"] == 0.4 and wire["top_p"] == 0.8
    assert wire["top_k"] == 20 and wire["stop_sequences"] == ["END"]
    assert wire["max_tokens"] == 100


async def test_gemini_generic_sampling_stop_and_saved_cap_are_not_dropped() -> None:
    model = "gemini-3.1-pro-preview"
    observed = await invoke(
        configured(provider="google_gemini", protocol="google", generic=True),
        model=model,
        endpoint=f"https://generativelanguage.googleapis.com/v1alpha/models/{model}:generateContent",
        result=google_result(image=False),
        functions=False,
        controls=None,
    )
    config = json.loads(observed.request.content)["generationConfig"]
    assert config["temperature"] == 0.4 and config["top_p"] == 0.8
    assert config["top_k"] == 20 and config["stop_sequences"] == ["END"]
    assert config["max_output_tokens"] == 100


@pytest.mark.parametrize("google", [False, True])
@pytest.mark.parametrize("reasoning", [False, True])
async def test_generic_structured_and_reasoning_controls_reach_provider(
    google: bool, reasoning: bool
) -> None:
    model = "gemini-3.1-pro-preview" if google else "claude-sonnet-4-6"
    selected = configured(
        provider="google_gemini" if google else "anthropic",
        protocol="google" if google else "anthropic",
        generic=False,
    )
    selected = selected.model_copy(
        update={
            "configuration": selected.configuration.model_copy(
                update={
                    "parameters": None,
                    "max_output_tokens": 16000,
                    "supported_features": (
                        "input:text",
                        "max_output_tokens",
                        "structured_response",
                        "reasoning",
                    ),
                    "reasoning_efforts": ("high",),
                }
            )
        }
    )
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    controls: dict[str, object] = (
        {"reasoning": {"effort": "high"}}
        if reasoning
        else {
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "answer",
                    "schema": schema,
                    "strict": True,
                }
            }
        }
    )
    result = (
        google_result(image=False)
        if google
        else {
            "id": "msg_offline",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [{"type": "text", "text": '{"answer":"fixture"}'}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 2, "output_tokens": 1},
        }
    )
    observed = await invoke(
        selected,
        model=model,
        endpoint=(
            "https://generativelanguage.googleapis.com/v1alpha/models/"
            f"{model}:generateContent"
            if google
            else "https://api.anthropic.com/v1/messages"
        ),
        result=result,
        functions=False,
        controls=controls,
    )
    wire = json.loads(observed.request.content)
    assert observed.physical_calls == 1
    if google:
        config = wire["generationConfig"]
        assert config["max_output_tokens"] == 16000
        if reasoning:
            assert config["thinkingConfig"] == {
                "includeThoughts": True,
                "thinkingLevel": "high",
            }
        else:
            assert config["response_mime_type"] == "application/json"
            assert config["response_json_schema"] == schema
    else:
        assert wire["max_tokens"] == 16000
        if reasoning:
            assert wire["thinking"] == {"type": "adaptive", "display": "summarized"}
            assert wire["output_config"]["effort"] == "high"
        else:
            assert wire["output_format"] == {"type": "json_schema", "schema": schema}
