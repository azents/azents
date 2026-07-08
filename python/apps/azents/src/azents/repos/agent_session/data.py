"""AgentSession repository data models."""

import datetime

from pydantic import BaseModel, Field

from azents.core.enums import (
    AgentSessionEndReason,
    AgentSessionKind,
    AgentSessionPrimaryKind,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    AgentSessionTitleSource,
)


class AgentSession(BaseModel):
    """AgentSession domain model."""

    id: str = Field(description="AgentSession ID")
    workspace_id: str = Field(description="Workspace ID")
    agent_id: str = Field(description="Agent ID")
    handle: str = Field(description="Human-readable session handle")
    session_kind: AgentSessionKind = Field(description="Session listing category")
    status: AgentSessionStatus = Field(description="AgentSession status")
    primary_kind: AgentSessionPrimaryKind | None = Field(
        default=None,
        description="Primary session role",
    )
    start_reason: AgentSessionStartReason = Field(description="Start reason")
    title: str | None = Field(description="User-facing session title")
    title_source: AgentSessionTitleSource | None = Field(
        description="Source of the current session title",
    )
    title_generated_at: datetime.datetime | None = Field(
        description="Automatic title generation time",
    )
    title_generation_event_id: str | None = Field(
        description="Event ID used for automatic title generation",
    )
    last_user_input_at: datetime.datetime = Field(
        description="Latest user input timestamp or creation-time baseline",
    )
    end_reason: AgentSessionEndReason | None = Field(
        default=None, description="End reason"
    )
    model_input_head_event_id: str | None = Field(
        default=None,
        description="Model input head event ID",
    )
    model_input_head_model_order: int | None = Field(
        default=None,
        description="Model input head model order",
    )
    model_file_gc_cursor_event_id: str | None = Field(
        default=None,
        description="ModelFile GC cursor event ID",
    )
    model_file_gc_cursor_model_order: int = Field(
        default=0,
        description="ModelFile GC cursor model order",
    )
    started_at: datetime.datetime = Field(description="Start time")
    lifecycle_started_at: datetime.datetime | None = Field(
        default=None, description="Lifecycle start hook claim time"
    )
    run_state: AgentSessionRunState = Field(
        default=AgentSessionRunState.IDLE,
        description="Session execution state",
    )
    run_heartbeat_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.UTC),
        description="Run heartbeat time",
    )
    pending_command_id: str | None = Field(
        default=None, description="Pending command ID"
    )
    pending_command_name: str | None = Field(
        default=None, description="Pending command name"
    )
    pending_command_payload: dict[str, object] | None = Field(
        default=None,
        description="Pending command payload",
    )
    pending_command_user_id: str | None = Field(
        default=None, description="Pending command user ID"
    )
    pending_command_created_at: datetime.datetime | None = Field(
        default=None,
        description="Pending command created timestamp",
    )
    stop_requested_at: datetime.datetime | None = Field(
        default=None,
        description="Stop intent timestamp",
    )
    stop_requested_by: str | None = Field(
        default=None, description="Stop requesting user ID"
    )
    stop_request_id: str | None = Field(
        default=None, description="Stop request correlation ID"
    )
    ended_at: datetime.datetime | None = Field(default=None, description="End time")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class PendingSessionCommand(BaseModel):
    """AgentSession pending command."""

    id: str = Field(description="Pending command ID")
    name: str = Field(description="Command name")
    payload: dict[str, object] = Field(description="Command payload")
    user_id: str | None = Field(description="Command requesting user ID")
    created_at: datetime.datetime = Field(description="Command created timestamp")


class AgentSessionCreate(BaseModel):
    """AgentSession create schema."""

    workspace_id: str = Field(description="Workspace ID")
    agent_id: str = Field(description="Agent ID")
    title: str | None = Field(description="User-facing session title")
    session_kind: AgentSessionKind = Field(
        default=AgentSessionKind.ROOT,
        description="Session listing category",
    )
    primary_kind: AgentSessionPrimaryKind | None = Field(
        default=None,
        description="Primary session role",
    )
    start_reason: AgentSessionStartReason = Field(
        default=AgentSessionStartReason.INITIAL,
        description="Start reason",
    )
