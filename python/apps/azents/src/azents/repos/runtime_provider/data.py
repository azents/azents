"""RuntimeProvider repository data models."""

import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from azents.core.enums import RuntimeProviderKind, RuntimeProviderScope


class RuntimeProvider(BaseModel):
    """Runtime Provider domain model."""

    id: str = Field(description="DB row ID")
    provider_id: str = Field(description="Provider logical ID")
    scope: RuntimeProviderScope = Field(description="Provider scope")
    workspace_id: str | None = Field(default=None, description="Workspace ID")
    kind: RuntimeProviderKind = Field(description="Provider kind")
    display_name: str = Field(description="Display name")
    enabled: bool = Field(description="Provider enabled flag")
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
    """Runtime Provider create schema."""

    provider_id: str = Field(min_length=1, description="Provider logical ID")
    scope: RuntimeProviderScope = Field(description="Provider scope")
    workspace_id: str | None = Field(default=None, description="Workspace ID")
    kind: RuntimeProviderKind = Field(description="Provider kind")
    display_name: str = Field(min_length=1, description="Display name")
    enabled: bool = Field(default=True, description="Provider enabled flag")
    capabilities: dict[str, Any] = Field(
        default_factory=dict, description="Provider capabilities"
    )
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
