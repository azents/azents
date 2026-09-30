"""Tests for deterministic model listing fixtures."""

import pytest

from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.testing.deterministic_model_listing import (
    build_deterministic_listing,
    parse_deterministic_fixture_variant,
)


def test_model_settings_fixture_exposes_supported_and_unsupported_tools() -> None:
    """Expose one hosted-tool model and one model without built-in tools."""
    variant = parse_deterministic_fixture_variant(
        "__testenv_model_listing:deterministic-model-settings"
    )

    assert variant == "deterministic-model-settings"
    listing = build_deterministic_listing(
        variant=variant,
        provider=LLMProvider.OPENAI,
        integration_id="integration-id",
    )

    by_identifier = {model.model_identifier: model for model in listing.models}
    assert by_identifier[
        "gpt-5.5"
    ].normalized_capabilities.built_in_tools.supported == [
        "web_search",
        "image_generation",
    ]
    assert (
        by_identifier["gpt-5.5-mini"].normalized_capabilities.built_in_tools.supported
        == []
    )


def test_context_ranges_fixture_exposes_default_and_maximum() -> None:
    """Expose a split main range and a maximum-only lightweight range."""
    variant = parse_deterministic_fixture_variant(
        "__testenv_model_listing:deterministic-context-ranges"
    )

    assert variant == "deterministic-context-ranges"
    listing = build_deterministic_listing(
        variant=variant,
        provider=LLMProvider.OPENAI,
        integration_id="integration-id",
    )

    main, lightweight = listing.models
    assert main.normalized_capabilities.context_window.default_input_tokens == 96_000
    assert main.normalized_capabilities.context_window.max_input_tokens == 256_000
    assert (
        lightweight.normalized_capabilities.context_window.default_input_tokens is None
    )
    assert (
        lightweight.normalized_capabilities.context_window.max_input_tokens == 512_000
    )


def test_openrouter_fixture_preserves_known_and_unknown_publishers() -> None:
    """Expose broad OpenRouter model ids with conservative capabilities."""
    variant = parse_deterministic_fixture_variant(
        "__testenv_model_listing:deterministic-openrouter"
    )

    assert variant == "deterministic-openrouter"
    listing = build_deterministic_listing(
        variant=variant,
        provider=LLMProvider.OPENROUTER,
        integration_id="integration-id",
    )

    by_identifier = {model.model_identifier: model for model in listing.models}
    known = by_identifier["anthropic/claude-sonnet-4.6"]
    unknown = by_identifier["new-publisher/frontier-text"]

    assert known.model_developer.value == "anthropic"
    assert unknown.model_developer.value == "other"
    assert known.normalized_capabilities.modalities.input == ["text", "image"]
    assert unknown.normalized_capabilities.built_in_tools.supported == ["web_search"]
    assert listing.summary.returned_count == 2
    assert listing.summary.skipped_count == 1


def test_model_settings_fixture_adds_astra_sol_without_changing_old_models() -> None:
    """Expose premium-speed models in the existing deterministic fixture mode."""
    listing = build_deterministic_listing(
        variant="deterministic-model-settings",
        provider=LLMProvider.OPENAI,
        integration_id="integration-id",
    )
    by_identifier = {model.model_identifier: model for model in listing.models}
    assert listing.summary.returned_count == 4
    assert listing.summary.skipped_count == 1
    assert by_identifier["gpt-5.5"].supported_execution_options == [
        ModelExecutionOptionId.FAST
    ]
    assert by_identifier["gpt-5.5-mini"].supported_execution_options == []
    for identifier, name in (
        ("gpt-6-astra", "GPT 6 Astra Deterministic"),
        ("gpt-5.6-sol", "GPT 5.6 Sol Deterministic"),
    ):
        model = by_identifier[identifier]
        assert model.model_display_name == name
        assert model.supported_execution_options == [
            ModelExecutionOptionId.FAST,
            ModelExecutionOptionId.ULTRAFAST,
        ]
        assert {
            ModelReasoningEffort.XHIGH,
            ModelReasoningEffort.HIGH,
        } <= set(model.normalized_capabilities.reasoning.effort_levels)
        assert model.normalized_capabilities.context_window.max_input_tokens == 128_000
        assert model.normalized_capabilities.context_window.max_output_tokens == 16_000
        assert model.model_snapshot["fixture_variant"] == "deterministic-model-settings"


@pytest.mark.parametrize(
    "provider", [LLMProvider.CHATGPT_OAUTH, LLMProvider.XAI, LLMProvider.OPENROUTER]
)
def test_model_settings_fixture_leaves_other_providers_unchanged(
    provider: LLMProvider,
) -> None:
    """The additive API fixture does not invent another provider's speed support."""
    listing = build_deterministic_listing(
        variant="deterministic-model-settings",
        provider=provider,
        integration_id="integration-id",
    )
    assert listing.summary.returned_count == 2
    assert all(model.supported_execution_options == [] for model in listing.models)
