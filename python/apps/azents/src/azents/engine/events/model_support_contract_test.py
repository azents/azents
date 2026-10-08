"""One final feature view admits complete typed request conditions."""

import dataclasses
from typing import Literal

import pytest

from azents.core.llm_catalog import (
    ModelBuiltInToolCapabilities,
    ModelCapabilities,
    ModelParameterCapabilities,
    ModelReasoningCapabilities,
    ModelReasoningEffort,
    ModelToolCallingCapabilities,
)
from azents.core.model_capability_contract import (
    ModelCapabilityFeature,
    ModelFeatureCondition,
    ModelRequestConstraints,
)
from azents.engine.events.effective_model_request import (
    EffectiveModelRequest,
    normalize_effective_model_request,
)
from azents.engine.events.model_support_contract import (
    ModelRequestFeatureError,
    ModelSupportContext,
    ModelSupportRequest,
    effective_model_support_context,
    model_support_allowed,
    resolve_model_support_context,
    saved_builtin_tool_allowed,
    saved_structured_response_support,
    validate_saved_model_request,
)


def _capabilities(
    *,
    default: Literal["none", "high"] | None = None,
    conditions: tuple[ModelFeatureCondition, ...] = (),
) -> ModelCapabilities:
    return ModelCapabilities(
        tool_calling=ModelToolCallingCapabilities(
            supported=True, parallel_tool_calls=True, strict_json_schema=True
        ),
        reasoning=ModelReasoningCapabilities(
            supported=True,
            effort_levels=[
                ModelReasoningEffort(level)
                for level in (
                    "none",
                    "minimal",
                    "low",
                    "medium",
                    "high",
                    "xhigh",
                    "max",
                )
            ],
            summaries=True,
        ),
        structured_response=True,
        built_in_tools=ModelBuiltInToolCapabilities(
            supported=["web_search", "image_generation"]
        ),
        parameters=ModelParameterCapabilities(
            temperature=True,
            max_output_tokens=True,
            top_p=True,
            top_k=True,
            stop_sequences=True,
        ),
        request_constraints=ModelRequestConstraints(
            known_default=default, feature_conditions=conditions
        ),
    )


def _native(options: dict[str, object]) -> EffectiveModelRequest:
    return normalize_effective_model_request(
        dialect="native_responses", options=options, parameters=None, native_tools=None
    )


def _condition(feature: ModelCapabilityFeature) -> ModelFeatureCondition:
    return ModelFeatureCondition(
        feature=feature, reasoning_efforts=("none",), function_tools=None
    )


@pytest.mark.parametrize(
    "effort", ["none", "minimal", "low", "medium", "high", "xhigh", "max"]
)
def test_individual_encoded_efforts_survive_without_remapping(effort: str) -> None:
    request = _native({"reasoning": {"effort": effort}})
    validate_saved_model_request(_capabilities(), request=request)
    assert request.reasoning_effort == effort


@pytest.mark.parametrize("default", [None, "none", "high"])
def test_only_genuine_request_omission_uses_known_saved_default(
    default: Literal["none", "high"] | None,
) -> None:
    request = _native({})
    context = effective_model_support_context(_capabilities(default=default), request)
    assert context.reasoning_effort == default
    assert request.reasoning_effort is None


@pytest.mark.parametrize("override", [None, {}])
def test_explicit_reasoning_clear_never_inherits_saved_default(
    override: object,
) -> None:
    request = _native({"reasoning": override})
    context = effective_model_support_context(_capabilities(default="none"), request)
    assert context.reasoning_effort is None


@pytest.mark.parametrize(
    "thinking",
    [{"thinking_budget": 1024}, {"thinking_budget": -1}],
)
def test_google_budget_and_adaptive_do_not_acquire_default_effort(
    thinking: dict[str, object],
) -> None:
    request = normalize_effective_model_request(
        dialect="google",
        options={"google_thinking_config": thinking},
        parameters=None,
        native_tools=None,
    )
    context = effective_model_support_context(_capabilities(default="none"), request)
    assert context.reasoning_effort is None
    validate_saved_model_request(_capabilities(default="none"), request=request)


@pytest.mark.parametrize("reasoning", [None, {}, {"effort": "high"}])
def test_sampling_condition_rejects_cleared_or_unmet_effort_without_mutation(
    reasoning: object,
) -> None:
    capabilities = _capabilities(
        default="none", conditions=(_condition(ModelCapabilityFeature.TEMPERATURE),)
    )
    request = _native({"reasoning": reasoning, "temperature": 0})
    original = request
    with pytest.raises(ModelRequestFeatureError, match="temperature conditions"):
        validate_saved_model_request(capabilities, request=request)
    assert request == original
    assert request.temperature == 0


