"""Target identity compatibility and ambiguity regression tests."""

import hashlib
import json

import pytest

from azents_llm_contract.target import InferenceTarget


def test_canonical_material_is_shared_and_exact() -> None:
    target = InferenceTarget("default", "integration-a", "provider/model")
    assert (
        target.target_id
        == hashlib.sha256(b'["default","integration-a","provider/model"]').hexdigest()
    )


def test_identity_does_not_depend_on_candidate_position() -> None:
    first = InferenceTarget("default", "integration-a", "model")
    second = InferenceTarget("default", "integration-b", "model")
    original = {target.target_id: target for target in (first, second)}
    reordered = {target.target_id: target for target in (second, first)}
    assert original == reordered
    assert first.target_id != second.target_id


@pytest.mark.parametrize(
    "other",
    [
        InferenceTarget("lightweight", "integration-a", "model"),
        InferenceTarget("default", "integration-b", "model"),
        InferenceTarget("default", "integration-a", "Model"),
        InferenceTarget("default", "integration-a", "model "),
    ],
)
def test_each_component_distinguishes_targets(other: InferenceTarget) -> None:
    assert (
        InferenceTarget("default", "integration-a", "model").target_id
        != other.target_id
    )


def test_structured_encoding_has_no_delimiter_collisions() -> None:
    assert (
        InferenceTarget("a:b", "c", "d").target_id
        != InferenceTarget("a", "b:c", "d").target_id
    )


def test_unicode_encoding_does_not_normalize_provider_identifiers() -> None:
    target = InferenceTarget("기본", "integration-a", "모델/é")
    material = json.dumps(
        ["기본", "integration-a", "모델/é"], ensure_ascii=False, separators=(",", ":")
    )
    assert target.target_id == hashlib.sha256(material.encode()).hexdigest()
    assert (
        target.target_id
        != InferenceTarget("기본", "integration-a", "모델/e\u0301").target_id
    )


@pytest.mark.parametrize("parts", [("", "a", "b"), ("a", "", "b"), ("a", "b", "")])
def test_empty_identity_is_rejected(parts: tuple[str, str, str]) -> None:
    with pytest.raises(ValueError, match="nonempty"):
        InferenceTarget(*parts)
