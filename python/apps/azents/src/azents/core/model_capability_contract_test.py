"""Versioned support semantics and historical saved-capability compatibility."""

import socket
from typing import Never

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


def _supported() -> CapabilitySupport:
    return CapabilitySupport(state="supported", origin="explicit", predicate=None)


def _unknown() -> CapabilitySupport:
    return CapabilitySupport(state="unknown", origin=None, predicate=None)


def _contract() -> ModelCapabilityContract:
    return ModelCapabilityContract(
        version=2,
        reasoning=ReasoningSupport(
            support=_supported(),
            completeness="partial",
            efforts=(
                EffortDeclaration(level="high", state="supported", origin="explicit"),
                EffortDeclaration(
                    level="xhigh", state="supported", origin="contract_derived"
                ),
                EffortDeclaration(level="max", state="unsupported", origin="explicit"),
            ),
            default_effort=None,
        ),
        reasoning_summaries=_unknown(),
        function_calling=_supported(),
        parallel_function_calls=_unknown(),
        strict_function_schema=CapabilitySupport(
            state="unsupported", origin="explicit", predicate=None
        ),
        structured_response=_supported(),
        parameters=ParameterSupport(
            temperature=CapabilitySupport(
                state="conditional",
                origin="explicit",
                predicate=SupportPredicate(
                    reasoning_efforts=("none",), function_tools=None
                ),
            ),
            max_output_tokens=_supported(),
            top_p=_unknown(),
            top_k=_unknown(),
            stop_sequences=CapabilitySupport(
                state="unsupported", origin="contract_derived", predicate=None
            ),
        ),
        input_modalities=(
            ModalitySupport(modality="text", support=_supported()),
            ModalitySupport(modality="image", support=_unknown()),
        ),
        output_modalities=(ModalitySupport(modality="text", support=_supported()),),
        built_in_tools=(BuiltinToolSupport(tool="web_search", support=_supported()),),
    )


def _capabilities(contract: ModelCapabilityContract) -> ModelCapabilities:
    return ModelCapabilities(
        modalities=ModelModalities(
            input=[
                ModelModality(item.modality)
                for item in contract.input_modalities
                if item.support.enabled
            ],
            output=[
                ModelModality(item.modality)
                for item in contract.output_modalities
                if item.support.enabled
            ],
        ),
        tool_calling=ModelToolCallingCapabilities(
            supported=contract.function_calling.enabled,
            parallel_tool_calls=contract.parallel_function_calls.nullable_enabled,
            strict_json_schema=contract.strict_function_schema.nullable_enabled,
        ),
        reasoning=ModelReasoningCapabilities(
            supported=contract.reasoning.support.enabled,
            effort_levels=[
                ModelReasoningEffort(level)
                for level in contract.reasoning.enabled_efforts
            ],
            summaries=contract.reasoning_summaries.nullable_enabled,
        ),
        built_in_tools=ModelBuiltInToolCapabilities(
            supported=[
                item.tool for item in contract.built_in_tools if item.support.enabled
            ]
        ),
        parameters=ModelParameterCapabilities(
            temperature=contract.parameters.temperature.enabled,
            max_output_tokens=contract.parameters.max_output_tokens.enabled,
            top_p=contract.parameters.top_p.enabled,
            top_k=contract.parameters.top_k.enabled,
            stop_sequences=contract.parameters.stop_sequences.enabled,
        ),
        semantic_contract=contract,
    )


def test_historical_snapshot_retains_exact_serialized_shape() -> None:
    """Absence of a descriptor remains the unchanged historical contract."""
    historical = ModelCapabilities(
        reasoning=ModelReasoningCapabilities(
            supported=True, effort_levels=[ModelReasoningEffort.MAX]
        ),
        parameters=ModelParameterCapabilities(temperature=True, stop_sequences=True),
    ).model_dump(mode="json")
    restored = ModelCapabilities.model_validate(historical)
    assert restored.semantic_contract is None
    assert "semantic_contract" not in historical
    assert restored.model_dump(mode="json") == historical
    assert restored.reasoning.effort_levels == [ModelReasoningEffort.MAX]
    assert restored.parameters.temperature is True
    assert restored.parameters.stop_sequences is True