def test_sampling_condition_uses_known_default_without_putting_it_on_wire() -> None:
    capabilities = _capabilities(
        default="none", conditions=(_condition(ModelCapabilityFeature.TEMPERATURE),)
    )
    request = _native({"temperature": 0})
    validate_saved_model_request(capabilities, request=request)
    assert request.reasoning.kind == "omitted"
    assert request.reasoning_effort is None


@pytest.mark.parametrize("has_functions", [None, False, True])
def test_function_predicate_requires_actual_context_not_guess(
    has_functions: bool | None,
) -> None:
    capabilities = _capabilities(
        conditions=(
            ModelFeatureCondition(
                feature=ModelCapabilityFeature.TEMPERATURE,
                reasoning_efforts=None,
                function_tools=True,
            ),
        )
    )
    allowed = model_support_allowed(
        ModelCapabilityFeature.TEMPERATURE,
        capabilities=capabilities,
        context=ModelSupportContext(
            reasoning_effort=None, function_tools=has_functions
        ),
    )
    assert allowed is (has_functions is True)


@pytest.mark.parametrize(
    "feature",
    [
        ModelCapabilityFeature.FUNCTION_CALLING,
        ModelCapabilityFeature.TEMPERATURE,
        ModelCapabilityFeature.STRICT_FUNCTION_SCHEMA,
        ModelCapabilityFeature.STRUCTURED_RESPONSE,
    ],
)
def test_absent_feature_is_definite_denial_not_an_unknown_state(
    feature: ModelCapabilityFeature,
) -> None:
    assert (
        model_support_allowed(
            feature,
            capabilities=ModelCapabilities(),
            context=ModelSupportContext(reasoning_effort=None, function_tools=True),
        )
        is False
    )


@pytest.mark.parametrize(
    ("options", "feature"),
    [
        ({"temperature": 0}, ModelCapabilityFeature.TEMPERATURE),
        ({"max_output_tokens": 100}, ModelCapabilityFeature.MAX_OUTPUT_TOKENS),
        ({"top_p": 0}, ModelCapabilityFeature.TOP_P),
        ({"top_k": 1}, ModelCapabilityFeature.TOP_K),
        ({"stop": []}, ModelCapabilityFeature.STOP_SEQUENCES),
        ({"parallel_tool_calls": True}, ModelCapabilityFeature.PARALLEL_FUNCTION_CALLS),
        (
            {"text": {"format": {"type": "json_schema"}}},
            ModelCapabilityFeature.STRUCTURED_RESPONSE,
        ),
        (
            {"reasoning": {"summary": "auto"}},
            ModelCapabilityFeature.REASONING_SUMMARIES,
        ),
    ],
)
def test_all_requested_controls_use_the_same_final_feature_gate(
    options: dict[str, object],
    feature: ModelCapabilityFeature,
) -> None:
    with pytest.raises(ModelRequestFeatureError) as raised:
        validate_saved_model_request(ModelCapabilities(), request=_native(options))
    assert raised.value.feature == feature
    assert not raised.value.conditional


def test_null_controls_and_parallel_false_do_not_request_positive_features() -> None:
    request = _native({"temperature": None, "parallel_tool_calls": False})
    validate_saved_model_request(ModelCapabilities(), request=request)
    assert request.parallel_function_calls is False
    assert request.present_fields == frozenset({"temperature", "parallel_tool_calls"})


def test_requested_effort_requires_its_individually_declared_level() -> None:
    capabilities = _capabilities()
    capabilities.reasoning.effort_levels = [ModelReasoningEffort.HIGH]
    request = _native({"reasoning": {"effort": "max"}})
    with pytest.raises(ValueError, match="not authorized"):
        validate_saved_model_request(capabilities, request=request)
    assert request.reasoning_effort == "max"


def test_budget_requests_reasoning_feature_without_inventing_effort_declaration() -> (
    None
):
    request = normalize_effective_model_request(
        dialect="google",
        options={"google_thinking_config": {"thinking_budget": 4096}},
        parameters=None,
        native_tools=None,
    )
    capabilities = _capabilities()
    capabilities.reasoning.effort_levels = []
    validate_saved_model_request(capabilities, request=request)
    with pytest.raises(ModelRequestFeatureError) as raised:
        validate_saved_model_request(ModelCapabilities(), request=request)
    assert raised.value.feature is ModelCapabilityFeature.REASONING


