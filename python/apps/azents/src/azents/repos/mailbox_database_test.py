"""Mailbox action identity restoration preserves opaque action relay semantics."""

import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import MailboxItemKind, MailboxSchedulingMode
from azents.rdb.models.event import JSONValue
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.data import MailboxItem, MailboxPresentationItem
from azents.repos.mailbox_database import MailboxDatabaseRepository


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        (None, None),
        ({}, None),
        ({"type": None}, None),
        ({"type": 1}, None),
        ({"type": False}, None),
        ({"type": []}, None),
        ({"type": ""}, ""),
        (
            {"type": "future_action", "extension": {"nested": [1, None]}},
            "future_action",
        ),
    ],
)
def test_action_identity_preserves_permissive_discriminator_and_opaque_fields(
    action: dict[str, JSONValue] | None,
    expected: str | None,
) -> None:
    item = MailboxPresentationItem(
        item_key="action_message:0",
        presentation_kind="action_message",
        action=action,
    )
    assert item.action_identity.action_type == expected
    encoded = item.model_dump(mode="json")
    assert encoded["action"] == action
    assert "action_identity" not in encoded
    assert "_action_identity" not in encoded
    assert "action_identity" not in item.model_json_schema()["properties"]
    restored = MailboxPresentationItem.model_validate_json(item.model_dump_json())
    assert restored.action_identity == item.action_identity


@pytest.mark.parametrize(
    "kind", [MailboxItemKind.ACTION_MESSAGE, MailboxItemKind.USER_MESSAGE]
)
async def test_seen_action_uses_restored_identity_and_preserves_kind_filter(
    kind: MailboxItemKind,
) -> None:
    pending = MailboxItem(
        id="mailbox",
        session_id="session",
        kind=kind,
        scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        requested_enabled_execution_options=[],
        sender_user_id=None,
        order_group="default",
        order_sequence=1,
        content="",
        idempotency_key=None,
        metadata={},
        action={"type": "future_action", "extension": "retained"},
        attachments=[],
        file_parts=[],
        created_at=datetime.datetime.now(datetime.UTC),
    )
    mailbox = AsyncMock(spec=MailboxRepository)
    mailbox.list_by_session_id.return_value = [pending]
    executions = AsyncMock(spec=ActionExecutionRepository)
    executions.has_action_type_by_session_id.return_value = False
    transcript = AsyncMock(spec=EventTranscriptRepository)
    transcript.has_action_execution_result_with_type.return_value = False
    repository = MailboxDatabaseRepository(mailbox, transcript, executions)
    found = await repository.has_seen_action_type(
        AsyncMock(spec=AsyncSession), session_id="session", action_type="future_action"
    )
    assert found is (kind is MailboxItemKind.ACTION_MESSAGE)
    if found:
        executions.has_action_type_by_session_id.assert_not_awaited()
        transcript.has_action_execution_result_with_type.assert_not_awaited()
