"""Agent Runtime v1 Public API data models."""

import datetime

from pydantic import BaseModel, Field
from typing_extensions import Self

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    RuntimeSummary,
)
from azents.core.runtime_execution_policy import (
    RuntimeExecutionModuleId,
    RuntimeExecutionNetworkMode,
    RuntimeExecutionPolicyLayer,
    RuntimeExecutionPolicyStatus,
    RuntimeExecutionRequiredAction,
    RuntimeExecutionStorageMode,
)
from azents.services.agent_runtime.lifecycle_data import (
    AgentRuntimeLifecycleOutput,
    AgentRuntimeOutput,
)
from azents.services.runtime_execution_policy.application_service import (
    RuntimeExecutionCapabilitySummary,
    RuntimeExecutionConfiguredSummary,
    RuntimeExecutionPolicyStatusProjection,
    RuntimeExecutionSnapshotSummary,
)


class AgentRuntimeActionsResponse(BaseModel):
    """Agent Runtime action availability response."""

    start: bool
    stop: bool
    restart: bool
    reset: bool
    use_runner: bool


class AgentRuntimeFailureResponse(BaseModel):
    """Agent Runtime failure response."""

    generation: int
    code: str
    message: str


class AgentRuntimeSummaryResponse(BaseModel):
    """Agent Runtime summary response."""

    summary: RuntimeSummary
    actions: AgentRuntimeActionsResponse
    failure: AgentRuntimeFailureResponse | None


class RuntimeExecutionCapabilitySummaryResponse(BaseModel):
    """One safe Runtime execution capability summary."""

    module_id: RuntimeExecutionModuleId
    version: int
    enabled: bool

    @classmethod
    def convert_from(cls, data: RuntimeExecutionCapabilitySummary) -> Self:
        """Convert one capability summary."""
        return cls(
            module_id=data.module_id,
            version=data.version,
            enabled=data.enabled,
        )


class RuntimeExecutionConfiguredSummaryResponse(BaseModel):
    """Safe configured Runtime execution-policy summary."""

    profile_id: str
    digest: str
    capabilities: list[RuntimeExecutionCapabilitySummaryResponse]
    storage_mode: RuntimeExecutionStorageMode
    storage_capacity_bytes: int | None
    network_mode: RuntimeExecutionNetworkMode

    @classmethod
    def convert_from(cls, data: RuntimeExecutionConfiguredSummary) -> Self:
        """Convert configured policy without implementation details."""
        return cls(
            profile_id=data.profile_id,
            digest=data.digest,
            capabilities=[
                RuntimeExecutionCapabilitySummaryResponse.convert_from(item)
                for item in data.capabilities
            ],
            storage_mode=data.storage_mode,
            storage_capacity_bytes=data.storage_capacity_bytes,
            network_mode=data.network_mode,
        )


class RuntimeExecutionSnapshotSummaryResponse(BaseModel):
    """Safe target or applied Runtime execution-policy summary."""

    profile_id: str
    digest: str
    desired_generation: int
    capabilities: list[RuntimeExecutionCapabilitySummaryResponse]
    storage_mode: RuntimeExecutionStorageMode
    storage_capacity_bytes: int | None
    network_mode: RuntimeExecutionNetworkMode

    @classmethod
    def convert_from(cls, data: RuntimeExecutionSnapshotSummary) -> Self:
        """Convert one immutable snapshot summary."""
        return cls(
            profile_id=data.profile_id,
            digest=data.digest,
            desired_generation=data.desired_generation,
            capabilities=[
                RuntimeExecutionCapabilitySummaryResponse.convert_from(item)
                for item in data.capabilities
            ],
            storage_mode=data.storage_mode,
            storage_capacity_bytes=data.storage_capacity_bytes,
            network_mode=data.network_mode,
        )


class AgentRuntimeExecutionPolicyStatusResponse(BaseModel):
    """Safe server-authoritative Runtime execution-policy status."""

    status: RuntimeExecutionPolicyStatus
    configured: RuntimeExecutionConfiguredSummaryResponse
    target: RuntimeExecutionSnapshotSummaryResponse | None
    applied: RuntimeExecutionSnapshotSummaryResponse | None
    desired_generation: int
    governing_layers: dict[str, RuntimeExecutionPolicyLayer]
    reason_codes: list[str]
    required_action: RuntimeExecutionRequiredAction

    @classmethod
    def convert_from(cls, data: RuntimeExecutionPolicyStatusProjection) -> Self:
        """Convert the read-only execution-policy projection."""
        return cls(
            status=data.status,
            configured=RuntimeExecutionConfiguredSummaryResponse.convert_from(
                data.configured
            ),
            target=(
                RuntimeExecutionSnapshotSummaryResponse.convert_from(data.target)
                if data.target is not None
                else None
            ),
            applied=(
                RuntimeExecutionSnapshotSummaryResponse.convert_from(data.applied)
                if data.applied is not None
                else None
            ),
            desired_generation=data.desired_generation,
            governing_layers=data.governing_layers,
            reason_codes=list(data.reason_codes),
            required_action=data.required_action,
        )


