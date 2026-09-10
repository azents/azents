"""Tests for the code-owned image-generation model registry."""

from azents.core.enums import LLMModelLifecycleStatus, LLMProvider
from azents.core.image_generation_catalog import (
    IMAGE_GENERATION_MODEL_REGISTRY_REVISION,
    image_generation_lifecycle_is_executable,
    image_generation_registry_entries_for_provider,
    image_generation_registry_entry,
)


def test_openai_registry_uses_exact_reviewed_seed_order() -> None:
    """Keep the initial explicit choices stable and ordered by recommendation."""
    entries = image_generation_registry_entries_for_provider(LLMProvider.OPENAI)

    assert IMAGE_GENERATION_MODEL_REGISTRY_REVISION == 1
    assert [entry.provider_model_identifier for entry in entries] == [
        "gpt-image-2.5-flare",
        "gpt-image-2.5-sunburst",
    ]
    assert [entry.recommendation_rank for entry in entries] == [1, 2]
    assert entries[0].description == (
        "Recommended for fast, cost-balanced image generation."
    )
    assert entries[1].description == "Highest-quality image generation choice."


def test_registry_lookup_uses_exact_provider_and_identifier() -> None:
    """Do not treat aliases or a different provider as registry membership."""
    assert (
        image_generation_registry_entry(
            provider=LLMProvider.OPENAI,
            provider_model_identifier="gpt-image-2.5-flare",
        )
        is not None
    )
    assert (
        image_generation_registry_entry(
            provider=LLMProvider.XAI,
            provider_model_identifier="gpt-image-2.5-flare",
        )
        is None
    )
    assert (
        image_generation_registry_entry(
            provider=LLMProvider.OPENAI,
            provider_model_identifier="gpt-image-2.5-flare-preview",
        )
        is None
    )


def test_only_active_and_deprecated_lifecycle_statuses_are_executable() -> None:
    """Disabled and source-removed registry entries cannot authorize a pin."""
    assert image_generation_lifecycle_is_executable(LLMModelLifecycleStatus.ACTIVE)
    assert image_generation_lifecycle_is_executable(LLMModelLifecycleStatus.DEPRECATED)
    assert not image_generation_lifecycle_is_executable(
        LLMModelLifecycleStatus.DISABLED
    )
    assert not image_generation_lifecycle_is_executable(
        LLMModelLifecycleStatus.REMOVED_FROM_SOURCE
    )
