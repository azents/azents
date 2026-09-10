"""Code-owned image-generation model registry and eligibility policy."""

import dataclasses

from azents.core.enums import LLMModelLifecycleStatus, LLMProvider


@dataclasses.dataclass(frozen=True)
class ImageGenerationModelRegistryEntry:
    """One reviewed provider image-generation model definition."""

    provider: LLMProvider
    provider_model_identifier: str
    display_name: str
    description: str
    recommendation_rank: int | None
    lifecycle_status: LLMModelLifecycleStatus


IMAGE_GENERATION_MODEL_REGISTRY_REVISION = 1

IMAGE_GENERATION_MODEL_REGISTRY: tuple[ImageGenerationModelRegistryEntry, ...] = (
    ImageGenerationModelRegistryEntry(
        provider=LLMProvider.OPENAI,
        provider_model_identifier="gpt-image-2.5-flare",
        display_name="GPT Image 2.5 Flare",
        description="Recommended for fast, cost-balanced image generation.",
        recommendation_rank=1,
        lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
    ),
    ImageGenerationModelRegistryEntry(
        provider=LLMProvider.OPENAI,
        provider_model_identifier="gpt-image-2.5-sunburst",
        display_name="GPT Image 2.5 Sunburst",
        description="Highest-quality image generation choice.",
        recommendation_rank=2,
        lifecycle_status=LLMModelLifecycleStatus.ACTIVE,
    ),
)


def image_generation_registry_entries_for_provider(
    provider: LLMProvider,
) -> list[ImageGenerationModelRegistryEntry]:
    """Return executable registry entries in deterministic display order."""
    return sorted(
        (
            entry
            for entry in IMAGE_GENERATION_MODEL_REGISTRY
            if entry.provider == provider
            and image_generation_lifecycle_is_executable(entry.lifecycle_status)
        ),
        key=lambda entry: (
            entry.recommendation_rank is None,
            entry.recommendation_rank,
            entry.display_name,
            entry.provider_model_identifier,
        ),
    )


def image_generation_registry_entry(
    *,
    provider: LLMProvider,
    provider_model_identifier: str,
) -> ImageGenerationModelRegistryEntry | None:
    """Return one configured registry entry by its exact provider identifier."""
    for entry in IMAGE_GENERATION_MODEL_REGISTRY:
        if (
            entry.provider == provider
            and entry.provider_model_identifier == provider_model_identifier
        ):
            return entry
    return None


def image_generation_lifecycle_is_executable(
    lifecycle_status: LLMModelLifecycleStatus,
) -> bool:
    """Return whether one registry lifecycle is currently executable."""
    return lifecycle_status in {
        LLMModelLifecycleStatus.ACTIVE,
        LLMModelLifecycleStatus.DEPRECATED,
    }
