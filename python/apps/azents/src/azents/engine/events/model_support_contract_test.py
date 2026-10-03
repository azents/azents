"""Request-local validation of saved semantic support and historical snapshots."""

import dataclasses
from typing import Literal

import pytest
from google.genai.types import ThinkingLevel
from pydantic_ai.profiles.google import GoogleModelProfile
from pydantic_ai.providers.google import GoogleProvider

from azents.core.enums import LLMProvider
from azents.core.llm_catalog import (
    ModelCapabilities,
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
    ReasoningSupport,
    SupportPredicate,
)
from azents.engine.events.model_support_contract import (
    ModelSupportContext,
    ModelSupportRequest,
    decode_model_support_options,
    model_support_allowed,
    model_support_request_from_options,
    resolve_model_support_context,
    saved_builtin_tool_allowed,
    saved_structured_response_support,
    validate_saved_model_request,
)
from azents.engine.events.openai_responses import (
    OpenAIResponsesLowerer,
    OpenAIResponsesRequest,
)
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.run.types import BuiltinToolSpec


def supported() -> CapabilitySupport:
    return CapabilitySupport(state="supported", origin="explicit", predicate=None)


def unknown() -> CapabilitySupport:
    return CapabilitySupport(state="unknown", origin=None, predicate=None)


def unsupported() -> CapabilitySupport:
    return CapabilitySupport(state="unsupported", origin="explicit", predicate=None)


def conditional() -> CapabilitySupport:
    return CapabilitySupport(
        state="conditional",
        origin="explicit",
        predicate=SupportPredicate(reasoning_efforts=("none",), function_tools=None),
    )


def semantic_capabilities(
    *,
    default_none: bool,
    temperature: CapabilitySupport,
    structured: CapabilitySupport,
) -> ModelCapabilities:
    reasoning = ReasoningSupport(
        support=supported(),
        completeness="complete",
        efforts=tuple(
            EffortDeclaration(level=level, state="supported", origin="explicit")
            for level in ("none", "high", "xhigh", "max")
        ),
        default_effort=(
            DefaultEffortEvidence(level="none", origin="explicit")
            if default_none
            else None
        ),
    )
    contract = ModelCapabilityContract(
        version=2,
        reasoning=reasoning,
        reasoning_summaries=unknown(),
        function_calling=supported(),
        parallel_function_calls=unknown(),
        strict_function_schema=supported(),
        structured_response=structured,
        parameters=ParameterSupport(
            temperature=temperature,
            max_output_tokens=supported(),
            top_p=unknown(),
            top_k=unsupported(),
            stop_sequences=unsupported(),
        ),
        input_modalities=(ModalitySupport(modality="text", support=supported()),),
        output_modalities=(ModalitySupport(modality="text", support=supported()),),
        built_in_tools=(),
    )
    return ModelCapabilities(
        tool_calling=ModelToolCallingCapabilities(
            supported=True, parallel_tool_calls=None, strict_json_schema=True
        ),
        modalities=ModelModalities(
            input=[ModelModality.TEXT], output=[ModelModality.TEXT]
        ),
        reasoning=ModelReasoningCapabilities(
            supported=True,
            effort_levels=[
                ModelReasoningEffort(level) for level in reasoning.enabled_efforts
            ],
            summaries=None,
        ),
        parameters=ModelParameterCapabilities(
            temperature=temperature.enabled,
            max_output_tokens=True,
            top_p=False,
            top_k=False,
            stop_sequences=False,
        ),
        semantic_contract=contract,
    )


def request(*, effort: str | None, temperature: bool) -> ModelSupportRequest:
    return ModelSupportRequest(
        reasoning_effort=effort,
        function_tools=False,
        temperature=temperature,
        max_output_tokens=False,
        top_p=False,
        top_k=False,
        stop_sequences=False,
        parallel_function_calls=False,
        strict_function_schema=False,
        structured_response=False,
        reasoning_summary=False,
    )


