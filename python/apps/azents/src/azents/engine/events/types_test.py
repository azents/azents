"""Event transcript type tests."""

import datetime

import pytest
from pydantic import ValidationError

from azents.core.enums import EventKind
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    RequestedInferenceProfile,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolResultPayload,
    Event,
    FileOutputPart,
    InputTextPart,
    NativeArtifact,
    ProviderToolResultPayload,
    SystemErrorPayload,
    TokenUsagePayload,
    TurnMarkerPayload,
    UserMessagePayload,
    build_native_compat_key,
)
from azents.engine.run.types import FunctionToolResult


def _artifact() -> NativeArtifact:
    """Create a native artifact for tests."""
    compat_key = build_native_compat_key(
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-5.1",
        schema_version="1",
    )
    return NativeArtifact(
        compat_key=compat_key,
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-5.1",
        schema_version="1",
        item={"type": "message"},
    )


def test_native_artifact_validates_compat_key() -> None:
    artifact = _artifact()

    assert artifact.compatible_with(
        "litellm:responses:openai:gpt-5.1:1",
    )
    assert not artifact.compatible_with(
        "litellm:responses:anthropic:claude-sonnet-4.5:1",
    )


def test_native_artifact_rejects_mismatched_compat_key() -> None:
    with pytest.raises(ValidationError):
        NativeArtifact(
            compat_key="wrong",
            adapter="litellm",
            native_format="responses",
            provider="openai",
            model="gpt-5.1",
            schema_version="1",
            item={"type": "message"},
        )


def test_event_accepts_matching_payload() -> None:
    now = datetime.datetime.now(datetime.UTC)

    event = Event(
        id="0" * 32,
        session_id="session-1",
        kind=EventKind.USER_MESSAGE,
        payload=UserMessagePayload(content="hello"),
        created_at=now,
    )

    assert event.kind == EventKind.USER_MESSAGE


def test_event_rejects_payload_kind_mismatch() -> None:
    now = datetime.datetime.now(datetime.UTC)

    with pytest.raises(ValidationError):
        Event(
            id="0" * 32,
            session_id="session-1",
            kind=EventKind.USER_MESSAGE,
            payload=AssistantMessagePayload(
                content="hello",
                native_artifact=_artifact(),
            ),
            created_at=now,
        )


def test_turn_marker_decodes_historical_payload_without_provenance() -> None:
    payload = TurnMarkerPayload.model_validate(
        {
            "run_id": "run-1",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "raw": {},
            },
        }
    )

    assert payload.applied_inference_profile is None
    assert payload.effective_context_window_tokens is None
    assert payload.effective_auto_compaction_threshold_tokens is None


def test_user_message_decodes_historical_payload_without_profile() -> None:
    payload = UserMessagePayload.model_validate({"content": "historical"})

    assert payload.applied_inference_profile is None


def test_user_message_decodes_historical_profile_without_display_name() -> None:
    payload = UserMessagePayload.model_validate(
        {
            "content": "historical",
            "applied_inference_profile": {
                "model_target_label": "Quality",
                "reasoning_effort": "high",
            },
        }
    )

    assert payload.applied_inference_profile is not None
    assert payload.applied_inference_profile.model_display_name is None


def test_user_message_preserves_requested_inference_profile() -> None:
    payload = UserMessagePayload(
        content="use quality",
        requested_inference_profile=RequestedInferenceProfile(
            model_target_label="Quality",
            reasoning_effort=None,
        ),
    )

    assert payload.model_dump(mode="json")["requested_inference_profile"] == {
        "model_target_label": "Quality",
        "reasoning_effort": None,
    }


def test_user_message_preserves_applied_inference_profile() -> None:
    payload = UserMessagePayload(
        content="use quality",
        applied_inference_profile=AppliedInferenceProfile(
            model_target_label="Quality",
            model_display_name="GPT 5.5",
            reasoning_effort=ModelReasoningEffort.HIGH,
        ),
    )

    assert payload.model_dump(mode="json", exclude_none=True) == {
        "content": "use quality",
        "attachments": [],
        "metadata": {},
        "applied_inference_profile": {
            "model_target_label": "Quality",
            "model_display_name": "GPT 5.5",
            "reasoning_effort": "high",
        },
    }


def test_user_message_accepts_text_and_file_parts() -> None:
    payload = UserMessagePayload(
        content=[
            InputTextPart(text="inspect"),
            FileOutputPart(
                model_file_id="model-file-1",
                media_type="application/pdf",
                name="file.pdf",
            ),
        ]
    )

    assert isinstance(payload.content, list)
    assert [part.type for part in payload.content] == ["input_text", "file"]


def test_file_output_part_drops_provider_specific_payload() -> None:
    payload = FileOutputPart.model_validate(
        {
            "type": "file",
            "model_file_id": "model-file-1",
            "media_type": "application/pdf",
            "name": "doc.pdf",
            "file_data": "data:application/pdf;base64,abc",
            "file_id": "provider-file-1",
            "metadata": {
                "file_data": "data:application/pdf;base64,abc",
                "safe": "value",
            },
        }
    )

    data = payload.model_dump(mode="json")
    assert "file_data" not in data
    assert "file_id" not in data
    assert payload.metadata == {"safe": "value"}


def test_system_error_payload_uses_event_fields() -> None:
    payload = SystemErrorPayload(
        content="Model call failed",
        severity="error",
        recoverable=True,
        reset_suggested=False,
    )

    assert payload.model_dump(mode="json", exclude_none=True) == {
        "content": "Model call failed",
        "severity": "error",
        "recoverable": True,
        "reset_suggested": False,
    }


def test_provider_tool_result_is_not_client_tool_result_subclass() -> None:
    payload = ProviderToolResultPayload(
        call_id="provider-1",
        name="image_generation",
        status="completed",
        native_artifact=_artifact(),
    )

    assert type(payload) is ProviderToolResultPayload
    assert not isinstance(payload, ClientToolResultPayload)


def test_function_tool_result_metadata_defaults_to_isolated_dicts() -> None:
    first = FunctionToolResult(output="one")
    second = FunctionToolResult(output="two")

    assert first.metadata == {}
    assert second.metadata == {}
    assert first.metadata is not second.metadata


def test_function_tool_result_metadata_requires_json_object() -> None:
    with pytest.raises(ValidationError):
        FunctionToolResult.model_validate({"output": "ok", "metadata": ["bad"]})


def test_client_tool_result_metadata_requires_json_object() -> None:
    payload = ClientToolResultPayload(
        call_id="call-1",
        status="completed",
        output="ok",
        metadata={"nested": {"items": ["stdout", None]}},
    )

    assert payload.metadata == {"nested": {"items": ["stdout", None]}}
    with pytest.raises(ValidationError):
        ClientToolResultPayload.model_validate(
            {
                "call_id": "call-1",
                "status": "completed",
                "output": "ok",
                "metadata": "bad",
            }
        )


def test_event_token_usage_requires_raw_payload() -> None:
    """Token usage cannot be stored without adapter raw payload."""
    with pytest.raises(ValidationError):
        TokenUsagePayload.model_validate(
            {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            }
        )
