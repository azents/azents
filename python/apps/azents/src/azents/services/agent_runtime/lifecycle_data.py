"""Agent Runtime lifecycle service data models."""

import dataclasses

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


class AgentRuntimeOutput(BaseModel):
    """Agent Runtime API output model."""

    runtime: AgentRuntime = Field(description="Raw runtime state")
    state: AgentRuntimeSummaryState = Field(description="Server-computed state")


class AgentRuntimeLifecycleOutput(BaseModel):
    """Lifecycle command output model."""

    runtime: AgentRuntime = Field(description="Changed Runtime")
    state: AgentRuntimeSummaryState = Field(description="Server-computed state")
    command_type: RuntimeLifecycleCommandType = Field(description="Command type")
    desired_generation: int = Field(description="Desired generation")


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
    "AgentRuntimeFailureSummary",
    "AgentRuntimeLifecycleOutput",
    "AgentRuntimeOutput",
    "AgentRuntimeSummaryState",
    "InvalidResetFinalDesiredState",
    "ProviderDisconnected",
    "RuntimeProviderUnavailable",
    "RuntimeNotFound",
]
