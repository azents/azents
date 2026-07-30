"""Runtime Profile persistence data contracts."""

import datetime
from dataclasses import dataclass
from typing import Any

from azents.core.runtime_profile import (
    RuntimeConfigurationResolutionStatus,
    RuntimeInfrastructureProfileKind,
    RuntimeProfileLifecycle,
    RuntimeReconcileSourceKind,
    RuntimeReconcileTaskStatus,
    RuntimeRecreationItemStatus,
    RuntimeRecreationOperationStatus,
    RuntimeRecreationTargetKind,
)


@dataclass(frozen=True)
class RuntimeInfrastructureProfile:
    """One Provider-owned typed infrastructure Profile."""

    id: str
    provider_id: str
    profile_kind: RuntimeInfrastructureProfileKind
    display_name: str
    description: str
    lifecycle: RuntimeProfileLifecycle
    contract_family: str
    schema_version: int
    spec: dict[str, Any]
    required_capabilities: tuple[str, ...]
    version: int
    digest: str
    created_by_user_id: str | None
    updated_by_user_id: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeInfrastructureProfileCreate:
    """Values for one initial Provider infrastructure Profile revision."""

    provider_id: str
    profile_kind: RuntimeInfrastructureProfileKind
    display_name: str
    description: str
    lifecycle: RuntimeProfileLifecycle
    contract_family: str
    schema_version: int
    spec: dict[str, Any]
    required_capabilities: tuple[str, ...]
    digest: str
    actor_user_id: str | None


@dataclass(frozen=True)
class RuntimeInfrastructureProfileReplace:
    """Complete optimistic replacement of one infrastructure Profile."""

    display_name: str
    description: str
    lifecycle: RuntimeProfileLifecycle
    contract_family: str
    schema_version: int
    spec: dict[str, Any]
    required_capabilities: tuple[str, ...]
    digest: str
    actor_user_id: str | None


@dataclass(frozen=True)
class WorkspaceRuntimeProfile:
    """One complete Runtime choice owned by one Workspace."""

    id: str
    workspace_id: str
    provider_id: str
    infrastructure_profile_id: str
    display_name: str
    description: str
    lifecycle: RuntimeProfileLifecycle
    policy: dict[str, Any]
    version: int
    digest: str
    created_by_workspace_user_id: str | None
    updated_by_workspace_user_id: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class WorkspaceRuntimeProfileCreate:
    """Values for one initial Workspace Runtime Profile revision."""

    workspace_id: str
    provider_id: str
    infrastructure_profile_id: str
    display_name: str
    description: str
    lifecycle: RuntimeProfileLifecycle
    policy: dict[str, Any]
    digest: str
    actor_workspace_user_id: str | None


@dataclass(frozen=True)
class WorkspaceRuntimeProfileReplace:
    """Complete optimistic replacement of one Workspace Runtime Profile."""

    provider_id: str
    infrastructure_profile_id: str
    display_name: str
    description: str
    lifecycle: RuntimeProfileLifecycle
    policy: dict[str, Any]
    digest: str
    actor_workspace_user_id: str | None


@dataclass(frozen=True)
class RuntimeConfigurationRevision:
    """Immutable desired or applied full Runtime configuration evidence."""

    id: str
    runtime_id: str
    provider_id: str
    provider_capability_revision_id: str | None
    infrastructure_profile_id: str
    infrastructure_profile_version: int
    workspace_runtime_profile_id: str
    workspace_runtime_profile_version: int
    agent_selection_version: int
    resolution_status: RuntimeConfigurationResolutionStatus
    reason_code: str | None
    required_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    resolved_configuration: dict[str, Any] | None
    source_trace: dict[str, Any]
    digest: str
    target_desired_generation: int
    provider_reported_digest: str | None
    runner_reported_digest: str | None
    provider_acknowledged_at: datetime.datetime | None
    runtime_observed_at: datetime.datetime | None
    created_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeConfigurationRevisionCreate:
    """Complete values for immutable Runtime configuration evidence."""

    runtime_id: str
    provider_id: str
    provider_capability_revision_id: str | None
    infrastructure_profile_id: str
    infrastructure_profile_version: int
    workspace_runtime_profile_id: str
    workspace_runtime_profile_version: int
    agent_selection_version: int
    resolution_status: RuntimeConfigurationResolutionStatus
    reason_code: str | None
    required_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    resolved_configuration: dict[str, Any] | None
    source_trace: dict[str, Any]
    digest: str
    target_desired_generation: int


@dataclass(frozen=True)
class RuntimeConfigurationReconcileTask:
    """Durable bounded fan-out task for one changed source version."""

    id: str
    source_type: RuntimeReconcileSourceKind
    source_id: str
    source_version: str
    cursor: str | None
    status: RuntimeReconcileTaskStatus
    attempt: int
    available_at: datetime.datetime
    failure_code: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeRecreationOperation:
    """One authority-scoped durable recreation operation."""

    id: str
    target_kind: RuntimeRecreationTargetKind
    target_id: str
    target_version: str
    status: RuntimeRecreationOperationStatus
    concurrency_limit: int
    actor_user_id: str | None
    actor_workspace_user_id: str | None
    total_count: int
    pending_count: int
    running_count: int
    succeeded_count: int
    skipped_count: int
    failed_count: int
    created_at: datetime.datetime
    started_at: datetime.datetime | None
    completed_at: datetime.datetime | None


@dataclass(frozen=True)
class RuntimeRecreationOperationItem:
    """One generation-fenced Runtime item in a recreation operation."""

    id: str
    operation_id: str
    runtime_id: str
    expected_configuration_revision_id: str
    status: RuntimeRecreationItemStatus
    attempt: int
    failure_code: str | None
    failure_message: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