@pytest.mark.parametrize("effort", ["none", "high", "xhigh", "max"])
def test_explicit_effort_wins_over_known_saved_default(effort: str) -> None:
    capabilities = semantic_capabilities(
        default_none=True, temperature=conditional(), structured=supported()
    )
    context = resolve_model_support_context(
        capabilities, requested_effort=effort, function_tools=True
    )
    assert context.reasoning_effort == effort
    assert context.function_tools is True


@pytest.mark.parametrize("default_none", [False, True])
def test_omitted_effort_is_known_default_or_unknown(default_none: bool) -> None:
    capabilities = semantic_capabilities(
        default_none=default_none, temperature=conditional(), structured=supported()
    )
    context = resolve_model_support_context(
        capabilities, requested_effort=None, function_tools=False
    )
    assert context.reasoning_effort == ("none" if default_none else None)


@pytest.mark.parametrize(
    ("effort", "expected"), [(None, False), ("none", True), ("high", False)]
)
def test_effort_condition_does_not_treat_omission_as_none(
    effort: str | None, expected: bool
) -> None:
    assert (
        model_support_allowed(
            conditional(),
            context=ModelSupportContext(reasoning_effort=effort, function_tools=False),
        )
        is expected
    )


@pytest.mark.parametrize("actual", [False, True])
def test_predicate_checks_function_tools_conjunction(actual: bool) -> None:
    support = CapabilitySupport(
        state="conditional",
        origin="explicit",
        predicate=SupportPredicate(reasoning_efforts=("none",), function_tools=True),
    )
    assert (
        model_support_allowed(
            support,
            context=ModelSupportContext(reasoning_effort="none", function_tools=actual),
        )
        is actual
    )


@pytest.mark.parametrize(
    ("support", "expected"),
    [(supported(), True), (unsupported(), False), (unknown(), None)],
)
def test_unconditional_support_keeps_unknown_distinct(
    support: CapabilitySupport, expected: bool | None
) -> None:
    assert (
        model_support_allowed(
            support,
            context=ModelSupportContext(reasoning_effort=None, function_tools=False),
        )
        is expected
    )


@pytest.mark.parametrize("effort", ["none", "high", "xhigh", "max"])
def test_individually_authorized_efforts_are_not_clamped(effort: str) -> None:
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    selected = request(effort=effort, temperature=False)
    validate_saved_model_request(capabilities, request=selected)
    assert selected.reasoning_effort == effort


@pytest.mark.parametrize("effort", ["low", "medium", "minimal", "other"])
def test_missing_effort_declaration_does_not_acquire_wire_enum_support(
    effort: str,
) -> None:
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    with pytest.raises(ValueError, match="not authorized"):
        validate_saved_model_request(
            capabilities, request=request(effort=effort, temperature=False)
        )


@pytest.mark.parametrize("default_none", [False, True])
def test_sampling_condition_uses_saved_default_without_changing_request(
    default_none: bool,
) -> None:
    capabilities = semantic_capabilities(
        default_none=default_none, temperature=conditional(), structured=supported()
    )
    selected = request(effort=None, temperature=True)
    if default_none:
        validate_saved_model_request(capabilities, request=selected)
    else:
        with pytest.raises(ValueError, match="temperature conditions"):
            validate_saved_model_request(capabilities, request=selected)
    assert selected.reasoning_effort is None
    assert selected.temperature is True


def test_active_effort_and_sampling_rejected_instead_of_dropping_sampling() -> None:
    capabilities = semantic_capabilities(
        default_none=True, temperature=conditional(), structured=supported()
    )
    selected = request(effort="high", temperature=True)
    with pytest.raises(ValueError, match="temperature conditions"):
        validate_saved_model_request(capabilities, request=selected)
    assert selected.reasoning_effort == "high"
    assert selected.temperature is True


def test_unknown_sampling_does_not_create_a_new_model_denial() -> None:
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    validate_saved_model_request(
        capabilities, request=request(effort="high", temperature=True)
    )


