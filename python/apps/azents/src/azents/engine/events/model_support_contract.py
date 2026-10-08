"""Admit typed request intent against the single final saved feature view."""

import dataclasses

from azents.core.llm_catalog import ModelCapabilities
from azents.core.model_capability_contract import ModelCapabilityFeature
from azents.engine.events.effective_model_request import (
    AdaptiveReasoning,
    BudgetReasoning,
    DisabledReasoning,
    EffectiveModelRequest,
    EffortReasoning,
    OmittedReasoning,
    ReasoningIntent,
)


@dataclasses.dataclass(frozen=True)
class ModelSupportContext:
    """Effective condition dimensions from one request, never a source lookup."""

    reasoning_effort: str | None
    function_tools: bool | None


@dataclasses.dataclass(frozen=True)
class ModelSupportRequest:
    """Preparatory selected controls before a physical provider request exists.

    Lowerer and operation dispatch use ``EffectiveModelRequest`` instead. This
    selection view cannot represent encoded budgets or cleared SDK overrides.
    """

    reasoning_effort: str | None
    function_tools: bool | None
    temperature: bool
    max_output_tokens: bool
    top_p: bool
    top_k: bool
    stop_sequences: bool
    parallel_function_calls: bool
    strict_function_schema: bool
    structured_response: bool
    reasoning_summary: bool


class ModelRequestFeatureError(ValueError):
    """A requested final feature is absent or its actual condition is unmet."""

    def __init__(self, feature: ModelCapabilityFeature, *, conditional: bool) -> None:
        self.feature = feature
        self.conditional = conditional
        message = (
            f"The selected request does not satisfy {feature.value} conditions."
            if conditional
            else f"The saved model capabilities do not support {feature.value}."
        )
        super().__init__(message)


def resolve_model_support_context(
    capabilities: ModelCapabilities,
    *,
    requested_effort: str | None,
    function_tools: bool | None,
    reasoning_intent: ReasoningIntent | None = None,
) -> ModelSupportContext:
    """Apply a known saved default only to genuine request omission.

    Encoded clear, adaptive thinking, or a budget without a canonical level stays
    level-less. The nullable preparatory effort is an omitted selection, whereas
    an effective provider request always supplies its explicit reasoning kind.

    :param capabilities: immutable final capability and request metadata snapshot
    :param requested_effort: canonical scalar physically selected, or omission
    :param function_tools: actual declarations, or missing preparatory context
    :param reasoning_intent: provider-encoded request kind, or preparatory omission
    :returns: condition context; does not add defaults to the wire
    """
    omitted = (
        isinstance(reasoning_intent, OmittedReasoning)
        if reasoning_intent is not None
        else requested_effort is None
    )
    effort = requested_effort
    if omitted:
        effort = capabilities.request_constraints.known_default
    return ModelSupportContext(reasoning_effort=effort, function_tools=function_tools)


def effective_model_support_context(
    capabilities: ModelCapabilities, request: EffectiveModelRequest
) -> ModelSupportContext:
    """Resolve final conditions from one normalized provider request."""
    return resolve_model_support_context(
        capabilities,
        requested_effort=request.reasoning_effort,
        function_tools=request.function_tools,
        reasoning_intent=request.reasoning,
    )


def model_support_allowed(
    feature: ModelCapabilityFeature,
    *,
    capabilities: ModelCapabilities,
    context: ModelSupportContext,
) -> bool:
    """Evaluate final feature membership and its optional request conjunction.

    :param feature: the requested feature's stable derived key
    :param capabilities: the only support authority
    :param context: actual request conditions; a missing dimension cannot satisfy it
    :returns: definite authorization, with no second or unknown support state
    """
    if not capabilities.supports(feature):
        return False
    for condition in capabilities.request_constraints.feature_conditions:
        if condition.feature != feature:
            continue
        if condition.reasoning_efforts is not None and (
            context.reasoning_effort is None
            or context.reasoning_effort not in condition.reasoning_efforts
        ):
            return False
        if condition.function_tools is not None and (
            context.function_tools is None
            or context.function_tools != condition.function_tools
        ):
            return False
    return True


def _require_feature(
    capabilities: ModelCapabilities,
    feature: ModelCapabilityFeature,
    context: ModelSupportContext,
) -> None:
    if model_support_allowed(feature, capabilities=capabilities, context=context):
        return
    raise ModelRequestFeatureError(feature, conditional=capabilities.supports(feature))


