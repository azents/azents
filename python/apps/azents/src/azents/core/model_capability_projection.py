"""Presence-aware model facts bounded by implemented Azents request contracts."""

from typing import Literal, NamedTuple

from pydantic_ai.providers.google import GoogleProvider

from azents.core.builtin_tools import supported_builtin_capabilities
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
    BuiltinToolSupport,
    CapabilitySupport,
    DefaultEffortEvidence,
    EffortDeclaration,
    ModalitySupport,
    ModelCapabilityContract,
    ParameterSupport,
    ReasoningEffortValue,
    ReasoningSupport,
)
from azents.core.model_capability_evidence import (
    ProviderCapabilityEvidence,
    empty_provider_capability_evidence,
)
from azents.core.model_catalog_identity import source_model_matches
from azents.core.model_catalog_source import (
    CatalogFact,
    CatalogSourceFacts,
    CatalogSourceModel,
)

CAPABILITY_PROJECTION_REVISION = "2"
type ProjectionProtocol = Literal[
    "native_responses", "responses", "chat", "anthropic", "google", "bedrock"
]


class _ProjectedModalities(NamedTuple):
    input: tuple[ModalitySupport, ...]
    output: tuple[ModalitySupport, ...]


def _unknown() -> CapabilitySupport:
    return CapabilitySupport(state="unknown", origin=None, predicate=None)


def _derived(value: bool) -> CapabilitySupport:
    return CapabilitySupport(
        state="supported" if value else "unsupported",
        origin="contract_derived",
        predicate=None,
    )


def _prefer[T](
    listing: CatalogFact[T], source: CatalogFact[T] | None
) -> CatalogFact[T] | None:
    """Only an absent declaration may be enriched; null remains unknown."""
    return listing if listing.state != "absent" else source


def _support(fact: CatalogFact[bool] | None) -> CapabilitySupport:
    if fact is None or fact.value is None:
        return _unknown()
    return CapabilitySupport(
        state="supported" if fact.value else "unsupported",
        origin="explicit",
        predicate=None,
    )


def _positive(fact: CatalogFact[int] | None) -> int | None:
    return (
        fact.value
        if fact is not None and fact.value is not None and fact.value > 0
        else None
    )


def _route(
    provider: LLMProvider, model_developer: LLMModelDeveloper | None
) -> ProjectionProtocol:
    if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        return "native_responses"
    if provider == LLMProvider.AWS_BEDROCK:
        return "bedrock"
    if provider == LLMProvider.ANTHROPIC or (
        provider == LLMProvider.GOOGLE_VERTEX_AI
        and model_developer == LLMModelDeveloper.ANTHROPIC
    ):
        return "anthropic"
    if provider in {LLMProvider.GOOGLE_GEMINI, LLMProvider.GOOGLE_VERTEX_AI}:
        return "google"
    return "chat" if provider == LLMProvider.KIMI_OAUTH else "responses"


def _effort_value(level: ModelReasoningEffort) -> ReasoningEffortValue:
    """Convert the stable enum to the semantic contract's wire vocabulary."""
    match level:
        case ModelReasoningEffort.NONE:
            return "none"
        case ModelReasoningEffort.MINIMAL:
            return "minimal"
        case ModelReasoningEffort.LOW:
            return "low"
        case ModelReasoningEffort.MEDIUM:
            return "medium"
        case ModelReasoningEffort.HIGH:
            return "high"
        case ModelReasoningEffort.XHIGH:
            return "xhigh"
        case ModelReasoningEffort.MAX:
            return "max"


