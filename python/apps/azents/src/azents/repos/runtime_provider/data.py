"""Runtime Provider repository data models."""

import datetime
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, model_validator

from azents.core.enums import (
    RuntimeProviderAuditEventType,
    RuntimeProviderAvailabilityMode,
    RuntimeProviderBootstrapAdapterKind,
    RuntimeProviderBootstrapDeclarationState,
    RuntimeProviderKind,
    RuntimeProviderLifecycleState,
    RuntimeProviderRegistrationMethod,
    RuntimeProviderScope,
)


class RuntimeProvider(BaseModel):
    """Runtime Provider aggregate domain model."""

    id: str = Field(description="DB row ID")
    provider_id: str = Field(description="Provider logical ID")
    scope: RuntimeProviderScope = Field(description="Provider scope")
    workspace_id: str | None = Field(default=None, description="Workspace ID")
    kind: RuntimeProviderKind = Field(description="Provider kind")
    display_name: str = Field(description="Display name")
    registration_method: RuntimeProviderRegistrationMethod = Field(
        description="Origin that established the Provider"
    )
    enabled: bool = Field(description="Provider enabled flag")
    lifecycle_state: RuntimeProviderLifecycleState = Field(
        description="Permanent Provider lifecycle state"
    )
    availability_mode: RuntimeProviderAvailabilityMode = Field(
        description="Workspace availability policy"
    )
    admin_version: int = Field(description="Provider Admin policy version")
    capabilities: dict[str, Any] = Field(description="Provider capabilities")
    config_schema: dict[str, Any] | None = Field(
        default=None, description="Provider config schema"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Provider metadata"
    )
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class RuntimeProviderCreate(BaseModel):
    """Complete values for creating a Runtime Provider aggregate."""

    provider_id: str = Field(min_length=1, description="Provider logical ID")
    scope: RuntimeProviderScope = Field(description="Provider scope")
    workspace_id: str | None = Field(default=None, description="Workspace ID")
    kind: RuntimeProviderKind = Field(description="Provider kind")
    display_name: str = Field(min_length=1, description="Display name")
    registration_method: RuntimeProviderRegistrationMethod = Field(
        description="Origin that establishes the Provider"
    )
    enabled: bool = Field(description="Provider enabled flag")
    lifecycle_state: RuntimeProviderLifecycleState = Field(
        description="Permanent Provider lifecycle state"
    )
    availability_mode: RuntimeProviderAvailabilityMode = Field(
        description="Workspace availability policy"
    )
    capabilities: dict[str, Any] = Field(description="Provider capabilities")
    config_schema: dict[str, Any] | None = Field(
        default=None, description="Provider config schema"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Provider metadata"
    )

    @model_validator(mode="after")
    def validate_scope(self) -> "RuntimeProviderCreate":
        """Validate scope and workspace_id combination."""
        if self.scope == RuntimeProviderScope.WORKSPACE and self.workspace_id is None:
            raise ValueError("Workspace runtime provider requires workspace_id")
        if self.scope == RuntimeProviderScope.SYSTEM and self.workspace_id is not None:
            raise ValueError("System runtime provider must not have workspace_id")
        return self


@dataclass(frozen=True)
class RuntimeProviderBootstrapSource:
    """Durable trusted bootstrap source state."""

    id: str
    source_key: str
    adapter_kind: RuntimeProviderBootstrapAdapterKind
    last_revision: str | None
    last_digest: str | None
    last_reconciled_at: datetime.datetime | None
    error_code: str | None
    error_message: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeProviderBootstrapSourceCreate:
    """Values needed to establish a trusted bootstrap source."""

    source_key: str
    adapter_kind: RuntimeProviderBootstrapAdapterKind


@dataclass(frozen=True)
class RuntimeProviderBootstrapDeclaration:
    """One source-owned declaration and its optional Provider link."""

    id: str
    source_id: str
    declaration_key: str
    provider_logical_id: str
    kind: RuntimeProviderKind
    provider_id: str | None
    source_revision: str
    source_digest: str
    state: RuntimeProviderBootstrapDeclarationState
    creation_seeds: dict[str, Any] | None
    conflict_code: str | None
    conflict_message: str | None
    last_seen_at: datetime.datetime | None
    withdrawn_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass(frozen=True)
class RuntimeProviderBootstrapDeclarationCreate:
    """Complete values for storing a source declaration."""

    source_id: str
    declaration_key: str
    provider_logical_id: str
    kind: RuntimeProviderKind
    provider_id: str | None
    source_revision: str
    source_digest: str
    state: RuntimeProviderBootstrapDeclarationState
    creation_seeds: dict[str, Any] | None
    conflict_code: str | None
    conflict_message: str | None
    last_seen_at: datetime.datetime | None
    withdrawn_at: datetime.datetime | None


@dataclass(frozen=True)
class RuntimeProviderAuditEventCreate:
    """Metadata-only Provider aggregate audit event values."""

    provider_id: str
    event_type: RuntimeProviderAuditEventType
    actor_user_id: str | None
    metadata: dict[str, Any] | None
    created_at: datetime.datetime