def validate_saved_model_request(
    capabilities: ModelCapabilities,
    *,
    request: ModelSupportRequest | EffectiveModelRequest,
) -> None:
    """Validate selected controls or complete effective intent without rewriting it.

    :param capabilities: immutable final support authority
    :param request: preparatory selection or normalized actual wire intent
    :raises ModelRequestFeatureError: a feature is absent or a condition is unmet
    :raises ValueError: an explicitly encoded effort is not a declared level
    """
    if isinstance(request, EffectiveModelRequest):
        context = effective_model_support_context(capabilities, request)
        controls = (
            (request.function_tools, ModelCapabilityFeature.FUNCTION_CALLING),
            (request.temperature is not None, ModelCapabilityFeature.TEMPERATURE),
            (
                request.max_output_tokens is not None,
                ModelCapabilityFeature.MAX_OUTPUT_TOKENS,
            ),
            (request.top_p is not None, ModelCapabilityFeature.TOP_P),
            (request.top_k is not None, ModelCapabilityFeature.TOP_K),
            (request.stop_sequences is not None, ModelCapabilityFeature.STOP_SEQUENCES),
            (
                request.parallel_function_calls is True,
                ModelCapabilityFeature.PARALLEL_FUNCTION_CALLS,
            ),
            (
                request.strict_function_schema,
                ModelCapabilityFeature.STRICT_FUNCTION_SCHEMA,
            ),
            (request.structured_response, ModelCapabilityFeature.STRUCTURED_RESPONSE),
            (request.summary_requested, ModelCapabilityFeature.REASONING_SUMMARIES),
        )
        effort_selected = isinstance(request.reasoning, EffortReasoning)
        reasoning_requested = isinstance(
            request.reasoning,
            EffortReasoning | BudgetReasoning | AdaptiveReasoning | DisabledReasoning,
        ) or isinstance(
            request.encoded_thinking,
            BudgetReasoning | AdaptiveReasoning | DisabledReasoning,
        )
    else:
        context = resolve_model_support_context(
            capabilities,
            requested_effort=request.reasoning_effort,
            function_tools=request.function_tools,
        )
        controls = (
            (request.function_tools is True, ModelCapabilityFeature.FUNCTION_CALLING),
            (request.temperature, ModelCapabilityFeature.TEMPERATURE),
            (request.max_output_tokens, ModelCapabilityFeature.MAX_OUTPUT_TOKENS),
            (request.top_p, ModelCapabilityFeature.TOP_P),
            (request.top_k, ModelCapabilityFeature.TOP_K),
            (request.stop_sequences, ModelCapabilityFeature.STOP_SEQUENCES),
            (
                request.parallel_function_calls,
                ModelCapabilityFeature.PARALLEL_FUNCTION_CALLS,
            ),
            (
                request.strict_function_schema,
                ModelCapabilityFeature.STRICT_FUNCTION_SCHEMA,
            ),
            (request.structured_response, ModelCapabilityFeature.STRUCTURED_RESPONSE),
            (request.reasoning_summary, ModelCapabilityFeature.REASONING_SUMMARIES),
        )
        effort_selected = request.reasoning_effort is not None
        reasoning_requested = effort_selected
    if reasoning_requested:
        _require_feature(capabilities, ModelCapabilityFeature.REASONING, context)
    if effort_selected and request.reasoning_effort not in {
        level.value for level in capabilities.reasoning.effort_levels
    }:
        raise ValueError(
            "Reasoning effort is not authorized by the saved capability snapshot"
        )
    for requested, feature in controls:
        if requested:
            _require_feature(capabilities, feature, context)
    if isinstance(request, EffectiveModelRequest):
        for tool in request.builtin_tools:
            feature = (
                ModelCapabilityFeature.WEB_SEARCH
                if tool == "web_search"
                else ModelCapabilityFeature.IMAGE_GENERATION
            )
            _require_feature(capabilities, feature, context)


def saved_structured_response_support(
    capabilities: ModelCapabilities,
    *,
    requested_effort: str | None,
    function_tools: bool,
) -> bool:
    """Evaluate response-format support independently of strict function schemas."""
    context = resolve_model_support_context(
        capabilities, requested_effort=requested_effort, function_tools=function_tools
    )
    return model_support_allowed(
        ModelCapabilityFeature.STRUCTURED_RESPONSE,
        capabilities=capabilities,
        context=context,
    )


def saved_builtin_tool_allowed(
    capabilities: ModelCapabilities,
    *,
    tool: str,
    context: ModelSupportContext,
) -> bool:
    """Authorize route-projected builtins from the same final capability view."""
    if tool == "web_search":
        feature = ModelCapabilityFeature.WEB_SEARCH
    elif tool == "image_generation":
        feature = ModelCapabilityFeature.IMAGE_GENERATION
    else:
        return False
    return model_support_allowed(feature, capabilities=capabilities, context=context)
