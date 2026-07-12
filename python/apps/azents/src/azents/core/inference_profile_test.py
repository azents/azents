"""Inference profile contract tests."""

import datetime

import pytest
from pydantic import ValidationError

from azents.core.agent import AgentModelSelection
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    RequestedInferenceProfile,
    SessionInferenceState,
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


@pytest.mark.parametrize(
    "effort",
    [
        ModelReasoningEffort.NONE,
        ModelReasoningEffort.MINIMAL,
        ModelReasoningEffort.XHIGH,
        ModelReasoningEffort.MAX,
    ],
)
def test_requested_profile_accepts_supported_expanded_effort(
    effort: ModelReasoningEffort,
) -> None:
    profile = RequestedInferenceProfile(
        model_target_label="Quality",
        reasoning_effort=effort,
    )

    assert profile.model_dump(mode="json") == {
        "model_target_label": "Quality",
        "reasoning_effort": effort.value,
    }


def test_requested_profile_rejects_unknown_effort_at_runtime() -> None:
    with pytest.raises(ValidationError):
        RequestedInferenceProfile.model_validate(
            {
                "model_target_label": "Quality",
                "reasoning_effort": "future-effort",
            }
        )


def test_public_profile_schema_exposes_opaque_nullable_effort() -> None:
    for profile_type in (RequestedInferenceProfile, AppliedInferenceProfile):
        schema = profile_type.model_json_schema()
        effort_schema = schema["properties"]["reasoning_effort"]
        assert effort_schema["anyOf"] == [
            {"type": "string"},
            {"type": "null"},
        ]


def test_applied_profile_accepts_persisted_payload_without_display_name() -> None:
    profile = AppliedInferenceProfile.model_validate(
        {
            "model_target_label": "Quality",
            "reasoning_effort": "high",
        }
    )

    assert profile.model_display_name is None


def test_session_state_projects_only_applied_public_settings() -> None:
    state = SessionInferenceState(
        model_target_label="Quality",
        model_selection=_selection(),
        reasoning_effort=ModelReasoningEffort.HIGH,
        effective_context_window_tokens=100_000,
        effective_auto_compaction_threshold_tokens=80_000,
        resolved_at=datetime.datetime.now(datetime.UTC),
    )

    assert state.applied_profile.model_dump(mode="json") == {
        "model_target_label": "Quality",
        "model_display_name": "GPT-5.4",
        "reasoning_effort": "high",
    }
    assert "llm_provider_integration_id" not in state.applied_profile.model_dump()