@pytest.mark.parametrize("control", ["top_k", "stop_sequences"])
def test_known_unsupported_parameter_fails(control: str) -> None:
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    base = request(effort=None, temperature=False)
    selected = (
        dataclasses.replace(base, top_k=True)
        if control == "top_k"
        else dataclasses.replace(base, stop_sequences=True)
    )
    with pytest.raises(ValueError, match="does not support"):
        validate_saved_model_request(capabilities, request=selected)


def test_historical_snapshot_keeps_previous_request_behavior() -> None:
    capabilities = ModelCapabilities()
    selected = dataclasses.replace(
        request(effort="historical-value", temperature=True), stop_sequences=True
    )
    validate_saved_model_request(capabilities, request=selected)
    assert capabilities.semantic_contract is None


@pytest.mark.parametrize("strict", [False, True, None])
def test_historical_structured_title_uses_previous_flag(strict: bool | None) -> None:
    capabilities = ModelCapabilities(
        tool_calling=ModelToolCallingCapabilities(strict_json_schema=strict)
    )
    assert (
        saved_structured_response_support(
            capabilities, requested_effort=None, function_tools=False
        )
        is strict
    )


def test_structured_response_is_independent_of_strict_function_support() -> None:
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=unsupported()
    )
    assert capabilities.tool_calling.strict_json_schema is True
    assert (
        saved_structured_response_support(
            capabilities, requested_effort=None, function_tools=False
        )
        is False
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"reasoning": {"effort": "none"}},
        {"extra_body": {"reasoning": {"effort": "none"}}},
        {"openai_reasoning_effort": "none"},
        {"anthropic_effort": "none"},
    ],
)
def test_typed_options_preserve_explicit_none_effort(raw: dict[str, object]) -> None:
    options = decode_model_support_options(raw)
    assert options.explicit_effort == "none"
    selected = model_support_request_from_options(
        options,
        selected_effort=None,
        function_tools=False,
        strict_function_schema=False,
    )
    assert selected.reasoning_effort == "none"


def test_typed_options_preserve_false_zero_empty_and_omitted_controls() -> None:
    raw: dict[str, object] = {
        "parallel_tool_calls": False,
        "temperature": 0,
        "stop": [],
        "extra_headers": {"x-test": "unrelated"},
    }
    selected = model_support_request_from_options(
        decode_model_support_options(raw),
        selected_effort=None,
        function_tools=False,
        strict_function_schema=False,
    )
    assert selected.temperature is True
    assert selected.stop_sequences is True
    assert selected.parallel_function_calls is False
    assert selected.reasoning_effort is None
    assert raw["parallel_tool_calls"] is False


@pytest.mark.parametrize(
    "raw",
    [
        {"reasoning": {"effort": "high"}},
        {"extra_body": {"reasoning": {"effort": "high"}}},
        {
            "reasoning": {"effort": "none"},
            "extra_body": {"reasoning": {"effort": "high"}},
        },
    ],
)
def test_conflicting_selected_and_wire_efforts_fail(raw: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="Conflicting"):
        model_support_request_from_options(
            decode_model_support_options(raw),
            selected_effort="none",
            function_tools=False,
            strict_function_schema=False,
        )


def test_response_format_and_summary_have_independent_requests() -> None:
    selected = model_support_request_from_options(
        decode_model_support_options(
            {
                "reasoning": {"summary": "none"},
                "text": {"format": {"type": "json_schema"}},
            }
        ),
        selected_effort=None,
        function_tools=False,
        strict_function_schema=False,
    )
    assert selected.structured_response is True
    assert selected.strict_function_schema is False
    assert selected.reasoning_summary is False


def _lowerer(
    native: bool,
    capabilities: ModelCapabilities,
    *,
    effort: str | None,
    options: dict[str, object] | None,
    tools: list[dict[str, object]] | None,
) -> OpenAIResponsesLowerer | PydanticAILowerer:
    if native:
        return OpenAIResponsesLowerer(
            provider=LLMProvider.OPENAI,
            model="exact-saved-model",
            credential_kwargs={},
            model_capabilities=capabilities,
            supported_execution_options=[],
            enabled_execution_options=[],
            reasoning_effort=effort,
            kwargs=options,
            tools=tools,
        )
    return PydanticAILowerer(
        provider=LLMProvider.OPENROUTER.value,
        provider_id=LLMProvider.OPENROUTER,
        model="exact-saved-model",
        model_capabilities=capabilities,
        supported_execution_options=[],
        enabled_execution_options=[],
        reasoning_effort=effort,
        kwargs=options,
        tools=tools,
    )


