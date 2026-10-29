"""Saved controls, three-state reasoning intent and request-dependent support."""

import pytest
from azents_llm_contract.authority import TargetBinding
from azents_llm_contract.settings import FeatureCondition, GenerationSettings

from azents_llm_proxy.authority_test import binding
from azents_llm_proxy.request import decode_request
from azents_llm_proxy.request_test import request
from azents_llm_proxy.settings import UnsupportedRequest, normalize_request


def configured() -> TargetBinding:
    value = binding()
    return value.model_copy(
        update={
            "configuration": value.configuration.model_copy(
                update={
                    "parameters": GenerationSettings(
                        temperature=0.4,
                        top_p=0.8,
                        top_k=20,
                        stop_sequences=("stop",),
                        reasoning_effort="high",
                    ),
                    "supported_features": (
                        "input:text",
                        "temperature",
                        "top_p",
                        "top_k",
                        "stop_sequences",
                        "reasoning",
                        "reasoning_summaries",
                        "max_output_tokens",
                        "function_calling",
                        "parallel_function_calls",
                        "strict_function_schema",
                        "structured_response",
                    ),
                    "reasoning_efforts": ("low", "high"),
                }
            )
        }
    )


def test_saved_controls_are_defaults_and_do_not_mutate_request() -> None:
    selected = decode_request(request())
    result = normalize_request(selected, configured())
    assert result["temperature"] == 0.4
    assert result["top_p"] == 0.8 and result["top_k"] == 20
    assert result["stop"] == ["stop"]
    assert result["reasoning"] == {"effort": "high"}
    assert "max_output_tokens" not in result
    assert "metadata" not in result and result["store"] is False
    assert "reasoning" not in selected.payload and "metadata" in selected.payload


@pytest.mark.parametrize("declaration", [None, {}, {"effort": None}])
def test_explicit_reasoning_clear_does_not_restore_saved_default(
    declaration: object,
) -> None:
    result = normalize_request(
        decode_request({**request(), "reasoning": declaration}), configured()
    )
    reasoning = result["reasoning"]
    assert reasoning is not None and reasoning.get("effort") is None


def test_summary_only_keeps_saved_effort_and_alias_is_consumed() -> None:
    result = normalize_request(
        decode_request({**request(), "reasoning": {"summary": "auto"}}), configured()
    )
    assert result["reasoning"] == {"effort": "high", "summary": "auto"}
    alias = normalize_request(
        decode_request({**request(), "reasoning_effort": "low"}), configured()
    )
    assert alias["reasoning"] == {"effort": "low"}
    assert "reasoning_effort" not in alias
    with pytest.raises(UnsupportedRequest):
        normalize_request(
            decode_request({**request(), "reasoning": {}, "reasoning_effort": "low"}),
            configured(),
        )


@pytest.mark.parametrize(
    "saved,model,caller,expected",
    [
        (None, 500, None, None),
        (None, 500, 1000, 500),
        (1000, 500, None, 500),
        (1000, None, None, 1000),
        (1000, 500, 100, 100),
        (1000, None, 2000, 1000),
    ],
)
def test_output_cap_preserves_unset_and_clamps_only_explicit_intent(
    saved: int | None,
    model: int | None,
    caller: int | None,
    expected: int | None,
) -> None:
    value = configured()
    value = value.model_copy(
        update={
            "configuration": value.configuration.model_copy(
                update={
                    "max_output_tokens": saved,
                    "maximum_output_tokens": model,
                }
            )
        }
    )
    payload = request()
    if caller is not None:
        payload["max_output_tokens"] = caller
    result = normalize_request(decode_request(payload), value)
    assert result.get("max_output_tokens") == expected
    if expected is None:
        assert "max_output_tokens" not in result


@pytest.mark.parametrize(
    "field,value",
    [
        ("temperature", 0.1),
        ("top_p", 0.5),
        ("top_k", 2),
        ("max_output_tokens", 100),
        ("stop", "end"),
        ("parallel_tool_calls", True),
        ("reasoning", {"effort": "high"}),
        ("text", {"format": {"type": "json_object"}}),
        (
            "tools",
            [
                {
                    "type": "function",
                    "name": "tool",
                    "parameters": {"type": "object"},
                    "strict": True,
                }
            ],
        ),
    ],
)
def test_unsupported_features_fail_instead_of_being_dropped(
    field: str, value: object
) -> None:
    with pytest.raises(UnsupportedRequest):
        normalize_request(decode_request({**request(), field: value}), binding())


def test_feature_conditions_use_actual_reasoning_and_function_context() -> None:
    value = configured()
    value = value.model_copy(
        update={
            "configuration": value.configuration.model_copy(
                update={
                    "feature_conditions": (
                        FeatureCondition(
                            feature="temperature",
                            reasoning_efforts=("low",),
                            function_tools=False,
                        ),
                    ),
                }
            )
        }
    )
    with pytest.raises(UnsupportedRequest):
        normalize_request(decode_request(request()), value)
    result = normalize_request(
        decode_request({**request(), "reasoning": {"effort": "low"}}), value
    )
    assert result["temperature"] == 0.4
    with pytest.raises(UnsupportedRequest):
        normalize_request(
            decode_request(
                {
                    **request(),
                    "reasoning": {"effort": "low"},
                    "tools": [
                        {
                            "type": "function",
                            "name": "tool",
                            "parameters": {"type": "object"},
                            "strict": False,
                        }
                    ],
                }
            ),
            value,
        )


@pytest.mark.parametrize("tier", ["priority", "ultrafast", "auto", "flex", "scale"])
def test_tier_cannot_create_unsupported_execution_preference(tier: str) -> None:
    with pytest.raises(UnsupportedRequest):
        normalize_request(
            decode_request({**request(), "service_tier": tier}), binding()
        )


@pytest.mark.parametrize("tier", [None, "default", "priority", "fast", "ultrafast"])
def test_supported_tiers_preserve_intent_and_openai_disabled_default(
    tier: str | None,
) -> None:
    value = binding()
    value = value.model_copy(
        update={
            "configuration": value.configuration.model_copy(
                update={"supported_execution_options": ("fast", "ultrafast")}
            )
        }
    )
    payload = request()
    if tier is not None:
        payload["service_tier"] = tier
    result = normalize_request(decode_request(payload), value)
    assert result["service_tier"] == (
        "priority" if tier == "fast" else tier if tier is not None else "default"
    )
