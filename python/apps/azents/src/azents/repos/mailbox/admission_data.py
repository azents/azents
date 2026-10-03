"""Detached inputs and results for Mailbox admission operations."""

import dataclasses

from azents.core.enums import MailboxItemKind, MailboxSchedulingMode
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.engine.events.types import FileOutputPart
from azents.rdb.models.event import JSONValue
from azents.repos.mailbox.data import MailboxEnvelopePayload, MailboxItem


@dataclasses.dataclass(frozen=True)
class MailboxEnqueue:
    """Input buffer enqueue request."""

    session_id: str
    kind: MailboxItemKind
    scheduling_mode: MailboxSchedulingMode
    requested_model_target_label: str | None
    requested_reasoning_effort: ModelReasoningEffort | None
    requested_enabled_execution_options: list[ModelExecutionOptionId]
    sender_user_id: str | None
    order_group: str | None
    order_sequence: int
    content: str
    idempotency_key: str | None
    metadata: dict[str, str]
    attachments: list[str]
    file_parts: list[FileOutputPart]
    action: dict[str, JSONValue] | None
    payload: MailboxEnvelopePayload | None


@dataclasses.dataclass(frozen=True)
class MailboxAdmissionResult:
    """Input buffer enqueue result."""

    mailbox_item: MailboxItem
    created: bool
