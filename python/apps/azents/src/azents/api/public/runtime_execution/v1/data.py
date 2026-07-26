"""Runtime Execution v1 Public API schemas."""

import datetime
from typing import Self

from pydantic import BaseModel, Field

from azents.core.runtime_execution_policy import (
    RuntimeExecutionAuditEventType,
    RuntimeExecutionAvailabilityReason,
    RuntimeExecutionChangeDirection,
    RuntimeExecutionManagementLayer,
    RuntimeExecutionPolicyDocument,
    RuntimeExecutionPolicyRestriction,
    RuntimeExecutionProfileLifecycle,
    RuntimeExecutionResolution,
)
from azents.repos.runtime_execution_policy.data import (
    RuntimeExecutionPolicyAuditEvent,
)
from azents.services.runtime_execution_policy.service import (
    AgentRuntimeExecutionPolicyView,
    RuntimeExecutionProfileAvailability,
    WorkspaceRuntimeExecutionPolicyView,
)


class WorkspaceRuntimeExecutionPolicyResponse(BaseModel):
    """Current explicit or implicit Workspace execution policy."""

    workspace_id: str
    version: int
    restriction: RuntimeExecutionPolicyRestriction
    digest: str
    allowed_profile_ids: list[str]
    updated_at: datetime.datetime | None

    @classmethod
    def convert_from(cls, data: WorkspaceRuntimeExecutionPolicyView) -> Self:
        """Convert the safe Workspace policy projection."""
        return cls(
            workspace_id=data.workspace_id,
            version=data.version,
            restriction=data.restriction,
            digest=data.digest,
            allowed_profile_ids=sorted(data.allowed_profile_ids),
            updated_at=data.updated_at,
        )


class WorkspaceRuntimeExecutionPolicyReplaceRequest(BaseModel):
    """Complete optimistic Workspace policy replacement."""

    expected_version: int = Field(ge=0)
    restriction: RuntimeExecutionPolicyRestriction
    allowed_profile_ids: set[str] = Field(min_length=1, max_length=100)


class WorkspaceRuntimeExecutionProfileResponse(BaseModel):
    """Workspace availability of one Platform Profile."""

    id: str
    display_name: str
    description: str
    lifecycle: RuntimeExecutionProfileLifecycle
    version: int
    policy: RuntimeExecutionPolicyDocument
    digest: str
    reserved: bool
    allowed: bool
    available: bool
    reason: RuntimeExecutionAvailabilityReason | None

    @classmethod
    def convert_from(cls, data: RuntimeExecutionProfileAvailability) -> Self:
        """Convert one bounded Workspace Profile availability projection."""
        profile = data.profile
        return cls(
            id=profile.id,
            display_name=profile.display_name,
            description=profile.description,
            lifecycle=profile.lifecycle,
            version=profile.version,
            policy=profile.policy,
            digest=profile.digest,
            reserved=profile.reserved,
            allowed=data.allowed,
            available=data.available,
            reason=data.reason,
        )


class WorkspaceRuntimeExecutionProfileListResponse(BaseModel):
    """Workspace-visible Profile availability collection."""

    items: list[WorkspaceRuntimeExecutionProfileResponse]


class AgentRuntimeExecutionPolicyResponse(BaseModel):
    """Configured Agent intent and hierarchy-only effective preview."""

    agent_id: str
    version: int
    profile_id: str
    profile_version: int
    profile_lifecycle: RuntimeExecutionProfileLifecycle
    restriction: RuntimeExecutionPolicyRestriction
    digest: str
    effective_preview: RuntimeExecutionResolution
    provider_compatibility_evaluated: bool
    updated_at: datetime.datetime

    @classmethod
    def convert_from(cls, data: AgentRuntimeExecutionPolicyView) -> Self:
        """Convert the safe configured Agent policy projection."""
        return cls(
            agent_id=data.setting.agent_id,
            version=data.setting.version,
            profile_id=data.setting.profile_id,
            profile_version=data.profile.version,
            profile_lifecycle=data.profile.lifecycle,
            restriction=data.setting.restriction,
            digest=data.setting.digest,
            effective_preview=data.resolution,
            provider_compatibility_evaluated=data.provider_compatibility_evaluated,
            updated_at=data.setting.updated_at,
        )


class AgentRuntimeExecutionPolicyReplaceRequest(BaseModel):
    """Complete optimistic Agent intent replacement."""

    expected_version: int = Field(ge=1)
    profile_id: str = Field(min_length=1, max_length=32)
    restriction: RuntimeExecutionPolicyRestriction


class RuntimeExecutionPolicyAuditEventResponse(BaseModel):
    """Metadata-only authorized execution-policy audit event."""

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
            actor_user_id=data.actor_user_id,
            actor_workspace_user_id=data.actor_workspace_user_id,
            system_authority=data.system_authority,
            before_digest=data.before_digest,
            after_digest=data.after_digest,
            created_at=data.created_at,
        )


class RuntimeExecutionPolicyAuditListResponse(BaseModel):
    """Metadata-only authorized execution-policy audit collection."""

    items: list[RuntimeExecutionPolicyAuditEventResponse]
