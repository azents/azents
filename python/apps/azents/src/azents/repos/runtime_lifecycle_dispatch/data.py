"""Runtime lifecycle dispatch repository data contracts."""

import dataclasses
import enum
from datetime import timedelta

from azents_runtime_control.provider import (
    RuntimeLifecycleCommandType as RuntimeProviderCommandType,
)
from azents_runtime_control.runtime_configuration import RuntimeConfigurationEnvelope

from azents.core.enums import (
    AgentRuntimeCapability,
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
    RuntimeProviderConnectionState,
    RuntimeProviderObservedState,
)
from azents.repos.agent_runtime.data import AgentRuntime


class RuntimeLifecycleDispatchRejectionReason(enum.StrEnum):
    """Bounded reason that one selected Runtime was not admitted."""

    AGENT_CAPABILITY_CHANGED = "agent_capability_changed"
    RUNTIME_SNAPSHOT_CHANGED = "runtime_snapshot_changed"
    REPAIR_TARGET_CHANGED = "repair_target_changed"
    LIFECYCLE_CLAIM_UNAVAILABLE = "lifecycle_claim_unavailable"
    PROVIDER_NOT_CONFIGURED = "provider_not_configured"
    PROVIDER_GENERATION_CHANGED = "provider_generation_changed"
    CONFIGURATION_INVALID = "configuration_invalid"


@dataclasses.dataclass(frozen=True)
class RuntimeLifecycleDispatchRequest:
    """Existing dispatch authority selected by Runtime reconciliation."""

    runtime: AgentRuntime
    command_type: RuntimeProviderCommandType
    claim_lifecycle: bool
    required_provider_generation: int | None
    required_observed_generation: int | None
    required_configuration_sequence: int | None
    lifecycle_retry_delay: timedelta


@dataclasses.dataclass(frozen=True)
class RuntimeLifecycleDispatchSnapshot:
    """Immutable database snapshot shared by preflight and outcome fencing."""

    runtime_id: str
    agent_id: str
    workspace_id: str
    agent_runtime_capability: AgentRuntimeCapability
    agent_runtime_capability_version: int
    provider_id: str
    provider_resource_id: str | None
    configuration_sequence: int
    desired_state: RuntimeDesiredState
    desired_generation: int
    last_lifecycle_command: RuntimeLifecycleCommandType | None
    reset_final_desired_state: RuntimeDesiredState | None
    terminal_delete_requested_generation: int | None
    provider_generation: int
    provider_observed_generation: int
    provider_observed_state: RuntimeProviderObservedState
    last_lifecycle_dispatch_generation: int
    provider_connection_state: RuntimeProviderConnectionState
    command_type: RuntimeProviderCommandType


@dataclasses.dataclass(frozen=True)
class RuntimeLifecycleDispatchPreflight(RuntimeLifecycleDispatchSnapshot):
    """Claim-free dispatch snapshot completed before coordination lookup."""

    claim_lifecycle: bool
    required_provider_generation: int | None
    required_observed_generation: int | None
    required_configuration_sequence: int | None
    lifecycle_retry_delay: timedelta


@dataclasses.dataclass(frozen=True)
class RuntimeLifecycleDispatchAdmission(RuntimeLifecycleDispatchSnapshot):
    """Claimed database-authorized Provider command snapshot."""

    connection_generation: int
    runtime_configuration: RuntimeConfigurationEnvelope


@dataclasses.dataclass(frozen=True)
class RuntimeLifecycleDispatchRejection:
    """Completed database result for a dispatch that was not admitted."""

    reason: RuntimeLifecycleDispatchRejectionReason
    failure_code: str | None
    failure_message: str | None


type RuntimeLifecycleDispatchAdmissionResult = (
    RuntimeLifecycleDispatchAdmission | RuntimeLifecycleDispatchRejection
)

type RuntimeLifecycleDispatchPreflightResult = (
    RuntimeLifecycleDispatchPreflight | RuntimeLifecycleDispatchRejection
)
