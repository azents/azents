"""Session initialization repository data models."""

import datetime

from pydantic import BaseModel, Field

from azents.core.enums import (
    SessionInitializationEventKind,
    SessionInitializationStatus,
    SessionInitializationStepStatus,
    SessionInitializationStepType,
)


class SessionInitialization(BaseModel):
    """AgentSession initialization lifecycle."""

    id: str = Field(description="Session initialization ID")
    session_id: str = Field(description="AgentSession ID")
    status: SessionInitializationStatus = Field(description="Initialization status")
    failure_summary: str | None = Field(description="User-safe failure summary")
    retry_count: int = Field(description="Retry count")
    started_at: datetime.datetime | None = Field(description="Start time")
    completed_at: datetime.datetime | None = Field(description="Completion time")
    failed_at: datetime.datetime | None = Field(description="Failure time")
    canceled_at: datetime.datetime | None = Field(description="Cancellation time")
    cleaned_at: datetime.datetime | None = Field(description="Cleanup completion time")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class SessionInitializationCreate(BaseModel):
    """Session initialization create schema."""

    session_id: str = Field(description="AgentSession ID")
    status: SessionInitializationStatus = Field(description="Initialization status")
    failure_summary: str | None = Field(description="User-safe failure summary")
    started_at: datetime.datetime | None = Field(description="Start time")
    completed_at: datetime.datetime | None = Field(description="Completion time")
    failed_at: datetime.datetime | None = Field(description="Failure time")
    canceled_at: datetime.datetime | None = Field(description="Cancellation time")
    cleaned_at: datetime.datetime | None = Field(description="Cleanup completion time")


class SessionInitializationStep(BaseModel):
    """AgentSession initialization step."""

    id: str = Field(description="Session initialization step ID")
    initialization_id: str = Field(description="Session initialization ID")
    session_id: str = Field(description="AgentSession ID")
    sequence: int = Field(description="Stable step order")
    step_key: str = Field(description="Stable key within one initialization")
    step_type: SessionInitializationStepType = Field(description="Typed step kind")
    status: SessionInitializationStepStatus = Field(description="Step status")
    blocking: bool = Field(description="Whether failure blocks run dispatch")
    retryable: bool = Field(description="Whether retry is allowed")
    attempt: int = Field(description="Current attempt number")
    depends_on_step_keys: list[str] = Field(description="Dependency step keys")
    resource_descriptors: list[object] = Field(
        description="Created or claimed resources"
    )
    failure_reason: str | None = Field(description="User-safe failure reason")
    started_at: datetime.datetime | None = Field(description="Start time")
    completed_at: datetime.datetime | None = Field(description="Completion time")
    failed_at: datetime.datetime | None = Field(description="Failure time")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class SessionInitializationStepCreate(BaseModel):
    """Session initialization step create schema."""

    initialization_id: str = Field(description="Session initialization ID")
    session_id: str = Field(description="AgentSession ID")
    sequence: int = Field(description="Stable step order")
    step_key: str = Field(description="Stable key within one initialization")
    step_type: SessionInitializationStepType = Field(description="Typed step kind")
    blocking: bool = Field(description="Whether failure blocks run dispatch")
    retryable: bool = Field(description="Whether retry is allowed")
    depends_on_step_keys: list[str] = Field(description="Dependency step keys")
    resource_descriptors: list[object] = Field(
        description="Created or claimed resources"
    )


class SessionInitializationEvent(BaseModel):
    """AgentSession initialization event."""

    id: str = Field(description="Session initialization event ID")
    initialization_id: str = Field(description="Session initialization ID")
    step_id: str | None = Field(description="Session initialization step ID")
    session_id: str = Field(description="AgentSession ID")
    sequence: int = Field(description="Monotonic event sequence")
    kind: SessionInitializationEventKind = Field(description="Event kind")
    command_argv: list[str] | None = Field(description="Command argv")
    content: str | None = Field(description="Event content")
    exit_code: int | None = Field(description="Command exit code")
    created_at: datetime.datetime = Field(description="Created time")


class SessionInitializationEventCreate(BaseModel):
    """Session initialization event create schema."""

    initialization_id: str = Field(description="Session initialization ID")
    step_id: str | None = Field(description="Session initialization step ID")
    session_id: str = Field(description="AgentSession ID")
    kind: SessionInitializationEventKind = Field(description="Event kind")
    command_argv: list[str] | None = Field(description="Command argv")
    content: str | None = Field(description="Event content")
    exit_code: int | None = Field(description="Command exit code")
