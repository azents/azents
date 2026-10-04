"""Resolve scoped model declarations before applying transport constraints."""

import dataclasses
from typing import Literal

from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelModality, ModelReasoningEffort
from azents.core.model_capability_evidence import (
    ProviderCapabilityEvidence,
    absent_catalog_fact,
    empty_provider_capability_evidence,
)
from azents.core.model_catalog_identity import source_model_matches
from azents.core.model_catalog_source import CatalogFact, CatalogSourceModel


@dataclasses.dataclass(frozen=True)
class ModelFactProvenance:
    """Record evidence ownership independently of final feature membership."""

    field: str
    owner: Literal["provider", "source", "absent"]
    presence: Literal["absent", "null", "value"]


@dataclasses.dataclass(frozen=True)
class ResolvedModalityFact:
    """Retain declared model media even when a route cannot transport it."""

    modality: ModelModality
    declaration: CatalogFact[bool]


@dataclasses.dataclass(frozen=True)
class ResolvedModelFacts:
    """One scoped evidence view, retaining original declarations for diagnostics."""

    declarations: ProviderCapabilityEvidence
    provider_declarations: ProviderCapabilityEvidence
    source_model: CatalogSourceModel | None
    input_modalities: tuple[ResolvedModalityFact, ...]
    output_modalities: tuple[ResolvedModalityFact, ...]
    provenance: tuple[ModelFactProvenance, ...]
    diagnostics: tuple[str, ...]


def _modality_fact(
    modality: ModelModality,
    *,
    listing: CatalogFact[tuple[str, ...]],
    listing_flag: CatalogFact[bool] | None,
    source_list: CatalogFact[tuple[str, ...]] | None,
    source_flag: CatalogFact[bool] | None,
) -> CatalogFact[bool]:
    """Interpret complete lists and scalar declarations without a codec ceiling."""
    if listing.state == "value":
        return CatalogFact(state="value", value=modality.value in (listing.value or ()))
    if listing_flag is not None and listing_flag.state != "absent":
        return listing_flag
    if listing.state == "null":
        return CatalogFact(state="null", value=None)
    if source_flag is not None and source_flag.value is False:
        return source_flag
    if source_list is not None and source_list.state != "absent":
        return (
            CatalogFact(state="value", value=modality.value in source_list.value)
            if source_list.value is not None
            else CatalogFact(state="null", value=None)
        )
    return source_flag if source_flag is not None else absent_catalog_fact()


