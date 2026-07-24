"""ChatWriteRequest repository data models."""

import datetime

from pydantic import BaseModel, Field

from azents.rdb.models.chat_write_request import ChatWriteRequestType


class ChatWriteRequest(BaseModel):
    """REST write idempotency record."""

    id: str = Field(description="ChatWriteRequest ID")
    session_id: str = Field(description="AgentSession ID")
    requester_user_id: str = Field(description="Authenticated requester User ID")
    client_request_id: str = Field(description="Client-generated idempotency key")
    write_type: ChatWriteRequestType = Field(description="Write request type")
    accepted_type: ChatWriteRequestType = Field(description="Accepted target type")
    accepted_id: str = Field(description="Accepted target ID")
    history_reload_required: bool = Field(
        description="Whether durable history reload is required"
    )
    payload: dict[str, object] = Field(description="Write request snapshot")
    created_at: datetime.datetime = Field(description="Creation timestamp")


class ChatWriteRequestCreate(BaseModel):
    """ChatWriteRequest creation schema."""

    session_id: str = Field(description="AgentSession ID")
    requester_user_id: str = Field(description="Authenticated requester User ID")
    client_request_id: str = Field(description="Client-generated idempotency key")
    write_type: ChatWriteRequestType = Field(description="Write request type")
    accepted_type: ChatWriteRequestType = Field(description="Accepted target type")
    accepted_id: str = Field(description="Accepted target ID")
    history_reload_required: bool = Field(
        description="Whether durable history reload is required"
    )
    payload: dict[str, object] = Field(description="Write request snapshot")