@pytest.mark.parametrize("native", [True, False])
@pytest.mark.parametrize(
    ("state", "effort", "requested", "expected"),
    [
        ("unsupported", None, None, False),
        ("unsupported", None, False, False),
        ("unknown", None, None, None),
        ("supported", None, None, None),
        ("supported", None, True, True),
        ("conditional", "none", None, None),
        ("conditional", "high", None, False),
        ("conditional", None, None, False),
    ],
)
def test_saved_parallel_denial_reaches_both_request_dialects(
    native: bool,
    state: Literal["supported", "unsupported", "unknown", "conditional"],
    effort: str | None,
    requested: bool | None,
    expected: bool | None,
) -> None:
    caps = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    assert caps.semantic_contract is not None
    support = {
        "supported": supported(),
        "unsupported": unsupported(),
        "unknown": unknown(),
        "conditional": conditional(),
    }[state]
    caps.semantic_contract = caps.semantic_contract.model_copy(
        update={"parallel_function_calls": support}
    )
    caps.tool_calling.parallel_tool_calls = support.nullable_enabled
    before = caps.model_dump_json()
    lowered = _lowerer(
        native,
        caps,
        effort=effort,
        options=None if requested is None else {"parallel_tool_calls": requested},
        tools=None,
    ).lower([], model="exact-saved-model")
    if isinstance(lowered, OpenAIResponsesRequest):
        options = lowered.options
    else:
        assert lowered.settings is not None
        options = lowered.settings
    if expected is None:
        assert "parallel_tool_calls" not in options
    else:
        assert options["parallel_tool_calls"] is expected
    assert caps.model_dump_json() == before


@pytest.mark.parametrize("native", [True, False])
def test_sampling_extra_body_presence_preserves_effective_wire_precedence(
    native: bool,
) -> None:
    caps = semantic_capabilities(
        default_none=False, temperature=unsupported(), structured=supported()
    )
    with pytest.raises(ValueError, match="temperature"):
        _lowerer(
            native,
            caps,
            effort=None,
            options={"extra_body": {"temperature": 0.0}},
            tools=None,
        ).lower([], model="exact-saved-model")
    decoded = decode_model_support_options(
        {"temperature": 0.2, "extra_body": {"temperature": None}}
    )
    requested = model_support_request_from_options(
        decoded,
        selected_effort=None,
        function_tools=False,
        strict_function_schema=False,
    )
    assert requested.temperature is False


@pytest.mark.parametrize("native", [True, False])
@pytest.mark.parametrize("field", ["parallel_tool_calls", "text", "response_format"])
def test_support_validation_reads_effective_sdk_body_controls(
    native: bool,
    field: str,
) -> None:
    caps = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=unsupported()
    )
    assert caps.semantic_contract is not None
    caps.semantic_contract = caps.semantic_contract.model_copy(
        update={"parallel_function_calls": unsupported()}
    )
    caps.tool_calling.parallel_tool_calls = False
    body: dict[str, object] = {
        "parallel_tool_calls": True,
        "text": {"format": {"type": "json_schema"}},
        "response_format": {"type": "json_object"},
    }
    with pytest.raises(ValueError):
        _lowerer(
            native,
            caps,
            effort=None,
            options={"extra_body": {field: body[field]}},
            tools=None,
        ).lower([], model="exact-saved-model")


