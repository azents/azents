"""Message repository data models."""

import datetime

from pydantic import BaseModel, Field

from azents.core.enums import MessageRole
from azents.engine.run.types import FunctionToolCall
from azents.transport.chat import ChatAttachmentSnapshot


class ChatMessage(BaseModel):
    """Message domain model for REST responses."""

    id: str = Field(description="Message ID")
    session_id: str = Field(description="Session ID")
    role: MessageRole = Field(description="Message role")
    content: str | None = Field(description="Message content")
    tool_calls: list[FunctionToolCall] | None = Field(description="Tool call list")
    tool_call_id: str | None = Field(description="Tool call ID")
    attachments: list[ChatAttachmentSnapshot] = Field(
        default_factory=list[ChatAttachmentSnapshot], description="Attachment list"
    )
    reasoning_summary: str | None = Field(
        default=None, description="Reasoning summary text"
    )
    usage: dict[str, object] | None = Field(
        default=None, description="Token usage by turn"
    )
    metadata: dict[str, str] | None = Field(
        default=None, description="Message metadata"
    )
    created_at: datetime.datetime = Field(description="Creation timestamp")
