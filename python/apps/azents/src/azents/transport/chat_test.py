"""Chat transport projection tests."""

import datetime

from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.core.inference_profile import AppliedInferenceProfile
from azents.services.chat.data import (
    ChatLiveRunOperation,
    ChatLiveRunState,
    PendingMailboxEnvelope,
    PendingMailboxItem,
    PendingMailboxUserMessagePresentation,
)
from azents.testing.types import is_string_object_dict
from azents.transport.chat import (
    chat_live_run_updated_dump,
    chat_mailbox_item_removed_dump,
    chat_mailbox_item_upserted_dump,
)


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
    assert is_string_object_dict(run)
    assert run["operation"] == {
        "kind": "preparing_context",
        "operation_id": "run-1:preparing-context",
        "status": "running",
    }
    assert "recovery" not in run


def test_mailbox_actions_use_typed_envelope_and_mailbox_identity() -> None:
    """Pending mailbox actions never use generic live-event vocabulary."""
    envelope = PendingMailboxEnvelope(
        mailbox_item_id="mailbox-1",
        session_id="session-1",
        kind="user_message",
        scheduling_mode="wake_session",
        created_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
        items=[
            PendingMailboxItem(
                id="mailbox-1:user_message:0",
                mailbox_item_id="mailbox-1",
                item_key="user_message:0",
                kind="user_message",
                created_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
                presentation=PendingMailboxUserMessagePresentation(
                    type="user_message",
                    content="hello",
                ),
            )
        ],
    )

    upserted = chat_mailbox_item_upserted_dump(envelope)
    removed = chat_mailbox_item_removed_dump("session-1", "mailbox-1")

    assert upserted["type"] == "mailbox_item_upserted"
    assert upserted["mailbox_item"] == envelope.model_dump(mode="json")
    assert removed == {
        "type": "mailbox_item_removed",
        "session_id": "session-1",
        "mailbox_item_id": "mailbox-1",
    }
