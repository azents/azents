"""Agent Runtime v1 Public API data models."""

import datetime
from typing import Literal

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
from azents.core.runtime_profile import RuntimeConfigurationResolutionStatus
from azents.repos.runtime_profile.data import RuntimeConfigurationRevision
from azents.services.agent_runtime.lifecycle_data import (
    AgentRuntimeConfigurationStatus,
    AgentRuntimeLifecycleOutput,
    AgentRuntimeOutput,
    RuntimeContainmentStatus,
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


class RuntimeConfigurationRevisionResponse(BaseModel):
    """Safe immutable Runtime configuration revision evidence."""

    id: str
    provider_id: str
    provider_capability_revision_id: str | None
    infrastructure_profile_id: str
    infrastructure_profile_version: int
    workspace_runtime_profile_id: str
    workspace_runtime_profile_version: int
    agent_selection_version: int
    resolution_status: RuntimeConfigurationResolutionStatus
    reason_code: str | None
    required_capabilities: list[str]
    missing_capabilities: list[str]
    digest: str
    target_desired_generation: int
    provider_reported_digest: str | None
    runner_reported_digest: str | None
    provider_acknowledged_at: datetime.datetime | None
    runtime_observed_at: datetime.datetime | None
    created_at: datetime.datetime

    @classmethod
    def convert_from(cls, data: RuntimeConfigurationRevision) -> Self:
        """Convert immutable evidence without resolved infrastructure details."""
        return cls(
            id=data.id,
            provider_id=data.provider_id,
            provider_capability_revision_id=data.provider_capability_revision_id,
            infrastructure_profile_id=data.infrastructure_profile_id,
            infrastructure_profile_version=data.infrastructure_profile_version,
            workspace_runtime_profile_id=data.workspace_runtime_profile_id,
            workspace_runtime_profile_version=data.workspace_runtime_profile_version,
            agent_selection_version=data.agent_selection_version,
            resolution_status=data.resolution_status,
            reason_code=data.reason_code,
            required_capabilities=list(data.required_capabilities),
            missing_capabilities=list(data.missing_capabilities),
            digest=data.digest,
            target_desired_generation=data.target_desired_generation,
            provider_reported_digest=data.provider_reported_digest,
            runner_reported_digest=data.runner_reported_digest,
            provider_acknowledged_at=data.provider_acknowledged_at,
            runtime_observed_at=data.runtime_observed_at,
            created_at=data.created_at,
        )


class AgentRuntimeConfigurationStatusResponse(BaseModel):
    """Desired and applied Runtime configuration status."""

    status: Literal[
        "profile_required",
        "configuration_blocked",
        "configured_not_created",
        "waiting_for_recreation",
        "applied",
    ]
    desired: RuntimeConfigurationRevisionResponse | None
    applied: RuntimeConfigurationRevisionResponse | None
    containment: RuntimeContainmentStatus

    @classmethod
    def convert_from(cls, data: AgentRuntimeConfigurationStatus) -> Self:
        """Convert server-authoritative configuration status."""
        return cls(
            status=data.status,
            desired=(
                RuntimeConfigurationRevisionResponse.convert_from(data.desired)
                if data.desired is not None
                else None
            ),
            applied=(
                RuntimeConfigurationRevisionResponse.convert_from(data.applied)
                if data.applied is not None
                else None
            ),
            containment=data.containment,
        )


class AgentRuntimeRawStateResponse(BaseModel):
    """Agent Runtime raw state response."""

    id: str
    workspace_id: str
    agent_id: str
    runtime_provider_id: str | None
    runtime_provider_resource_id: str | None
    infrastructure_profile_id: str | None
    workspace_runtime_profile_id: str | None
    desired_runtime_configuration_revision_id: str | None
    applied_runtime_configuration_revision_id: str | None
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
    configuration: AgentRuntimeConfigurationStatusResponse

    @classmethod
    def convert_from(cls, data: AgentRuntimeOutput) -> Self:
        """Convert service output to a response object."""
        return cls(
            runtime=AgentRuntimeRawStateResponse(
                id=data.runtime.id,
                workspace_id=data.runtime.workspace_id,
                agent_id=data.runtime.agent_id,
                runtime_provider_id=data.runtime.runtime_provider_id,
                runtime_provider_resource_id=(
                    data.runtime.runtime_provider_resource_id
                ),
                infrastructure_profile_id=data.runtime.infrastructure_profile_id,
                workspace_runtime_profile_id=(
                    data.runtime.workspace_runtime_profile_id
                ),
                desired_runtime_configuration_revision_id=(
                    data.runtime.desired_runtime_configuration_revision_id
                ),
                applied_runtime_configuration_revision_id=(
                    data.runtime.applied_runtime_configuration_revision_id
                ),
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
            configuration=AgentRuntimeConfigurationStatusResponse.convert_from(
                data.configuration
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
                configuration=data.configuration,
            )
        )
        return cls(
            runtime=base.runtime,
            state=base.state,
            configuration=base.configuration,
            command_type=data.command_type,
            desired_generation=data.desired_generation,
        )


class ResetAgentRuntimeRequest(BaseModel):
    """Agent Runtime reset request."""

    final_desired_state: RuntimeDesiredState = Field(
        description="Desired state after reset completes"
    )