@pytest.mark.parametrize("native", [True, False])
@pytest.mark.parametrize("has_function", [True, False])
def test_configurable_effort_potential_still_enforces_actual_dispatch_condition(
    native: bool,
    has_function: bool,
) -> None:
    caps = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    payload = caps.model_dump(mode="json")
    payload["semantic_contract"]["reasoning"]["support"] = {
        "state": "conditional",
        "origin": "explicit",
        "predicate": {"reasoning_efforts": ["high"], "function_tools": True},
    }
    payload["reasoning"]["supported"] = False
    payload["reasoning"]["effort_levels"] = []
    caps = ModelCapabilities.model_validate(payload)
    assert caps.configurable_reasoning_efforts() == [ModelReasoningEffort.HIGH]
    tools: list[dict[str, object]] | None = (
        [
            {
                "type": "function",
                "name": "lookup",
                "description": "Synthetic lookup",
                "parameters": {"type": "object", "properties": {}},
            }
        ]
        if has_function
        else None
    )
    lowerer = _lowerer(native, caps, effort="high", options=None, tools=tools)
    if not has_function:
        with pytest.raises(ValueError, match="reasoning effort conditions"):
            lowerer.lower([], model="exact-saved-model")
    else:
        lowerer.lower([], model="exact-saved-model")


@pytest.mark.parametrize(
    ("body", "requested"),
    [
        (None, False),
        ({}, False),
        ({"summary": "none"}, False),
        ({"summary": "auto"}, True),
    ],
)
def test_effective_body_summary_uses_sdk_object_override_precedence(
    body: dict[str, object] | None,
    requested: bool,
) -> None:
    options = decode_model_support_options(
        {
            "openai_reasoning_summary": "auto",
            "extra_body": {"reasoning": body},
        }
    )
    request = model_support_request_from_options(
        options,
        selected_effort=None,
        function_tools=False,
        strict_function_schema=False,
    )
    assert request.reasoning_summary is requested


@pytest.mark.parametrize("effort", ["none", "high", "xhigh", "max"])
def test_native_lowerer_preserves_individually_authorized_effort(effort: str) -> None:
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    lowered = _lowerer(
        True, capabilities, effort=effort, options=None, tools=None
    ).lower([], model="exact-saved-model")
    assert isinstance(lowered, OpenAIResponsesRequest)
    assert lowered.options["reasoning"] == {"effort": effort, "summary": "auto"}


def test_native_default_checks_sampling_without_adding_wire_effort() -> None:
    capabilities = semantic_capabilities(
        default_none=True, temperature=conditional(), structured=supported()
    )
    lowered = _lowerer(
        True, capabilities, effort=None, options={"temperature": 0}, tools=None
    ).lower([], model="exact-saved-model")
    assert isinstance(lowered, OpenAIResponsesRequest)
    assert lowered.options["temperature"] == 0
    assert "reasoning" not in lowered.options


def test_native_saved_v2_support_cannot_authorize_another_model() -> None:
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    with pytest.raises(ValueError, match="model identity"):
        _lowerer(True, capabilities, effort=None, options=None, tools=None).lower(
            [], model="another-model"
        )


@pytest.mark.parametrize("native", [False, True])
def test_lowerers_reject_unmet_condition_without_mutating_options(native: bool) -> None:
    capabilities = semantic_capabilities(
        default_none=True, temperature=conditional(), structured=supported()
    )
    options: dict[str, object] = {"temperature": 0.3}
    with pytest.raises(ValueError, match="temperature conditions"):
        _lowerer(
            native, capabilities, effort="high", options=options, tools=None
        ).lower([], model="exact-saved-model")
    assert options == {"temperature": 0.3}


@pytest.mark.parametrize("native", [False, True])
def test_explicit_strict_is_rejected_instead_of_silently_disabled(native: bool) -> None:
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    assert capabilities.semantic_contract is not None
    capabilities = capabilities.model_copy(
        update={
            "semantic_contract": capabilities.semantic_contract.model_copy(
                update={"strict_function_schema": unsupported()}
            )
        }
    )
    tool: dict[str, object] = {
        "type": "function",
        "name": "example",
        "parameters": {"type": "object", "properties": {}},
        "strict": True,
    }
    with pytest.raises(ValueError, match="strict function schemas"):
        _lowerer(native, capabilities, effort=None, options=None, tools=[tool]).lower(
            [], model="exact-saved-model"
        )
    assert tool["strict"] is True


