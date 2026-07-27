"""Runtime Execution v1 Admin API schemas."""

import datetime
from typing import Self

from pydantic import BaseModel, Field

from azents.core.runtime_execution_policy import (
    RuntimeExecutionAuditEventType,
    RuntimeExecutionChangeDirection,
    RuntimeExecutionManagementLayer,
    RuntimeExecutionPolicyDocument,
    RuntimeExecutionProfileLifecycle,
    RuntimeExecutionStorageMode,
)
from azents.repos.runtime_execution_policy.data import (
    RuntimeExecutionPolicyAuditEvent,
    RuntimeExecutionProfile,
)
from azents.services.runtime_execution_policy.service import (
    RuntimeExecutionManagementCapabilities,
)


class RuntimeExecutionManagementCapabilitiesResponse(BaseModel):
    """Safe server-owned policy management capability gate."""

    docker: bool
    storage_modes: list[RuntimeExecutionStorageMode]

    @classmethod
    def convert_from(cls, data: RuntimeExecutionManagementCapabilities) -> Self:
        """Convert the current server capability gate."""
        return cls(
            docker=data.docker,
            storage_modes=list(data.storage_modes),
        )


class RuntimeExecutionProfileResponse(BaseModel):
    """One stable named Runtime execution Profile."""

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

    @classmethod
    def convert_from(cls, data: RuntimeExecutionProfile) -> Self:
        """Convert one Profile to a safe API response."""
        return cls(
            id=data.id,
            display_name=data.display_name,
            description=data.description,
            lifecycle=data.lifecycle,
            version=data.version,
            policy=data.policy,
            digest=data.digest,
            reserved=data.reserved,
            system_key=data.system_key,
            updated_by_user_id=data.updated_by_user_id,
            created_at=data.created_at,
            updated_at=data.updated_at,
        )


class RuntimeExecutionProfileListResponse(BaseModel):
    """Paginated Profile collection."""

    items: list[RuntimeExecutionProfileResponse]
    capabilities: RuntimeExecutionManagementCapabilitiesResponse


class RuntimeExecutionProfileCreateRequest(BaseModel):
    """Create one ordinary active Profile."""

    profile_id: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^[a-z0-9][a-z0-9-]*$",
    )
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=4000)
    policy: RuntimeExecutionPolicyDocument


class RuntimeExecutionProfileReplaceRequest(BaseModel):
    """Complete optimistic Profile replacement."""

    expected_version: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=4000)
    policy: RuntimeExecutionPolicyDocument


class RuntimeExecutionProfileRetireRequest(BaseModel):
    """Optimistic Profile retirement."""

    expected_version: int = Field(ge=1)


class RuntimeExecutionPolicyAuditEventResponse(BaseModel):
    """Metadata-only execution-policy audit event."""

    id: str
    event_type: RuntimeExecutionAuditEventType
    management_layer: RuntimeExecutionManagementLayer
    target_id: str
    correlation_id: str
    classification: RuntimeExecutionChangeDirection
    changed_paths: list[str]
    impact_counts: dict[str, int]
    reason_code: str
    outcome_code: str
    workspace_id: str | None
    agent_id: str | None
    runtime_id: str | None
    actor_user_id: str | None
    actor_workspace_user_id: str | None
    system_authority: bool
    before_digest: str | None
    after_digest: str | None
    created_at: datetime.datetime

    @classmethod
    def convert_from(cls, data: RuntimeExecutionPolicyAuditEvent) -> Self:
        """Convert an audit row without policy or secret payloads."""
        return cls(
            id=data.id,
            event_type=data.event_type,
            management_layer=data.management_layer,
            target_id=data.target_id,
            correlation_id=data.correlation_id,
            classification=data.classification,
            changed_paths=list(data.changed_paths),
            impact_counts=data.impact_counts,
            reason_code=data.reason_code,
            outcome_code=data.outcome_code,
            workspace_id=data.workspace_id,
            agent_id=data.agent_id,
            runtime_id=data.runtime_id,
            actor_user_id=data.actor_user_id,
            actor_workspace_user_id=data.actor_workspace_user_id,
            system_authority=data.system_authority,
            before_digest=data.before_digest,
            after_digest=data.after_digest,
            created_at=data.created_at,
        )


class RuntimeExecutionPolicyAuditListResponse(BaseModel):
    """Metadata-only execution-policy audit collection."""

    items: list[RuntimeExecutionPolicyAuditEventResponse]
