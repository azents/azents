"""Closed protocol fields, explicit history and remote-resource rejection."""

import base64
import copy
import json

import pytest

from azents_llm_proxy.request import RequestRejected, decode_request

TARGET = "a" * 64
PNG = base64.b64encode(b"bounded-fixture-image").decode()


def request() -> dict[str, object]:
    return {
        "model": "model",
        "metadata": {"azents_target_id": TARGET},
        "input": "private-prompt",
    }


def test_normal_request_preserves_controls_and_selectors() -> None:
    decoded = decode_request(
        {
            **request(),
            "temperature": 0.2,
            "top_k": 10,
            "stream": True,
            "reasoning": {"effort": "high"},
            "prompt_cache_key": "caller-cache",
        }
    )
    assert decoded.model == "model" and decoded.target_id == TARGET
    assert decoded.payload["temperature"] == 0.2
    assert decoded.payload["prompt_cache_key"] == "caller-cache"
    assert "private-prompt" not in repr(decoded)


@pytest.mark.parametrize(
    "history",
    [
        [
            {
                "type": "reasoning",
                "id": "rs_fixture",
                "summary": [{"type": "summary_text", "text": "summary"}],
                "encrypted_content": "opaque-native-continuation",
            }
        ],
        [
            {
                "type": "function_call_output",
                "call_id": "call_fixture",
                "output": [{"type": "input_text", "text": "tool result"}],
            }
        ],
        [
            {
                "type": "message",
                "id": "msg_fixture",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": "reply", "annotations": []}
                ],
            }
        ],
    ],
)
def test_nested_sdk_iterables_are_validated_once_and_replayable(
    history: list[dict[str, object]],
) -> None:
    decoded = decode_request({**request(), "input": history})
    for _ in range(2):
        cloned = copy.deepcopy(decoded.payload)
        assert json.loads(json.dumps(cloned))["input"] == history


@pytest.mark.parametrize(
    "field",
    [
        "api_key",
        "api_base",
        "base_url",
        "extra_headers",
        "headers",
        "user_config",
        "callbacks",
        "success_callback",
        "fallbacks",
        "model_list",
        "custom_llm_provider",
        "litellm_params",
        "extra_body",
        "mock_response",
        "client",
    ],
)
def test_alternate_routing_controls_are_rejected(field: str) -> None:
    with pytest.raises(RequestRejected) as caught:
        decode_request({**request(), field: "credential-sentinel"})
    assert "credential-sentinel" not in str(caught.value)
    assert "private-prompt" not in str(caught.value)


@pytest.mark.parametrize(
    "body",
    [
        {"background": True},
        {"previous_response_id": "resp_foreign"},
        {"conversation": "conv_foreign"},
        {"store": True},
        {"prompt": {"id": "pmpt_foreign"}},
        {
            "tools": [
                {
                    "type": "mcp",
                    "server_label": "control",
                    "server_url": "http://internal.invalid",
                }
            ]
        },
        {"input": [{"type": "item_reference", "id": "foreign"}]},
        {
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_image", "image_url": "http://internal.invalid"}
                    ],
                }
            ]
        },
        {
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_image", "file_id": "foreign"}],
                }
            ]
        },
        {
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_file", "file_url": "http://internal.invalid"}
                    ],
                }
            ]
        },
    ],
)
def test_stored_remote_and_background_features_are_not_in_initial_scope(
    body: dict[str, object],
) -> None:
    with pytest.raises(RequestRejected):
        decode_request({**request(), **body})


def test_nested_sdk_override_is_rejected_not_forwarded() -> None:
    with pytest.raises(RequestRejected):
        decode_request(
            {
                **request(),
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup",
                        "parameters": {},
                        "extra_body": {"api_key": "sentinel"},
                    }
                ],
            }
        )
    with pytest.raises(RequestRejected):
        decode_request(
            {
                **request(),
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "hello",
                                "headers": {"Authorization": "sentinel"},
                            }
                        ],
                    }
                ],
            }
        )


def test_tool_argument_schema_is_opaque_not_a_routing_override() -> None:
    schema = {
        "type": "object",
        "properties": {"api_key": {"type": "string"}, "url": {"type": "string"}},
    }
    decoded = decode_request(
        {
            **request(),
            "tools": [
                {
                    "type": "function",
                    "name": "lookup",
                    "parameters": schema,
                    "strict": True,
                }
            ],
        }
    )
    assert decoded.payload["tools"] is not None
    assert next(iter(decoded.payload["tools"]))["type"] == "function"
    assert next(iter(decoded.payload["tools"]))["type"] == "function"


def test_explicit_inline_image_and_generated_image_history_are_retained() -> None:
    history = [
        {
            "type": "image_generation_call",
            "id": "ig_fixture",
            "status": "completed",
            "result": PNG,
        },
        {
            "role": "user",
            "content": [
                {"type": "input_image", "image_url": "data:image/png;base64," + PNG}
            ],
        },
    ]
    decoded = decode_request({**request(), "input": history})
    assert PNG in str(decoded.payload["input"])
    assert history[1]["content"] == [
        {"type": "input_image", "image_url": "data:image/png;base64," + PNG}
    ]


@pytest.mark.parametrize("metadata", [None, {}, {"azents_target_id": "not-a-target"}])
def test_selector_must_be_explicit(metadata: object) -> None:
    with pytest.raises(RequestRejected):
        decode_request({**request(), "metadata": metadata})


def test_image_tool_mask_cannot_fetch_remote_or_stored_resources() -> None:
    for mask in ({"file_id": "foreign"}, {"image_url": "http://internal.invalid"}):
        with pytest.raises(RequestRejected):
            decode_request(
                {
                    **request(),
                    "tools": [{"type": "image_generation", "input_image_mask": mask}],
                }
            )
