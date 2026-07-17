"""Chat transport projection tests."""

import datetime

from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.core.inference_profile import AppliedInferenceProfile
from azents.services.chat.data import (
    ChatLiveRunOperation,
    ChatLiveRunRecoveryState,
    ChatLiveRunState,
)
from azents.transport.chat import chat_live_run_updated_dump


def test_live_run_dump_exposes_minimal_operation_and_recovery() -> None:
    """WebSocket live Run uses the same minimal contract as REST."""
    profile = AppliedInferenceProfile(
        model_target_label="main",
        model_display_name="Test model",
        reasoning_effort=None,
    )
    active = chat_live_run_updated_dump(
        "session-1",
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
        ),
    )
    stopped = chat_live_run_updated_dump(
        "session-1",
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
        ),
    )

    active_run = active["run"]
    assert isinstance(active_run, dict)
    assert active_run["operation"] == {
        "kind": "preparing_context",
        "operation_id": "run-1",
        "status": "running",
    }
    assert active_run["recovery"] is None
    stopped_run = stopped["run"]
    assert isinstance(stopped_run, dict)
    assert stopped_run["operation"] is None
    assert stopped_run["recovery"] == {
        "kind": "provider_failure",
        "user_message": "Model provider error: quota exhausted",
        "operation": "compaction",
        "source_run_id": "run-2",
        "stopped_at": "2026-07-17T00:00:00+00:00",
    }
