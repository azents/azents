"""Immutable public chat write acceptance outcomes."""

import dataclasses

from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.repos.chat_write_request.data import ChatWriteRequest
from azents.repos.mailbox.data import MailboxItem


@dataclasses.dataclass(frozen=True)
class AcceptedChatWriteRequest:
    """REST write request acceptance result."""

    session_id: str
    record: ChatWriteRequest
    created: bool


@dataclasses.dataclass(frozen=True)
class AcceptedEditInput:
    """REST edit acceptance and edited input buffer creation result."""

    request: AcceptedChatWriteRequest
    mailbox_item: MailboxItem | None


@dataclasses.dataclass(frozen=True)
class AcceptedPendingCommand:
    """REST command acceptance and pending command storage result."""

    request: AcceptedChatWriteRequest
    command_id: str | None


@dataclasses.dataclass(frozen=True)
class AcceptedFailedRunRetry:
    """REST failed-run retry acceptance result."""

    request: AcceptedChatWriteRequest
    failed_event_id: str


@dataclasses.dataclass(frozen=True)
class AcceptedModelProfile:
    """REST model-profile replacement acceptance result."""

    request: AcceptedChatWriteRequest
    model_target_label: str
    reasoning_effort: ModelReasoningEffort | None
    enabled_execution_options: list[ModelExecutionOptionId]


@dataclasses.dataclass(frozen=True)
class AcceptedStopRequest:
    """REST stop intent recording result."""

    session_id: str
    stop_request_id: str
    runtime_was_running: bool
    stopped_session_ids: list[str]
