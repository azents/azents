"""AgentSession create-request idempotency data models."""

import dataclasses
import datetime

from pydantic import BaseModel, Field


class AgentSessionCreateRequestRecord(BaseModel):
    """Durable authority for one AgentSession create request."""

    id: str = Field(description="AgentSession create request ID")
    user_id: str = Field(description="Requester User ID")
    agent_id: str = Field(description="Target Agent ID")
    client_request_id: str = Field(description="Client-generated idempotency key")
    payload_hash: str = Field(description="Canonical semantic request SHA-256")
    agent_session_id: str | None = Field(description="Created AgentSession ID")
    input_buffer_id: str | None = Field(description="Accepted first InputBuffer ID")
    input_buffer_snapshot: dict[str, object] | None = Field(
        description="Accepted first InputBuffer snapshot",
    )
    created_at: datetime.datetime = Field(description="Authority creation time")
    completed_at: datetime.datetime | None = Field(description="Completion time")


class AgentSessionCreateRequestClaim(BaseModel):
    """Create-request authority claim."""

    user_id: str = Field(description="Requester User ID")
    agent_id: str = Field(description="Target Agent ID")
    client_request_id: str = Field(description="Client-generated idempotency key")
    payload_hash: str = Field(description="Canonical semantic request SHA-256")


@dataclasses.dataclass(frozen=True)
class AgentSessionCreateRequestClaimResult:
    """Result of claiming one create-request authority."""

    record: AgentSessionCreateRequestRecord
    claimed: bool
