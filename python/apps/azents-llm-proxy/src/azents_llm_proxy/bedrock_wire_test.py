"""Explicit AWS account signing at the real Proxy-to-Bedrock HTTP boundary."""

import json

import pytest

from azents_llm_proxy.authority_test import binding
from azents_llm_proxy.provider_test import bedrock
from azents_llm_proxy.tool_wire_test import invoke

pytestmark = pytest.mark.usefixtures("protected_provider_clients")


async def test_bedrock_explicit_keys_sign_only_the_selected_regional_endpoint() -> None:
    original = binding()
    selected = original.model_copy(
        update={
            "credential": bedrock("us-west-2"),
            "configuration": original.configuration.model_copy(
                update={"protocol": "bedrock"}
            ),
        }
    )
    model = "amazon.nova-lite-v1:0"
    observed = await invoke(
        selected,
        model=model,
        endpoint=f"https://bedrock-runtime.us-west-2.amazonaws.com/model/{model}/converse",
        result={
            "output": {
                "message": {"role": "assistant", "content": [{"text": "reply"}]}
            },
            "stopReason": "end_turn",
            "usage": {"inputTokens": 2, "outputTokens": 1, "totalTokens": 3},
            "metrics": {"latencyMs": 1},
        },
        functions=False,
        controls=None,
    )
    sent = observed.request
    assert sent.headers["authorization"].startswith(
        "AWS4-HMAC-SHA256 Credential=provider-call-sentinel/"
    )
    assert "/us-west-2/bedrock/aws4_request" in sent.headers["authorization"]
    assert "x-amz-security-token" not in sent.headers
    assert (
        json.loads(sent.content)["messages"][0]["content"][0]["text"]
        == "synthetic-tool-prompt"
    )
    assert observed.response.json()["usage"]["total_tokens"] == 3
