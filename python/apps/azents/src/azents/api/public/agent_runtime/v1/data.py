"""Agent Runtime v1 Public API data models."""

import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from typing_extensions import Self

from azents.core.enums import (
    AgentRuntimeCapability,
    AgentRuntimeRemovalStage,
    AgentRuntimeRemovalStatus,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
    RuntimeSummary,
    RuntimeTerminalDeleteAcknowledgementKind,
)
from azents.core.runtime_profile import RuntimeConfigurationResolutionStatus
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_runtime_removal_scope.data import AgentRuntimeRemovalImpact
from azents.repos.runtime_profile.data import RuntimeConfigurationRevision
from azents.services.agent_runtime.lifecycle_data import (
    AgentRuntimeAdditionOutput,
    AgentRuntimeConfigurationStatus,
    AgentRuntimeLifecycleOutput,
    AgentRuntimeReadOutput,
    AgentRuntimeRemovalOutput,
    AgentRuntimeRemovalProgress,
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

    @classmethod
    def convert_from(cls, data: AgentRuntime) -> Self:
        """Convert the optional physical Runtime state."""
        return cls(
            id=data.id,
            workspace_id=data.workspace_id,
            agent_id=data.agent_id,
            runtime_provider_id=data.runtime_provider_id,
            runtime_provider_resource_id=data.runtime_provider_resource_id,
            infrastructure_profile_id=data.infrastructure_profile_id,
            workspace_runtime_profile_id=data.workspace_runtime_profile_id,
            desired_runtime_configuration_revision_id=(
                data.desired_runtime_configuration_revision_id
            ),
            applied_runtime_configuration_revision_id=(
                data.applied_runtime_configuration_revision_id
            ),
            desired_state=data.desired_state,
            desired_generation=data.desired_generation,
            last_lifecycle_command=data.last_lifecycle_command,
            reset_final_desired_state=data.reset_final_desired_state,
            provider_observed_state=data.provider_observed_state,
            provider_observed_generation=data.provider_observed_generation,
            provider_connection_state=data.provider_connection_state,
            runner_state=data.runner_state,
            runner_generation=data.runner_generation,
            workspace_path=data.workspace_path,
            failure_generation=data.failure_generation,
            failure_code=data.failure_code,
            failure_message=data.failure_message,
            last_state_change_at=data.last_state_change_at,
            created_at=data.created_at,
            updated_at=data.updated_at,
        )


class AgentRuntimePublicActionsResponse(BaseModel):
    """Complete public Runtime action availability."""

    add: bool
    remove: bool
    start: bool
    stop: bool
    restart: bool
    reset: bool
    observe: bool
    use_runner: bool


class AgentRuntimeRemovalImpactResponse(BaseModel):
    """Privacy-safe aggregate Runtime removal impact."""

    active_root_session_count: int
    active_subagent_count: int
    active_run_count: int
    queued_runtime_action_count: int

    @classmethod
    def convert_from(cls, data: AgentRuntimeRemovalImpact) -> Self:
        """Convert aggregate impact without Session details."""
        return cls(
            active_root_session_count=data.active_root_session_count,
            active_subagent_count=data.active_subagent_count,
            active_run_count=data.active_run_count,
            queued_runtime_action_count=data.queued_runtime_action_count,
        )


class AgentRuntimeRemovalProgressResponse(BaseModel):
    """Bounded durable Runtime removal progress."""

    id: str
    status: AgentRuntimeRemovalStatus
    stage: AgentRuntimeRemovalStage
    confirmed_at: datetime.datetime
    cleanup_scanned_context_count: int
    cleanup_invalidated_context_count: int
    product_cleanup_completed_at: datetime.datetime | None
    physical_deletion_required: bool | None
    physical_delete_requested_at: datetime.datetime | None
    physical_delete_acknowledgement_kind: (
        RuntimeTerminalDeleteAcknowledgementKind | None
    )
    physical_delete_acknowledged_at: datetime.datetime | None
    attempt_count: int
    next_attempt_at: datetime.datetime | None
    last_error_kind: str | None
    last_error_summary: str | None
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None
    updated_at: datetime.datetime

    @classmethod
    def convert_from(cls, data: AgentRuntimeRemovalProgress) -> Self:
        """Convert removal progress without internal authority or private data."""
        return cls(
            id=data.id,
            status=data.status,
            stage=data.stage,
            confirmed_at=data.confirmed_at,
            cleanup_scanned_context_count=data.cleanup_scanned_context_count,
            cleanup_invalidated_context_count=(data.cleanup_invalidated_context_count),
            product_cleanup_completed_at=data.product_cleanup_completed_at,
            physical_deletion_required=data.physical_deletion_required,
            physical_delete_requested_at=data.physical_delete_requested_at,
            physical_delete_acknowledgement_kind=(
                data.physical_delete_acknowledgement_kind
            ),
            physical_delete_acknowledged_at=data.physical_delete_acknowledged_at,
            attempt_count=data.attempt_count,
            next_attempt_at=data.next_attempt_at,
            last_error_kind=data.last_error_kind,
            last_error_summary=data.last_error_summary,
            started_at=data.started_at,
            completed_at=data.completed_at,
            updated_at=data.updated_at,
        )


class AgentRuntimeResponse(BaseModel):
    """Unified capability-aware Agent Runtime response."""

    capability: AgentRuntimeCapability
    capability_version: int
    runtime_profile_id: str | None
    runtime_profile_selection_version: int
    runtime_profile_status: Literal[
        "not_applicable",
        "profile_required",
        "configured",
        "unavailable",
    ]
    runtime_profile_available: bool
    runtime_profile_availability_reason_code: str | None
    removal_impact: AgentRuntimeRemovalImpactResponse | None
    removal: AgentRuntimeRemovalProgressResponse | None
    runtime: AgentRuntimeRawStateResponse | None
    state: AgentRuntimeSummaryResponse | None
    configuration: AgentRuntimeConfigurationStatusResponse | None
    actions: AgentRuntimePublicActionsResponse

    @classmethod
    def convert_from(cls, data: AgentRuntimeReadOutput) -> Self:
        """Convert the unified service read model."""
        return cls(
            capability=data.capability,
            capability_version=data.capability_version,
            runtime_profile_id=data.runtime_profile_id,
            runtime_profile_selection_version=(data.runtime_profile_selection_version),
            runtime_profile_status=data.runtime_profile_status,
            runtime_profile_available=data.runtime_profile_available,
            runtime_profile_availability_reason_code=(
                data.runtime_profile_availability_reason_code
            ),
            removal_impact=(
                AgentRuntimeRemovalImpactResponse.convert_from(data.removal_impact)
                if data.removal_impact is not None
                else None
            ),
            removal=(
                AgentRuntimeRemovalProgressResponse.convert_from(data.removal)
                if data.removal is not None
                else None
            ),
            runtime=(
                AgentRuntimeRawStateResponse.convert_from(data.runtime)
                if data.runtime is not None
                else None
            ),
            state=(
                AgentRuntimeSummaryResponse(
                    summary=data.state.summary,
                    actions=AgentRuntimeActionsResponse.model_validate(
                        data.state.actions,
                        from_attributes=True,
                    ),
                    failure=(
                        AgentRuntimeFailureResponse.model_validate(
                            data.state.failure,
                            from_attributes=True,
                        )
                        if data.state.failure is not None
                        else None
                    ),
                )
                if data.state is not None
                else None
            ),
            configuration=(
                AgentRuntimeConfigurationStatusResponse.convert_from(data.configuration)
                if data.configuration is not None
                else None
            ),
            actions=AgentRuntimePublicActionsResponse.model_validate(
                data.actions,
                from_attributes=True,
            ),
        )


class AgentRuntimeLifecycleResponse(BaseModel):
    """Agent Runtime lifecycle command response."""

    runtime: AgentRuntimeRawStateResponse
    state: AgentRuntimeSummaryResponse
    configuration: AgentRuntimeConfigurationStatusResponse
    command_type: RuntimeLifecycleCommandType
    desired_generation: int

    @classmethod
    def convert_from_lifecycle(cls, data: AgentRuntimeLifecycleOutput) -> Self:
        """Convert service lifecycle output to a response object."""
        return cls(
            runtime=AgentRuntimeRawStateResponse.convert_from(data.runtime),
            state=AgentRuntimeSummaryResponse(
                summary=data.state.summary,
                actions=AgentRuntimeActionsResponse.model_validate(
                    data.state.actions,
                    from_attributes=True,
                ),
                failure=(
                    AgentRuntimeFailureResponse.model_validate(
                        data.state.failure,
                        from_attributes=True,
                    )
                    if data.state.failure is not None
                    else None
                ),
            ),
            configuration=AgentRuntimeConfigurationStatusResponse.convert_from(
                data.configuration
            ),
            command_type=data.command_type,
            desired_generation=data.desired_generation,
        )


class AddAgentRuntimeRequest(BaseModel):
    """Dedicated Runtime addition request."""

    workspace_runtime_profile_id: str = Field(
        description="Explicit available Workspace Runtime Profile ID"
    )
    expected_capability_version: int = Field(ge=1)
    expected_runtime_profile_selection_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=120)


