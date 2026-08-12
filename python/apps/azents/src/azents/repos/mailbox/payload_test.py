"""Typed mailbox payload contract tests."""

import datetime
from typing import cast

import pytest
from pydantic import TypeAdapter, ValidationError

from azents.core.enums import (
    ActionExecutionStatus,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.engine.events.types import ExternalChannelMessagePayload
from azents.rdb.models.event import JSONValue
from azents.repos.mailbox.data import (
    AgentCreateGitWorktreeContinuationResult,
    ExternalChannelContinuationMailboxPayload,
    ExternalChannelMessageMailboxPayload,
    MailboxEnvelopePayload,
    MailboxItem,
    MailboxPresentationItem,
    TurnActionContinuationMailboxPayload,
    TurnActionMailboxPayload,
    UserMessageMailboxPayload,
)


def _item(
    *,
    payload: MailboxEnvelopePayload | None = None,
    kind: MailboxItemKind = MailboxItemKind.USER_MESSAGE,
) -> MailboxItem:
    return MailboxItem(
        id="0123456789abcdef0123456789abcdef",
        session_id="1123456789abcdef0123456789abcdef",
        kind=kind,
        scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        sender_user_id=None,
        order_group="0123456789abcdef0123456789abcdef",
        order_sequence=0,
        content="hello",
        idempotency_key=None,
        metadata={"source": "test"},
        action=None,
        attachments=[],
        file_parts=[],
        payload=payload,
        created_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
    )


def _external_message_data() -> dict[str, object]:
    return {
        "provider": ExternalChannelProvider.SLACK.value,
        "provider_tenant_id": "tenant-1",
        "resource_id": "resource-1",
        "resource_label": "C123:1.0",
        "resource_type": ExternalChannelResourceType.THREAD.value,
        "binding_id": "binding-1",
        "invocation_batch_id": "batch-1",
        "external_message_id": "message-1",
        "projection_root_id": "external-channel:binding-1:message-1",
        "provider_message_key": "C123:1.0:1",
        "provider_position": "1",
        "principal_id": None,
        "provider_user_id": None,
        "sender_display_name": None,
        "author_type": "human",
        "prompt_role": "context",
        "body": "hello",
        "attachment_metadata": {},
        "reference_mappings": {},
        "provider_created_at": None,
        "provider_updated_at": None,
        "original_url": None,
        "truncated_context_message_count": 0,
        "truncated_context_size": 0,
    }


def test_mailbox_payload_requires_non_empty_unique_item_keys() -> None:
    with pytest.raises(ValidationError):
        UserMessageMailboxPayload(
            type="user_message",
            items=[
                MailboxPresentationItem(item_key="same", presentation_kind="message"),
                MailboxPresentationItem(item_key="same", presentation_kind="message"),
            ],
        )


def test_mailbox_item_rejects_kind_payload_discriminator_mismatch() -> None:
    with pytest.raises(ValidationError, match="discriminator"):
        _item(
            payload=TurnActionMailboxPayload(
                type="action_message",
                items=[
                    MailboxPresentationItem(
                        item_key="action_message:0",
                        presentation_kind="action_message",
                    )
                ],
            )
        )


def test_external_channel_continuation_payload_is_distinct_from_goal() -> None:
    payload = ExternalChannelContinuationMailboxPayload(
        type="external_channel_continuation",
        items=[
            MailboxPresentationItem(
                item_key="external_channel_continuation:0",
                presentation_kind="external_channel_continuation",
            )
        ],
    )

    item = _item(
        payload=payload,
        kind=MailboxItemKind.EXTERNAL_CHANNEL_CONTINUATION,
    )

    assert item.payload is not None
    assert item.payload.type == "external_channel_continuation"


def test_turn_action_continuation_decodes_closed_typed_payload() -> None:
    """Persisted bridge continuation JSON decodes without raw business unions."""
    raw = {
        "type": "turn_action_continuation",
        "items": [
            {
                "item_key": "turn_action_continuation:0",
                "presentation_kind": "turn_action_continuation",
            }
        ],
        "bridge_identity": "bridge-001",
        "action_execution_id": "execution-001",
        "originating_run_id": "run-001",
        "predecessor_run_id": "run-002",
        "terminal_status": "cancelled",
        "reason_code": "ownership_handover",
        "failure_summary": None,
        "cancellation_summary": (
            "Operation cancelled during Session ownership handover."
        ),
        "result": {
            "type": "agent_create_git_worktree",
            "source_project_path": "/workspace/agent/repo",
            "generated_worktree_path": None,
            "requested_starting_ref": "main",
            "resolved_base_commit": None,
            "branch_name": None,
        },
    }

    payload = TypeAdapter(MailboxEnvelopePayload).validate_python(raw)

    assert isinstance(payload, TurnActionContinuationMailboxPayload)
    assert payload.terminal_status is ActionExecutionStatus.CANCELLED
    assert payload.cancellation_summary == (
        "Operation cancelled during Session ownership handover."
    )
    assert isinstance(payload.result, AgentCreateGitWorktreeContinuationResult)


def test_turn_action_continuation_rejects_unbounded_terminal_summary() -> None:
    """Terminal explanations remain bounded before entering model context."""
    with pytest.raises(ValidationError):
        TurnActionContinuationMailboxPayload(
            type="turn_action_continuation",
            items=[
                MailboxPresentationItem(
                    item_key="turn_action_continuation:0",
                    presentation_kind="turn_action_continuation",
                )
            ],
            bridge_identity="bridge-001",
            action_execution_id="execution-001",
            originating_run_id="run-001",
            predecessor_run_id="run-002",
            terminal_status=ActionExecutionStatus.FAILED,
            reason_code=None,
            failure_summary="x" * 1001,
            cancellation_summary=None,
            result=AgentCreateGitWorktreeContinuationResult(
                type="agent_create_git_worktree",
                source_project_path="/workspace/agent/repo",
                generated_worktree_path=None,
                requested_starting_ref=None,
                resolved_base_commit=None,
                branch_name=None,
            ),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider", "unknown"),
        ("resource_label", ""),
    ),
)
def test_external_payload_rejects_malformed_provider_or_resource(
    field: str,
    value: object,
) -> None:
    payload = _external_message_data()
    payload[field] = value
    with pytest.raises(ValidationError):
        ExternalChannelMessagePayload.model_validate(payload)


def test_external_payload_rejects_more_than_one_message() -> None:
    with pytest.raises(ValidationError, match="requires one message"):
        ExternalChannelMessageMailboxPayload(
            type="external_channel_message",
            items=[
                MailboxPresentationItem(
                    item_key="external_channel_message:0",
                    presentation_kind="external_channel_message",
                    metadata=cast(
                        dict[str, JSONValue],
                        {"external_channel_message": _external_message_data()},
                    ),
                ),
                MailboxPresentationItem(
                    item_key="external_channel_message:1",
                    presentation_kind="external_channel_message",
                    metadata=cast(
                        dict[str, JSONValue],
                        {"external_channel_message": _external_message_data()},
                    ),
                ),
            ],
        )
