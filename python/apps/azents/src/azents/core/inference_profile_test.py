"""Inference profile contract tests."""

import datetime

import pytest
from pydantic import ValidationError

from azents.core.agent import AgentModelSelection
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.inference_profile import (
    RequestedInferenceProfile,
    ResolvedInferenceProfileSummary,
)
from azents.core.llm_catalog import ModelCapabilities, ModelReasoningEffort


def _selection() -> AgentModelSelection:
    return AgentModelSelection(
        llm_provider_integration_id="integration-secret-boundary",
        provider=LLMProvider.OPENAI,
        model_identifier="gpt-5.4",
        model_display_name="GPT-5.4",
        model_developer=LLMModelDeveloper.OPENAI,
        model_family="gpt-5",
        normalized_capabilities=ModelCapabilities(),
        model_snapshot={"private_catalog_detail": "not-public"},
        source_metadata={"private_diagnostic": "not-public"},
        last_refreshed_at=datetime.datetime.now(datetime.UTC),
    )


def test_requested_profile_requires_explicit_nullable_effort() -> None:
    with pytest.raises(ValidationError):
        RequestedInferenceProfile.model_validate({"model_target_label": "Quality"})

    profile = RequestedInferenceProfile(
        model_target_label="Quality",
        reasoning_effort=None,
    )

    assert profile.reasoning_effort is None


def test_requested_profile_accepts_normalized_effort() -> None:
    profile = RequestedInferenceProfile(
        model_target_label="Quality",
        reasoning_effort=ModelReasoningEffort.HIGH,
    )

    assert profile.model_dump(mode="json") == {
        "model_target_label": "Quality",
        "reasoning_effort": "high",
    }


def test_resolved_summary_excludes_internal_snapshot_data() -> None:
    summary = ResolvedInferenceProfileSummary.from_model_selection(_selection())
    dumped = summary.model_dump(mode="json")

    assert dumped == {
        "provider": "openai",
        "model_identifier": "gpt-5.4",
        "model_display_name": "GPT-5.4",
        "model_developer": "openai",
    }
    assert "llm_provider_integration_id" not in dumped
    assert "model_snapshot" not in dumped
    assert "source_metadata" not in dumped