def test_explicit_null_descriptor_retains_legacy_defaults() -> None:
    """An explicit historical null does not manufacture evidence or new support."""
    restored = ModelCapabilities.model_validate({"semantic_contract": None})
    assert restored == ModelCapabilities()
    assert restored.model_dump(mode="json") == ModelCapabilities().model_dump(
        mode="json"
    )


def test_versioned_contract_roundtrip_preserves_partial_facts_and_conditions() -> None:
    """Saved semantics keep the exact justified subset and an unknown default."""
    capabilities = _capabilities(_contract())
    restored = ModelCapabilities.model_validate_json(capabilities.model_dump_json())
    assert restored == capabilities
    assert restored.semantic_contract is not None
    assert restored.semantic_contract.version == 2
    assert restored.semantic_contract.reasoning.completeness == "partial"
    assert restored.semantic_contract.reasoning.default_effort is None
    assert restored.reasoning.effort_levels == [
        ModelReasoningEffort.HIGH,
        ModelReasoningEffort.XHIGH,
    ]
    assert restored.semantic_contract.reasoning.efforts[1].origin == "contract_derived"
    assert restored.semantic_contract.parameters.temperature.state == "conditional"
    assert restored.parameters.temperature is False
    assert (
        restored.semantic_contract.parameters.temperature.predicate
        == SupportPredicate(reasoning_efforts=("none",), function_tools=None)
    )


def test_structured_response_does_not_enable_strict_function_schemas() -> None:
    """Strict functions and structured responses remain independent facts."""
    capabilities = _capabilities(_contract())
    assert capabilities.semantic_contract is not None
    assert capabilities.semantic_contract.structured_response.enabled is True
    assert capabilities.tool_calling.strict_json_schema is False


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("tool_calling", {"supported": False}),
        ("tool_calling", {"parallel_tool_calls": True}),
        ("tool_calling", {"strict_json_schema": True}),
        ("reasoning", {"supported": False}),
        ("reasoning", {"summaries": False}),
        ("reasoning", {"effort_levels": ["high", "xhigh", "max"]}),
        ("parameters", {"temperature": True}),
        ("parameters", {"max_output_tokens": False}),
        ("parameters", {"top_p": True}),
        ("parameters", {"top_k": True}),
        ("parameters", {"stop_sequences": True}),
        ("modalities", {"input": ["text", "image"]}),
        ("modalities", {"output": []}),
        ("built_in_tools", {"supported": []}),
    ],
)
def test_legacy_views_cannot_compete_with_semantic_authority(
    field: str, changed: dict[str, object]
) -> None:
    """A decoder rejects stale or independently editable effective views."""
    payload = _capabilities(_contract()).model_dump(mode="json")
    payload[field].update(changed)
    with pytest.raises(ValidationError, match="must match the saved semantic contract"):
        ModelCapabilities.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"state": "conditional", "origin": "explicit", "predicate": None},
        {"state": "supported", "origin": None, "predicate": None},
        {"state": "unsupported", "origin": None, "predicate": None},
        {"state": "unknown", "origin": "explicit", "predicate": None},
        {
            "state": "supported",
            "origin": "explicit",
            "predicate": {"reasoning_efforts": ["none"], "function_tools": None},
        },
        {"state": "supported", "origin": "explicit"},
    ],
)
def test_support_requires_explicit_valid_evidence_shape(
    payload: dict[str, object],
) -> None:
    """Missing evidence fields and condition-free conditional claims are rejected."""
    with pytest.raises(ValidationError):
        CapabilitySupport.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"reasoning_efforts": None, "function_tools": None},
        {"reasoning_efforts": [], "function_tools": None},
        {"reasoning_efforts": ["none", "none"], "function_tools": None},
        {"reasoning_efforts": ["ultra"], "function_tools": None},
        {"reasoning_efforts": ["none"]},
        {"reasoning_efforts": ["none"], "function_tools": None, "expression": "true"},
    ],
)
def test_condition_is_bounded_and_known(payload: dict[str, object]) -> None:
    """Only typed effort/function predicates enter saved semantic authorization."""
    with pytest.raises(ValidationError):
        SupportPredicate.model_validate(payload)


