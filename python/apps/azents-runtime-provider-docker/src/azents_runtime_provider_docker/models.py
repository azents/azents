"""Docker Provider domain models."""

import dataclasses
import enum
from datetime import datetime


class RuntimeDesiredState(enum.StrEnum):
    """Final desired Runtime state for reset."""

    RUNNING = "running"
    STOPPED = "stopped"


class RuntimeLifecycleCommandType(enum.StrEnum):
    """Provider lifecycle command types."""

    START = "start"
    STOP = "stop"
    RESTART = "restart"
    RESET = "reset"
    OBSERVE = "observe"


class RuntimeProviderObservedState(enum.StrEnum):
    """Provider observed Runtime states."""

    UNKNOWN = "unknown"
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    RECOVERING = "recovering"
    RESETTING = "resetting"
    FAILED = "failed"


@dataclasses.dataclass(frozen=True)
class RuntimeIdentity:
    """Runtime identity needed by a Provider command."""

    runtime_id: str
    agent_id: str
    workspace_id: str


@dataclasses.dataclass(frozen=True)
class RuntimeContainerAuth:
    """Auth and connection material injected into the Runtime container."""

    control_endpoint: str
    runner_auth_token: str


@dataclasses.dataclass(frozen=True)
class RuntimeLifecycleCommand:
    """Lifecycle command consumed by the Docker Provider."""

    command_type: RuntimeLifecycleCommandType
    identity: RuntimeIdentity
    desired_generation: int
    provider_generation: int
    runner_image: str
    auth: RuntimeContainerAuth
    reset_final_desired_state: RuntimeDesiredState | None = None


@dataclasses.dataclass(frozen=True)
class RuntimeProviderReport:
    """Provider observed-state report produced by Docker Provider."""

    runtime_id: str
    provider_id: str
    provider_generation: int
    observed_state: RuntimeProviderObservedState
    observed_desired_generation: int
    provider_runtime_id: str | None
    workspace_path: str
    reason: str
    diagnostic: dict[str, str]
    reported_at: datetime


@dataclasses.dataclass(frozen=True)
class RuntimeLifecycleResult:
    """Lifecycle command result plus the report to send to Control."""

    command_type: RuntimeLifecycleCommandType
    report: RuntimeProviderReport
