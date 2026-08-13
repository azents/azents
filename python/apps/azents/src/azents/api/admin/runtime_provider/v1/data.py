"""Runtime Provider inventory and authentication v1 Admin API schemas."""

import datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, Field, ValidationError

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBindingAuditEventType,
    RuntimeProviderBindingOwner,
    RuntimeProviderBindingState,
    RuntimeProviderLifecycleState,
)
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
from azents.repos.runtime_provider.data import RuntimeProvider
from azents.repos.runtime_provider_binding.data import (
    RuntimeProviderAuthBindingAuditEvent,
)
from azents.repos.runtime_provider_policy.data import (
    RuntimeProviderContractRevision,
)
from azents.services.runtime_profile_admin.service import (
    AdminWorkspaceRuntimeProfileDetailProjection,
    RuntimeInfrastructureProfileDeletionImpactProjection,
    RuntimeInfrastructureProfileProjection,
)
from azents.services.runtime_provider_admin.service import (
    RuntimeProviderOperationalDiagnosticsProjection,
)
from azents.services.runtime_provider_binding_admin.service import (
    RuntimeProviderBindingAdminProjection,
    RuntimeProviderBindingRotation,
)


class RuntimeProviderResponse(BaseModel):
    """Durable Runtime Provider inventory item."""

    id: str
    provider_id: str
    scope: str
    workspace_id: str | None
    kind: str
    display_name: str
    registration_method: str
    enabled: bool
    lifecycle_state: RuntimeProviderLifecycleState
    availability_mode: RuntimeProviderAvailabilityMode
    current_contract_revision_id: str | None
    active_config_revision_id: str | None
    admin_version: int
    capabilities: dict[str, Any]
    config_schema: dict[str, Any] | None
    metadata: dict[str, Any] | None

    @classmethod
    def convert_from(cls, provider: RuntimeProvider) -> "RuntimeProviderResponse":
        """Convert the repository aggregate to the public response."""
        return cls(
            id=provider.id,
            provider_id=provider.provider_id,
            scope=provider.scope.value,
            workspace_id=provider.workspace_id,
            kind=provider.kind.value,
            display_name=provider.display_name,
            registration_method=provider.registration_method.value,
            enabled=provider.enabled,
            lifecycle_state=provider.lifecycle_state,
            availability_mode=provider.availability_mode,
            current_contract_revision_id=provider.current_contract_revision_id,
            active_config_revision_id=provider.active_config_revision_id,
            admin_version=provider.admin_version,
            capabilities=provider.capabilities,
            config_schema=provider.config_schema,
            metadata=provider.metadata,
        )


class RuntimeProviderListResponse(BaseModel):
    """Provider inventory response."""

    items: list[RuntimeProviderResponse]


class RuntimeProviderOperationalWarningResponse(BaseModel):
    """One bounded warning-only Provider deployment diagnostic."""

    code: str
    severity: str
    metadata: dict[str, str]


class RuntimeProviderOperationalDiagnosticsResponse(BaseModel):
    """Active-generation Provider diagnostics or explicit unavailability."""

    available: bool
    generation: int | None
    protocol_version: str | None
    checked_at: datetime.datetime | None
    warnings: list[RuntimeProviderOperationalWarningResponse]

    @classmethod
    def convert_from(
        cls,
        projection: RuntimeProviderOperationalDiagnosticsProjection | None,
    ) -> "RuntimeProviderOperationalDiagnosticsResponse":
        """Convert only the current active connection diagnostic snapshot."""
        if projection is None:
            return cls(
                available=False,
                generation=None,
                protocol_version=None,
                checked_at=None,
                warnings=[],
            )
        return cls(
            available=True,
            generation=projection.generation,
            protocol_version=projection.protocol_version,
            checked_at=projection.diagnostics.checked_at,
            warnings=[
                RuntimeProviderOperationalWarningResponse(
                    code=warning.code,
                    severity=warning.severity.value,
                    metadata=dict(warning.metadata),
                )
                for warning in projection.diagnostics.warnings
            ],
        )


class RuntimeProviderContractResponse(BaseModel):
    """One immutable Provider capability contract revision."""

    id: str
    digest: str
    implementation_version: str
    protocol_version: str
    contract: dict[str, Any]
    compatibility: dict[str, Any]
    created_at: datetime.datetime

    @classmethod
    def convert_from(
        cls,
        contract: RuntimeProviderContractRevision,
    ) -> "RuntimeProviderContractResponse":
        """Convert the repository contract to an Admin-safe response."""
        return cls(
            id=contract.id,
            digest=contract.digest,
            implementation_version=contract.implementation_version,
            protocol_version=contract.protocol_version,
            contract=contract.contract,
            compatibility=contract.compatibility,
            created_at=contract.created_at,
        )