def resolve_model_facts(
    *,
    provider: LLMProvider,
    exact_model: str,
    source_model: CatalogSourceModel | None,
    evidence: ProviderCapabilityEvidence | None,
) -> ResolvedModelFacts:
    """Assemble account facts and exact hosting-source facts with presence preserved."""
    if not exact_model:
        raise ValueError("Model facts require an exact execution identifier.")
    if source_model is not None and not source_model_matches(
        provider=provider, model_identifier=exact_model, source_model=source_model
    ):
        raise ValueError("Capability source does not match the exact hosting identity.")
    listing = evidence if evidence is not None else empty_provider_capability_evidence()
    source = source_model.facts if source_model is not None else None
    provenance: list[ModelFactProvenance] = []

    def choose[T](
        field: str, account: CatalogFact[T], generic: CatalogFact[T] | None
    ) -> CatalogFact[T]:
        selected = account if account.state != "absent" else generic
        if selected is None:
            selected = absent_catalog_fact()
        owner: Literal["provider", "source", "absent"] = (
            "provider"
            if account.state != "absent"
            else "source"
            if generic is not None and generic.state != "absent"
            else "absent"
        )
        provenance.append(ModelFactProvenance(field, owner, selected.state))
        return selected

    source_efforts: CatalogFact[tuple[ModelReasoningEffort, ...]] | None = None
    if source_model is not None:
        interpreted = source_model.reasoning
        values = tuple(
            item.level for item in interpreted.levels if item.support == "supported"
        )
        source_efforts = (
            CatalogFact(state="value", value=values)
            if interpreted.complete or values
            else CatalogFact(state="null", value=None)
            if source is not None and source.reasoning_efforts.state == "null"
            else absent_catalog_fact()
        )
    structured = source.response_schema if source is not None else None
    if structured is not None and structured.state == "absent":
        structured = source.native_structured_output if source is not None else None
    image = source.image_input if source is not None else None
    if image is not None and image.state == "absent":
        image = source.vision if source is not None else None
    declarations = ProviderCapabilityEvidence(
        default_input_tokens=choose(
            "default_input_tokens", listing.default_input_tokens, None
        ),
        max_input_tokens=choose(
            "max_input_tokens",
            listing.max_input_tokens,
            source.max_input_tokens if source else None,
        ),
        max_output_tokens=choose(
            "max_output_tokens",
            listing.max_output_tokens,
            source.max_output_tokens if source else None,
        ),
        input_modalities=choose(
            "input_modalities",
            listing.input_modalities,
            source.input_modalities if source else None,
        ),
        output_modalities=choose(
            "output_modalities",
            listing.output_modalities,
            source.output_modalities if source else None,
        ),
        image_input=choose("image_input", listing.image_input, image),
        video_input=choose(
            "video_input", listing.video_input, source.video_input if source else None
        ),
        function_calling=choose(
            "function_calling",
            listing.function_calling,
            source.function_calling if source else None,
        ),
        parallel_function_calling=choose(
            "parallel_function_calling",
            listing.parallel_function_calling,
            source.parallel_function_calling if source else None,
        ),
        strict_function_schema=choose(
            "strict_function_schema",
            listing.strict_function_schema,
            source.bedrock_strict_tools
            if source and provider is LLMProvider.AWS_BEDROCK
            else None,
        ),
        structured_response=choose(
            "structured_response", listing.structured_response, structured
        ),
        reasoning=choose(
            "reasoning", listing.reasoning, source.reasoning if source else None
        ),
        reasoning_efforts=choose(
            "reasoning_efforts", listing.reasoning_efforts, source_efforts
        ),
        default_reasoning_effort=choose(
            "default_reasoning_effort",
            listing.default_reasoning_effort,
            source.default_reasoning_effort if source else None,
        ),
        reasoning_summaries=choose(
            "reasoning_summaries", listing.reasoning_summaries, None
        ),
        temperature=choose(
            "temperature", listing.temperature, source.sampling if source else None
        ),
        top_p=choose("top_p", listing.top_p, source.sampling if source else None),
        top_k=choose("top_k", listing.top_k, None),
        stop_sequences=choose("stop_sequences", listing.stop_sequences, None),
        max_output_parameter=choose(
            "max_output_parameter", listing.max_output_parameter, None
        ),
        web_search=choose(
            "web_search", listing.web_search, source.web_search if source else None
        ),
        client_image_generation=choose(
            "client_image_generation", listing.client_image_generation, None
        ),
        hosted_image_generation=choose(
            "hosted_image_generation", listing.hosted_image_generation, None
        ),
        responses_api=choose("responses_api", listing.responses_api, None),
    )
    inputs = tuple(
        ResolvedModalityFact(
            modality,
            _modality_fact(
                modality,
                listing=listing.input_modalities,
                listing_flag=listing.image_input
                if modality is ModelModality.IMAGE
                else listing.video_input
                if modality is ModelModality.VIDEO
                else None,
                source_list=source.input_modalities if source else None,
                source_flag=image
                if modality is ModelModality.IMAGE
                else source.pdf_input
                if source and modality is ModelModality.PDF
                else source.audio_input
                if source and modality is ModelModality.AUDIO
                else source.video_input
                if source and modality is ModelModality.VIDEO
                else None,
            ),
        )
        for modality in ModelModality
    )
    outputs = tuple(
        ResolvedModalityFact(
            modality,
            _modality_fact(
                modality,
                listing=listing.output_modalities,
                listing_flag=None,
                source_list=source.output_modalities if source else None,
                source_flag=source.audio_output
                if source and modality is ModelModality.AUDIO
                else None,
            ),
        )
        for modality in ModelModality
    )
    diagnostics = (
        ("reasoning_efforts_conflict_with_explicit_reasoning_denial",)
        if declarations.reasoning.value is False
        and declarations.reasoning_efforts.value
        else ()
    )
    return ResolvedModelFacts(
        declarations=declarations,
        provider_declarations=listing,
        source_model=source_model,
        input_modalities=inputs,
        output_modalities=outputs,
        provenance=tuple(provenance),
        diagnostics=diagnostics,
    )
