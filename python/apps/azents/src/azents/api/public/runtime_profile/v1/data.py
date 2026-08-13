"""Workspace Runtime Profile v1 Public API schemas."""

import datetime

from pydantic import BaseModel, Field, ValidationError

from azents.core.runtime_profile import (
    RuntimeInfrastructureProfileSpec,
    RuntimeNetworkProjection,
    RuntimeProfileLifecycle,
    WorkspaceRuntimeProfilePolicy,
    compose_workspace_runtime_profile,
    parse_runtime_infrastructure_profile_api_spec,
    parse_runtime_infrastructure_profile_spec,
    parse_workspace_runtime_profile_policy,
    project_runtime_network,
)
from azents.repos.runtime_profile.data import WorkspaceRuntimeProfileDeletion
from azents.services.runtime_profile_workspace.service import (
    SelectableInfrastructureProfileProjection,
    WorkspaceRuntimeProfileDefaultProjection,
    WorkspaceRuntimeProfileProjection,
)


class SelectableInfrastructureProfileResponse(BaseModel):
    """One Provider/Profile option currently selectable by the Workspace."""

    id: str
    provider_id: str
    provider_display_name: str
    provider_kind: str
    profile_kind: str
    display_name: str
    description: str
    spec: RuntimeInfrastructureProfileSpec
    infrastructure_network: RuntimeNetworkProjection
    required_capabilities: list[str]
    version: int
    digest: str
    capability_revision_id: str

    @classmethod
    def convert_from(
        cls,
        projection: SelectableInfrastructureProfileProjection,
    ) -> "SelectableInfrastructureProfileResponse":
        """Convert one safe selectable Profile projection."""
        profile = projection.profile
        provider = projection.provider
        spec = parse_runtime_infrastructure_profile_api_spec(profile.spec)
        return cls(
            id=profile.id,
            provider_id=provider.provider_id,
            provider_display_name=provider.display_name,
            provider_kind=provider.kind.value,
            profile_kind=profile.profile_kind.value,
            display_name=profile.display_name,
            description=profile.description,
            spec=spec,
            infrastructure_network=project_runtime_network(spec),
            required_capabilities=list(profile.required_capabilities),
            version=profile.version,
            digest=profile.digest,
            capability_revision_id=projection.capability_revision_id,
        )


class SelectableInfrastructureProfileListResponse(BaseModel):
    """Workspace-selectable infrastructure Profile list."""

    items: list[SelectableInfrastructureProfileResponse]


class WorkspaceRuntimeProfileResponse(BaseModel):
    """One complete Workspace-owned Runtime choice."""

    id: str
    provider_id: str
    infrastructure_profile_id: str
    display_name: str
    description: str
    lifecycle: RuntimeProfileLifecycle
    policy: WorkspaceRuntimeProfilePolicy
    infrastructure_network: RuntimeNetworkProjection | None
    effective_network: RuntimeNetworkProjection | None
    version: int
    digest: str
    available: bool
    availability_reason_code: str | None
    capability_revision_id: str | None
    infrastructure_profile_version: int
    compatible: bool
    missing_capabilities: list[str]
    incompatible_constraints: list[str]
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @classmethod
    def convert_from(
        cls,
        projection: WorkspaceRuntimeProfileProjection,
    ) -> "WorkspaceRuntimeProfileResponse":
        """Convert one Workspace Profile availability projection."""
        profile = projection.profile
        compatibility = projection.compatibility
        policy = parse_workspace_runtime_profile_policy(profile.policy)
        infrastructure_network: RuntimeNetworkProjection | None = None
        effective_network: RuntimeNetworkProjection | None = None
        try:
            infrastructure = parse_runtime_infrastructure_profile_spec(
                projection.infrastructure_profile.spec
            )
            infrastructure_network = project_runtime_network(infrastructure)
            effective = parse_runtime_infrastructure_profile_spec(
                compose_workspace_runtime_profile(infrastructure, policy)
            )
            effective_network = project_runtime_network(effective)
        except ValidationError, ValueError:
            pass
        return cls(
            id=profile.id,
            provider_id=projection.provider.provider_id,
            infrastructure_profile_id=profile.infrastructure_profile_id,
            display_name=profile.display_name,
            description=profile.description,
            lifecycle=profile.lifecycle,
            policy=policy,
            infrastructure_network=infrastructure_network,
            effective_network=effective_network,
            version=profile.version,
            digest=profile.digest,
            available=projection.available,
            availability_reason_code=projection.reason_code,
            capability_revision_id=projection.capability_revision_id,
            infrastructure_profile_version=(projection.infrastructure_profile.version),
            compatible=compatibility.compatible,
            missing_capabilities=list(compatibility.missing_capabilities),
            incompatible_constraints=list(compatibility.incompatible_constraints),
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )


