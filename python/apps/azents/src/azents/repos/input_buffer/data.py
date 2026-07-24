"""InputBuffer repository data models."""

import datetime

from pydantic import BaseModel, Field

from azents.core.enums import InputBufferKind, InputBufferSchedulingMode
from azents.core.llm_catalog import ModelReasoningEffort
from azents.engine.events.types import FileOutputPart
from azents.rdb.models.event import JSONValue


class InputBuffer(BaseModel):
    """User input accepted but not yet injected into model turn."""

    id: str = Field(description="InputBuffer ID")
    session_id: str = Field(description="AgentSession ID")
    kind: InputBufferKind = Field(description="InputBuffer payload kind")
    scheduling_mode: InputBufferSchedulingMode = Field(
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
    created_at: datetime.datetime = Field(description="Accepted time")


class InputBufferCreate(BaseModel):
    """InputBuffer create schema."""

    session_id: str = Field(description="AgentSession ID")
    kind: InputBufferKind = Field(description="InputBuffer payload kind")
    scheduling_mode: InputBufferSchedulingMode = Field(
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
