"""Event agent execution repository data models."""

import datetime

from pydantic import BaseModel, Field

from azents.core.enums import AgentRunPhase, AgentRunStatus, EventKind
from azents.engine.events.types import ActiveToolCall
from azents.engine.run.failure import FailedRunRetryState
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
    retry_state: FailedRunRetryState | None = Field(
        default=None,
        description="Durable failed-run retry state",
    )
    last_completed_event_id: str | None = Field(
        default=None,
        description="Last completed event ID",
    )
    terminal_result_event_id: str | None = Field(
        default=None,
        description="Terminal result source event ID",
    )
    terminal_result_message: str | None = Field(
        default=None,
        description="Terminal result message projected for parent observation",
    )
    stop_requested_at: datetime.datetime | None = Field(
        default=None,
        description="Stop requested time",
    )
    ended_at: datetime.datetime | None = Field(default=None, description="End time")
