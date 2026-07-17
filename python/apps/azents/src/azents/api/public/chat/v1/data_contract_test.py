"""Chat v1 public schema contract tests."""

import datetime

from azents.api.public.chat.v1.data import (
    ChatEditMessageWriteRequest,
    ChatLiveRunStateResponse,
    ChatMessageWriteRequest,
    ChatStoppedRunRetryRequest,
    UploadResponse,
)
from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.core.inference_profile import AppliedInferenceProfile
from azents.services.chat.data import (
    ChatLiveRunOperation,
    ChatLiveRunRecoveryState,
    ChatLiveRunState,
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


def test_stopped_run_retry_request_uses_run_identity() -> None:
    """Stopped retry targets the recoverable Run rather than a history event."""
    request = ChatStoppedRunRetryRequest(
        agent_id="agent-1",
        stopped_run_id="run-1",
        client_request_id="request-1",
    )

    assert request.model_dump(mode="json") == {
        "agent_id": "agent-1",
        "stopped_run_id": "run-1",
        "client_request_id": "request-1",
    }


def test_live_run_response_exposes_operation_and_stopped_recovery() -> None:
    """REST live state uses the shared minimal operation and recovery shapes."""
    profile = AppliedInferenceProfile(
        model_target_label="main",
        model_display_name="Test model",
        reasoning_effort=None,
    )
    active = ChatLiveRunStateResponse.from_domain(
        ChatLiveRunState(
            run_id="run-1",
            phase=AgentRunPhase.COMPACTING,
            status=AgentRunStatus.RUNNING,
            inference_profile=profile,
            model_call_started_at=datetime.datetime(
                2026,
                7,
                17,
                tzinfo=datetime.UTC,
            ),
            operation=ChatLiveRunOperation(
                kind="preparing_context",
                operation_id="run-1",
                status="running",
            ),
        )
    )
    stopped = ChatLiveRunStateResponse.from_domain(
        ChatLiveRunState(
            run_id="run-2",
            phase=AgentRunPhase.IDLE,
            status=AgentRunStatus.STOPPED,
            inference_profile=profile,
            model_call_started_at=None,
            recovery=ChatLiveRunRecoveryState(
                kind="provider_failure",
                user_message="Model provider error: quota exhausted",
                operation="compaction",
                source_run_id="run-2",
                stopped_at="2026-07-17T00:00:00+00:00",
            ),
        )
    )
    directly_stopped = ChatLiveRunStateResponse.from_domain(
        ChatLiveRunState(
            run_id="run-3",
            phase=AgentRunPhase.IDLE,
            status=AgentRunStatus.STOPPED,
            inference_profile=profile,
            model_call_started_at=None,
            recovery=ChatLiveRunRecoveryState(
                kind="stopped",
                user_message="Execution stopped.",
                operation="sampling",
                source_run_id="run-3",
                stopped_at="2026-07-17T00:01:00+00:00",
            ),
        )
    )

    assert active.operation is not None
    assert active.operation.model_dump(mode="json") == {
        "kind": "preparing_context",
        "operation_id": "run-1",
        "status": "running",
    }
    assert active.recovery is None
    assert stopped.operation is None
    assert stopped.recovery is not None
    assert stopped.recovery.model_dump(mode="json") == {
        "kind": "provider_failure",
        "user_message": "Model provider error: quota exhausted",
        "operation": "compaction",
        "source_run_id": "run-2",
        "stopped_at": "2026-07-17T00:00:00+00:00",
    }
    assert directly_stopped.recovery is not None
    assert directly_stopped.recovery.model_dump(mode="json") == {
        "kind": "stopped",
        "user_message": "Execution stopped.",
        "operation": "sampling",
        "source_run_id": "run-3",
        "stopped_at": "2026-07-17T00:01:00+00:00",
    }
