"""Chat v1 public schema contract tests."""

import datetime

from azents.api.public.chat.v1.data import (
    AgentSessionModelAvailabilityResponse,
    AgentSessionResponse,
    ChatEditMessageWriteRequest,
    ChatLiveRunRetryStateResponse,
    ChatMessageWriteRequest,
    ChatSessionModelProfileResponse,
    ChatSessionModelProfileUpdateRequest,
    UploadResponse,
)
from azents.core.enums import (
    AgentSessionProductMode,
    AgentSessionRunState,
    AgentSessionStatus,
)
from azents.core.inference_profile import (
    SessionAppliedInferenceProfile,
    SessionInferenceState,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_availability import (
    ModelCandidateIdentity,
    SessionModelAvailability,
)
from azents.repos.agent_session.data import AgentSession
from azents.services.chat.data import ChatLiveRunRetryState


def test_upload_response_does_not_expose_file_part() -> None:
    """Upload returns only attachment metadata and does not create FilePart."""
    response = UploadResponse(
        attachment_id="attachment-1",
        uri="exchange://workspace/agent/file",
        media_type="image/png",
        size=10,
        name="image.png",
    )

    assert "file_part" not in response.model_dump(mode="json")


def test_model_profile_contract_contains_only_session_intent() -> None:
    """The model-profile API does not expose physical model details."""
    request = ChatSessionModelProfileUpdateRequest(
        client_request_id="request-1",
        model_target_label="Quality",
        reasoning_effort=ModelReasoningEffort.HIGH,
        enabled_execution_options=[],
    )
    response = ChatSessionModelProfileResponse(
        session_id="session-1",
        model_target_label=request.model_target_label,
        reasoning_effort=request.reasoning_effort,
        enabled_execution_options=request.enabled_execution_options,
    )

    assert set(response.model_dump(mode="json")) == {
        "session_id",
        "model_target_label",
        "reasoning_effort",
        "enabled_execution_options",
    }
    assert "model_selection" not in response.model_dump(mode="json")


def test_model_profile_update_accepts_historical_payload_without_options() -> None:
    """Existing clients may omit execution options and retain all-off intent."""
    request = ChatSessionModelProfileUpdateRequest.model_validate(
        {
            "client_request_id": "request-1",
            "model_target_label": "Quality",
            "reasoning_effort": "high",
        }
    )

    assert request.enabled_execution_options == []


def test_model_availability_response_converts_core_projection() -> None:
    """The public availability response accepts the core Pydantic model."""
    now = datetime.datetime.now(datetime.UTC)
    availability = SessionModelAvailability(
        semantic_label="Quality",
        primary=ModelCandidateIdentity(
            llm_provider_integration_id="integration-1",
            model_identifier="model-1",
        ),
        primary_display_name="Primary model",
        state="available",
        deadline=None,
        server_time=now,
        first_usable_fallback_display_name=None,
        reservation=None,
    )

    response = AgentSessionModelAvailabilityResponse.from_domain(availability)

    assert response.model_dump(mode="json") == availability.model_dump(mode="json")


def test_session_projection_reads_applied_intent_not_prepared_state() -> None:
    """Public Session fields never expose the prepared physical snapshot."""
    now = datetime.datetime.now(datetime.UTC)
    session = AgentSession.model_construct(
        id="session-1",
        agent_id="agent-1",
        applied_inference_profile=SessionAppliedInferenceProfile(
            model_target_label="new",
            reasoning_effort=None,
            enabled_execution_options=[],
        ),
        inference_state=SessionInferenceState.model_construct(
            model_target_label="old",
        ),
        title=None,
        title_source=None,
        status=AgentSessionStatus.ACTIVE,
        primary_kind=None,
        product_mode=AgentSessionProductMode.TEAM,
        run_state=AgentSessionRunState.IDLE,
        pinned=False,
        archived_at=None,
        purge_after=None,
        archive_retention_days_snapshot=None,
        created_at=now,
        updated_at=now,
    )

    response = AgentSessionResponse.from_domain(
        session,
        unread_terminal_run_id=None,
        auto_archive_after=None,
    )

    assert response.current_model_target_label == "new"
    assert response.current_reasoning_effort is None


def test_chat_message_write_request_ignores_client_owned_file_parts() -> None:
    """Client-sent FilePart is not owned by the public schema."""
    request = ChatMessageWriteRequest.model_validate(
        {
            "agent_id": "agent-1",
            "client_request_id": "request-1",
            "message": "hello",
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
            "attachments": ["exchange://workspace/agent/file"],
            "file_parts": [
                {
                    "type": "file",
                    "model_file_id": "model-file-1",
                    "media_type": "image/png",
                }
            ],
        }
    )

    assert not hasattr(request, "file_parts")
    assert request.attachments == ["exchange://workspace/agent/file"]


def test_chat_edit_message_write_request_ignores_client_owned_file_parts() -> None:
    """Edit requests also do not own client-owned FilePart in the public schema."""
    request = ChatEditMessageWriteRequest.model_validate(
        {
            "agent_id": "agent-1",
            "client_request_id": "request-1",
            "message_id": "message-1",
            "message": "hello",
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
            "attachments": ["exchange://workspace/agent/file"],
            "file_parts": [
                {
                    "type": "file",
                    "model_file_id": "model-file-1",
                    "media_type": "image/png",
                }
            ],
        }
    )

    assert not hasattr(request, "file_parts")
    assert request.attachments == ["exchange://workspace/agent/file"]


def test_live_retry_response_preserves_error_kind() -> None:
    """REST live retry state keeps the provider/runtime presentation kind."""
    response = ChatLiveRunRetryStateResponse.from_domain(
        ChatLiveRunRetryState(
            error_kind="model_provider",
            status="waiting",
            last_error_message="Model provider error: Request rejected.",
            failed_attempt_count=1,
            max_retries=10,
            backoff_seconds=1,
            next_retry_at="2026-07-18T00:00:01+00:00",
            attempts=[],
        )
    )

    assert response.model_dump(mode="json")["error_kind"] == "model_provider"