def _reasoning(
    *,
    model: CatalogSourceModel | None,
    evidence: ProviderCapabilityEvidence,
    route: ProjectionProtocol,
    model_developer: LLMModelDeveloper | None,
    google_efforts: tuple[ModelReasoningEffort, ...] | None,
) -> ReasoningSupport:
    facts = model.facts if model is not None else None
    listing_efforts = evidence.reasoning_efforts
    support = _support(_prefer(evidence.reasoning, facts.reasoning if facts else None))
    declarations: tuple[EffortDeclaration, ...]
    complete = False
    if evidence.reasoning.value is False:
        declarations = ()
        complete = True
    elif listing_efforts.state == "value":
        declared = listing_efforts.value or ()
        declarations = tuple(
            EffortDeclaration(
                level=_effort_value(level),
                state="supported" if level in declared else "unsupported",
                origin="explicit",
            )
            for level in ModelReasoningEffort
        )
        complete = True
        if declared and evidence.reasoning.value is None:
            # The exact provider's positive array resolves weaker source conflicts.
            support = _derived(True)
    elif listing_efforts.state == "null":
        declarations = ()
    elif model is not None:
        declarations = tuple(
            EffortDeclaration(
                level=_effort_value(item.level),
                state=item.support,
                origin=(
                    None
                    if item.origin == "unknown"
                    else "contract_derived"
                    if item.origin == "source_contract"
                    else "explicit"
                ),
            )
            for item in model.reasoning.levels
        )
        complete = model.reasoning.complete
    else:
        declarations = ()
    if (
        support.state == "unknown"
        and evidence.reasoning.state == "absent"
        and any(declaration.state == "supported" for declaration in declarations)
    ):
        support = _derived(True)
    if support.state in {"unknown", "unsupported"}:
        declarations = tuple(item for item in declarations if item.state != "supported")
    # These are actual lowerer domains, not model-profile effort predictions.
    allowed = set(ModelReasoningEffort)
    if route == "google":
        allowed = set(google_efforts or ())
    elif route == "anthropic":
        allowed -= {ModelReasoningEffort.NONE, ModelReasoningEffort.MINIMAL}
    elif route == "bedrock":
        allowed = (
            {
                ModelReasoningEffort.LOW,
                ModelReasoningEffort.MEDIUM,
                ModelReasoningEffort.HIGH,
                ModelReasoningEffort.XHIGH,
                ModelReasoningEffort.MAX,
            }
            if model_developer == LLMModelDeveloper.ANTHROPIC
            else set()
        )
    declarations = tuple(
        EffortDeclaration(
            level=item.level, state="unsupported", origin="contract_derived"
        )
        if item.state == "supported" and ModelReasoningEffort(item.level) not in allowed
        else item
        for item in declarations
    )
    meaningful = any(item.state != "unknown" for item in declarations)
    completeness = "complete" if complete else "partial" if meaningful else "unknown"
    if completeness == "unknown":
        declarations = ()
    default_fact = _prefer(
        evidence.default_reasoning_effort,
        facts.default_reasoning_effort if facts else None,
    )
    default = None
    if default_fact is not None and default_fact.value is not None:
        value = _effort_value(default_fact.value)
        denied = any(
            item.level == value and item.state == "unsupported" for item in declarations
        )
        accepted = any(
            item.level == value and item.state == "supported" for item in declarations
        )
        if (
            support.state != "unsupported"
            and not denied
            and default_fact.value in allowed
            and (not complete or accepted)
        ):
            default = DefaultEffortEvidence(level=value, origin="explicit")
    return ReasoningSupport(
        support=support,
        completeness=completeness,
        efforts=declarations,
        default_effort=default,
    )


def google_lossless_efforts(
    *, provider: LLMProvider, model: str
) -> tuple[ModelReasoningEffort, ...]:
    """Bound scalar efforts to explicitly declared, unchanged Google wire levels.

    This reads the retained adapter's encoding traits, not source support. Sparse
    profile defaults and invented effort-to-token budgets do not prove a lossless
    mapping. Native OpenAI never enters this provider-specific helper.
    """
    if provider not in {LLMProvider.GOOGLE_GEMINI, LLMProvider.GOOGLE_VERTEX_AI}:
        raise ValueError("Google wire effort bounds require a Google provider route.")
    profile = GoogleProvider.model_profile(model)
    if profile is None or profile.get("google_supports_thinking_level") is not True:
        return ()
    levels = profile.get("google_thinking_levels")
    if not isinstance(levels, frozenset):
        return ()
    return tuple(
        effort
        for effort in (
            ModelReasoningEffort.MINIMAL,
            ModelReasoningEffort.LOW,
            ModelReasoningEffort.MEDIUM,
            ModelReasoningEffort.HIGH,
        )
        if effort.value.upper() in levels
    )


def _modality_support(
    *,
    modality: ModelModality,
    listing: CatalogFact[tuple[str, ...]],
    listing_flag: CatalogFact[bool] | None,
    source_list: CatalogFact[tuple[str, ...]] | None,
    source_flag: CatalogFact[bool] | None,
    implemented: bool,
) -> CapabilitySupport:
    if not implemented:
        return _derived(False)
    if listing.state == "value":
        return CapabilitySupport(
            state="supported" if modality in (listing.value or ()) else "unsupported",
            origin="explicit",
            predicate=None,
        )
    if listing_flag is not None and listing_flag.state != "absent":
        return _support(listing_flag)
    if listing.state == "null":
        return _unknown()
    if source_flag is not None and source_flag.value is False:
        return _support(source_flag)
    if source_list is not None and source_list.state != "absent":
        if source_list.value is None:
            return _unknown()
        return CapabilitySupport(
            state="supported" if modality.value in source_list.value else "unsupported",
            origin="explicit",
            predicate=None,
        )
    if source_flag is not None and source_flag.state != "absent":
        return _support(source_flag)
    return _derived(True) if modality == ModelModality.TEXT else _unknown()


