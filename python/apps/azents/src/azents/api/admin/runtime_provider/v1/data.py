"""Runtime Provider inventory v1 Admin API schemas."""

from typing import Any

from pydantic import BaseModel, Field

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
    RuntimeProviderLifecycleState,
)
from azents.repos.runtime_provider.data import RuntimeProvider


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
