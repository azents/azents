"""Inference profile contract tests."""

import datetime

import pytest
from pydantic import ValidationError

from azents.core.agent import AgentModelSelection
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    AppliedModelRoute,
    RequestedInferenceProfile,
    SessionAppliedInferenceProfile,
    SessionInferenceState,
)
from azents.core.llm_catalog import ModelCapabilities, ModelReasoningEffort
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.testing.model_selection import make_test_model_settings


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
        enabled_execution_options=[],
    )

    assert profile.reasoning_effort is None


def test_session_applied_profile_contains_only_agent_owned_intent() -> None:
    """Applied Session intent excludes physical model configuration."""
    profile = SessionAppliedInferenceProfile(
        model_target_label="Quality",
        reasoning_effort=ModelReasoningEffort.HIGH,
        enabled_execution_options=[],
    )

    assert profile.model_dump(mode="json") == {
        "model_target_label": "Quality",
        "reasoning_effort": "high",
        "enabled_execution_options": [],
    }


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
        enabled_execution_options=[],
    )

    assert profile.model_dump(mode="json") == {
        "model_target_label": "Quality",
        "reasoning_effort": effort.value,
        "enabled_execution_options": [],
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
        model_settings=make_test_model_settings(),
        reasoning_effort=ModelReasoningEffort.HIGH,
        effective_context_window_tokens=100_000,
        effective_auto_compaction_threshold_tokens=80_000,
        resolved_at=datetime.datetime.now(datetime.UTC),
        enabled_execution_options=[],
        applied_model_route=AppliedModelRoute(
            operation_id="operation-1",
            operation_kind="foreground",
            candidate_ordinal=2,
            candidate_role="fallback",
            provider=LLMProvider.OPENAI,
            llm_provider_integration_id="integration-secret-boundary",
            model_identifier="gpt-5.4",
            model_display_name="GPT-5.4",
            effective_context_window_tokens=100_000,
            effective_auto_compaction_threshold_tokens=80_000,
        ),
    )

    assert state.applied_profile.model_dump(mode="json") == {
        "model_target_label": "Quality",
        "model_display_name": "GPT-5.4",
        "reasoning_effort": "high",
        "enabled_execution_options": [],
    }
    assert "llm_provider_integration_id" not in state.applied_profile.model_dump()
    assert state.applied_model_route is not None
    assert state.applied_model_route.candidate_role == "fallback"
    assert state.using_fallback is True


def _profile_payload(
    profile_type: type[
        RequestedInferenceProfile
        | AppliedInferenceProfile
        | SessionAppliedInferenceProfile
        | SessionInferenceState
    ],
    enabled: list[str],
) -> dict[str, object]:
    """Build required fields without bypassing runtime profile validation."""
    payload: dict[str, object] = {
        "model_target_label": "Quality",
        "reasoning_effort": "high",
        "enabled_execution_options": enabled,
    }
    if profile_type is SessionInferenceState:
        payload.update(
            model_selection=_selection(),
            model_settings=make_test_model_settings(),
            effective_context_window_tokens=100_000,
            effective_auto_compaction_threshold_tokens=80_000,
            resolved_at=datetime.datetime.now(datetime.UTC),
        )
    return payload


@pytest.mark.parametrize(
    "profile_type",
    [
        RequestedInferenceProfile,
        AppliedInferenceProfile,
        SessionAppliedInferenceProfile,
        SessionInferenceState,
    ],
)
@pytest.mark.parametrize("enabled", [[], ["fast"], ["ultrafast"]])
def test_every_profile_accepts_valid_speed_preference(
    profile_type: type[
        RequestedInferenceProfile
        | AppliedInferenceProfile
        | SessionAppliedInferenceProfile
        | SessionInferenceState
    ],
    enabled: list[str],
) -> None:
    """Requested, applied, and prepared shapes all recognize Ultrafast."""
    profile = profile_type.model_validate(_profile_payload(profile_type, enabled))
    assert profile.enabled_execution_options == [
        ModelExecutionOptionId(option) for option in enabled
    ]
    assert profile.model_dump(mode="json")["enabled_execution_options"] == enabled


@pytest.mark.parametrize(
    "profile_type",
    [
        RequestedInferenceProfile,
        AppliedInferenceProfile,
        SessionAppliedInferenceProfile,
        SessionInferenceState,
    ],
)
@pytest.mark.parametrize(
    ("enabled", "message"),
    [
        (["fast", "ultrafast"], "exclusive"),
        (["ultrafast", "fast"], "exclusive"),
        (["fast", "fast"], "unique"),
        (["ultrafast", "ultrafast"], "unique"),
        (["future-speed"], "Input should be"),
    ],
)
def test_every_profile_rejects_invalid_speed_shape(
    profile_type: type[
        RequestedInferenceProfile
        | AppliedInferenceProfile
        | SessionAppliedInferenceProfile
        | SessionInferenceState
    ],
    enabled: list[str],
    message: str,
) -> None:
    """Invalid preferences fail instead of being silently rewritten."""
    with pytest.raises(ValidationError, match=message):
        profile_type.model_validate(_profile_payload(profile_type, enabled))


@pytest.mark.parametrize(
    "profile_type",
    [RequestedInferenceProfile, AppliedInferenceProfile],
)
def test_historical_profiles_keep_ordinary_preference(
    profile_type: type[RequestedInferenceProfile | AppliedInferenceProfile],
) -> None:
    """Retain only the existing historical decoding boundary."""
    profile = profile_type.model_validate(
        {"model_target_label": "Quality", "reasoning_effort": None}
    )
    assert profile.enabled_execution_options == []


@pytest.mark.parametrize(
    "profile_type",
    [SessionAppliedInferenceProfile, SessionInferenceState],
)
def test_nonhistorical_profiles_require_explicit_enabled_options(
    profile_type: type[SessionAppliedInferenceProfile | SessionInferenceState],
) -> None:
    """Do not broaden historical defaults to other profile contracts."""
    payload = _profile_payload(profile_type, [])
    del payload["enabled_execution_options"]
    with pytest.raises(ValidationError, match="enabled_execution_options"):
        profile_type.model_validate(payload)
