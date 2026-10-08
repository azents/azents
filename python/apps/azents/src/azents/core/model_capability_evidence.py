"""Provider-returned capability facts preserved independently of projection defaults."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_catalog_source import CatalogFact


def absent_catalog_fact[T]() -> CatalogFact[T]:
    """Create an absent fact, including during historical candidate replay."""
    return CatalogFact(state="absent", value=None)


class ProviderCapabilityEvidence(BaseModel):
    """Partial listing evidence; every omitted feature remains an absent fact.

    List-valued value declarations are complete in their provider-documented
    scope, including explicitly empty lists. Null is supplied but unknown.
    Defaults are intentional for this partial-evidence bag, not model denials.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    default_input_tokens: CatalogFact[int] = Field(default_factory=absent_catalog_fact)
    max_input_tokens: CatalogFact[int] = Field(default_factory=absent_catalog_fact)
    max_output_tokens: CatalogFact[int] = Field(default_factory=absent_catalog_fact)
    input_modalities: CatalogFact[tuple[str, ...]] = Field(
        default_factory=absent_catalog_fact
    )
    output_modalities: CatalogFact[tuple[str, ...]] = Field(
        default_factory=absent_catalog_fact
    )
    image_input: CatalogFact[bool] = Field(default_factory=absent_catalog_fact)
    video_input: CatalogFact[bool] = Field(default_factory=absent_catalog_fact)
    function_calling: CatalogFact[bool] = Field(default_factory=absent_catalog_fact)
    parallel_function_calling: CatalogFact[bool] = Field(
        default_factory=absent_catalog_fact
    )
    strict_function_schema: CatalogFact[bool] = Field(
        default_factory=absent_catalog_fact
    )
    structured_response: CatalogFact[bool] = Field(default_factory=absent_catalog_fact)
    reasoning: CatalogFact[bool] = Field(default_factory=absent_catalog_fact)
    reasoning_efforts: CatalogFact[tuple[ModelReasoningEffort, ...]] = Field(
        default_factory=absent_catalog_fact
    )
    default_reasoning_effort: CatalogFact[ModelReasoningEffort] = Field(
        default_factory=absent_catalog_fact
    )
    reasoning_summaries: CatalogFact[bool] = Field(default_factory=absent_catalog_fact)
    temperature: CatalogFact[bool] = Field(default_factory=absent_catalog_fact)
    top_p: CatalogFact[bool] = Field(default_factory=absent_catalog_fact)
    top_k: CatalogFact[bool] = Field(default_factory=absent_catalog_fact)
    stop_sequences: CatalogFact[bool] = Field(default_factory=absent_catalog_fact)
    max_output_parameter: CatalogFact[bool] = Field(default_factory=absent_catalog_fact)
    web_search: CatalogFact[bool] = Field(default_factory=absent_catalog_fact)
    client_image_generation: CatalogFact[bool] = Field(
        default_factory=absent_catalog_fact
    )
    hosted_image_generation: CatalogFact[bool] = Field(
        default_factory=absent_catalog_fact
    )
    responses_api: CatalogFact[bool] = Field(default_factory=absent_catalog_fact)

    @model_validator(mode="after")
    def validate_bounds(self) -> ProviderCapabilityEvidence:
        """Reject malformed restored declarations."""
        for fact in (
            self.default_input_tokens,
            self.max_input_tokens,
            self.max_output_tokens,
        ):
            if fact.value is not None and not 0 <= fact.value <= 2**63 - 1:
                raise ValueError("Provider token limit is out of bounds.")
        for fact in (self.input_modalities, self.output_modalities):
            if fact.value is not None and len(fact.value) > 256:
                raise ValueError("Provider modality declaration is too long.")
            if fact.value is not None and len(set(fact.value)) != len(fact.value):
                raise ValueError("Provider modality declaration contains duplicates.")
        efforts = self.reasoning_efforts.value
        if efforts is not None and len(set(efforts)) != len(efforts):
            raise ValueError("Provider effort declaration contains duplicates.")
        return self


def empty_provider_capability_evidence() -> ProviderCapabilityEvidence:
    """Restore a missing historical envelope as unknown, never normalized defaults."""
    return ProviderCapabilityEvidence()