def _media(
    *,
    facts: CatalogSourceFacts | None,
    evidence: ProviderCapabilityEvidence,
    route: ProjectionProtocol,
) -> _ProjectedModalities:
    image_flag = facts.image_input if facts else None
    if image_flag is not None and image_flag.state == "absent":
        image_flag = facts.vision if facts else None
    input_support = {
        modality: _modality_support(
            modality=modality,
            listing=evidence.input_modalities,
            listing_flag=(
                evidence.image_input
                if modality == ModelModality.IMAGE
                else evidence.video_input
                if modality == ModelModality.VIDEO
                else None
            ),
            source_list=facts.input_modalities if facts else None,
            source_flag=(
                image_flag
                if modality == ModelModality.IMAGE
                else facts.pdf_input
                if facts and modality == ModelModality.PDF
                else None
            ),
            implemented=modality
            in {ModelModality.TEXT, ModelModality.IMAGE, ModelModality.PDF},
        )
        for modality in ModelModality
    }
    # Native visual PDF is an implemented file route, not an audio/video modality.
    if (
        route == "native_responses"
        and input_support[ModelModality.IMAGE].enabled
        and input_support[ModelModality.PDF].state == "unknown"
        and evidence.input_modalities.state == "absent"
    ):
        input_support[ModelModality.PDF] = _derived(True)
    return _ProjectedModalities(
        tuple(
            ModalitySupport(modality=modality.value, support=value)
            for modality, value in input_support.items()
        ),
        tuple(
            ModalitySupport(
                modality=modality.value,
                support=_modality_support(
                    modality=modality,
                    listing=evidence.output_modalities,
                    listing_flag=None,
                    source_list=facts.output_modalities if facts else None,
                    source_flag=None,
                    implemented=modality == ModelModality.TEXT,
                ),
            )
            for modality in ModelModality
        ),
    )


