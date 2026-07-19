"""Tests for deterministic model listing fixtures."""

from azents.core.enums import LLMProvider
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
