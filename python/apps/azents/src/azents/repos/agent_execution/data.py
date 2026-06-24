"""Event agent execution repository data models."""

import datetime

from pydantic import BaseModel, Field

from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionEndReason,
    AgentSessionStartReason,
    AgentSessionStatus,
    EventKind,
)
from azents.engine.events.types import ActiveToolCall
from azents.rdb.models.event import JSONValue


class EventCreate(BaseModel):
    """Event create schema."""

    session_id: str = Field(description="AgentSession ID")
    kind: EventKind = Field(description="Event kind")
    payload: dict[str, JSONValue] = Field(description="Event payload")
    model_order: int | None = Field(
        default=None,
        description="Model input logical order",
    )
    external_id: str | None = Field(default=None, description="Dedup key")
    adapter: str | None = Field(default=None, description="Adapter name")
    provider: str | None = Field(default=None, description="Provider name")
    model: str | None = Field(default=None, description="Model name")
    native_format: str | None = Field(default=None, description="Native format")
    schema_version: str = Field(default="1", description="Event schema version")


class EventSessionCreate(BaseModel):
    """Event session create schema."""

    id: str | None = Field(default=None, description="AgentSession ID")
    workspace_id: str = Field(description="Workspace ID")
    agent_runtime_id: str = Field(description="AgentRuntime ID")
    agent_id: str = Field(description="Agent ID")
    status: AgentSessionStatus = Field(
        default=AgentSessionStatus.ACTIVE,
        description="Session status",
    )
    start_reason: AgentSessionStartReason = Field(
        default=AgentSessionStartReason.INITIAL,
        description="Start reason",
    )
    end_reason: AgentSessionEndReason | None = Field(
        default=None,
        description="End reason",
    )
    ended_at: datetime.datetime | None = Field(default=None, description="End time")


class EventSessionState(BaseModel):
    """Event session state."""

    id: str = Field(description="AgentSession ID")
    workspace_id: str = Field(description="Workspace ID")
    agent_runtime_id: str = Field(description="AgentRuntime ID")
    agent_id: str = Field(description="Agent ID")
    status: AgentSessionStatus = Field(description="Session status")
    start_reason: AgentSessionStartReason = Field(description="Start reason")
    end_reason: AgentSessionEndReason | None = Field(
        default=None,
        description="End reason",
    )
    model_input_head_event_id: str | None = Field(
        default=None,
        description="Model input head event ID",
    )
    started_at: datetime.datetime = Field(description="Start time")
    ended_at: datetime.datetime | None = Field(default=None, description="End time")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class AgentRunCreate(BaseModel):
    """Agent run create schema."""

    id: str | None = Field(default=None, description="AgentRun ID")
    session_id: str = Field(description="AgentSession ID")
    run_index: int | None = Field(
        default=None,
        description="Session-scoped monotonic run index",
    )
    phase: AgentRunPhase = Field(
        default=AgentRunPhase.IDLE,
        description="Initial phase",
    )
    status: AgentRunStatus = Field(
        default=AgentRunStatus.RUNNING,
        description="Initial status",
    )


class AgentRunPatch(BaseModel):
    """Agent run partial update schema."""

    phase: AgentRunPhase | None = Field(default=None, description="Run phase")
    status: AgentRunStatus | None = Field(default=None, description="Run status")
    active_tool_calls: list[ActiveToolCall] | None = Field(
        default=None,
        description="Active tool calls",
    )
    last_completed_event_id: str | None = Field(
        default=None,
        description="Last completed event ID",
    )
    stop_requested_at: datetime.datetime | None = Field(
        default=None,
        description="Stop requested time",
    )
    ended_at: datetime.datetime | None = Field(default=None, description="End time")
