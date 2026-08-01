"""Workspace Runtime Profile v1 Public API schemas."""

import datetime

from pydantic import BaseModel, Field

from azents.core.runtime_profile import (
    RuntimeInfrastructureProfileSpec,
    RuntimeProfileLifecycle,
    WorkspaceRuntimeProfilePolicyV1,
    parse_runtime_infrastructure_profile_spec,
)
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
        return cls(
            id=profile.id,
            provider_id=provider.provider_id,
            provider_display_name=provider.display_name,
            provider_kind=provider.kind.value,
            profile_kind=profile.profile_kind.value,
            display_name=profile.display_name,
            description=profile.description,
            spec=parse_runtime_infrastructure_profile_spec(profile.spec),
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
    policy: WorkspaceRuntimeProfilePolicyV1
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
        return cls(
            id=profile.id,
            provider_id=projection.provider.provider_id,
            infrastructure_profile_id=profile.infrastructure_profile_id,
            display_name=profile.display_name,
            description=profile.description,
            lifecycle=profile.lifecycle,
            policy=WorkspaceRuntimeProfilePolicyV1.model_validate(profile.policy),
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
    policy: WorkspaceRuntimeProfilePolicyV1


class WorkspaceRuntimeProfileReplaceRequest(BaseModel):
    """Complete optimistic replacement of one Workspace Runtime Profile."""

    expected_version: int = Field(ge=1)
    infrastructure_profile_id: str
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=4000)
    lifecycle: RuntimeProfileLifecycle
    policy: WorkspaceRuntimeProfilePolicyV1


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
