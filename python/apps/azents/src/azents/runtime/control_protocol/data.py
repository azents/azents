"""Agent Runtime control protocol data types."""

import dataclasses
from datetime import datetime
from typing import Protocol

from azents.core.enums import (
    RuntimeLifecycleCommandType,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.runtime.coordination.data import JsonValue, RuntimeCoordinationTarget


class RuntimeRequestIdFactory(Protocol):
    """Request id generator used by control protocol dispatch."""

    def __call__(self) -> str:
        """Return a new request id."""
        ...


@dataclasses.dataclass(frozen=True)
class RuntimeProtocolCapabilities:
    """Provider or Runner protocol capability set."""

    values: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class RuntimeProviderRegistration:
    """Provider registration payload accepted by Control."""

    provider_id: str
    provider_type: str
    scope: str
    workspace_id: str | None
    protocol_version: str
    capabilities: RuntimeProtocolCapabilities
    config_schema_version: str
    metadata: dict[str, JsonValue]
    auth_credential_id: str
    connection_id: str
    owner_replica_id: str


@dataclasses.dataclass(frozen=True)
class RuntimeProviderRegistrationAccepted:
    """Provider registration result issued by Control."""

    provider_id: str
    connection_id: str
    generation: int
    heartbeat_interval_seconds: int


@dataclasses.dataclass(frozen=True)
class RuntimeRunnerRegistration:
    """Runner registration payload accepted by Control."""

    runtime_id: str
    runner_id: str
    protocol_version: str
    capabilities: RuntimeProtocolCapabilities
    health: str
    workspace_path: str
    metadata: dict[str, JsonValue]
    auth_credential_id: str
    connection_id: str
    owner_replica_id: str


@dataclasses.dataclass(frozen=True)
class RuntimeRunnerRegistrationAccepted:
    """Runner registration result issued by Control."""

    runtime_id: str
    runner_id: str
    connection_id: str
    generation: int
    heartbeat_interval_seconds: int


@dataclasses.dataclass(frozen=True)
class RuntimeProviderReport:
    """Provider runtime observed-state report.

    ``workspace_path`` is the authoritative Agent Workspace path source. Runner
    state reports must not be required before UI, prompt, or file API code can
    resolve the Agent Workspace root.
    """

    runtime_id: str
    provider_id: str
    provider_generation: int
    observed_state: RuntimeProviderObservedState
    observed_desired_generation: int
    workspace_path: str | None
    reason: str | None
    diagnostic: dict[str, JsonValue]
    reported_at: datetime


@dataclasses.dataclass(frozen=True)
class RuntimeRunnerStateReport:
    """Runner state report."""

    runtime_id: str
    runner_id: str
    runner_generation: int
    runner_state: RuntimeRunnerState
    capabilities: RuntimeProtocolCapabilities
    active_operation_ids: tuple[str, ...]
    health: str
    workspace_path: str
    diagnostic: dict[str, JsonValue]
    reported_at: datetime


@dataclasses.dataclass(frozen=True)
class RuntimeProviderCommand:
    """Provider lifecycle command envelope."""

    provider_id: str
    provider_generation: int
    runtime_id: str
    desired_generation: int
    command_type: RuntimeLifecycleCommandType
    reset_final_desired_state: str | None
    payload: dict[str, JsonValue]
    deadline_at: datetime | None


@dataclasses.dataclass(frozen=True)
class RuntimeRunnerOperation:
    """Runner operation envelope."""

    runtime_id: str
    runner_generation: int
    operation_type: str
    owner_session_id: str | None
    payload: dict[str, JsonValue]
    deadline_at: datetime
    body_stream_id: str | None


@dataclasses.dataclass(frozen=True)
class RuntimeDispatchResult:
    """Control dispatch result for Provider commands and Runner operations."""

    operation_id: str
    request_id: str
    request_stream_id: str
    reply_stream_id: str
    target: RuntimeCoordinationTarget


@dataclasses.dataclass(frozen=True)
class RuntimeReplyAppendResult:
    """Result of appending a Provider/Runner reply event."""

    cursor: str
    final: bool
    operation_id: str | None


@dataclasses.dataclass(frozen=True)
class RuntimeProtocolRouteUnavailable:
    """No current connection can route the request."""

    target: RuntimeCoordinationTarget
    subject_id: str


@dataclasses.dataclass(frozen=True)
class RuntimeProtocolStaleGeneration:
    """The request or event used a stale generation token."""

    target: RuntimeCoordinationTarget
    subject_id: str
    generation: int