class WorkspaceRuntimeProfileListResponse(BaseModel):
    """Workspace-owned Runtime Profile list."""

    items: list[WorkspaceRuntimeProfileResponse]


class WorkspaceRuntimeProfileCreateRequest(BaseModel):
    """Create one complete Workspace Runtime Profile."""

    infrastructure_profile_id: str
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=4000)
    lifecycle: RuntimeProfileLifecycle = RuntimeProfileLifecycle.ACTIVE
    policy: WorkspaceRuntimeProfilePolicy


class WorkspaceRuntimeProfileReplaceRequest(BaseModel):
    """Complete optimistic replacement of one Workspace Runtime Profile."""

    expected_version: int = Field(ge=1)
    infrastructure_profile_id: str
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=4000)
    lifecycle: RuntimeProfileLifecycle
    policy: WorkspaceRuntimeProfilePolicy


class WorkspaceRuntimeProfileDeleteRequest(BaseModel):
    """Exact optimistic Workspace Runtime Profile deletion request."""

    expected_version: int = Field(ge=1)


class WorkspaceRuntimeProfileDeleteResponse(BaseModel):
    """Bounded impact from one committed Runtime Profile deletion."""

    profile_id: str
    cleared_workspace_default: bool
    cleared_agent_count: int = Field(ge=0)
    affected_running_runtime_count: int = Field(ge=0)
    superseded_recreation_operation_count: int = Field(ge=0)

    @classmethod
    def convert_from(
        cls,
        deletion: WorkspaceRuntimeProfileDeletion,
    ) -> "WorkspaceRuntimeProfileDeleteResponse":
        """Convert one committed deletion result."""
        return cls(
            profile_id=deletion.profile_id,
            cleared_workspace_default=deletion.cleared_workspace_default,
            cleared_agent_count=deletion.cleared_agent_count,
            affected_running_runtime_count=(deletion.affected_running_runtime_count),
            superseded_recreation_operation_count=(
                deletion.superseded_recreation_operation_count
            ),
        )


class WorkspaceRuntimeProfileDefaultResponse(BaseModel):
    """Current optimistic Workspace Runtime Profile default."""

    runtime_profile_id: str | None
    version: int = Field(ge=1)
    profile: WorkspaceRuntimeProfileResponse | None

    @classmethod
    def convert_from(
        cls,
        projection: WorkspaceRuntimeProfileDefaultProjection,
    ) -> "WorkspaceRuntimeProfileDefaultResponse":
        """Convert the default and optional availability projection."""
        return cls(
            runtime_profile_id=projection.runtime_profile_id,
            version=projection.version,
            profile=(
                WorkspaceRuntimeProfileResponse.convert_from(projection.profile)
                if projection.profile is not None
                else None
            ),
        )


class WorkspaceRuntimeProfileDefaultReplaceRequest(BaseModel):
    """Optimistically set or clear the Workspace Runtime Profile default."""

    expected_version: int = Field(ge=1)
    runtime_profile_id: str | None
