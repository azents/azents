"""Chat v1 public schema contract tests."""

from azents.api.public.chat.v1.data import (
    ChatEditMessageWriteRequest,
    ChatMessageWriteRequest,
    UploadResponse,
)


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