def test_structured_response_and_strict_function_support_remain_independent() -> None:
    capabilities = _capabilities()
    capabilities.structured_response = False
    assert not saved_structured_response_support(
        capabilities, requested_effort=None, function_tools=False
    )
    assert model_support_allowed(
        ModelCapabilityFeature.STRICT_FUNCTION_SCHEMA,
        capabilities=capabilities,
        context=ModelSupportContext(reasoning_effort=None, function_tools=True),
    )
    capabilities.structured_response = True
    capabilities.tool_calling.strict_json_schema = False
    assert saved_structured_response_support(
        capabilities, requested_effort=None, function_tools=False
    )


@pytest.mark.parametrize("effort", [None, "none", "high"])
def test_configured_builtin_uses_actual_condition_context(effort: str | None) -> None:
    capabilities = _capabilities(
        conditions=(_condition(ModelCapabilityFeature.WEB_SEARCH),)
    )
    context = resolve_model_support_context(
        capabilities, requested_effort=effort, function_tools=False
    )
    assert saved_builtin_tool_allowed(
        capabilities, tool="web_search", context=context
    ) is (effort == "none")
    assert not saved_builtin_tool_allowed(capabilities, tool="other", context=context)


def test_preparatory_controls_are_a_selection_view_not_an_options_normalizer() -> None:
    request = ModelSupportRequest(
        reasoning_effort=None,
        function_tools=None,
        temperature=True,
        max_output_tokens=False,
        top_p=False,
        top_k=False,
        stop_sequences=False,
        parallel_function_calls=False,
        strict_function_schema=False,
        structured_response=False,
        reasoning_summary=False,
    )
    capabilities = _capabilities(
        default="none", conditions=(_condition(ModelCapabilityFeature.TEMPERATURE),)
    )
    validate_saved_model_request(capabilities, request=request)
    bad = dataclasses.replace(request, reasoning_effort="high")
    with pytest.raises(ModelRequestFeatureError):
        validate_saved_model_request(capabilities, request=bad)
    assert request.reasoning_effort is None


@pytest.mark.parametrize("tool", ["web_search", "image_generation"])
def test_raw_native_tool_body_cannot_bypass_final_builtin_membership(tool: str) -> None:
    request = normalize_effective_model_request(
        dialect="openai_responses",
        options={"extra_body": {"tools": [{"type": tool}]}},
        parameters=None,
        native_tools=None,
    )
    with pytest.raises(ModelRequestFeatureError) as raised:
        validate_saved_model_request(ModelCapabilities(), request=request)
    assert raised.value.feature.value == f"builtin:{tool}"
    validate_saved_model_request(_capabilities(), request=request)


def test_raw_native_tool_body_requires_satisfied_actual_builtin_predicate() -> None:
    request = normalize_effective_model_request(
        dialect="openai_responses",
        options={
            "openai_reasoning_effort": "high",
            "extra_body": {"tools": [{"type": "web_search"}]},
        },
        parameters=None,
        native_tools=None,
    )
    capabilities = _capabilities(
        default="none", conditions=(_condition(ModelCapabilityFeature.WEB_SEARCH),)
    )
    with pytest.raises(ModelRequestFeatureError) as raised:
        validate_saved_model_request(capabilities, request=request)
    assert raised.value.feature is ModelCapabilityFeature.WEB_SEARCH
    assert raised.value.conditional


def test_native_custom_client_declaration_requires_function_calling_membership() -> (
    None
):
    request = normalize_effective_model_request(
        dialect="native_responses",
        options={},
        parameters=None,
        native_tools=[{"type": "custom", "name": "apply_patch"}],
    )
    assert request.function_tools
    assert not request.strict_function_schema
    with pytest.raises(ModelRequestFeatureError) as raised:
        validate_saved_model_request(ModelCapabilities(), request=request)
    assert raised.value.feature is ModelCapabilityFeature.FUNCTION_CALLING


def test_native_custom_declaration_cannot_satisfy_function_absent_condition() -> None:
    capabilities = _capabilities(
        conditions=(
            ModelFeatureCondition(
                feature=ModelCapabilityFeature.TEMPERATURE,
                reasoning_efforts=None,
                function_tools=False,
            ),
        )
    )
    request = normalize_effective_model_request(
        dialect="native_responses",
        options={"temperature": 0},
        parameters=None,
        native_tools=[{"type": "custom", "name": "apply_patch"}],
    )
    with pytest.raises(ModelRequestFeatureError) as raised:
        validate_saved_model_request(capabilities, request=request)
    assert raised.value.feature is ModelCapabilityFeature.TEMPERATURE
