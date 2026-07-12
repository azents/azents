"""LLM catalog capability contract tests."""

import pytest
from pydantic import ValidationError

from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelModality,
    ModelReasoningEffort,
    UnsupportedMediaPolicy,
    build_initial_model_capabilities,
)


def test_model_capabilities_serializes_required_top_level_keys() -> None:
    """Default capability serializes to stable JSON shape."""
    capabilities = ModelCapabilities()

    data = capabilities.model_dump(mode="json")

    assert set(data) == {
        "context_window",
        "modalities",
        "tool_calling",
        "reasoning",
        "built_in_tools",
        "parameters",
        "compatibility",
    }
    assert data["context_window"] == {
        "max_input_tokens": None,
        "max_output_tokens": None,
    }
    assert data["modalities"] == {"input": [], "output": []}
    assert data["tool_calling"] == {
        "supported": False,
        "parallel_tool_calls": None,
        "strict_json_schema": None,
    }
    assert data["reasoning"] == {
        "supported": False,
        "effort_levels": [],
        "summaries": None,
    }
    assert data["built_in_tools"] == {"supported": []}
    assert data["parameters"] == {
        "temperature": False,
        "max_output_tokens": False,
        "top_p": False,
        "top_k": False,
        "stop_sequences": False,
    }
    assert data["compatibility"] == {
        "provider_family": None,
        "responses_api": None,
        "unsupported_media_policy": None,
    }


def test_build_initial_model_capabilities_promotes_legacy_supported_fields() -> None:
    """Only legacy thinking and allowlisted metadata are promoted to capability."""
    capabilities = build_initial_model_capabilities(
        thinking=True,
        metadata={
            "max_input_tokens": 128000,
            "supported_builtin_tools": [
                "web_search",
                "unknown_tool",
                "image_generation",
                1,
            ],
            "ignored": "value",
        },
    )

    assert capabilities.reasoning.supported is True
    assert capabilities.context_window.max_input_tokens == 128000
    assert capabilities.built_in_tools.supported == ["web_search", "image_generation"]


@pytest.mark.parametrize(
    "metadata",
    [
        {"max_input_tokens": 0},
        {"max_input_tokens": -1},
        {"max_input_tokens": True},
        {"max_input_tokens": "128000"},
    ],
)
def test_build_initial_model_capabilities_ignores_invalid_max_input_tokens(
    metadata: dict[str, object],
) -> None:
    """max_input_tokens that is not a positive integer is not promoted."""
    capabilities = build_initial_model_capabilities(thinking=False, metadata=metadata)

    assert capabilities.context_window.max_input_tokens is None


def test_model_capabilities_accepts_normalized_enum_values() -> None:
    """Normalized enum-like values are validated."""
    capabilities = ModelCapabilities.model_validate(
        {
            "modalities": {
                "input": [ModelModality.TEXT, ModelModality.IMAGE],
                "output": [ModelModality.TEXT],
            },
            "reasoning": {
                "supported": True,
                "effort_levels": [ModelReasoningEffort.LOW, ModelReasoningEffort.HIGH],
                "summaries": True,
            },
            "compatibility": {"unsupported_media_policy": UnsupportedMediaPolicy.BLOCK},
        }
    )

    data = capabilities.model_dump(mode="json")
    assert data["modalities"]["input"] == ["text", "image"]
    assert data["reasoning"]["effort_levels"] == ["low", "high"]
    assert data["compatibility"]["unsupported_media_policy"] == "block"


def test_model_capabilities_ignores_unknown_future_fields() -> None:
    """Future capability fields are ignored without breaking current runtime."""
    capabilities = ModelCapabilities.model_validate(
        {
            "context_window": {
                "max_input_tokens": 128000,
                "cache_tokens": 10000,
            },
            "reasoning": {
                "supported": True,
                "effort_levels": ["low"],
                "encrypted_reasoning_items": True,
            },
            "pricing": {"input_per_million": 1.0},
        }
    )

    data = capabilities.model_dump(mode="json")
    assert data["context_window"] == {
        "max_input_tokens": 128000,
        "max_output_tokens": None,
    }
    assert data["reasoning"] == {
        "supported": True,
        "effort_levels": ["low"],
        "summaries": None,
    }
    assert "pricing" not in data


def test_model_capabilities_rejects_unknown_builtin_tool() -> None:
    """Contract rejects unregistered built-in tools."""
    with pytest.raises(ValidationError):
        ModelCapabilities.model_validate(
            {"built_in_tools": {"supported": ["unknown_tool"]}}
        )
