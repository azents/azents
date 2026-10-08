"""Apply reviewed execution-route contracts to resolved model facts."""

import dataclasses
from typing import Literal, assert_never

from pydantic_ai.profiles.google import GOOGLE_THINKING_LEVELS
from pydantic_ai.providers.google import GoogleProvider

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelModality, ModelReasoningEffort
from azents.core.model_capability_contract import (
    ModelCapabilityFeature,
    ModelFeatureCondition,
    ReasoningEffortValue,
)
from azents.core.model_catalog_source import CatalogFact
from azents.core.model_fact_resolution import ResolvedModelFacts
from azents.core.model_provider_protocol import vertex_model_family

type ProjectionProtocol = Literal[
    "native_responses", "responses", "chat", "anthropic", "google", "bedrock"
]


@dataclasses.dataclass(frozen=True)
class RouteFeatureExclusion:
    """Explain route exclusions without converting them into model denials."""

    feature: ModelCapabilityFeature
    reason: str


@dataclasses.dataclass(frozen=True)
class ResolvedRouteCapabilities:
    """The final supported set and its actual-request constraints."""

    protocol: ProjectionProtocol
    features: frozenset[ModelCapabilityFeature]
    conditions: tuple[ModelFeatureCondition, ...]
    efforts: tuple[ModelReasoningEffort, ...]
    known_default: ReasoningEffortValue | None
    exclusions: tuple[RouteFeatureExclusion, ...]


def effort_value(level: ModelReasoningEffort) -> ReasoningEffortValue:
    """Convert the stable enum without coercion or unsupported-effort aliases."""
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
        case _ as unreachable:
            assert_never(unreachable)


def projection_protocol(provider: LLMProvider, exact_model: str) -> ProjectionProtocol:
    """Use the existing hosting route, not a model-name capability prediction."""
    if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        return "native_responses"
    if provider is LLMProvider.AWS_BEDROCK:
        return "bedrock"
    if provider is LLMProvider.ANTHROPIC or (
        provider is LLMProvider.GOOGLE_VERTEX_AI
        and vertex_model_family(exact_model) == "anthropic"
    ):
        return "anthropic"
    if provider in {LLMProvider.GOOGLE_GEMINI, LLMProvider.GOOGLE_VERTEX_AI}:
        return "google"
    return "chat" if provider is LLMProvider.KIMI_OAUTH else "responses"


def google_lossless_efforts(
    *, provider: LLMProvider, model: str
) -> tuple[ModelReasoningEffort, ...]:
    """Read only Google codec domains; supplied model evidence still owns support."""
    if provider not in {LLMProvider.GOOGLE_GEMINI, LLMProvider.GOOGLE_VERTEX_AI}:
        raise ValueError("Google wire effort bounds require a Google provider route.")
    if (
        provider is LLMProvider.GOOGLE_VERTEX_AI
        and vertex_model_family(model) != "google"
    ):
        raise ValueError("Google wire effort bounds require a Google physical route.")
    # Strip only the physical resource envelope so the installed scalar codec
    # sees the same literal model identifier for native and Vertex resources.
    profile = GoogleProvider.model_profile(model.rsplit("/", maxsplit=1)[-1])
    if profile is None or profile.get("google_supports_thinking_level") is not True:
        return ()
    levels = profile.get("google_thinking_levels")
    if levels is None:
        levels = (
            GOOGLE_THINKING_LEVELS
            if profile.get("google_supports_minimal_thinking_level", True)
            else GOOGLE_THINKING_LEVELS - {"MINIMAL"}
        )
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


def _supported(declaration: CatalogFact[bool], *, contract: bool = False) -> bool:
    """Supplement omitted knowledge with verified contracts, retaining denials."""
    return declaration.value if declaration.value is not None else contract


