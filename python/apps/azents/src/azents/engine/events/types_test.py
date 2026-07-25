"""Event transcript type tests."""

import datetime

import pytest
from pydantic import ValidationError

from azents.core.enums import (
    AgentRunStatus,
    EventKind,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
)
from azents.core.inference_profile import (
    AppliedInferenceProfile,
    RequestedInferenceProfile,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.engine.events.types import (
    ActiveToolCall,
    AgentMessagePayload,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    ExternalChannelMessagePayload,
    FileOutputPart,
    InputTextPart,
    NativeArtifact,
    ProviderToolCallPayload,
    ProviderToolReference,
    ProviderToolSemanticContent,
    SystemErrorPayload,
    TokenUsagePayload,
    TurnMarkerPayload,
    UserMessagePayload,
    build_native_compat_key,
    upgrade_persisted_active_tool_call,
    validate_event_payload,
    validate_persisted_event_payload,
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


def test_agent_result_requires_complete_terminal_metadata() -> None:
    with pytest.raises(ValidationError, match="source Run metadata"):
        AgentMessagePayload(
            message_kind="agent_result",
            source_session_agent_id="source-agent",
            source_path="/root/reviewer",
            target_session_agent_id="target-agent",
            target_path="/root",
            content="Done.",
        )


def test_agent_result_accepts_terminal_run_metadata() -> None:
    payload = AgentMessagePayload(
        message_kind="agent_result",
        source_session_agent_id="source-agent",
        source_path="/root/reviewer",
        target_session_agent_id="target-agent",
        target_path="/root",
        source_run_id="1" * 32,
        source_run_index=2,
        run_status=AgentRunStatus.COMPLETED,
        source_terminal_result_event_id=None,
        content="Done.",
    )

    assert payload.run_status is AgentRunStatus.COMPLETED


def test_instruction_agent_message_rejects_result_metadata() -> None:
    with pytest.raises(ValidationError, match="cannot include result metadata"):
        AgentMessagePayload(
            message_kind="send_message",
            source_session_agent_id="source-agent",
            source_path="/root/reviewer",
            target_session_agent_id="target-agent",
            target_path="/root",
            source_run_id="1" * 32,
            source_run_index=2,
            run_status=AgentRunStatus.COMPLETED,
            content="Done.",
        )


def test_event_accepts_matching_payload() -> None:
    now = datetime.datetime.now(datetime.UTC)

    event = Event(
        id="0" * 32,
        session_id="session-1",
        kind=EventKind.USER_MESSAGE,
        payload=UserMessagePayload(sender_user_id=None, content="hello"),
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


def _external_message_payload(
    *,
    revision_kind: ExternalChannelMessageRevisionKind = (
        ExternalChannelMessageRevisionKind.ORIGINAL
    ),
    lifecycle: ExternalChannelMessageLifecycle = (
        ExternalChannelMessageLifecycle.CURRENT
    ),
    projection_root_id: str = "external-channel:binding-1:message-1",
    correction_of_revision_id: str | None = None,
) -> ExternalChannelMessagePayload:
    """Create one canonical External Channel payload."""
    return ExternalChannelMessagePayload(
        provider=ExternalChannelProvider.SLACK,
        provider_tenant_id="tenant-1",
        resource_id="resource-1",
        resource_label="C123:1.0",
        resource_type=ExternalChannelResourceType.THREAD,
        binding_id="binding-1",
        invocation_batch_id="batch-1",
        external_message_id="message-1",
        revision_id="revision-1",
        revision_kind=revision_kind,
        projection_root_id=projection_root_id,
        provider_message_key="C123:1.0:1",
        provider_position="1",
        principal_id="principal-1",
        provider_user_id="U1",
        sender_display_name="Alice",
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        authorization="authorized_invocation",
        lifecycle=lifecycle,
        body="hello",
        attachment_metadata={},
        provider_created_at=datetime.datetime(2026, 7, 22, tzinfo=datetime.UTC),
        provider_updated_at=None,
        original_url=None,
        truncated_context_message_count=0,
        truncated_context_size=0,
        correction_of_revision_id=correction_of_revision_id,
    )


def test_external_message_payload_is_registered_for_event_kind() -> None:
    payload = _external_message_payload()

    validated = validate_event_payload(
        EventKind.EXTERNAL_CHANNEL_MESSAGE,
        payload.model_dump(mode="json"),
    )

    assert isinstance(validated, ExternalChannelMessagePayload)
    assert validated.projection_root_id == "external-channel:binding-1:message-1"


def test_external_message_payload_preserves_required_nullable_fields() -> None:
    payload = _external_message_payload().model_copy(
        update={
            "principal_id": None,
            "provider_user_id": None,
            "sender_display_name": None,
            "body": None,
            "provider_created_at": None,
            "provider_updated_at": None,
            "original_url": None,
            "correction_of_revision_id": None,
        }
    )

    serialized = payload.model_dump(mode="json", exclude_none=True)

    assert serialized["principal_id"] is None
    assert serialized["provider_user_id"] is None
    assert serialized["sender_display_name"] is None
    assert serialized["body"] is None
    assert serialized["provider_created_at"] is None
    assert serialized["provider_updated_at"] is None
    assert serialized["original_url"] is None
    assert serialized["correction_of_revision_id"] is None
    assert validate_event_payload(EventKind.EXTERNAL_CHANNEL_MESSAGE, serialized) == (
        payload
    )


def test_external_message_payload_rejects_inconsistent_projection_root() -> None:
    with pytest.raises(ValidationError, match="projection root"):
        _external_message_payload(projection_root_id="external-channel:wrong")


def test_external_message_payload_allows_correction_without_known_original() -> None:
    payload = _external_message_payload(
        revision_kind=ExternalChannelMessageRevisionKind.EDIT,
        lifecycle=ExternalChannelMessageLifecycle.EDITED,
    )

    assert payload.correction_of_revision_id is None


def test_external_message_payload_rejects_revision_lifecycle_mismatch() -> None:
    with pytest.raises(ValidationError, match="revision lifecycle"):
        _external_message_payload(
            revision_kind=ExternalChannelMessageRevisionKind.DELETE,
            lifecycle=ExternalChannelMessageLifecycle.EDITED,
            correction_of_revision_id="revision-original",
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

    assert payload.sender_user_id is None
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
        sender_user_id=None,
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
        sender_user_id=None,
        content="use quality",
        applied_inference_profile=AppliedInferenceProfile(
            model_target_label="Quality",
            model_display_name="GPT 5.5",
            reasoning_effort=ModelReasoningEffort.HIGH,
        ),
    )

    assert payload.model_dump(mode="json", exclude_none=True) == {
        "sender_user_id": None,
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
        sender_user_id=None,
        content=[
            InputTextPart(text="inspect"),
            FileOutputPart(
                model_file_id="model-file-1",
                media_type="application/pdf",
                name="file.pdf",
            ),
        ],
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


def test_provider_tool_call_is_not_client_tool_result_subclass() -> None:
    payload = ProviderToolCallPayload(
        call_id="provider-1",
        name="image_generation",
        status="completed",
        semantic=ProviderToolSemanticContent(
            input=None,
            output=[],
            references=[],
        ),
        native_artifact=_artifact(),
    )

    assert type(payload) is ProviderToolCallPayload
    assert not isinstance(payload, ClientToolResultPayload)


def test_provider_tool_required_nullable_fields_survive_exclude_none_dump() -> None:
    reference = ProviderToolReference(
        kind="url",
        uri=None,
        title=None,
        excerpt=None,
        metadata={},
    )
    payload = ProviderToolCallPayload(
        call_id="provider-1",
        name="web_search",
        status=None,
        semantic=ProviderToolSemanticContent(
            input=None,
            output=[],
            references=[reference],
        ),
        native_artifact=_artifact(),
    )

    dumped = payload.model_dump(mode="json", exclude_none=True)

    assert dumped["status"] is None
    assert dumped["semantic"]["input"] is None
    assert dumped["semantic"]["references"] == [
        {
            "kind": "url",
            "uri": None,
            "title": None,
            "excerpt": None,
            "metadata": {},
        }
    ]
    assert ProviderToolCallPayload.model_validate(dumped) == payload


def test_provider_tool_payload_rejects_legacy_positional_fields() -> None:
    with pytest.raises(ValidationError):
        ProviderToolCallPayload.model_validate(
            {
                "call_id": "provider-1",
                "name": "web_search",
                "arguments": '{"query":"Azents"}',
                "native_artifact": _artifact(),
            }
        )
    with pytest.raises(ValidationError):
        ProviderToolCallPayload.model_validate(
            {
                "call_id": "provider-1",
                "name": "web_search",
                "status": "completed",
                "output": "legacy",
                "native_artifact": _artifact(),
            }
        )


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
        wire_dialect="json_function",
    )

    assert payload.metadata == {"nested": {"items": ["stdout", None]}}
    with pytest.raises(ValidationError):
        ClientToolResultPayload.model_validate(
            {
                "call_id": "call-1",
                "wire_dialect": "json_function",
                "status": "completed",
                "output": "ok",
                "metadata": "bad",
            }
        )


def test_persisted_client_tool_payload_without_dialect_upgrades_to_json_function() -> (
    None
):
    payload = validate_persisted_event_payload(
        EventKind.CLIENT_TOOL_CALL,
        {
            "call_id": "call-1",
            "name": "read",
            "arguments": "{}",
            "native_artifact": _artifact().model_dump(mode="json"),
        },
    )

    assert isinstance(payload, ClientToolCallPayload)
    assert payload.wire_dialect == "json_function"


def test_new_client_tool_writer_requires_explicit_dialect() -> None:
    with pytest.raises(ValidationError):
        validate_event_payload(
            EventKind.CLIENT_TOOL_CALL,
            {
                "call_id": "call-1",
                "name": "read",
                "arguments": "{}",
                "native_artifact": _artifact().model_dump(mode="json"),
            },
        )


@pytest.mark.parametrize("wire_dialect", [None, "unknown"])
def test_persisted_client_tool_payload_rejects_nonlegacy_invalid_dialect(
    wire_dialect: object,
) -> None:
    with pytest.raises(ValidationError):
        validate_persisted_event_payload(
            EventKind.CLIENT_TOOL_CALL,
            {
                "call_id": "call-1",
                "name": "read",
                "arguments": "{}",
                "wire_dialect": wire_dialect,
                "native_artifact": _artifact().model_dump(mode="json"),
            },
        )


def test_persisted_active_tool_call_without_dialect_upgrades_to_json_function() -> None:
    active = ActiveToolCall.model_validate(
        upgrade_persisted_active_tool_call(
            {
                "call_id": "call-1",
                "name": "read",
                "arguments": "{}",
                "started_at": datetime.datetime.now(datetime.UTC),
                "owner_generation": 1,
            }
        )
    )

    assert active.wire_dialect == "json_function"


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
