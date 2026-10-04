"""Canonical shared runtime provider data contracts."""

import datetime
from typing import Any

from pydantic import BaseModel, Field

from azents.core.enums import (
    RuntimeProviderAvailabilityMode,
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
    current_contract_revision_id: str | None = Field(
        description="Authoritative capability revision advertised by the Provider",
    )
    active_config_revision_id: str | None = Field(
        default=None, description="Desired active Provider configuration revision ID"
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
