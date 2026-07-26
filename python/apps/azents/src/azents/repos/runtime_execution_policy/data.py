"""Runtime execution policy persistence data contracts."""

import datetime
from dataclasses import dataclass
from typing import Any

from azents.core.runtime_execution_policy import (
    RuntimeExecutionAuditEventType,
    RuntimeExecutionChangeDirection,
    RuntimeExecutionManagementLayer,
    RuntimeExecutionPolicyDocument,
    RuntimeExecutionPolicyRestriction,
    RuntimeExecutionProfileLifecycle,
)


@dataclass(frozen=True)
class RuntimeExecutionPlatformPolicy:
    """Current installation-wide execution-policy ceiling."""

    id: str
    version: int
    policy: RuntimeExecutionPolicyDocument
    digest: str
    updated_by_user_id: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeExecutionProfile:
    """Current stable named Runtime execution Profile."""

    id: str
    display_name: str
    description: str
    lifecycle: RuntimeExecutionProfileLifecycle
    version: int
    policy: RuntimeExecutionPolicyDocument
    digest: str
    reserved: bool
    system_key: str | None
    updated_by_user_id: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeExecutionProfileCreate:
    """Values for creating one mutable Profile identity."""

    id: str
    display_name: str
    description: str
    policy: RuntimeExecutionPolicyDocument
    digest: str
    updated_by_user_id: str | None


@dataclass(frozen=True)
class WorkspaceRuntimeExecutionPolicy:
    """Current Workspace restriction and complete Profile allowance set."""

    workspace_id: str
    version: int
    restriction: RuntimeExecutionPolicyRestriction
    digest: str
    allowed_profile_ids: frozenset[str]
    updated_by_workspace_user_id: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class AgentRuntimeExecutionSetting:
    """Current Agent Profile selection and restrictive override."""

    agent_id: str
    profile_id: str
    version: int
    restriction: RuntimeExecutionPolicyRestriction
    digest: str
    updated_by_workspace_user_id: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeExecutionPolicyAuditEvent:
    """One append-only metadata-only management event."""

    id: str
    event_type: RuntimeExecutionAuditEventType
    management_layer: RuntimeExecutionManagementLayer
    target_id: str
    correlation_id: str
    classification: RuntimeExecutionChangeDirection
    changed_paths: tuple[str, ...]
    impact_counts: dict[str, int]
    reason_code: str
    outcome_code: str
    metadata: dict[str, Any]
    workspace_id: str | None
    agent_id: str | None
    runtime_id: str | None
    actor_user_id: str | None
    actor_workspace_user_id: str | None
    system_authority: bool
    before_digest: str | None
    after_digest: str | None
    created_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeExecutionPolicyAuditEventCreate:
    """Values for one secret-safe execution-policy audit event."""

    event_type: RuntimeExecutionAuditEventType
    management_layer: RuntimeExecutionManagementLayer
    target_id: str
    correlation_id: str
    classification: RuntimeExecutionChangeDirection
    changed_paths: tuple[str, ...]
    impact_counts: dict[str, int]
    reason_code: str
    outcome_code: str
    metadata: dict[str, Any]
    workspace_id: str | None
    agent_id: str | None
    runtime_id: str | None
    actor_user_id: str | None
    actor_workspace_user_id: str | None
    system_authority: bool
    before_digest: str | None
    after_digest: str | None