class AgentRuntimeRawStateResponse(BaseModel):
    """Agent Runtime raw state response."""

    id: str
    workspace_id: str
    agent_id: str
    runtime_provider_id: str | None
    provider_config: dict[str, object] | None
    desired_state: RuntimeDesiredState
    desired_generation: int
    last_lifecycle_command: RuntimeLifecycleCommandType | None
    reset_final_desired_state: RuntimeDesiredState | None
    provider_observed_state: RuntimeProviderObservedState
    provider_observed_generation: int
    provider_connection_state: RuntimeProviderConnectionState
    runner_state: RuntimeRunnerState
    runner_generation: int
    workspace_path: str | None
    failure_generation: int | None
    failure_code: str | None
    failure_message: str | None
    last_state_change_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class AgentRuntimeResponse(BaseModel):
    """Agent Runtime response."""

    runtime: AgentRuntimeRawStateResponse
    state: AgentRuntimeSummaryResponse
    execution_policy: AgentRuntimeExecutionPolicyStatusResponse

    @classmethod
    def convert_from(cls, data: AgentRuntimeOutput) -> Self:
        """Convert service output to a response object."""
        return cls(
            runtime=AgentRuntimeRawStateResponse(
                id=data.runtime.id,
                workspace_id=data.runtime.workspace_id,
                agent_id=data.runtime.agent_id,
                runtime_provider_id=data.runtime.runtime_provider_id,
                provider_config=data.runtime.provider_config,
                desired_state=data.runtime.desired_state,
                desired_generation=data.runtime.desired_generation,
                last_lifecycle_command=data.runtime.last_lifecycle_command,
                reset_final_desired_state=data.runtime.reset_final_desired_state,
                provider_observed_state=data.runtime.provider_observed_state,
                provider_observed_generation=data.runtime.provider_observed_generation,
                provider_connection_state=data.runtime.provider_connection_state,
                runner_state=data.runtime.runner_state,
                runner_generation=data.runtime.runner_generation,
                workspace_path=data.runtime.workspace_path,
                failure_generation=data.runtime.failure_generation,
                failure_code=data.runtime.failure_code,
                failure_message=data.runtime.failure_message,
                last_state_change_at=data.runtime.last_state_change_at,
                created_at=data.runtime.created_at,
                updated_at=data.runtime.updated_at,
            ),
            state=AgentRuntimeSummaryResponse(
                summary=data.state.summary,
                actions=AgentRuntimeActionsResponse.model_validate(
                    data.state.actions, from_attributes=True
                ),
                failure=(
                    AgentRuntimeFailureResponse.model_validate(
                        data.state.failure, from_attributes=True
                    )
                    if data.state.failure is not None
                    else None
                ),
            ),
            execution_policy=AgentRuntimeExecutionPolicyStatusResponse.convert_from(
                data.execution_policy
            ),
        )


class AgentRuntimeLifecycleResponse(AgentRuntimeResponse):
    """Agent Runtime lifecycle command response."""

    command_type: RuntimeLifecycleCommandType
    desired_generation: int

    @classmethod
    def convert_from_lifecycle(cls, data: AgentRuntimeLifecycleOutput) -> Self:
        """Convert service lifecycle output to a response object."""
        base = AgentRuntimeResponse.convert_from(
            AgentRuntimeOutput(
                runtime=data.runtime,
                state=data.state,
                execution_policy=data.execution_policy,
            )
        )
        return cls(
            runtime=base.runtime,
            state=base.state,
            execution_policy=base.execution_policy,
            command_type=data.command_type,
            desired_generation=data.desired_generation,
        )


class ResetAgentRuntimeRequest(BaseModel):
    """Agent Runtime reset request."""

    final_desired_state: RuntimeDesiredState = Field(
        description="Desired state after reset completes"
    )
