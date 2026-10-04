"""Final feature membership and read-only historical descriptor decoding."""

import copy
import json
import socket
from typing import Any, Never

import pytest
from pydantic import ValidationError

from azents.core.llm_catalog import (
    ModelBuiltInToolCapabilities,
    ModelCapabilities,
    ModelModalities,
    ModelModality,
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


def _legacy_support(state: str) -> dict[str, object]:
    return {
        "state": state,
        "origin": None if state == "unknown" else "explicit",
        "predicate": None,
    }


def _legacy_contract() -> dict[str, Any]:
    """Use stored JSON rather than a second public runtime support model."""
    supported = _legacy_support("supported")
    unknown = _legacy_support("unknown")
    unsupported = _legacy_support("unsupported")
    return {
        "version": 2,
        "reasoning": {
            "support": supported,
            "completeness": "partial",
            "efforts": [
                {"level": "high", "state": "supported", "origin": "explicit"},
                {"level": "max", "state": "unsupported", "origin": "explicit"},
            ],
            "default_effort": {"level": "high", "origin": "explicit"},
        },
        "reasoning_summaries": unknown,
        "function_calling": supported,
        "parallel_function_calls": unknown,
        "strict_function_schema": unsupported,
        "structured_response": supported,
        "parameters": {
            "temperature": {
                "state": "conditional",
                "origin": "explicit",
                "predicate": {"reasoning_efforts": ["none"], "function_tools": True},
            },
            "max_output_tokens": supported,
            "top_p": unknown,
            "top_k": unsupported,
            "stop_sequences": unsupported,
        },
        "input_modalities": [
            {"modality": "text", "support": supported},
            {"modality": "image", "support": unknown},
        ],
        "output_modalities": [{"modality": "text", "support": supported}],
        "built_in_tools": [{"tool": "web_search", "support": supported}],
    }


def test_final_defaults_have_no_supported_features_or_second_truth() -> None:
    capabilities = ModelCapabilities()
    assert capabilities.supported_features() == frozenset()
    assert all(not capabilities.supports(feature) for feature in ModelCapabilityFeature)
    payload = capabilities.model_dump(mode="json")
    assert "semantic_contract" not in payload
    assert "supported_features" not in payload
    assert "state" not in json.dumps(payload)
    assert payload["capability_schema_version"] == 3
    schema = json.dumps(ModelCapabilities.model_json_schema())
    assert "CapabilitySupport" not in schema
    assert "unknown" not in schema
    assert "unverified" not in schema


def test_all_final_feature_keys_derive_from_only_flat_fields() -> None:
    capabilities = ModelCapabilities(
        modalities=ModelModalities(
            input=list(ModelModality), output=list(ModelModality)
        ),
        tool_calling=ModelToolCallingCapabilities(
            supported=True, parallel_tool_calls=True, strict_json_schema=True
        ),
        reasoning=ModelReasoningCapabilities(
            supported=True, effort_levels=list(ModelReasoningEffort), summaries=True
        ),
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
        structured_response=True,
    )
    assert capabilities.supported_features() == frozenset(ModelCapabilityFeature)
    assert all(capabilities.supports(feature) for feature in ModelCapabilityFeature)
    assert capabilities.configurable_reasoning_efforts() == list(ModelReasoningEffort)
    capabilities.parameters.temperature = False
    assert not capabilities.supports(ModelCapabilityFeature.TEMPERATURE)


def test_structured_response_is_independent_from_strict_function_schema() -> None:
    capabilities = ModelCapabilities(structured_response=True)
    assert capabilities.supports(ModelCapabilityFeature.STRUCTURED_RESPONSE)
    assert not capabilities.supports(ModelCapabilityFeature.STRICT_FUNCTION_SCHEMA)
    assert not capabilities.supports(ModelCapabilityFeature.FUNCTION_CALLING)


def test_constraints_cannot_enable_absent_features() -> None:
    constraint = ModelFeatureCondition(
        feature=ModelCapabilityFeature.INPUT_IMAGE,
        reasoning_efforts=("high",),
        function_tools=None,
    )
    with pytest.raises(ValidationError, match="requires a present feature"):
        ModelCapabilities(
            request_constraints=ModelRequestConstraints(
                feature_conditions=(constraint,)
            )
        )
    capabilities = ModelCapabilities(
        modalities=ModelModalities(input=[ModelModality.IMAGE]),
        request_constraints=ModelRequestConstraints(feature_conditions=(constraint,)),
    )
    assert capabilities.supports(ModelCapabilityFeature.INPUT_IMAGE)
    assert capabilities.request_constraints.feature_conditions == (constraint,)
    assert (
        ModelCapabilities.model_validate_json(capabilities.model_dump_json())
        == capabilities
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"feature": "input:image", "reasoning_efforts": None, "function_tools": None},
        {"feature": "input:image", "reasoning_efforts": [], "function_tools": None},
        {
            "feature": "input:image",
            "reasoning_efforts": ["low", "low"],
            "function_tools": None,
        },
        {
            "feature": "input:image",
            "reasoning_efforts": ["ultra"],
            "function_tools": None,
        },
        {
            "feature": "input:future",
            "reasoning_efforts": ["low"],
            "function_tools": None,
        },
        {"feature": "input:image", "reasoning_efforts": ["low"]},
        {
            "feature": "input:image",
            "reasoning_efforts": ["low"],
            "function_tools": None,
            "state": "unknown",
        },
    ],
)
def test_request_constraints_are_closed_typed_data(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ModelFeatureCondition.model_validate(payload)


def test_duplicate_conditions_are_rejected() -> None:
    condition = ModelFeatureCondition(
        feature=ModelCapabilityFeature.FUNCTION_CALLING,
        reasoning_efforts=None,
        function_tools=True,
    )
    with pytest.raises(ValidationError, match="must be unique"):
        ModelRequestConstraints(feature_conditions=(condition, condition))


@pytest.mark.parametrize("level", list(ModelReasoningEffort))
def test_known_default_is_metadata_and_does_not_enable_reasoning(
    level: ModelReasoningEffort,
) -> None:
    capabilities = ModelCapabilities.model_validate(
        {"request_constraints": {"known_default": level.value}}
    )
    assert capabilities.request_constraints.known_default == level.value
    assert not capabilities.supports(ModelCapabilityFeature.REASONING)
    assert capabilities.configurable_reasoning_efforts() == []


def test_historical_descriptor_converts_once_without_mutating_input() -> None:
    original = {
        "semantic_contract": _legacy_contract(),
        "context_window": {"max_input_tokens": 128000},
        "parameters": {"temperature": False},
        "tool_calling": {"supported": False},
    }
    frozen = copy.deepcopy(original)
    capabilities = ModelCapabilities.model_validate(original)
    assert original == frozen
    assert capabilities.context_window.max_input_tokens == 128000
    assert capabilities.supports(ModelCapabilityFeature.FUNCTION_CALLING)
    assert capabilities.supports(ModelCapabilityFeature.TEMPERATURE)
    assert capabilities.supports(ModelCapabilityFeature.STRUCTURED_RESPONSE)
    assert not capabilities.supports(ModelCapabilityFeature.INPUT_IMAGE)
    assert not capabilities.supports(ModelCapabilityFeature.PARALLEL_FUNCTION_CALLS)
    assert capabilities.configurable_reasoning_efforts() == [ModelReasoningEffort.HIGH]
    assert capabilities.request_constraints.known_default == "high"
    assert capabilities.request_constraints.feature_conditions == (
        ModelFeatureCondition(
            feature=ModelCapabilityFeature.TEMPERATURE,
            reasoning_efforts=("none",),
            function_tools=True,
        ),
    )
    dumped = capabilities.model_dump(mode="json")
    assert "semantic_contract" not in dumped
    assert "state" not in json.dumps(dumped)
    assert ModelCapabilities.model_validate(dumped) == capabilities


@pytest.mark.parametrize("state", ["unknown", "unsupported"])
def test_historical_absence_never_enables_final_support(state: str) -> None:
    contract = _legacy_contract()
    contract["function_calling"] = _legacy_support(state)
    contract["reasoning"]["support"] = _legacy_support(state)
    contract["reasoning"]["efforts"] = []
    capabilities = ModelCapabilities.model_validate({"semantic_contract": contract})
    assert not capabilities.supports(ModelCapabilityFeature.FUNCTION_CALLING)
    assert not capabilities.supports(ModelCapabilityFeature.REASONING)
    assert capabilities.request_constraints.known_default == "high"


def test_historical_null_flags_are_final_false() -> None:
    capabilities = ModelCapabilities.model_validate(
        {
            "tool_calling": {"parallel_tool_calls": None, "strict_json_schema": None},
            "reasoning": {"summaries": None},
            "semantic_contract": None,
        }
    )
    assert capabilities == ModelCapabilities()
    assert capabilities.tool_calling.parallel_tool_calls is False
    assert capabilities.tool_calling.strict_json_schema is False
    assert capabilities.reasoning.summaries is False


def test_historical_orphan_function_refinements_remain_readable_without_support() -> (
    None
):
    """Valid v2 conditional refinements cannot enable an absent parent feature."""
    contract = _legacy_contract()
    contract["function_calling"] = _legacy_support("unknown")
    refinement = {
        "state": "conditional",
        "origin": "explicit",
        "predicate": {"reasoning_efforts": None, "function_tools": True},
    }
    contract["parallel_function_calls"] = refinement
    contract["strict_function_schema"] = refinement
    original = {"semantic_contract": contract}
    before = copy.deepcopy(original)
    restored = ModelCapabilities.model_validate(original)
    assert original == before
    assert not restored.tool_calling.supported
    assert not restored.tool_calling.parallel_tool_calls
    assert not restored.tool_calling.strict_json_schema
    assert all(
        condition.feature
        not in {
            ModelCapabilityFeature.PARALLEL_FUNCTION_CALLS,
            ModelCapabilityFeature.STRICT_FUNCTION_SCHEMA,
        }
        for condition in restored.request_constraints.feature_conditions
    )


def test_v3_cannot_supply_an_old_authoritative_descriptor() -> None:
    with pytest.raises(ValidationError, match="cannot contain a semantic descriptor"):
        ModelCapabilities.model_validate(
            {"capability_schema_version": 3, "semantic_contract": _legacy_contract()}
        )


@pytest.mark.parametrize(
    "field", ["input_modalities", "output_modalities", "built_in_tools"]
)
def test_malformed_historical_duplicate_declarations_fail(field: str) -> None:
    contract = _legacy_contract()
    contract[field] = [contract[field][0], contract[field][0]]
    with pytest.raises(ValidationError, match="must be unique"):
        ModelCapabilities.model_validate({"semantic_contract": contract})


def test_unsupported_capability_versions_fail_instead_of_silent_defaults() -> None:
    with pytest.raises(ValidationError):
        ModelCapabilities.model_validate({"capability_schema_version": 4})
    contract = _legacy_contract()
    contract["version"] = 1
    with pytest.raises(ValidationError):
        ModelCapabilities.model_validate({"semantic_contract": contract})


@pytest.mark.parametrize("feature", ["parallel_tool_calls", "strict_json_schema"])
def test_function_refinements_require_function_support(feature: str) -> None:
    with pytest.raises(ValidationError, match="require function calling"):
        ModelCapabilities.model_validate({"tool_calling": {feature: True}})


def test_empty_or_absent_legacy_descriptor_is_readable_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_connection(*args: object, **kwargs: object) -> Never:
        raise AssertionError("Capability decoding cannot use network I/O.")

    monkeypatch.setattr(socket.socket, "connect", fail_connection)
    monkeypatch.setattr(socket, "create_connection", fail_connection)
    assert (
        ModelCapabilities.model_validate({"semantic_contract": None})
        == ModelCapabilities()
    )
    compiled = ModelCapabilities.model_validate(
        {"semantic_contract": _legacy_contract()}
    )
    assert ModelCapabilities.model_validate_json(compiled.model_dump_json()) == compiled
