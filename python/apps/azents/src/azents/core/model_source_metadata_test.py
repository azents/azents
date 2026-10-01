"""Exact source matching preserves provider-owned model identifiers."""

import pytest

from azents.core.enums import LLMProvider
from azents.core.model_source_metadata import (
    lookup_model_source_metadata,
    source_max_input_tokens,
)
from azents.engine.context.window import resolve_model_input_tokens


@pytest.mark.parametrize(
    ("provider", "model_identifier", "source_key"),
    [
        (LLMProvider.OPENAI, "selected-model", "selected-model"),
        (LLMProvider.CHATGPT_OAUTH, "selected-model", "openai/selected-model"),
        (LLMProvider.ANTHROPIC, "selected-model", "anthropic/selected-model"),
        (LLMProvider.GOOGLE_GEMINI, "selected-model", "gemini/selected-model"),
        (LLMProvider.XAI, "selected-model", "xai/selected-model"),
        (LLMProvider.XAI_OAUTH, "selected-model", "xai/selected-model"),
        (LLMProvider.KIMI_OAUTH, "selected-model", "moonshot/selected-model"),
        (
            LLMProvider.OPENROUTER,
            "publisher/selected-model",
            "openrouter/publisher/selected-model",
        ),
        (
            LLMProvider.AWS_BEDROCK,
            "arn:aws:bedrock:us-east-1:123:inference-profile/us.anthropic.model",
            "bedrock/arn:aws:bedrock:us-east-1:123:inference-profile/us.anthropic.model",
        ),
        (
            LLMProvider.GOOGLE_VERTEX_AI,
            "projects/project/locations/us/publishers/anthropic/models/model",
            "vertex_ai/projects/project/locations/us/publishers/anthropic/models/model",
        ),
    ],
)
def test_exact_source_namespace_preserves_entire_model_identifier(
    provider: LLMProvider,
    model_identifier: str,
    source_key: str,
) -> None:
    """Neither publisher paths nor cloud resource segments are stripped."""
    payload = {source_key: {"max_input_tokens": 272_000}}
    matched = lookup_model_source_metadata(
        provider=provider,
        model_identifier=model_identifier,
        payload=payload,
    )
    assert matched is not None
    assert matched.source_model_key == source_key
    assert source_max_input_tokens(matched) == 272_000
    assert set(payload) == {source_key}


def test_publisher_suffix_does_not_become_a_cross_provider_match() -> None:
    """A price/context model with the same final segment is not an exact match."""
    matched = lookup_model_source_metadata(
        provider=LLMProvider.OPENROUTER,
        model_identifier="publisher/model",
        payload={"model": {"max_input_tokens": 1_000_000}},
    )
    assert matched is None
    assert source_max_input_tokens(matched) is None


def test_openai_current_raw_key_precedes_namespaced_alias() -> None:
    """Preserve the existing explicit OpenAI source-key precedence."""
    matched = lookup_model_source_metadata(
        provider=LLMProvider.OPENAI,
        model_identifier="model",
        payload={
            "model": {"max_input_tokens": 128_000},
            "openai/model": {"max_input_tokens": 256_000},
        },
    )
    assert matched is not None
    assert matched.source_model_key == "model"
    assert source_max_input_tokens(matched) == 128_000


def test_conflicting_bare_provider_does_not_enlarge_context() -> None:
    matched = lookup_model_source_metadata(
        provider=LLMProvider.ANTHROPIC,
        model_identifier="same",
        payload={"same": {"litellm_provider": "openai", "max_input_tokens": 1_000_000}},
    )
    assert matched is None
    resolved = resolve_model_input_tokens(
        64_000, None, source_max_input_tokens(matched), None
    )
    assert resolved.max_input_tokens == 64_000
    assert resolved.effective_input_tokens == 64_000


def test_conflicting_bare_key_does_not_mask_valid_namespaced_metadata() -> None:
    matched = lookup_model_source_metadata(
        provider=LLMProvider.OPENAI,
        model_identifier="same",
        payload={
            "same": {"litellm_provider": "anthropic", "max_input_tokens": 1_000_000},
            "openai/same": {"litellm_provider": "openai", "max_input_tokens": 256_000},
        },
    )
    assert matched is not None
    assert matched.source_model_key == "openai/same"
    assert source_max_input_tokens(matched) == 256_000


@pytest.mark.parametrize("value", [None, True, False, 0, -1, 2.5, "128000"])
def test_invalid_source_maximum_remains_unknown(value: object) -> None:
    """Only positive integer metadata is a source context maximum."""
    matched = lookup_model_source_metadata(
        provider=LLMProvider.XAI,
        model_identifier="alias",
        payload={"xai/alias": {"max_input_tokens": value}},
    )
    assert source_max_input_tokens(matched) is None
