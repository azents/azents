"""Explicit client tool and reasoning history survives real SDK transforms."""

import json

import pytest
from azents_llm_contract.authority import ApiKeyCredential
from pydantic import SecretStr

from azents_llm_proxy.authority_test import binding
from azents_llm_proxy.proxy_test import RESULT
from azents_llm_proxy.tool_wire_test import invoke

pytestmark = pytest.mark.usefixtures("protected_provider_clients")


def history() -> list[dict[str, object]]:
    return [
        {"role": "user", "content": "Use the client function."},
        {
            "type": "function_call",
            "id": "fc_fixture",
            "call_id": "call_fixture",
            "name": "lookup",
            "arguments": '{"city":"Seoul"}',
            "status": "completed",
        },
        {
            "type": "function_call_output",
            "call_id": "call_fixture",
            "output": '{"temperature":17}',
        },
    ]


async def test_native_model_change_preserves_tools_and_encrypted_reasoning() -> None:
    model = "gpt-5.5"
    reasoning = {
        "type": "reasoning",
        "id": "rs_fixture",
        "summary": [{"type": "summary_text", "text": "reasoning-summary-sentinel"}],
        "encrypted_content": "encrypted-reasoning-sentinel",
        "status": "completed",
    }
    inputs = [*history(), reasoning]
    observed = await invoke(
        binding(),
        model=model,
        endpoint="https://api.openai.com/v1/responses",
        result={**RESULT, "model": model},
        functions=False,
        controls={"input": inputs},
    )
    assert observed.response.status_code == 200, observed.response.text
    assert observed.physical_calls == 1
    wire = json.loads(observed.request.content)
    assert wire["input"] == inputs
    assert wire["model"] == model


async def test_provider_change_keeps_client_call_and_result_pair() -> None:
    model = "claude-sonnet-4-6"
    original = binding()
    selected = original.model_copy(
        update={
            "credential": ApiKeyCredential(
                kind="api_key",
                provider="anthropic",
                api_key=SecretStr("continuation-fixture-key"),
            ),
            "configuration": original.configuration.model_copy(
                update={"protocol": "anthropic"}
            ),
        }
    )
    result = {
        "id": "msg_fixture",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "The temperature is 17."}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 2, "output_tokens": 1},
    }
    observed = await invoke(
        selected,
        model=model,
        endpoint="https://api.anthropic.com/v1/messages",
        result=result,
        functions=False,
        controls={"input": history()},
    )
    assert observed.response.status_code == 200, observed.response.text
    assert observed.physical_calls == 1
    messages = json.loads(observed.request.content)["messages"]
    call = next(
        part
        for message in messages
        for part in message["content"]
        if isinstance(part, dict) and part.get("type") == "tool_use"
    )
    output = next(
        part
        for message in messages
        for part in message["content"]
        if isinstance(part, dict) and part.get("type") == "tool_result"
    )
    assert call["id"] == output["tool_use_id"] == "call_fixture"
    assert call["name"] == "lookup" and call["input"] == {"city": "Seoul"}
    assert "17" in json.dumps(output["content"])