def test_function_tool_condition_remains_conditional() -> None:
    """Function presence and effort constraints are saved as a conjunction."""
    predicate = SupportPredicate(
        reasoning_efforts=("high", "xhigh"), function_tools=True
    )
    support = CapabilitySupport(
        state="conditional", origin="explicit", predicate=predicate
    )
    assert support.enabled is False
    assert support.nullable_enabled is False
    assert CapabilitySupport.model_validate_json(support.model_dump_json()) == support


@pytest.mark.parametrize("completeness", ["complete", "unknown"])
def test_empty_effort_set_preserves_completeness(completeness: str) -> None:
    """An explicit complete empty set is different from missing effort information."""
    payload = _contract().reasoning.model_dump(mode="json")
    payload.update(completeness=completeness, efforts=[])
    reasoning = ReasoningSupport.model_validate(payload)
    assert reasoning.completeness == completeness
    assert reasoning.enabled_efforts == ()


@pytest.mark.parametrize(
    "updates",
    [
        {"completeness": "unknown"},
        {"completeness": "partial", "efforts": []},
        {
            "efforts": [{"level": "high", "state": "supported", "origin": "explicit"}]
            * 2
        },
        {"default_effort": {"level": "max", "origin": "explicit"}},
        {
            "completeness": "complete",
            "default_effort": {"level": "low", "origin": "explicit"},
        },
        {
            "completeness": "complete",
            "efforts": [{"level": "high", "state": "unknown", "origin": None}],
        },
        {"support": {"state": "unsupported", "origin": "explicit", "predicate": None}},
    ],
)
def test_contradictory_effort_sets_are_rejected(updates: dict[str, object]) -> None:
    """Completeness and known default assertions cannot contradict individual facts."""
    payload = _contract().reasoning.model_dump(mode="json")
    payload.update(updates)
    with pytest.raises(ValidationError):
        ReasoningSupport.model_validate(payload)


def test_known_default_does_not_fill_an_unknown_effort_set() -> None:
    """A default declaration is independent from enumerating all accepted efforts."""
    reasoning = ReasoningSupport(
        support=_supported(),
        completeness="unknown",
        efforts=(),
        default_effort=DefaultEffortEvidence(level="medium", origin="explicit"),
    )
    assert reasoning.enabled_efforts == ()
    assert reasoning.default_effort is not None
    assert reasoning.default_effort.level == "medium"


@pytest.mark.parametrize("level", list(ModelReasoningEffort))
def test_all_current_effort_wire_values_roundtrip(level: ModelReasoningEffort) -> None:
    """The descriptor vocabulary matches existing saved effort wire values."""
    declaration = EffortDeclaration.model_validate(
        {"level": level.value, "state": "supported", "origin": "explicit"}
    )
    assert (
        EffortDeclaration.model_validate_json(declaration.model_dump_json())
        == declaration
    )


@pytest.mark.parametrize(
    "field", ["input_modalities", "output_modalities", "built_in_tools"]
)
def test_duplicate_semantic_facts_are_rejected(field: str) -> None:
    """Repeated declarations cannot obscure a conflicting saved fact."""
    payload = _contract().model_dump(mode="json")
    payload[field] = [payload[field][0], payload[field][0]]
    with pytest.raises(ValidationError, match="must be unique"):
        ModelCapabilityContract.model_validate(payload)


def test_version_and_required_descriptor_fields_are_not_defaulted() -> None:
    """New producers must consciously supply the complete semantic contract."""
    payload = _contract().model_dump(mode="json")
    del payload["structured_response"]
    with pytest.raises(ValidationError):
        ModelCapabilityContract.model_validate(payload)
    payload = _contract().model_dump(mode="json")
    payload["version"] = 1
    with pytest.raises(ValidationError):
        ModelCapabilityContract.model_validate(payload)


def test_contract_roundtrip_does_not_use_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Saved contract validation is local and independent of mutable source access."""

    def fail_connection(*args: object, **kwargs: object) -> Never:
        raise AssertionError("Capability contract validation must not use network I/O.")

    monkeypatch.setattr(socket.socket, "connect", fail_connection)
    monkeypatch.setattr(socket, "create_connection", fail_connection)
    capabilities = _capabilities(_contract())
    assert (
        ModelCapabilities.model_validate_json(capabilities.model_dump_json())
        == capabilities
    )