class RuntimeProviderContractListResponse(BaseModel):
    """Provider contract revision history."""

    items: list[RuntimeProviderContractResponse]


class RuntimeInfrastructureProfileResponse(BaseModel):
    """One Provider-owned infrastructure Profile with compatibility evidence."""

    id: str
    profile_kind: str
    display_name: str
    description: str
    lifecycle: RuntimeProfileLifecycle
    contract_family: str
    schema_version: int
    spec: RuntimeInfrastructureProfileSpec | None
    required_capabilities: list[str]
    version: int
    digest: str
    compatible: bool
    compatibility_reason_code: str | None
    missing_capabilities: list[str]
    incompatible_constraints: list[str]
    capability_revision_id: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @classmethod
    def convert_from(
        cls,
        projection: RuntimeInfrastructureProfileProjection,
    ) -> "RuntimeInfrastructureProfileResponse":
        """Convert one compatibility projection to an Admin response."""
        profile = projection.profile
        compatibility = projection.compatibility
        try:
            spec = parse_runtime_infrastructure_profile_api_spec(profile.spec)
        except ValidationError:
            spec = None
        return cls(
            id=profile.id,
            profile_kind=profile.profile_kind.value,
            display_name=profile.display_name,
            description=profile.description,
            lifecycle=profile.lifecycle,
            contract_family=profile.contract_family,
            schema_version=profile.schema_version,
            spec=spec,
            required_capabilities=list(profile.required_capabilities),
            version=profile.version,
            digest=profile.digest,
            compatible=compatibility.compatible,
            compatibility_reason_code=compatibility.reason_code,
            missing_capabilities=list(compatibility.missing_capabilities),
            incompatible_constraints=list(compatibility.incompatible_constraints),
            capability_revision_id=projection.capability_revision_id,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )


class RuntimeInfrastructureProfileListResponse(BaseModel):
    """Provider-scoped infrastructure Profile list."""

    items: list[RuntimeInfrastructureProfileResponse]


class RuntimeInfrastructureProfileDeletionReferenceResponse(BaseModel):
    """One current Workspace Runtime Profile reference and bounded usage."""

    workspace_id: str
    workspace_name: str
    workspace_handle: str
    workspace_runtime_profile_id: str
    workspace_runtime_profile_display_name: str
    workspace_runtime_profile_lifecycle: RuntimeProfileLifecycle
    workspace_runtime_profile_version: int = Field(ge=1)
    selected_agent_count: int = Field(ge=0)
    running_runtime_count: int = Field(ge=0)


class RuntimeInfrastructureProfileDeletionImpactResponse(BaseModel):
    """Fresh deletion impact for one exact infrastructure Profile."""

    profile_id: str
    profile_kind: str
    display_name: str
    version: int = Field(ge=1)
    blocking_reference_count: int = Field(ge=0)
    references: list[RuntimeInfrastructureProfileDeletionReferenceResponse]
    applied_only_running_runtime_count: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)

    @classmethod
    def convert_from(
        cls,
        projection: RuntimeInfrastructureProfileDeletionImpactProjection,
    ) -> "RuntimeInfrastructureProfileDeletionImpactResponse":
        """Convert current Profile deletion impact to an Admin response."""
        profile = projection.profile
        impact = projection.impact
        return cls(
            profile_id=profile.id,
            profile_kind=profile.profile_kind.value,
            display_name=profile.display_name,
            version=profile.version,
            blocking_reference_count=impact.blocking_reference_count,
            references=[
                RuntimeInfrastructureProfileDeletionReferenceResponse(
                    workspace_id=reference.workspace_id,
                    workspace_name=reference.workspace_name,
                    workspace_handle=reference.workspace_handle,
                    workspace_runtime_profile_id=(
                        reference.workspace_runtime_profile_id
                    ),
                    workspace_runtime_profile_display_name=(
                        reference.workspace_runtime_profile_display_name
                    ),
                    workspace_runtime_profile_lifecycle=(
                        reference.workspace_runtime_profile_lifecycle
                    ),
                    workspace_runtime_profile_version=(
                        reference.workspace_runtime_profile_version
                    ),
                    selected_agent_count=reference.selected_agent_count,
                    running_runtime_count=reference.running_runtime_count,
                )
                for reference in impact.references
            ],
            applied_only_running_runtime_count=(
                impact.applied_only_running_runtime_count
            ),
            offset=impact.offset,
            limit=impact.limit,
        )


