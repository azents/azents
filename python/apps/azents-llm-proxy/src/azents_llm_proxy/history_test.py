"""A finite replay correction retains explicit image bytes and provenance."""

import base64

import pytest
from litellm.responses.litellm_completion_transformation.transformation import (
    LiteLLMCompletionResponsesConfig,
)

from azents_llm_proxy.history import bridge_image_history
from azents_llm_proxy.request import decode_request
from azents_llm_proxy.request_test import request
from azents_llm_proxy.settings import FidelityUnavailable

PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lE"
    "QVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII="
)


def test_generated_image_survives_existing_bridge_with_exact_bytes_and_order() -> None:
    selected = decode_request(
        {
            **request(),
            "input": [
                {"role": "user", "content": "before"},
                {
                    "type": "image_generation_call",
                    "id": "ig_synthetic",
                    "status": "completed",
                    "result": PNG,
                },
                {"role": "user", "content": "after"},
            ],
        }
    )
    rewritten = bridge_image_history(selected.payload)
    history = rewritten["input"]
    assert not isinstance(history, str)
    messages = (
        LiteLLMCompletionResponsesConfig.transform_responses_api_input_to_messages(
            input=list(history),
            responses_api_request={},
        )
    )
    assert messages[0]["content"] == "before" and messages[-1]["content"] == "after"
    assert "Provider tool call: image_generation completed" in str(
        messages[1]["content"]
    )
    assert f"data:image/png;base64,{PNG}" in str(messages[1]["content"])
    assert "image_generation_call" in str(selected.payload)
    assert selected.input_features == {"input:text", "input:image"}


@pytest.mark.parametrize("content", [b"not-an-image", b"", b"GIF-invalid-header"])
def test_unknown_image_format_is_not_fabricated_or_silently_lost(
    content: bytes,
) -> None:
    payload = decode_request(request()).payload
    payload["input"] = [
        {
            "type": "image_generation_call",
            "id": "ig_synthetic",
            "status": "completed",
            "result": base64.b64encode(content).decode(),
        }
    ]
    with pytest.raises(FidelityUnavailable):
        bridge_image_history(payload)
