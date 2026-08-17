"""MailboxItem repository data models."""

import datetime
from typing import Annotated, Literal, TypeAlias, cast

from pydantic import BaseModel, Field, model_validator

from azents.core.enums import (
    ActionExecutionStatus,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.core.llm_catalog import ModelReasoningEffort
from azents.engine.events.types import FileOutputPart
from azents.rdb.models.event import JSONValue


class MailboxPresentationItem(BaseModel):
    """Stable presentation item embedded in a mailbox envelope."""

    item_key: str = Field(min_length=1)
    presentation_kind: str = Field(min_length=1)
    content: str = ""
    metadata: dict[str, JSONValue] = Field(default_factory=dict)
    action: dict[str, JSONValue] | None = None
    attachments: list[str] = Field(default_factory=list)
    file_parts: list[FileOutputPart] = Field(default_factory=list)


class MailboxPayloadBase(BaseModel):
    """Common validated envelope payload shape."""

    items: list[MailboxPresentationItem] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_item_keys(self) -> "MailboxPayloadBase":
        """Require deterministic, non-empty, unique presentation keys."""
        keys = [item.item_key for item in self.items]
        if len(keys) != len(set(keys)):
            raise ValueError("Mailbox payload item keys must be unique.")
        return self


class UserMessageMailboxPayload(MailboxPayloadBase):
    """Typed user-message mailbox payload."""

    type: Literal["user_message"]


class GoalContinuationMailboxPayload(MailboxPayloadBase):
    """Typed goal-continuation mailbox payload."""

    type: Literal["goal_continuation"]


class ExternalChannelContinuationMailboxPayload(MailboxPayloadBase):
    """Typed External Channel continuation mailbox payload."""

    type: Literal["external_channel_continuation"]


class ScheduledTaskTriggerMailboxPayload(MailboxPayloadBase):
    """Typed Scheduled Task cycle trigger mailbox payload."""

    type: Literal["scheduled_task_trigger"]
    cycle_id: str = Field(min_length=32, max_length=32)


class ScheduledTaskContinuationMailboxPayload(MailboxPayloadBase):
    """Typed Scheduled Task cycle continuation mailbox payload."""

    type: Literal["scheduled_task_continuation"]
    cycle_id: str = Field(min_length=32, max_length=32)


class AgentCreateGitWorktreeContinuationResult(BaseModel):
    """Bounded model-facing result for an Agent worktree create action."""

    type: Literal["agent_create_git_worktree"]
    source_project_path: str = Field(min_length=1)
    generated_worktree_path: str | None
    requested_starting_ref: str | None
    resolved_base_commit: str | None
    branch_name: str | None


class AgentRemoveGitWorktreeContinuationResult(BaseModel):
    """Bounded model-facing result for an Agent worktree remove action."""

    type: Literal["agent_remove_git_worktree"]
    worktree_path: str = Field(min_length=1)
    preserved_branch_name: str | None
    force: bool
    dirty_content_discarded: bool
    retry_guidance: str | None


TurnActionContinuationResult: TypeAlias = Annotated[
    AgentCreateGitWorktreeContinuationResult | AgentRemoveGitWorktreeContinuationResult,
    Field(discriminator="type"),
]


class TurnActionContinuationMailboxPayload(MailboxPayloadBase):
    """Hidden one-shot model continuation for a terminal registered bridge."""

    type: Literal["turn_action_continuation"]
    bridge_identity: str = Field(min_length=1)
    action_execution_id: str = Field(min_length=1)
    originating_run_id: str = Field(min_length=1)
    predecessor_run_id: str = Field(min_length=1)
    terminal_status: Literal[
        ActionExecutionStatus.COMPLETED,
        ActionExecutionStatus.FAILED,
        ActionExecutionStatus.CANCELLED,
    ]
    reason_code: str | None
    failure_summary: str | None = Field(max_length=1000)
    cancellation_summary: str | None = Field(max_length=1000)
    result: TurnActionContinuationResult


class AgentMessageMailboxPayload(MailboxPayloadBase):
    """Typed Agent-message mailbox payload."""

    type: Literal["agent_message"]


class ExternalChannelMessageMailboxPayload(MailboxPayloadBase):
    """Typed immutable single-message External Channel snapshot."""

    type: Literal["external_channel_message"]
    context_omitted: bool = False
    initial_title_eligible: bool = False

    @model_validator(mode="after")
    def validate_single_message(self) -> "ExternalChannelMessageMailboxPayload":
        """Require exactly one canonical provider-message presentation."""
        if len(self.items) != 1:
            raise ValueError("External Channel mailbox payload requires one message.")
        item = self.items[0]
        if (
            item.item_key != "external_channel_message:0"
            or item.presentation_kind != "external_channel_message"
        ):
            raise ValueError("External Channel mailbox message shape is invalid.")
        return self


class TurnActionMailboxPayload(MailboxPayloadBase):
    """Typed Turn Action mailbox payload."""

    type: Literal["action_message"]


MailboxEnvelopePayload: TypeAlias = Annotated[
    UserMessageMailboxPayload
    | GoalContinuationMailboxPayload
    | ExternalChannelContinuationMailboxPayload
    | ScheduledTaskTriggerMailboxPayload
    | ScheduledTaskContinuationMailboxPayload
    | TurnActionContinuationMailboxPayload
    | AgentMessageMailboxPayload
    | ExternalChannelMessageMailboxPayload
    | TurnActionMailboxPayload,
    Field(discriminator="type"),
]


def mailbox_payload_from_fields(
    *,
    kind: MailboxItemKind,
    content: str,
    metadata: dict[str, str],
    action: dict[str, JSONValue] | None,
    attachments: list[str],
    file_parts: list[FileOutputPart],
) -> MailboxEnvelopePayload:
    """Build a closed typed payload from admission-boundary fields."""
    item = MailboxPresentationItem(
        item_key=f"{kind.value}:0",
        presentation_kind=kind.value,
        content=content,
        metadata=cast(dict[str, JSONValue], metadata),
        action=action,
        attachments=attachments,
        file_parts=file_parts,
    )
    if kind is MailboxItemKind.USER_MESSAGE:
        return UserMessageMailboxPayload(type=kind.value, items=[item])
    if kind is MailboxItemKind.GOAL_CONTINUATION:
        return GoalContinuationMailboxPayload(type=kind.value, items=[item])
    if kind is MailboxItemKind.EXTERNAL_CHANNEL_CONTINUATION:
        return ExternalChannelContinuationMailboxPayload(type=kind.value, items=[item])
    if kind is MailboxItemKind.SCHEDULED_TASK_TRIGGER:
        return ScheduledTaskTriggerMailboxPayload(
            type=kind.value,
            cycle_id=metadata.get("cycle_id", ""),
            items=[item],
        )
    if kind is MailboxItemKind.SCHEDULED_TASK_CONTINUATION:
        return ScheduledTaskContinuationMailboxPayload(
            type=kind.value,
            cycle_id=metadata.get("cycle_id", ""),
            items=[item],
        )
    if kind is MailboxItemKind.TURN_ACTION_CONTINUATION:
        raise ValueError(
            "TurnAction continuation admission requires its closed typed payload"
        )
    if kind is MailboxItemKind.AGENT_MESSAGE:
        return AgentMessageMailboxPayload(type=kind.value, items=[item])
    if kind is MailboxItemKind.EXTERNAL_CHANNEL_MESSAGE:
        return ExternalChannelMessageMailboxPayload(type=kind.value, items=[item])
    return TurnActionMailboxPayload(type=kind.value, items=[item])


class MailboxItem(BaseModel):
    """User input accepted but not yet injected into model turn."""

    id: str = Field(description="MailboxItem ID")
    session_id: str = Field(description="AgentSession ID")
    kind: MailboxItemKind = Field(description="MailboxItem payload kind")
    scheduling_mode: MailboxSchedulingMode = Field(
        description="Producer-selected session scheduling intent",
    )
    requested_model_target_label: str | None = Field(
        description="Requested Agent-owned model target label",
    )
    requested_reasoning_effort: ModelReasoningEffort | None = Field(
        description="Requested reasoning effort, or null for Default/inheritance",
    )
    sender_user_id: str | None = Field(description="Author User ID")
    order_group: str = Field(description="Stable FIFO order group")
    order_sequence: int = Field(ge=0, description="Sequence within the FIFO group")
    content: str = Field(description="Input body")
    idempotency_key: str | None = Field(description="Source idempotency key")
    metadata: dict[str, str] = Field(description="Input metadata snapshot")
    action: dict[str, JSONValue] | None = Field(
        default=None,
        description="Action payload snapshot",
    )
    attachments: list[str] = Field(description="Attachment URI snapshot")
    file_parts: list[FileOutputPart] = Field(
        description="Model input FilePart snapshot",
    )
    payload: MailboxEnvelopePayload | None = Field(
        default=None,
        description="Closed immutable typed mailbox envelope payload",
    )
    created_at: datetime.datetime = Field(description="Accepted time")

    @model_validator(mode="after")
    def ensure_payload(self) -> "MailboxItem":
        """Ensure fixtures and admission callers always expose a typed payload."""
        if self.payload is None:
            self.payload = mailbox_payload_from_fields(
                kind=self.kind,
                content=self.content,
                metadata=self.metadata,
                action=self.action,
                attachments=self.attachments,
                file_parts=self.file_parts,
            )
        elif self.payload.type != self.kind.value:
            raise ValueError("Mailbox item kind must match payload discriminator.")
        return self

    @property
    def presentation(self) -> MailboxPresentationItem:
        """Return the first typed presentation item for single-item processors."""
        assert self.payload is not None
        return self.payload.items[0]


class MailboxItemCreate(BaseModel):
    """MailboxItem create schema."""

    session_id: str = Field(description="AgentSession ID")
    kind: MailboxItemKind = Field(description="MailboxItem payload kind")
    scheduling_mode: MailboxSchedulingMode = Field(
        description="Producer-selected session scheduling intent",
    )
    requested_model_target_label: str | None = Field(
        description="Requested Agent-owned model target label",
    )
    requested_reasoning_effort: ModelReasoningEffort | None = Field(
        description="Requested reasoning effort, or null for Default/inheritance",
    )
    sender_user_id: str | None = Field(description="Author User ID")
    order_group: str | None = Field(
        description="Stable FIFO order group, or null to use the new row ID",
    )
    order_sequence: int = Field(ge=0, description="Sequence within the FIFO group")
    content: str = Field(description="Input body")
    idempotency_key: str | None = Field(description="Source idempotency key")
    metadata: dict[str, str] = Field(description="Input metadata snapshot")
    action: dict[str, JSONValue] | None = Field(
        default=None,
        description="Action payload snapshot",
    )
    attachments: list[str] = Field(description="Attachment URI snapshot")
    file_parts: list[FileOutputPart] = Field(
        description="Model input FilePart snapshot",
    )
    payload: MailboxEnvelopePayload | None = Field(
        default=None,
        description="Closed immutable typed mailbox envelope payload",
    )