def test_pydantic_explicit_parallel_true_is_not_silently_overwritten() -> None:
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    assert capabilities.semantic_contract is not None
    capabilities = capabilities.model_copy(
        update={
            "semantic_contract": capabilities.semantic_contract.model_copy(
                update={"parallel_function_calls": unsupported()}
            )
        }
    )
    with pytest.raises(ValueError, match="parallel function calls"):
        _lowerer(
            False,
            capabilities,
            effort=None,
            options={"parallel_tool_calls": True},
            tools=None,
        ).lower([], model="exact-saved-model")


def test_function_condition_is_deferred_until_actual_declarations_are_known() -> None:
    support = CapabilitySupport(
        state="conditional",
        origin="explicit",
        predicate=SupportPredicate(reasoning_efforts=None, function_tools=True),
    )
    assert (
        model_support_allowed(
            support,
            context=ModelSupportContext(reasoning_effort=None, function_tools=None),
        )
        is None
    )
    assert (
        model_support_allowed(
            support,
            context=ModelSupportContext(reasoning_effort=None, function_tools=False),
        )
        is False
    )
    assert (
        model_support_allowed(
            support,
            context=ModelSupportContext(reasoning_effort=None, function_tools=True),
        )
        is True
    )


def test_pydantic_preserves_explicit_summary_none() -> None:
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    lowered = _lowerer(
        False,
        capabilities,
        effort="high",
        options={"extra_body": {"reasoning": {"effort": "high", "summary": "none"}}},
        tools=None,
    ).lower([], model="exact-saved-model")
    assert not isinstance(lowered, OpenAIResponsesRequest)
    assert lowered.settings["extra_body"] == {
        "reasoning": {"effort": "high", "summary": "none"}
    }


@pytest.mark.parametrize("effort", ["minimal", "low", "medium", "high"])
def test_google_v2_level_mapping_preserves_exact_choice(
    effort: Literal["minimal", "low", "medium", "high"],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        GoogleProvider,
        "model_profile",
        lambda model: GoogleModelProfile(
            google_supports_thinking_level=True,
            google_thinking_levels=frozenset({"MINIMAL", "LOW", "MEDIUM", "HIGH"}),
        ),
    )
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    assert capabilities.semantic_contract is not None
    capabilities = capabilities.model_copy(
        update={
            "semantic_contract": capabilities.semantic_contract.model_copy(
                update={
                    "reasoning": capabilities.semantic_contract.reasoning.model_copy(
                        update={
                            "efforts": (
                                EffortDeclaration(
                                    level=effort, state="supported", origin="explicit"
                                ),
                            )
                        }
                    )
                }
            )
        }
    )
    lowered = PydanticAILowerer(
        provider="google_gemini",
        provider_id=LLMProvider.GOOGLE_GEMINI,
        model="exact-wire-model",
        tools=None,
        model_capabilities=capabilities,
        supported_execution_options=[],
        enabled_execution_options=[],
        reasoning_effort=effort,
    ).lower([], model="exact-wire-model")
    assert dict(lowered.settings)["google_thinking_config"] == {
        "thinking_level": ThinkingLevel(effort.upper()),
        "include_thoughts": True,
    }


