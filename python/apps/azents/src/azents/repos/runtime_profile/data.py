"""Runtime Profile persistence data contracts."""

import datetime
from dataclasses import dataclass
from typing import Any

from azents.core.runtime_profile import (
    RuntimeConfigurationDocument,
    RuntimeConfigurationStateStatus,
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
    terminal_enabled: bool
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
    terminal_enabled: bool
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
    terminal_enabled: bool
    digest: str
    actor_user_id: str | None


@dataclass(frozen=True)
class RuntimeInfrastructureProfileReference:
    """One current Workspace Runtime Profile reference and bounded usage."""

    workspace_id: str
    workspace_name: str
    workspace_handle: str
    workspace_runtime_profile_id: str
    workspace_runtime_profile_display_name: str
    workspace_runtime_profile_lifecycle: RuntimeProfileLifecycle
    workspace_runtime_profile_version: int
    selected_agent_count: int
    running_runtime_count: int


@dataclass(frozen=True)
class RuntimeInfrastructureProfileDeletionImpact:
    """Current blocking and applied-only impact for one infrastructure Profile."""

    blocking_reference_count: int
    references: tuple[RuntimeInfrastructureProfileReference, ...]
    applied_only_running_runtime_count: int
    offset: int
    limit: int


@dataclass(frozen=True)
class RuntimeInfrastructureProfileDeletion:
    """Bounded outcome from one committed infrastructure Profile deletion."""

    profile_id: str
    superseded_recreation_operation_count: int
    skipped_recreation_item_count: int


@dataclass(frozen=True)
class RuntimeInfrastructureProfileDeleteOutcome:
    """Exact deletion result or current conflict evidence."""

    deletion: RuntimeInfrastructureProfileDeletion | None
    current_profile: RuntimeInfrastructureProfile | None
    blocking_reference_count: int


@dataclass(frozen=True)
class WorkspaceRuntimeProfileUsage:
    """Current Agent selection and running Runtime counts."""

    selected_agent_count: int
    running_runtime_count: int


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
    terminal_enabled: bool
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
    terminal_enabled: bool
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
    terminal_enabled: bool
    digest: str
    actor_workspace_user_id: str | None


@dataclass(frozen=True)
class WorkspaceRuntimeProfileDeletion:
    """Bounded impact from one committed Workspace Profile deletion."""

    profile_id: str
    cleared_workspace_default: bool
    cleared_agent_count: int
    affected_running_runtime_count: int
    superseded_recreation_operation_count: int


@dataclass(frozen=True)
class WorkspaceRuntimeProfileDeleteOutcome:
    """Exact deletion result or current optimistic conflict evidence."""

    deletion: WorkspaceRuntimeProfileDeletion | None
    current_profile: WorkspaceRuntimeProfile | None


@dataclass(frozen=True)
class RuntimeConfigurationSlot:
    """One current desired configuration slot."""

    sequence: int
    status: RuntimeConfigurationStateStatus
    target_generation: int
    digest: str | None
    document: RuntimeConfigurationDocument | None
    reason_code: str | None
    provider_reported_digest: str | None
    runner_reported_digest: str | None
    provider_acknowledged_at: datetime.datetime | None
    runner_observed_at: datetime.datetime | None


@dataclass(frozen=True)
class RuntimeConfigurationAppliedSlot:
    """One current applied configuration slot."""

    sequence: int
    target_generation: int
    digest: str
    document: RuntimeConfigurationDocument
    applied_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeConfigurationState:
    """Bounded desired/applied current configuration authority."""

    runtime_id: str
    desired: RuntimeConfigurationSlot
    applied: RuntimeConfigurationAppliedSlot | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeConfigurationDesiredStateWrite:
    """Input for a current desired-state overwrite."""

    runtime_id: str
    status: RuntimeConfigurationStateStatus
    target_generation: int
    digest: str | None
    document: RuntimeConfigurationDocument | None
    reason_code: str | None


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
    expected_configuration_sequence: int
    expected_configuration_digest: str
    expected_desired_generation: int
    status: RuntimeRecreationItemStatus
    attempt: int
    dispatched_generation: int | None
    failure_code: str | None
    failure_message: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
