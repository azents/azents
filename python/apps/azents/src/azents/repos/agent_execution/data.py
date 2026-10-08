"""Event agent execution repository data models."""

import datetime
from typing import TypedDict

from pydantic import BaseModel, Field

from azents.core.enums import (
    AgentRunParentResultDeliveryState,
    AgentRunPhase,
    AgentRunStatus,
    EventKind,
)
from azents.core.json_value import JSONValue
from azents.core.model_operation import ModelOperationState
from azents.engine.events.types import ActiveToolCall
from azents.engine.run.failure import FailedRunRetryState


class EventCreate(BaseModel):
    """Event create schema."""

    session_id: str = Field(description="AgentSession ID")
    kind: EventKind = Field(description="Event kind")
    payload: dict[str, JSONValue] = Field(description="Event payload")
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
    scheduled_task_cycle_id: str | None = Field(
        min_length=32,
        max_length=32,
        description="Scheduled Task cycle binding",
    )
    parent_agent_run_id: str | None
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
    model_operation_state: ModelOperationState | None = Field(
        default=None,
        description="Durable foreground and compaction model operation state",
    )


class AgentRunPatch(TypedDict, total=False):
    """Presence-aware run updates; omitted fields retain their current values."""

    scheduled_task_cycle_id: str | None
    phase: AgentRunPhase | None
    status: AgentRunStatus | None
    parent_agent_run_id: str | None
    started_at: datetime.datetime | None
    model_call_started_at: datetime.datetime | None
    active_tool_calls: list[ActiveToolCall] | None
    retry_state: FailedRunRetryState | None
    model_operation_state: ModelOperationState | None
    last_completed_event_id: str | None
    terminal_result_event_id: str | None
    terminal_result_message: str | None
    parent_result_delivery_state: AgentRunParentResultDeliveryState | None
    parent_result_mailbox_item_id: str | None
    parent_result_enqueued_at: datetime.datetime | None
    stop_requested_at: datetime.datetime | None
    ended_at: datetime.datetime | None