@pytest.mark.parametrize("effort", ["none", "high"])
def test_google_v2_does_not_invent_budget_or_change_none_to_low(
    effort: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        GoogleProvider,
        "model_profile",
        lambda model: GoogleModelProfile(google_supports_thinking_level=False),
    )
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    with pytest.raises(ValueError, match="no lossless mapping"):
        PydanticAILowerer(
            provider="google_gemini",
            provider_id=LLMProvider.GOOGLE_GEMINI,
            model="exact-wire-model",
            tools=None,
            model_capabilities=capabilities,
            supported_execution_options=[],
            enabled_execution_options=[],
            reasoning_effort=effort,
        ).lower([], model="exact-wire-model")


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("effort", [None, "none", "high"])
def test_strict_function_conditions_are_evaluated_without_rewriting_declarations(
    native: bool,
    effort: str | None,
) -> None:
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    assert capabilities.semantic_contract is not None
    capabilities.semantic_contract = capabilities.semantic_contract.model_copy(
        update={"strict_function_schema": conditional()}
    )
    tool: dict[str, object] = {
        "type": "function",
        "name": "example",
        "parameters": {"type": "object", "properties": {}},
        "strict": True,
    }
    lowerer = _lowerer(native, capabilities, effort=effort, options=None, tools=[tool])
    if effort != "none":
        with pytest.raises(ValueError, match="strict function schemas conditions"):
            lowerer.lower([], model="exact-saved-model")
    else:
        lowered = lowerer.lower([], model="exact-saved-model")
        if isinstance(lowered, OpenAIResponsesRequest):
            assert lowered.tools[0]["strict"] is True
        else:
            assert lowered.parameters.function_tools[0].strict is True
    assert tool["strict"] is True


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("strict", [False, True])
def test_unknown_strict_keeps_explicit_true_or_false_at_provider_boundary(
    native: bool,
    strict: bool,
) -> None:
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    assert capabilities.semantic_contract is not None
    capabilities.semantic_contract = capabilities.semantic_contract.model_copy(
        update={"strict_function_schema": unknown()}
    )
    tool: dict[str, object] = {
        "type": "function",
        "name": "example",
        "parameters": {"type": "object", "properties": {}},
        "strict": strict,
    }
    lowered = _lowerer(
        native, capabilities, effort=None, options=None, tools=[tool]
    ).lower([], model="exact-saved-model")
    if isinstance(lowered, OpenAIResponsesRequest):
        assert lowered.tools[0]["strict"] is strict
    else:
        assert lowered.parameters.function_tools[0].strict is strict


def _hosted_lowerer(
    native: bool,
    capabilities: ModelCapabilities,
    *,
    effort: str | None,
    functions: bool,
) -> OpenAIResponsesLowerer | PydanticAILowerer:
    tools: list[dict[str, object]] = (
        [
            {
                "type": "function",
                "name": "example",
                "parameters": {"type": "object", "properties": {}},
                "strict": False,
            }
        ]
        if functions
        else []
    )
    hosted = [BuiltinToolSpec(name="web_search", config={})]
    if native:
        return OpenAIResponsesLowerer(
            provider=LLMProvider.OPENAI,
            model="exact-saved-model",
            credential_kwargs={},
            model_capabilities=capabilities,
            supported_execution_options=[],
            enabled_execution_options=[],
            reasoning_effort=effort,
            tools=tools,
            hosted_tools=hosted,
        )
    return PydanticAILowerer(
        provider=LLMProvider.OPENROUTER.value,
        provider_id=LLMProvider.OPENROUTER,
        model="exact-saved-model",
        model_capabilities=capabilities,
        supported_execution_options=[],
        enabled_execution_options=[],
        reasoning_effort=effort,
        tools=tools,
        hosted_tools=hosted,
    )


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize(
    ("effort", "default_none", "functions", "allowed"),
    [
        ("none", False, False, True),
        ("none", False, True, False),
        ("high", False, False, False),
        (None, True, False, True),
        (None, False, False, False),
    ],
)
def test_hosted_tool_conditions_use_actual_effort_and_function_presence(
    native: bool,
    effort: str | None,
    default_none: bool,
    functions: bool,
    allowed: bool,
) -> None:
    capabilities = semantic_capabilities(
        default_none=default_none, temperature=unknown(), structured=supported()
    )
    assert capabilities.semantic_contract is not None
    capabilities.semantic_contract = capabilities.semantic_contract.model_copy(
        update={
            "built_in_tools": (
                BuiltinToolSupport(
                    tool="web_search",
                    support=CapabilitySupport(
                        state="conditional",
                        origin="explicit",
                        predicate=SupportPredicate(
                            reasoning_efforts=("none",), function_tools=False
                        ),
                    ),
                ),
            )
        }
    )
    assert capabilities.built_in_tools.supported == []
    lowerer = _hosted_lowerer(native, capabilities, effort=effort, functions=functions)
    if not allowed:
        with pytest.raises(ValueError, match="builtin tool|Hosted tool"):
            lowerer.lower([], model="exact-saved-model")
    else:
        lowered = lowerer.lower([], model="exact-saved-model")
        if isinstance(lowered, OpenAIResponsesRequest):
            assert lowered.tools[-1]["type"] == "web_search"
            if effort is None:
                assert "reasoning" not in lowered.options
        else:
            assert len(lowered.parameters.native_tools) == 1


