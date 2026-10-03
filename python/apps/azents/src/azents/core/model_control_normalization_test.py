"""Assigned models retain identity while effective controls become compatible."""

import pytest

from azents.core.inference_profile import (
    RequestedInferenceProfile,
    adapt_inference_profile_to_model,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.testing.model_selection import make_test_model_selection


@pytest.mark.parametrize(
    ("requested", "supported", "expected"),
    [
        ("high", ["low", "high"], "high"),
        ("high", ["low", "medium"], "medium"),
        ("low", ["high", "xhigh"], "high"),
        ("max", ["low", "high", "xhigh"], "xhigh"),
        ("high", [], None),
        (None, ["low", "high"], None),
    ],
)
def test_assigned_model_adapts_effort_and_drops_only_unsupported_options(
    requested: str | None, supported: list[str], expected: str | None
) -> None:
    selection = make_test_model_selection(model_identifier="fixed-model")
    selection.normalized_capabilities.reasoning.supported = bool(supported)
    selection.normalized_capabilities.reasoning.effort_levels = [
        ModelReasoningEffort(value) for value in supported
    ]
    selection.supported_execution_options = []
    profile = RequestedInferenceProfile(
        model_target_label="Quality",
        reasoning_effort=ModelReasoningEffort(requested) if requested else None,
        enabled_execution_options=[ModelExecutionOptionId.FAST],
    )
    before = profile.model_dump_json()
    model_before = selection.model_dump_json()
    applied = adapt_inference_profile_to_model(profile, selection)
    assert applied.reasoning_effort == expected
    assert applied.enabled_execution_options == []
    assert applied.model_target_label == "Quality"
    assert selection.model_identifier == "fixed-model"
    assert profile.model_dump_json() == before
    assert selection.model_dump_json() == model_before


def test_assigned_model_keeps_supported_options() -> None:
    selection = make_test_model_selection()
    selection.supported_execution_options = [ModelExecutionOptionId.FAST]
    profile = RequestedInferenceProfile(
        model_target_label="Quality",
        reasoning_effort=None,
        enabled_execution_options=[ModelExecutionOptionId.FAST],
    )
    assert adapt_inference_profile_to_model(profile, selection) == profile