class RuntimeInfrastructureProfileDeleteRequest(BaseModel):
    """Exact optimistic infrastructure Profile deletion request."""

    expected_version: int = Field(ge=1)


class RuntimeInfrastructureProfileDeleteResponse(BaseModel):
    """Bounded outcome from one infrastructure Profile deletion."""

    profile_id: str
    superseded_recreation_operation_count: int = Field(ge=0)
    skipped_recreation_item_count: int = Field(ge=0)


class AdminWorkspaceRuntimeProfileDetailResponse(BaseModel):
    """System-Admin read-only Workspace Runtime Profile detail."""

    workspace_id: str
    workspace_name: str
    workspace_handle: str
    profile_id: str
    display_name: str
    description: str
    lifecycle: RuntimeProfileLifecycle
    policy: WorkspaceRuntimeProfilePolicy
    infrastructure_network: RuntimeNetworkProjection | None
    effective_network: RuntimeNetworkProjection | None
    version: int = Field(ge=1)
    digest: str
    provider_id: str
    provider_display_name: str
    provider_kind: str
    infrastructure_profile_id: str
    infrastructure_profile_display_name: str
    infrastructure_profile_kind: str
    infrastructure_profile_lifecycle: RuntimeProfileLifecycle
    infrastructure_profile_version: int = Field(ge=1)
    selected_agent_count: int = Field(ge=0)
    running_runtime_count: int = Field(ge=0)
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @classmethod
    def convert_from(
        cls,
        projection: AdminWorkspaceRuntimeProfileDetailProjection,
    ) -> "AdminWorkspaceRuntimeProfileDetailResponse":
        """Convert the System Admin read-only Workspace Profile projection."""
        profile = projection.profile
        infrastructure = projection.infrastructure_profile
        provider = projection.provider
        policy = parse_workspace_runtime_profile_policy(profile.policy)
        infrastructure_network: RuntimeNetworkProjection | None = None
        effective_network: RuntimeNetworkProjection | None = None
        try:
            infrastructure_spec = parse_runtime_infrastructure_profile_spec(
                infrastructure.spec
            )
            infrastructure_network = project_runtime_network(infrastructure_spec)
            effective_spec = parse_runtime_infrastructure_profile_spec(
                compose_workspace_runtime_profile(infrastructure_spec, policy)
            )
            effective_network = project_runtime_network(effective_spec)
        except ValidationError, ValueError:
            pass
        return cls(
            workspace_id=projection.workspace_id,
            workspace_name=projection.workspace.name,
            workspace_handle=projection.workspace.handle,
            profile_id=profile.id,
            display_name=profile.display_name,
            description=profile.description,
            lifecycle=profile.lifecycle,
            policy=policy,
            infrastructure_network=infrastructure_network,
            effective_network=effective_network,
            version=profile.version,
            digest=profile.digest,
            provider_id=provider.provider_id,
            provider_display_name=provider.display_name,
            provider_kind=provider.kind.value,
            infrastructure_profile_id=infrastructure.id,
            infrastructure_profile_display_name=infrastructure.display_name,
            infrastructure_profile_kind=infrastructure.profile_kind.value,
            infrastructure_profile_lifecycle=infrastructure.lifecycle,
            infrastructure_profile_version=infrastructure.version,
            selected_agent_count=projection.usage.selected_agent_count,
            running_runtime_count=projection.usage.running_runtime_count,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )


class RuntimeInfrastructureProfileCreateRequest(BaseModel):
    """Create one Provider-owned typed infrastructure Profile."""

    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=4000)
    lifecycle: RuntimeProfileLifecycle = RuntimeProfileLifecycle.ACTIVE
    spec: RuntimeInfrastructureProfileSpec


class RuntimeInfrastructureProfileReplaceRequest(BaseModel):
    """Complete optimistic replacement of one infrastructure Profile."""

    expected_version: int = Field(ge=1)
    display_name: str = Field(min_length=1, max_length=120)
    description: str = Field(max_length=4000)
    lifecycle: RuntimeProfileLifecycle
    spec: RuntimeInfrastructureProfileSpec


class RuntimeProviderPolicyUpdateRequest(BaseModel):
    """Mutable Provider administrative policy update."""

    enabled: bool
    lifecycle_state: RuntimeProviderLifecycleState
    availability_mode: RuntimeProviderAvailabilityMode


