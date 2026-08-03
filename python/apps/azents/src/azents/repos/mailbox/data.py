"""MailboxItem repository data models."""

import datetime
from typing import Annotated, Literal, TypeAlias, cast

from pydantic import BaseModel, Field, model_validator

from azents.core.enums import MailboxItemKind, MailboxSchedulingMode
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


class AgentMessageMailboxPayload(MailboxPayloadBase):
    """Typed Agent-message mailbox payload."""

    type: Literal["agent_message"]


class ExternalChannelInvocationMailboxPayload(MailboxPayloadBase):
    """Typed immutable External Channel invocation snapshot."""

    type: Literal["external_channel_invocation"]
    initial_title_eligible: bool = False

    @model_validator(mode="after")
    def validate_item_sequence(self) -> "ExternalChannelInvocationMailboxPayload":
        """Require the immutable projection order to remain contiguous."""
        expected_keys = [
            f"external_channel:{index}" for index in range(len(self.items))
        ]
        if [item.item_key for item in self.items] != expected_keys:
            raise ValueError("External invocation batch sequence is not contiguous.")
        return self


class TurnActionMailboxPayload(MailboxPayloadBase):
    """Typed Turn Action mailbox payload."""

    type: Literal["action_message"]


MailboxEnvelopePayload: TypeAlias = Annotated[
    UserMessageMailboxPayload
    | GoalContinuationMailboxPayload
    | ExternalChannelContinuationMailboxPayload
    | AgentMessageMailboxPayload
    | ExternalChannelInvocationMailboxPayload
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
        item_key=(
            "external_channel:0"
            if kind is MailboxItemKind.EXTERNAL_CHANNEL_INVOCATION
            else f"{kind.value}:0"
        ),
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
    if kind is MailboxItemKind.AGENT_MESSAGE:
        return AgentMessageMailboxPayload(type=kind.value, items=[item])
    if kind is MailboxItemKind.EXTERNAL_CHANNEL_INVOCATION:
        return ExternalChannelInvocationMailboxPayload(type=kind.value, items=[item])
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
