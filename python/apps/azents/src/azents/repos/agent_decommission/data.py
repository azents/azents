"""Agent decommission repository data models."""

import datetime

from pydantic import BaseModel, Field

from azents.core.enums import AgentDecommissionStatus


class AgentDecommissionJob(BaseModel):
    """Durable Agent decommission job."""

    id: str = Field(description="Decommission job ID")
    agent_id: str = Field(description="Target Agent ID")
    workspace_id: str = Field(description="Target Workspace ID")
    requested_by_workspace_user_id: str | None = Field(
        default=None,
        description="WorkspaceUser that requested decommission",
    )
    status: AgentDecommissionStatus = Field(description="Job status")
    attempt_count: int = Field(ge=0, description="Attempt count")
    lease_owner: str | None = Field(default=None, description="Lease owner")
    lease_until: datetime.datetime | None = Field(
        default=None,
        description="Lease expiry",
    )
    next_attempt_at: datetime.datetime | None = Field(
        default=None,
        description="Scheduled retry time",
    )
    last_error_kind: str | None = Field(default=None, description="Last error kind")
    last_error_summary: str | None = Field(
        default=None,
        description="Last safe error summary",
    )
    started_at: datetime.datetime | None = Field(
        default=None,
        description="First processing time",
    )
    completed_at: datetime.datetime | None = Field(
        default=None,
        description="Completion time",
    )
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")
