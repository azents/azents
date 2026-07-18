"""Chat v1 public schema contract tests."""

from azents.api.public.chat.v1.data import (
    ChatEditMessageWriteRequest,
    ChatLiveRunRetryStateResponse,
    ChatMessageWriteRequest,
    UploadResponse,
)
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
