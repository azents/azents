"""Chat transport projection tests."""

import datetime

from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.core.inference_profile import AppliedInferenceProfile
from azents.services.chat.data import ChatLiveRunOperation, ChatLiveRunState
from azents.transport.chat import chat_live_run_updated_dump


def test_live_run_dump_exposes_minimal_operation() -> None:
    """WebSocket live Run uses the same minimal operation contract as REST."""
    profile = AppliedInferenceProfile(
        model_target_label="main",
        model_display_name="Test model",
        reasoning_effort=None,
    )
    dumped = chat_live_run_updated_dump(
        "session-1",
        ChatLiveRunState(
            run_id="run-1",
            phase=AgentRunPhase.COMPACTING,
            status=AgentRunStatus.RUNNING,
            inference_profile=profile,
            model_call_started_at=datetime.datetime(
                2026,
                7,
                18,
                tzinfo=datetime.UTC,
            ),
            operation=ChatLiveRunOperation(
                kind="preparing_context",
                operation_id="run-1:preparing-context",
                status="running",
            ),
        ),
    )

    run = dumped["run"]
    assert isinstance(run, dict)
    assert run["operation"] == {
        "kind": "preparing_context",
        "operation_id": "run-1:preparing-context",
        "status": "running",
    }
    assert "recovery" not in run