class RemoveAgentRuntimeRequest(BaseModel):
    """Final irreversible Runtime removal request."""

    expected_capability_version: int = Field(ge=1)
    expected_runtime_profile_selection_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=120)
    confirmed: bool = Field(description="Explicit final destructive confirmation")

    @field_validator("confirmed")
    @classmethod
    def validate_confirmed(cls, value: bool) -> bool:
        """Require the final destructive confirmation."""
        if not value:
            raise ValueError("Runtime removal must be explicitly confirmed.")
        return value


class AgentRuntimeAdditionResponse(BaseModel):
    """Committed or replayed Runtime addition."""

    runtime: AgentRuntimeResponse
    replayed: bool

    @classmethod
    def convert_from(cls, data: AgentRuntimeAdditionOutput) -> Self:
        """Convert a dedicated addition output."""
        return cls(
            runtime=AgentRuntimeResponse.convert_from(data.runtime),
            replayed=data.replayed,
        )


class AgentRuntimeRemovalResponse(BaseModel):
    """Committed or replayed Runtime removal."""

    runtime: AgentRuntimeResponse
    replayed: bool

    @classmethod
    def convert_from(cls, data: AgentRuntimeRemovalOutput) -> Self:
        """Convert a dedicated removal output."""
        return cls(
            runtime=AgentRuntimeResponse.convert_from(data.runtime),
            replayed=data.replayed,
        )


class AgentRuntimeActionErrorDetail(BaseModel):
    """Stable dedicated Runtime action error."""

    code: str
    message: str


class AgentRuntimeActionErrorResponse(BaseModel):
    """FastAPI envelope for a dedicated Runtime action error."""

    detail: AgentRuntimeActionErrorDetail


class ResetAgentRuntimeRequest(BaseModel):
    """Agent Runtime reset request."""

    final_desired_state: RuntimeDesiredState = Field(
        description="Desired state after reset completes"
    )
