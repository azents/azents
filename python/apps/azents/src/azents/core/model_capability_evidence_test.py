"""Presence-aware provider evidence validation and canonical JSON replay."""

import json

import pytest
from pydantic import ValidationError

from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_catalog_source import CatalogFact


def test_evidence_replays_absent_null_false_and_empty_independently() -> None:
    evidence = ProviderCapabilityEvidence(
        reasoning=CatalogFact(state="null", value=None),
        function_calling=CatalogFact(state="value", value=False),
        reasoning_efforts=CatalogFact(state="value", value=()),
        input_modalities=CatalogFact(state="value", value=()),
        output_modalities=CatalogFact(state="value", value=("text", "future-media")),
    )
    restored = ProviderCapabilityEvidence.model_validate_json(
        evidence.model_dump_json()
    )

    assert restored == evidence
    assert restored.temperature == CatalogFact(state="absent", value=None)
    assert restored.reasoning == CatalogFact(state="null", value=None)
    assert restored.function_calling == CatalogFact(state="value", value=False)
    assert restored.reasoning_efforts == CatalogFact(state="value", value=())
    assert restored.input_modalities == CatalogFact(state="value", value=())
    assert restored.output_modalities.value == ("text", "future-media")


def test_evidence_does_not_intersect_explicit_effort_arrays() -> None:
    evidence = ProviderCapabilityEvidence(
        reasoning_efforts=CatalogFact(
            state="value",
            value=(ModelReasoningEffort.XHIGH, ModelReasoningEffort.MAX),
        ),
        default_reasoning_effort=CatalogFact(
            state="value", value=ModelReasoningEffort.MAX
        ),
    )
    restored = ProviderCapabilityEvidence.model_validate_json(
        evidence.model_dump_json()
    )

    assert restored.reasoning_efforts.value == (
        ModelReasoningEffort.XHIGH,
        ModelReasoningEffort.MAX,
    )
    assert restored.default_reasoning_effort.value == ModelReasoningEffort.MAX
    assert restored.reasoning.state == "absent"


@pytest.mark.parametrize(
    "payload",
    [
        {"function_calling": {"state": "absent", "value": False}},
        {"function_calling": {"state": "null", "value": True}},
        {"function_calling": {"state": "value", "value": None}},
        {"function_calling": {"state": "value", "value": "false"}},
        {"max_input_tokens": {"state": "value", "value": True}},
        {"max_input_tokens": {"state": "value", "value": -1}},
        {"max_output_tokens": {"state": "value", "value": 2**63}},
        {"input_modalities": {"state": "value", "value": ["text", "text"]}},
        {"input_modalities": {"state": "value", "value": list(map(str, range(257)))}},
        {"reasoning_efforts": {"state": "value", "value": ["max", "max"]}},
        {"reasoning_efforts": {"state": "value", "value": ["ultra"]}},
        {"unknown_runtime_hint": True},
    ],
)
def test_evidence_rejects_malformed_restored_declarations(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ProviderCapabilityEvidence.model_validate_json(json.dumps(payload))