def resolve_route_capabilities(
    *,
    provider: LLMProvider,
    exact_model: str,
    model_developer: LLMModelDeveloper | None,
    facts: ResolvedModelFacts,
) -> ResolvedRouteCapabilities:
    """Compile support potential separately from source presence and codec limits."""
    declared = facts.declarations
    source = facts.source_model.facts if facts.source_model else None
    protocol = projection_protocol(provider, exact_model)
    features: set[ModelCapabilityFeature] = set()
    exclusions: list[RouteFeatureExclusion] = []
    conditions: list[ModelFeatureCondition] = []
    # Managed coding routes supply JSON function declarations. Kimi Code's
    # coding/v1 contract and MoonshotAI/kimi-cli producer (9ab1286b8fe4e6bcd...)
    # pass tools for eligible managed models without a per-model tool flag.
    # This is not public Moonshot hosting or a model-name prediction, and does
    # not imply parallel calls, strict schemas, output schemas or hosted tools.
    coding_functions = provider in {
        LLMProvider.CHATGPT_OAUTH,
        LLMProvider.XAI_OAUTH,
        LLMProvider.KIMI_OAUTH,
    }
    # Exact model evidence: xAI grok-4.7 reference and scoped provider acceptance
    # establish these features on the API inference route used by both auth modes.
    grok47 = (
        provider in {LLMProvider.XAI, LLMProvider.XAI_OAUTH}
        and exact_model == "grok-4.7"
    )
    # Codex's common strict-schema producer grammar plus reviewed 2026-10-04
    # same-host nonce acceptance establish these exact OAuth model contracts.
    # This is support potential, not account entitlement or every-schema-subset
    # acceptance, and does not borrow facts from the public OpenAI hosting route.
    chatgpt_schemas = provider is LLMProvider.CHATGPT_OAUTH and exact_model in {
        "gpt-6-astra",
        "gpt-6.1-sol",
    }
    function_contract = coding_functions or grok47
    if (
        provider is LLMProvider.KIMI_OAUTH
        and declared.function_calling.value is not True
        and source is not None
        and source.function_calling.value is False
    ):
        function_contract = False
        exclusions.append(
            RouteFeatureExclusion(
                ModelCapabilityFeature.FUNCTION_CALLING,
                "The exact coding source denies function calling and no positive "
                "provider declaration overrides it; the route contract is withheld.",
            )
        )
    function = _supported(declared.function_calling, contract=function_contract)
    if function:
        features.add(ModelCapabilityFeature.FUNCTION_CALLING)
    parallel = function and _supported(
        declared.parallel_function_calling, contract=grok47
    )
    strict = function and _supported(
        declared.strict_function_schema,
        contract=grok47 or chatgpt_schemas or provider is LLMProvider.OPENAI,
    )
    if parallel:
        features.add(ModelCapabilityFeature.PARALLEL_FUNCTION_CALLS)
    if strict:
        features.add(ModelCapabilityFeature.STRICT_FUNCTION_SCHEMA)
    if _supported(declared.structured_response, contract=grok47 or chatgpt_schemas):
        features.add(ModelCapabilityFeature.STRUCTURED_RESPONSE)
    if protocol == "bedrock" and ModelCapabilityFeature.STRUCTURED_RESPONSE in features:
        features.remove(ModelCapabilityFeature.STRUCTURED_RESPONSE)
        exclusions.append(
            RouteFeatureExclusion(
                ModelCapabilityFeature.STRUCTURED_RESPONSE,
                "The Converse lowerer does not encode native response schemas.",
            )
        )

    efforts = (
        declared.reasoning_efforts.value
        if declared.reasoning_efforts.value is not None
        else (
            ModelReasoningEffort.LOW,
            ModelReasoningEffort.MEDIUM,
            ModelReasoningEffort.HIGH,
            ModelReasoningEffort.XHIGH,
        )
        if grok47
        else ()
    )
    reasoning = _supported(declared.reasoning, contract=grok47 or bool(efforts))
    if reasoning:
        features.add(ModelCapabilityFeature.REASONING)
    else:
        efforts = ()
    allowed = set(ModelReasoningEffort)
    if provider is LLMProvider.KIMI_OAUTH:
        # The Chat lowerer has no lossless selected-effort mapping to Kimi's
        # reasoning_effort field. Preserve model reasoning and raw efforts
        # without advertising scalar controls or creating effort/budget aliases.
        allowed = set()
    elif protocol == "google":
        # Declared facts own support; this intersects only the implemented
        # lossless scalar codec domain. Budget-only models retain reasoning
        # support without acquiring an invented scalar effort or budget alias.
        allowed = set(google_lossless_efforts(provider=provider, model=exact_model))
    elif protocol == "anthropic":
        allowed -= {ModelReasoningEffort.NONE, ModelReasoningEffort.MINIMAL}
    elif protocol == "bedrock":
        allowed = (
            set(ModelReasoningEffort)
            - {ModelReasoningEffort.NONE, ModelReasoningEffort.MINIMAL}
            if model_developer is LLMModelDeveloper.ANTHROPIC
            else set()
        )
    efforts = tuple(
        level for level in ModelReasoningEffort if level in efforts and level in allowed
    )
    default = (
        declared.default_reasoning_effort.value
        if declared.default_reasoning_effort.value is not None
        else ModelReasoningEffort.HIGH
        if grok47 and declared.default_reasoning_effort.state == "absent"
        else None
    )
    if (
        not reasoning
        or default not in allowed
        or (declared.reasoning_efforts.state == "value" and default not in efforts)
    ):
        default = None
    if _supported(declared.reasoning_summaries, contract=grok47):
        features.add(ModelCapabilityFeature.REASONING_SUMMARIES)

    scalar_facts = (
        (ModelCapabilityFeature.TEMPERATURE, declared.temperature, grok47),
        (ModelCapabilityFeature.TOP_P, declared.top_p, grok47),
        (ModelCapabilityFeature.TOP_K, declared.top_k, False),
        (ModelCapabilityFeature.STOP_SEQUENCES, declared.stop_sequences, False),
        (ModelCapabilityFeature.MAX_OUTPUT_TOKENS, declared.max_output_parameter, True),
    )
    for feature, declaration, default_contract in scalar_facts:
        if _supported(declaration, contract=default_contract):
            features.add(feature)
    for feature in (
        ModelCapabilityFeature.TOP_K,
        ModelCapabilityFeature.STOP_SEQUENCES,
    ):
        unsupported_codec = protocol in {"native_responses", "responses"} or (
            protocol == "chat" and feature is ModelCapabilityFeature.TOP_K
        )
        if unsupported_codec and feature in features:
            features.remove(feature)
            exclusions.append(
                RouteFeatureExclusion(
                    feature, "The selected lowerer does not encode this parameter."
                )
            )
    reviewed_non_none_sampling = provider in {
        LLMProvider.OPENAI,
        LLMProvider.CHATGPT_OAUTH,
    } and exact_model in {"gpt-6-astra", "gpt-6.1-sol"}
    if protocol == "native_responses" and reasoning and reviewed_non_none_sampling:
        for feature in (
            ModelCapabilityFeature.TEMPERATURE,
            ModelCapabilityFeature.TOP_P,
        ):
            if feature not in features:
                continue
            if ModelReasoningEffort.NONE in efforts:
                conditions.append(
                    ModelFeatureCondition(
                        feature=feature,
                        reasoning_efforts=("none",),
                        function_tools=None,
                    )
                )
            else:
                features.remove(feature)
                exclusions.append(
                    RouteFeatureExclusion(
                        feature,
                        "Sampling requires the none effort, which is not supported "
                        "by this native reasoning route.",
                    )
                )

    input_media: set[ModelModality] = set()
    for item in facts.input_modalities:
        media_contract = item.modality is ModelModality.TEXT or (
            item.modality is ModelModality.IMAGE
            and (provider is LLMProvider.CHATGPT_OAUTH or grok47)
        )
        if not _supported(item.declaration, contract=media_contract):
            continue
        feature = ModelCapabilityFeature(f"input:{item.modality.value}")
        if item.modality in {
            ModelModality.TEXT,
            ModelModality.IMAGE,
            ModelModality.PDF,
        }:
            input_media.add(item.modality)
            features.add(feature)
        else:
            exclusions.append(
                RouteFeatureExclusion(
                    feature, "The product does not implement this rich-input route."
                )
            )
    pdf = next(
        item.declaration
        for item in facts.input_modalities
        if item.modality is ModelModality.PDF
    )
    if (
        protocol == "native_responses"
        and ModelModality.IMAGE in input_media
        and pdf.value is None
        and facts.provider_declarations.input_modalities.state == "absent"
    ):
        features.add(ModelCapabilityFeature.INPUT_PDF)
    for item in facts.output_modalities:
        image_contract = (
            protocol == "google"
            and item.modality is ModelModality.IMAGE
            and declared.hosted_image_generation.value is True
        )
        if not _supported(
            item.declaration,
            contract=item.modality is ModelModality.TEXT or image_contract,
        ):
            continue
        feature = ModelCapabilityFeature(f"output:{item.modality.value}")
        if item.modality is ModelModality.TEXT or (
            protocol == "google" and item.modality is ModelModality.IMAGE
        ):
            features.add(feature)
        else:
            exclusions.append(
                RouteFeatureExclusion(
                    feature,
                    "This text-model route does not implement this output form.",
                )
            )

    # xAI's exact grok-4.7 model contract and /developers/tools/web-search
    # document hosted web_search on its Responses inference route. Discovery
    # omissions do not deny it; explicit declarations still own denials.
    web_contract = provider is LLMProvider.CHATGPT_OAUTH or grok47
    if (
        grok47
        and declared.web_search.value is not True
        and source is not None
        and source.web_search.value is False
    ):
        web_contract = False
        exclusions.append(
            RouteFeatureExclusion(
                ModelCapabilityFeature.WEB_SEARCH,
                "The exact xAI source denies hosted web search and no positive "
                "provider declaration overrides it; the route contract is withheld.",
            )
        )
    web = _supported(declared.web_search, contract=web_contract)
    if web and protocol not in {"bedrock", "chat"}:
        features.add(ModelCapabilityFeature.WEB_SEARCH)
    elif web:
        exclusions.append(
            RouteFeatureExclusion(
                ModelCapabilityFeature.WEB_SEARCH,
                "This route has no maintained hosted web-search owner.",
            )
        )
    if provider in {
        LLMProvider.OPENAI,
        LLMProvider.CHATGPT_OAUTH,
        LLMProvider.XAI,
        LLMProvider.XAI_OAUTH,
    }:
        client_image_route = (
            source is None
            or source.mode.value is None
            or source.mode.value in {"chat", "responses"}
        )
        # This installed client function tool is authorized by the inference
        # route, not predicted from a model name or a hosted image endpoint.
        if (
            function
            and client_image_route
            and _supported(declared.client_image_generation, contract=True)
        ):
            features.add(ModelCapabilityFeature.IMAGE_GENERATION)
            conditions.append(
                ModelFeatureCondition(
                    feature=ModelCapabilityFeature.IMAGE_GENERATION,
                    reasoning_efforts=None,
                    function_tools=True,
                )
            )
    elif protocol == "google" and ModelCapabilityFeature.OUTPUT_IMAGE in features:
        if _supported(declared.hosted_image_generation, contract=True):
            features.add(ModelCapabilityFeature.IMAGE_GENERATION)
        else:
            features.remove(ModelCapabilityFeature.OUTPUT_IMAGE)
            exclusions.append(
                RouteFeatureExclusion(
                    ModelCapabilityFeature.OUTPUT_IMAGE,
                    "Hosted image generation was explicitly denied by the provider.",
                )
            )
    return ResolvedRouteCapabilities(
        protocol=protocol,
        features=frozenset(features),
        conditions=tuple(conditions),
        efforts=efforts,
        known_default=effort_value(default) if default is not None else None,
        exclusions=tuple(exclusions),
    )