@pytest.mark.parametrize("support", [unknown(), unsupported()])
def test_unknown_or_unsupported_hosted_facts_do_not_acquire_authorization(
    support: CapabilitySupport,
) -> None:
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    assert capabilities.semantic_contract is not None
    capabilities.semantic_contract = capabilities.semantic_contract.model_copy(
        update={
            "built_in_tools": (BuiltinToolSupport(tool="web_search", support=support),)
        }
    )
    capabilities.built_in_tools.supported = ["web_search"]
    assert not saved_builtin_tool_allowed(
        capabilities,
        tool="web_search",
        context=ModelSupportContext(reasoning_effort=None, function_tools=False),
    )


@pytest.mark.parametrize("native", [False, True])
def test_historical_hosted_tool_authorization_keeps_existing_list(native: bool) -> None:
    capabilities = ModelCapabilities()
    capabilities.built_in_tools.supported = ["web_search"]
    lowered = _hosted_lowerer(native, capabilities, effort=None, functions=False).lower(
        [], model="exact-saved-model"
    )
    if isinstance(lowered, OpenAIResponsesRequest):
        assert lowered.tools[-1]["type"] == "web_search"
    else:
        assert len(lowered.parameters.native_tools) == 1


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("effort", ["none", "high"])
def test_explicit_summary_condition_is_checked_without_dropping_summary(
    native: bool,
    effort: str,
) -> None:
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=supported()
    )
    assert capabilities.semantic_contract is not None
    capabilities.semantic_contract = capabilities.semantic_contract.model_copy(
        update={"reasoning_summaries": conditional()}
    )
    reasoning: dict[str, object] = {"effort": effort, "summary": "auto"}
    options: dict[str, object] = (
        {"reasoning": reasoning} if native else {"extra_body": {"reasoning": reasoning}}
    )
    lowerer = _lowerer(native, capabilities, effort=effort, options=options, tools=None)
    if effort == "high":
        with pytest.raises(ValueError, match="reasoning summary conditions"):
            lowerer.lower([], model="exact-saved-model")
    else:
        lowered = lowerer.lower([], model="exact-saved-model")
        if isinstance(lowered, OpenAIResponsesRequest):
            assert lowered.options["reasoning"] == reasoning
        else:
            assert lowered.settings["extra_body"] == {"reasoning": reasoning}
    assert reasoning["summary"] == "auto"


@pytest.mark.parametrize("effort", ["none", "high"])
def test_native_structured_condition_is_checked_without_dropping_format(
    effort: str,
) -> None:
    capabilities = semantic_capabilities(
        default_none=False, temperature=unknown(), structured=conditional()
    )
    text: dict[str, object] = {
        "format": {
            "type": "json_schema",
            "name": "answer",
            "schema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "strict": True,
        }
    }
    lowerer = _lowerer(
        True, capabilities, effort=effort, options={"text": text}, tools=None
    )
    if effort == "high":
        with pytest.raises(ValueError, match="structured output conditions"):
            lowerer.lower([], model="exact-saved-model")
    else:
        lowered = lowerer.lower([], model="exact-saved-model")
        assert isinstance(lowered, OpenAIResponsesRequest)
        assert lowered.options["text"] == text
    assert text["format"] == {
        "type": "json_schema",
        "name": "answer",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    }


@pytest.mark.parametrize("default_none", [False, True])
def test_title_structured_predicate_uses_saved_default_not_omission_as_none(
    default_none: bool,
) -> None:
    capabilities = semantic_capabilities(
        default_none=default_none, temperature=unknown(), structured=conditional()
    )
    assert (
        saved_structured_response_support(
            capabilities, requested_effort=None, function_tools=False
        )
        is default_none
    )