def project_capabilities(
    *,
    provider: LLMProvider,
    exact_model: str,
    source_model: CatalogSourceModel | None,
    evidence: ProviderCapabilityEvidence | None,
    model_developer: LLMModelDeveloper | None,
) -> ModelCapabilities:
    """Project exact-scoped descriptive facts without profile or mutable lookups.

    :param exact_model: unchanged execution identifier from the identity adapter
    :param source_model: exact-scoped source match, or absent evidence
    :param evidence: typed declarations actually supplied by the provider listing
    """
    if not exact_model:
        raise ValueError("Capability projection requires an exact model identifier.")
    if source_model is not None and not source_model_matches(
        provider=provider, model_identifier=exact_model, source_model=source_model
    ):
        raise ValueError("Capability source does not match the exact hosting identity.")
    listing = evidence if evidence is not None else empty_provider_capability_evidence()
    facts = source_model.facts if source_model is not None else None
    route = _route(provider, model_developer)
    function = _support(
        _prefer(listing.function_calling, facts.function_calling if facts else None)
    )
    parallel = _support(
        _prefer(
            listing.parallel_function_calling,
            facts.parallel_function_calling if facts else None,
        )
    )
    strict_source = facts.bedrock_strict_tools if facts and route == "bedrock" else None
    strict = _support(_prefer(listing.strict_function_schema, strict_source))
    if (
        listing.strict_function_schema.state == "absent"
        and provider == LLMProvider.OPENAI
        and function.enabled
    ):
        strict = _derived(True)
    if not function.enabled:
        if parallel.enabled:
            parallel = _derived(False)
        if strict.enabled:
            strict = _derived(False)
    structure_fact = facts.response_schema if facts else None
    if structure_fact is not None and structure_fact.state == "absent":
        structure_fact = facts.native_structured_output if facts else None
    structured = _support(_prefer(listing.structured_response, structure_fact))
    if route == "bedrock":
        # The installed Converse path does not lower native response schemas.
        structured = _derived(False)
    reasoning = _reasoning(
        model=source_model,
        evidence=listing,
        route=route,
        model_developer=model_developer,
        google_efforts=(
            google_lossless_efforts(provider=provider, model=exact_model)
            if route == "google"
            else None
        ),
    )
    summaries = _support(listing.reasoning_summaries)
    temperature = _support(
        _prefer(listing.temperature, facts.sampling if facts else None)
    )
    top_p = _support(_prefer(listing.top_p, facts.sampling if facts else None))
    top_k = _support(listing.top_k)
    stop = _support(listing.stop_sequences)
    if route in {"native_responses", "responses"}:
        stop = _derived(False)
        top_k = _derived(False)
    elif route == "chat":
        top_k = _derived(False)
    max_output = (
        _derived(True)
        if listing.max_output_parameter.state == "absent"
        else _support(listing.max_output_parameter)
    )
    web = _support(_prefer(listing.web_search, facts.web_search if facts else None))
    if provider == LLMProvider.CHATGPT_OAUTH and listing.web_search.state == "absent":
        # Codex route policy supports search for every account-visible model.
        # Optional generic source metadata does not own that provider contract.
        web = _derived(True)
    elif route in {"bedrock", "chat"}:
        web = _derived(False)
    client_image = provider in {
        LLMProvider.OPENAI,
        LLMProvider.CHATGPT_OAUTH,
        LLMProvider.XAI,
        LLMProvider.XAI_OAUTH,
    }
    if client_image:
        registry_tools = supported_builtin_capabilities(
            provider=provider,
            model_identifier=exact_model,
            metadata={
                "mode": facts.mode.value
                if facts and facts.mode.value is not None
                else "chat",
                # This gates the existing client executor's function transport,
                # not the unknown generic model-function support declaration.
                "supports_function_calling": function.state != "unsupported",
                "supported_builtin_tools": (
                    ["image_generation"]
                    if listing.client_image_generation.value is True
                    else []
                ),
            },
        )
        image = (
            _support(listing.client_image_generation)
            if listing.client_image_generation.state != "absent"
            else _derived(True)
            if "image_generation" in registry_tools
            else _unknown()
        )
        if function.state == "unsupported" and image.enabled:
            image = _derived(False)
    elif route == "google":
        image = _support(listing.hosted_image_generation)
    else:
        image = _derived(False)
    inputs, outputs = _media(facts=facts, evidence=listing, route=route)
    contract = ModelCapabilityContract(
        version=2,
        reasoning=reasoning,
        reasoning_summaries=summaries,
        function_calling=function,
        parallel_function_calls=parallel,
        strict_function_schema=strict,
        structured_response=structured,
        parameters=ParameterSupport(
            temperature=temperature,
            max_output_tokens=max_output,
            top_p=top_p,
            top_k=top_k,
            stop_sequences=stop,
        ),
        input_modalities=inputs,
        output_modalities=outputs,
        built_in_tools=(
            BuiltinToolSupport(tool="web_search", support=web),
            BuiltinToolSupport(tool="image_generation", support=image),
        ),
    )
    return ModelCapabilities(
        context_window=ModelContextWindow(
            default_input_tokens=_positive(listing.default_input_tokens),
            max_input_tokens=_positive(
                _prefer(
                    listing.max_input_tokens, facts.max_input_tokens if facts else None
                )
            ),
            max_output_tokens=_positive(
                _prefer(
                    listing.max_output_tokens,
                    facts.max_output_tokens if facts else None,
                )
            ),
        ),
        modalities=ModelModalities(
            input=[
                ModelModality(item.modality) for item in inputs if item.support.enabled
            ],
            output=[
                ModelModality(item.modality) for item in outputs if item.support.enabled
            ],
        ),
        tool_calling=ModelToolCallingCapabilities(
            supported=function.enabled,
            parallel_tool_calls=parallel.nullable_enabled,
            strict_json_schema=strict.nullable_enabled,
        ),
        reasoning=ModelReasoningCapabilities(
            supported=reasoning.support.enabled,
            effort_levels=[
                ModelReasoningEffort(level) for level in reasoning.enabled_efforts
            ],
            summaries=summaries.nullable_enabled,
        ),
        built_in_tools=ModelBuiltInToolCapabilities(
            supported=[
                item.tool for item in contract.built_in_tools if item.support.enabled
            ]
        ),
        parameters=ModelParameterCapabilities(
            temperature=temperature.enabled,
            max_output_tokens=max_output.enabled,
            top_p=top_p.enabled,
            top_k=top_k.enabled,
            stop_sequences=stop.enabled,
        ),
        compatibility=ModelCompatibilityCapabilities(
            provider_family=provider.value,
            responses_api=(
                listing.responses_api.value
                if listing.responses_api.state != "absent"
                else route in {"native_responses", "responses"}
            ),
        ),
        semantic_contract=contract,
    )
