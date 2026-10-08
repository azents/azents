"""Compile one final capability view from scoped facts and route constraints."""

import dataclasses

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import (
    ModelBuiltInToolCapabilities,
    ModelCapabilities,
    ModelCompatibilityCapabilities,
    ModelContextWindow,
    ModelModalities,
    ModelModality,
    ModelParameterCapabilities,
    ModelReasoningCapabilities,
    ModelReasoningEffort,
    ModelToolCallingCapabilities,
)
from azents.core.model_capability_contract import (
    ModelCapabilityFeature,
    ModelRequestConstraints,
)
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_catalog_source import CatalogFact, CatalogSourceModel
from azents.core.model_fact_resolution import ResolvedModelFacts, resolve_model_facts
from azents.core.route_capability_constraints import (
    RouteFeatureExclusion,
    resolve_route_capabilities,
)
from azents.core.route_capability_constraints import (
    google_lossless_efforts as _google_lossless_efforts,
)

CAPABILITY_PROJECTION_REVISION = "4"


@dataclasses.dataclass(frozen=True)
class CompiledModelCapabilities:
    """Keep source diagnostics outside the definitive supported-feature contract."""

    capabilities: ModelCapabilities
    facts: ResolvedModelFacts
    route_exclusions: tuple[RouteFeatureExclusion, ...]


def _positive(declaration: CatalogFact[int]) -> int | None:
    """Keep current positive-limit policy without changing captured source facts."""
    value = declaration.value
    return value if value is not None and value > 0 else None


def compile_model_capabilities(
    *,
    provider: LLMProvider,
    exact_model: str,
    source_model: CatalogSourceModel | None,
    evidence: ProviderCapabilityEvidence | None,
    model_developer: LLMModelDeveloper | None,
) -> CompiledModelCapabilities:
    """Resolve model facts, apply actual route constraints, then publish once."""
    facts = resolve_model_facts(
        provider=provider,
        exact_model=exact_model,
        source_model=source_model,
        evidence=evidence,
    )
    route = resolve_route_capabilities(
        provider=provider,
        exact_model=exact_model,
        model_developer=model_developer,
        facts=facts,
    )
    supported = route.features
    declared = facts.declarations
    capabilities = ModelCapabilities(
        context_window=ModelContextWindow(
            default_input_tokens=_positive(declared.default_input_tokens),
            max_input_tokens=_positive(declared.max_input_tokens),
            max_output_tokens=_positive(declared.max_output_tokens),
        ),
        modalities=ModelModalities(
            input=[
                modality
                for modality in ModelModality
                if ModelCapabilityFeature(f"input:{modality.value}") in supported
            ],
            output=[
                modality
                for modality in ModelModality
                if ModelCapabilityFeature(f"output:{modality.value}") in supported
            ],
        ),
        tool_calling=ModelToolCallingCapabilities(
            supported=ModelCapabilityFeature.FUNCTION_CALLING in supported,
            parallel_tool_calls=ModelCapabilityFeature.PARALLEL_FUNCTION_CALLS
            in supported,
            strict_json_schema=ModelCapabilityFeature.STRICT_FUNCTION_SCHEMA
            in supported,
        ),
        structured_response=ModelCapabilityFeature.STRUCTURED_RESPONSE in supported,
        reasoning=ModelReasoningCapabilities(
            supported=ModelCapabilityFeature.REASONING in supported,
            effort_levels=list(route.efforts),
            summaries=ModelCapabilityFeature.REASONING_SUMMARIES in supported,
        ),
        parameters=ModelParameterCapabilities(
            temperature=ModelCapabilityFeature.TEMPERATURE in supported,
            max_output_tokens=ModelCapabilityFeature.MAX_OUTPUT_TOKENS in supported,
            top_p=ModelCapabilityFeature.TOP_P in supported,
            top_k=ModelCapabilityFeature.TOP_K in supported,
            stop_sequences=ModelCapabilityFeature.STOP_SEQUENCES in supported,
        ),
        built_in_tools=ModelBuiltInToolCapabilities(
            supported=[
                tool
                for tool, feature in (
                    ("web_search", ModelCapabilityFeature.WEB_SEARCH),
                    ("image_generation", ModelCapabilityFeature.IMAGE_GENERATION),
                )
                if feature in supported
            ],
        ),
        compatibility=ModelCompatibilityCapabilities(
            provider_family=provider.value,
            responses_api=declared.responses_api.value
            if declared.responses_api.state != "absent"
            else route.protocol in {"native_responses", "responses"},
        ),
        request_constraints=ModelRequestConstraints(
            known_default=route.known_default, feature_conditions=route.conditions
        ),
    )
    if capabilities.supported_features() != supported:
        raise ValueError(
            "Final capability compilation produced inconsistent feature membership."
        )
    return CompiledModelCapabilities(capabilities, facts, route.exclusions)


def compile_stored_choice(
    *,
    provider: LLMProvider,
    exact_model: str,
    evidence: ProviderCapabilityEvidence | None,
    source_model: CatalogSourceModel | None,
    model_developer: LLMModelDeveloper | None,
) -> CompiledModelCapabilities:
    """Recompile captured declarations without legacy boolean or mutable lookups.

    The caller decodes provider metadata at ingress and fences captured inputs
    at its publication or new-operation boundary. Historical capabilities are
    deliberately not an input: they cannot replace actual provider/source facts.
    """
    return compile_model_capabilities(
        provider=provider,
        exact_model=exact_model,
        source_model=source_model,
        evidence=evidence,
        model_developer=model_developer,
    )


def project_capabilities(
    *,
    provider: LLMProvider,
    exact_model: str,
    source_model: CatalogSourceModel | None,
    evidence: ProviderCapabilityEvidence | None,
    model_developer: LLMModelDeveloper | None,
) -> ModelCapabilities:
    """Return the definitive descriptor through the existing publication boundary."""
    return compile_model_capabilities(
        provider=provider,
        exact_model=exact_model,
        source_model=source_model,
        evidence=evidence,
        model_developer=model_developer,
    ).capabilities


def google_lossless_efforts(
    *, provider: LLMProvider, model: str
) -> tuple[ModelReasoningEffort, ...]:
    """Retain the reviewed public codec helper while separating its ownership."""
    return _google_lossless_efforts(provider=provider, model=model)
