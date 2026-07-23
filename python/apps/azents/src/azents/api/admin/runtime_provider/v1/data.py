"""Runtime Provider inventory and authentication v1 Admin API schemas."""

import datetime
from typing import Any

from pydantic import AwareDatetime, BaseModel, Field

from azents.core.enums import (
    RuntimeProviderAuthMethod,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBindingAuditEventType,
    RuntimeProviderBindingOwner,
    RuntimeProviderBindingState,
    RuntimeProviderLifecycleState,
)
from azents.repos.runtime_provider.data import RuntimeProvider
from azents.repos.runtime_provider_binding.data import (
    RuntimeProviderAuthBindingAuditEvent,
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
    accepted_contract_revision_id: str | None
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
            accepted_contract_revision_id=provider.accepted_contract_revision_id,
            active_config_revision_id=provider.active_config_revision_id,
            admin_version=provider.admin_version,
            capabilities=provider.capabilities,
            config_schema=provider.config_schema,
            metadata=provider.metadata,
        )


class RuntimeProviderListResponse(BaseModel):
    """Provider inventory response."""

    items: list[RuntimeProviderResponse]


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
