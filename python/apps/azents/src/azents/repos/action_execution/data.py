"""Action execution repository data models."""

import datetime

from pydantic import BaseModel, Field

from azents.core.enums import ActionExecutionEventKind, ActionExecutionStatus


class ActionExecution(BaseModel):
    """Durable execution state for one operation TurnAction event."""

    id: str = Field(description="Action execution ID")
    session_id: str = Field(description="AgentSession ID")
    action_event_id: str = Field(description="Durable action_message event ID")
    action_type: str = Field(description="Action discriminator")
    status: ActionExecutionStatus = Field(description="Execution status")
    attempt: int = Field(description="Current execution attempt")
    failure_summary: str | None = Field(description="User-safe failure summary")
    started_at: datetime.datetime | None = Field(description="Start time")
    completed_at: datetime.datetime | None = Field(description="Completion time")
    failed_at: datetime.datetime | None = Field(description="Failure time")
    failed_final_at: datetime.datetime | None = Field(
        description="Discard finalization time"
    )
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class ActionExecutionCreate(BaseModel):
    """Action execution create schema."""

    id: str | None = Field(description="Optional action execution ID")
    session_id: str = Field(description="AgentSession ID")
    action_event_id: str = Field(description="Durable action_message event ID")
    action_type: str = Field(description="Action discriminator")
    status: ActionExecutionStatus = Field(description="Initial execution status")
    attempt: int = Field(description="Initial execution attempt")


class ActionExecutionEvent(BaseModel):
    """Append-only action execution progress event."""

    id: str = Field(description="Action execution event ID")
    action_execution_id: str = Field(description="Action execution ID")
    session_id: str = Field(description="AgentSession ID")
    sequence: int = Field(description="Monotonic sequence within execution")
    kind: ActionExecutionEventKind = Field(description="Progress event kind")
    step_key: str | None = Field(description="Action-local step key")
    command_argv: list[str] | None = Field(description="Command argv snapshot")
    content: str | None = Field(description="Progress content")
    exit_code: int | None = Field(description="Command exit code")
    created_at: datetime.datetime = Field(description="Created time")


class ActionExecutionEventCreate(BaseModel):
    """Action execution event create schema."""

    action_execution_id: str = Field(description="Action execution ID")
    session_id: str = Field(description="AgentSession ID")
    kind: ActionExecutionEventKind = Field(description="Progress event kind")
    step_key: str | None = Field(description="Action-local step key")
    command_argv: list[str] | None = Field(description="Command argv snapshot")
    content: str | None = Field(description="Progress content")
    exit_code: int | None = Field(description="Command exit code")


class ActionExecutionProjection(BaseModel):
    """Action execution with ordered durable progress events."""

    execution: ActionExecution = Field(description="Action execution state")
    events: list[ActionExecutionEvent] = Field(description="Ordered progress events")
