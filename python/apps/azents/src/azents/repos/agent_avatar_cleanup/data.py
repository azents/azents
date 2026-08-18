"""Agent avatar cleanup repository data models."""

import datetime

from pydantic import BaseModel, Field

from azents.services.uploads.schema import StoredImage


class AgentAvatarCleanupJob(BaseModel):
    """One durable cleanup responsibility for a superseded avatar."""

    id: str = Field(description="Avatar cleanup job ID")
    agent_id: str | None = Field(
        ...,
        description="Original Agent ID retained only for diagnostics",
    )
    avatar: StoredImage = Field(description="Immutable internal avatar snapshot")
    attempt_count: int = Field(ge=0, description="Claimed deletion attempt count")
    next_attempt_at: datetime.datetime | None = Field(
        ...,
        description="Next eligible deletion attempt time",
    )
    lease_token: str | None = Field(..., description="Current cleanup pass token")
    lease_until: datetime.datetime | None = Field(
        ...,
        description="Current lease expiry",
    )
    last_failure_kind: str | None = Field(
        ...,
        description="Bounded latest deletion failure classification",
    )
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")
