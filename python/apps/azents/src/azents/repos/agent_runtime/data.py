"""AgentRuntime repository data models."""

import datetime
from typing import Any

from pydantic import BaseModel, Field

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    RuntimeSummary,
)


class AgentRuntime(BaseModel):
    """AgentRuntime domain model."""

    id: str = Field(description="AgentRuntime ID")
    workspace_id: str = Field(description="Workspace ID")
    agent_id: str = Field(description="Agent ID")
    runtime_provider_id: str | None = Field(
        default=None, description="Runtime Provider logical ID"
    )
    provider_config: dict[str, Any] | None = Field(
        default=None, description="Runtime Provider config override"
    )
    desired_state: RuntimeDesiredState = Field(
        default=RuntimeDesiredState.STOPPED,
        description="desired runtime state",
    )
    desired_generation: int = Field(default=0, description="desired state generation")
    last_lifecycle_command: RuntimeLifecycleCommandType | None = Field(
        default=None, description="Last lifecycle command"
    )
    reset_final_desired_state: RuntimeDesiredState | None = Field(
        default=None, description="Desired state after reset completion"
    )
    terminal_delete_requested_generation: int | None = Field(
        default=None, description="Terminal deletion request generation"
    )
    terminal_delete_acknowledged_generation: int | None = Field(
        default=None, description="Provider-acknowledged terminal deletion generation"
    )
    terminal_delete_acknowledged_at: datetime.datetime | None = Field(
        default=None, description="Terminal deletion acknowledgement time"
    )
    provider_observed_state: RuntimeProviderObservedState = Field(
        default=RuntimeProviderObservedState.UNKNOWN,
        description="Provider observed state",
    )
    provider_generation: int = Field(
        default=0, description="Provider stream generation"
    )
    provider_observed_generation: int = Field(
        default=0, description="Provider observed state generation"
    )
    provider_observed_at: datetime.datetime | None = Field(
        default=None, description="Provider observed state report time"
    )
    provider_observe_requested_at: datetime.datetime | None = Field(
        default=None, description="Last Provider observe request time"
    )
    last_lifecycle_dispatch_generation: int = Field(
        default=0, description="Last desired generation dispatched to Provider"
    )
    provider_connection_state: RuntimeProviderConnectionState = Field(
        default=RuntimeProviderConnectionState.DISCONNECTED,
        description="Provider connection state",
    )
    runner_state: RuntimeRunnerState = Field(
        default=RuntimeRunnerState.UNKNOWN,
        description="Runner state",
    )
    runner_generation: int = Field(default=0, description="Runner state generation")
    workspace_path: str | None = Field(
        default=None, description="Workspace path reported by Provider"
    )
    failure_generation: int | None = Field(
        default=None, description="Generation containing failure"
    )
    failure_code: str | None = Field(default=None, description="Failure code")
    failure_message: str | None = Field(default=None, description="Failure message")
    last_state_change_at: datetime.datetime | None = Field(
        default=None, description="Last runtime domain state change time"
    )
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class AgentRuntimeCreate(BaseModel):
    """AgentRuntime create schema."""

    workspace_id: str = Field(description="Workspace ID")
    agent_id: str = Field(description="Agent ID")
    runtime_provider_id: str | None = Field(
        default=None, description="Runtime Provider logical ID"
    )
    provider_config: dict[str, Any] | None = Field(
        default=None, description="Runtime Provider config override"
    )


class AgentRuntimeFailurePatch(BaseModel):
    """Runtime failure storage schema."""

    generation: int = Field(description="Failure generation")
    code: str = Field(description="Failure code")
    message: str = Field(description="Failure message")


class AgentRuntimeLifecycleCommand(BaseModel):
    """Runtime lifecycle command storage result."""

    runtime: AgentRuntime = Field(description="Changed AgentRuntime")
    command_type: RuntimeLifecycleCommandType = Field(description="Command type")
    desired_generation: int = Field(description="New desired generation")


class AgentRuntimeFailureSummary(BaseModel):
    """Runtime failure summary."""

    generation: int = Field(description="Failure generation")
    code: str = Field(description="Failure code")
    message: str = Field(description="Failure message")


class AgentRuntimeActions(BaseModel):
    """Runtime action availability calculated by server."""

    start: bool = Field(description="Start action availability")
    stop: bool = Field(description="Stop action availability")
    restart: bool = Field(description="Restart action availability")
    reset: bool = Field(description="Reset action availability")
    use_runner: bool = Field(description="Runner operation availability")


class AgentRuntimeSummaryState(BaseModel):
    """Runtime summary calculated by server."""

    summary: RuntimeSummary = Field(description="Runtime summary")
    actions: AgentRuntimeActions = Field(description="Runtime action availability")
    failure: AgentRuntimeFailureSummary | None = Field(
        default=None, description="Current generation failure"
    )
