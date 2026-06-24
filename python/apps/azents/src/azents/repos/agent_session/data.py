"""AgentSession repository data models."""

import datetime

from pydantic import BaseModel, Field

from azents.core.enums import (
    AgentSessionEndReason,
    AgentSessionStartReason,
    AgentSessionStatus,
)


class AgentSession(BaseModel):
    """AgentSession domain model."""

    id: str = Field(description="AgentSession ID")
    workspace_id: str = Field(description="Workspace ID")
    agent_runtime_id: str = Field(description="AgentRuntime ID")
    agent_id: str = Field(description="Agent ID")
    status: AgentSessionStatus = Field(description="AgentSession status")
    start_reason: AgentSessionStartReason = Field(description="Start reason")
    end_reason: AgentSessionEndReason | None = Field(
        default=None, description="End reason"
    )
    started_at: datetime.datetime = Field(description="Start time")
    lifecycle_started_at: datetime.datetime | None = Field(
        default=None, description="Lifecycle start hook claim time"
    )
    ended_at: datetime.datetime | None = Field(default=None, description="End time")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class AgentSessionCreate(BaseModel):
    """AgentSession create schema."""

    workspace_id: str = Field(description="Workspace ID")
    agent_runtime_id: str = Field(description="AgentRuntime ID")
    agent_id: str = Field(description="Agent ID")
    start_reason: AgentSessionStartReason = Field(
        default=AgentSessionStartReason.INITIAL,
        description="Start reason",
    )
