"""Common durable execution data independent of public Conversation identity."""

import datetime

from pydantic import BaseModel, Field

from azents.core.enums import (
    AgentSessionEndReason,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
)
from azents.core.inference_profile import (
    SessionAppliedInferenceProfile,
    SessionInferenceState,
)


class SessionExecutionRecord(BaseModel):
    """Detached canonical execution record, including profile-free sessions."""

    id: str = Field(description="AgentSession ID")
    workspace_id: str = Field(description="Workspace ID")
    agent_id: str = Field(description="Agent ID")
    inference_state: SessionInferenceState | None = Field(
        description="Resolved inference configuration prepared for the current turn",
    )
    applied_inference_profile: SessionAppliedInferenceProfile | None = Field(
        description="Agent-owned model intent applied to the Session",
    )
    applied_profile_generation: int = Field(
        ge=0,
        description="Monotonic generation of accepted applied-profile replacements",
    )
    status: AgentSessionStatus = Field(description="AgentSession status")
    start_reason: AgentSessionStartReason = Field(description="Start reason")
    last_activity_at: datetime.datetime = Field(
        description="Latest user, Agent, or tool activity timestamp",
    )
    end_reason: AgentSessionEndReason | None = Field(description="End reason")
    model_input_head_event_id: str | None = Field(
        description="Model input head event ID",
    )
    model_file_gc_cursor_event_id: str | None = Field(
        description="ModelFile GC cursor event ID",
    )
    started_at: datetime.datetime = Field(description="Start time")
    lifecycle_started_at: datetime.datetime | None = Field(
        description="Lifecycle start hook claim time"
    )
    run_state: AgentSessionRunState = Field(
        description="Session execution state",
    )
    run_heartbeat_at: datetime.datetime = Field(
        description="Run heartbeat time",
    )
    owner_generation: int = Field(
        ge=0,
        description="Durable session ownership generation",
    )
    stop_requested_at: datetime.datetime | None = Field(
        description="Stop intent timestamp",
    )
    stop_requester_user_id: str | None = Field(description="Stop requester User ID")
    stop_request_id: str | None = Field(description="Stop request correlation ID")
    archived_at: datetime.datetime | None = Field(
        description="Archive boundary timestamp"
    )
    purge_after: datetime.datetime | None = Field(
        description="Scheduled purge eligibility timestamp"
    )
    archive_policy_revision: int | None = Field(
        description="Retention policy revision snapshot"
    )
    archive_retention_days_snapshot: int | None = Field(
        description="Retention days snapshot; null means Unlimited"
    )
    ended_at: datetime.datetime | None = Field(description="End time")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")
    lifecycle_root_session_id: str | None = Field(
        description="Null denotes the execution's own lifecycle root"
    )
    model_file_gc_updated_at: datetime.datetime | None = Field(
        description="Last model-file GC cursor update"
    )