class RuntimeProviderAvailabilityRequest(BaseModel):
    """Workspace allow-list replacement request."""

    workspace_ids: set[str] = Field(default_factory=set)


class RuntimeProviderAuthenticationBindingResponse(BaseModel):
    """Secret-safe Provider authentication binding."""

    id: str
    provider_id: str
    auth_method: RuntimeProviderAuthMethod
    subject: str
    state: RuntimeProviderBindingState
    owner: RuntimeProviderBindingOwner
    bootstrap_declaration_id: str | None
    config: dict[str, Any] | None
    admin_version: int
    connected: bool
    last_authenticated_at: datetime.datetime | None
    last_connected_at: datetime.datetime | None
    revoked_at: datetime.datetime | None
    revoked_by_user_id: str | None
    revocation_reason: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @classmethod
    def convert_from(
        cls,
        projection: RuntimeProviderBindingAdminProjection,
    ) -> "RuntimeProviderAuthenticationBindingResponse":
        """Convert a secret-safe service projection."""
        binding = projection.binding
        return cls(
            id=binding.id,
            provider_id=projection.provider_id,
            auth_method=binding.auth_method,
            subject=binding.subject,
            state=binding.state,
            owner=binding.owner,
            bootstrap_declaration_id=binding.bootstrap_declaration_id,
            config=binding.config,
            admin_version=binding.admin_version,
            connected=projection.connected,
            last_authenticated_at=binding.last_authenticated_at,
            last_connected_at=binding.last_connected_at,
            revoked_at=binding.revoked_at,
            revoked_by_user_id=binding.revoked_by_user_id,
            revocation_reason=binding.revocation_reason,
            created_at=binding.created_at,
            updated_at=binding.updated_at,
        )


class RuntimeProviderAuthenticationBindingListResponse(BaseModel):
    """Provider-scoped authentication binding inventory."""

    items: list[RuntimeProviderAuthenticationBindingResponse]


class RuntimeProviderAuthenticationBindingCreateRequest(BaseModel):
    """Create one Admin-owned Provider authentication binding."""

    auth_method: RuntimeProviderAuthMethod
    subject: str = Field(min_length=1, max_length=255)
    config: dict[str, Any] | None


class RuntimeProviderAuthenticationBindingRotateRequest(BaseModel):
    """Rotate issued-token enrollment authority."""

    expected_admin_version: int = Field(ge=1)
    expires_at: AwareDatetime


class RuntimeProviderAuthenticationBindingRotateResponse(BaseModel):
    """One-time enrollment secret plus the rotated safe binding."""

    binding: RuntimeProviderAuthenticationBindingResponse
    grant_id: str
    secret: str
    expires_at: datetime.datetime

    @classmethod
    def convert_from(
        cls,
        rotation: RuntimeProviderBindingRotation,
    ) -> "RuntimeProviderAuthenticationBindingRotateResponse":
        """Convert a one-time rotation result."""
        return cls(
            binding=RuntimeProviderAuthenticationBindingResponse.convert_from(
                rotation.binding
            ),
            grant_id=rotation.grant_id,
            secret=rotation.secret,
            expires_at=rotation.expires_at,
        )


class RuntimeProviderAuthenticationBindingRevokeRequest(BaseModel):
    """Revoke a binding using optimistic concurrency."""

    expected_admin_version: int = Field(ge=1)
    reason: str | None = Field(max_length=255)


class RuntimeProviderAuthenticationBindingAuditEventResponse(BaseModel):
    """Metadata-only binding audit event."""

    id: str
    binding_id: str
    event_type: RuntimeProviderBindingAuditEventType
    actor_user_id: str | None
    previous_admin_version: int | None
    new_admin_version: int | None
    metadata: dict[str, Any] | None
    created_at: datetime.datetime

    @classmethod
    def convert_from(
        cls,
        event: RuntimeProviderAuthBindingAuditEvent,
    ) -> "RuntimeProviderAuthenticationBindingAuditEventResponse":
        """Convert a metadata-only audit event."""
        return cls(
            id=event.id,
            binding_id=event.binding_id,
            event_type=event.event_type,
            actor_user_id=event.actor_user_id,
            previous_admin_version=event.previous_admin_version,
            new_admin_version=event.new_admin_version,
            metadata=event.metadata,
            created_at=event.created_at,
        )


class RuntimeProviderAuthenticationBindingAuditListResponse(BaseModel):
    """Binding audit history response."""

    items: list[RuntimeProviderAuthenticationBindingAuditEventResponse]
