"""Agent Runtime lifecycle service data models."""

import dataclasses
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeLifecycleCommandType,
)
from azents.repos.agent_runtime.data import (
    AgentRuntime,
    AgentRuntimeActions,
    AgentRuntimeFailureSummary,
    AgentRuntimeSummaryState,
)
from azents.repos.runtime_profile.data import RuntimeConfigurationRevision


class AgentRuntimeConfigurationStatus(BaseModel):
    """Server-authoritative desired and applied Runtime configuration."""

    status: Literal[
        "profile_required",
        "configuration_blocked",
        "configured_not_created",
        "waiting_for_recreation",
        "applied",
    ]
    desired: RuntimeConfigurationRevision | None
    applied: RuntimeConfigurationRevision | None
    containment: "RuntimeContainmentStatus"


class RuntimeContainmentStatus(BaseModel):
    """Derived process-containment and Runtime operation projection."""

    enabled: bool
    applied: bool
    recreation_required: bool
    nested_docker_available: bool
    runtime_available: bool
    availability_reason_code: str | None


@dataclasses.dataclass(frozen=True)
class RuntimeOperationAuthority:
    """Expected desired Runtime configuration for one explicit operation."""

    configuration_revision_id: str
    configuration_digest: str
    desired_generation: int


@dataclasses.dataclass(frozen=True)
class RuntimeOperationTarget:
    """Immutable exact Runtime authority for one explicit operation."""

    id: str
    desired_generation: int
    runner_generation: int
    configuration_revision_id: str
    configuration_digest: str
    workspace_path: str


class RuntimeOperationTargetResolver(Protocol):
    """Resolve one exact Runtime authority for an explicit operation."""

    async def resolve_operation_target(
        self,
        agent_id: str,
        *,
        wait_timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 1.0,
        expected_authority: RuntimeOperationAuthority | None = None,
        start_if_stopped: bool = True,
    ) -> RuntimeOperationTarget:
        """Wait for and return one exact qualified Runtime target."""
        ...


class AgentRuntimeOutput(BaseModel):
    """Agent Runtime API output model."""

    runtime: AgentRuntime = Field(description="Raw runtime state")
    state: AgentRuntimeSummaryState = Field(description="Server-computed state")
    configuration: AgentRuntimeConfigurationStatus = Field(
        description="Server-computed Runtime configuration status"
    )


class AgentRuntimeLifecycleOutput(BaseModel):
    """Lifecycle command output model."""

    runtime: AgentRuntime = Field(description="Changed Runtime")
    state: AgentRuntimeSummaryState = Field(description="Server-computed state")
    command_type: RuntimeLifecycleCommandType = Field(description="Command type")
    desired_generation: int = Field(description="Desired generation")
    configuration: AgentRuntimeConfigurationStatus = Field(
        description="Server-computed Runtime configuration status"
    )


@dataclasses.dataclass(frozen=True)
class AgentNotFound:
    """Agent not found."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class AgentNotBelongToWorkspace:
    """Agent does not belong to workspace."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class AgentAccessDenied:
    """No Agent access permission."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class RuntimeNotFound:
    """Runtime not found."""

    runtime_id: str


@dataclasses.dataclass(frozen=True)
class ProviderDisconnected:
    """Cannot perform command while Provider is disconnected."""

    runtime_id: str


@dataclasses.dataclass(frozen=True)
class RuntimeProviderUnavailable:
    """No eligible Runtime Provider can provision this logical Runtime."""

    code: str
    provider_id: str | None
    message: str


@dataclasses.dataclass(frozen=True)
class InvalidResetFinalDesiredState:
    """reset final desired state is invalid."""

    final_desired_state: RuntimeDesiredState | None


__all__ = [
    "AgentAccessDenied",
    "AgentNotBelongToWorkspace",
    "AgentNotFound",
    "AgentRuntimeActions",
    "AgentRuntimeConfigurationStatus",
    "AgentRuntimeFailureSummary",
    "AgentRuntimeLifecycleOutput",
    "AgentRuntimeOutput",
    "AgentRuntimeSummaryState",
    "InvalidResetFinalDesiredState",
    "ProviderDisconnected",
    "RuntimeProviderUnavailable",
    "RuntimeNotFound",
    "RuntimeContainmentStatus",
    "RuntimeOperationAuthority",
    "RuntimeOperationTarget",
    "RuntimeOperationTargetResolver",
]
