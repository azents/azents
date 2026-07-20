"""Toolkit v1 Public API data models."""

import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from azents.core.enums import MCPOAuthConnectionStatus, ToolkitScopeType
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppAuthorizationReason,
)
from azents.services.toolkit.data import ToolkitSlug, ToolkitUpdateInput


class MCPOAuthConnectionSummaryResponse(BaseModel):
    """MCP OAuth connection summary response model."""

    status: MCPOAuthConnectionStatus
    issuer: str | None = None
    resource: str | None = None
    scope: str | None = None
    expires_at: datetime.datetime | None = None


class GitHubPlatformAuthorizationStateResponse(BaseModel):
    """Redacted reconnect state for a Platform GitHub Toolkit."""

    type: Literal["github_platform_app"]
    status: Literal["reconnect_required"]
    reason: PlatformGitHubAppAuthorizationReason


class ToolkitConfigResponse(BaseModel):
    """Toolkit Config response model."""

    id: str
    workspace_id: str
    toolkit_type: str
    slug: str
    name: str
    description: str | None
    config: dict[str, Any]
    prompt: str | None
    has_credentials: bool = Field(
        default=False,
        description="Whether credentials exist",
    )
    enabled: bool
    oauth_connection: MCPOAuthConnectionSummaryResponse | None = None
    authorization_state: GitHubPlatformAuthorizationStateResponse | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class ToolkitConfigListResponse(BaseModel):
    """Toolkit Config list response model."""

    items: list[ToolkitConfigResponse]


class ToolkitConfigCreateRequest(BaseModel):
    """Toolkit Config creation request."""

    toolkit_type: str = Field(description="Tool slug")
    slug: ToolkitSlug | None = Field(
        default=None,
        description=(
            "Workspace-unique slug. Use lowercase letters, numbers, "
            "and underscores only."
        ),
    )
    name: str = Field(description="Display name")
    description: str | None = Field(default=None, description="Description")
    config: dict[str, Any] = Field(description="Tool configuration")
    prompt: str | None = Field(default=None, description="Custom prompt")
    credentials: dict[str, Any] | None = Field(
        default=None,
        description="Credentials JSON object, such as MCP, encrypted on the server",
    )
    enabled: bool = Field(default=True, description="Enabled state")


class ToolkitConfigUpdateRequest(ToolkitUpdateInput):
    """Toolkit Config update request, for partial updates."""

    pass


class ToolkitScopeResponse(BaseModel):
    """ToolkitScope response model."""

    id: str
    toolkit_id: str
    scope_type: ToolkitScopeType
    scope_id: str
    created_at: datetime.datetime


class ToolkitScopeListResponse(BaseModel):
    """ToolkitScope list response model."""

    items: list[ToolkitScopeResponse]


class AgentToolkitResponse(BaseModel):
    """AgentToolkit response model."""

    id: str
    agent_id: str
    toolkit_id: str
    toolkit_type: str
    created_at: datetime.datetime


class AgentToolkitListResponse(BaseModel):
    """AgentToolkit list response model."""

    items: list[AgentToolkitResponse]


class AgentToolkitAttachRequest(BaseModel):
    """AgentToolkit attach request."""

    toolkit_id: str = Field(description="Toolkit ID to attach")


class ToolkitResponse(BaseModel):
    """Toolkit tool definition response model."""

    slug: str = Field(description="Tool slug")
    name: str = Field(description="Tool name")
    description: str = Field(description="Tool description")
    config_schema: dict[str, Any] = Field(description="Configuration JSON Schema")
    system_prompt: str = Field(description="Definition-level system prompt")


class ToolkitListResponse(BaseModel):
    """Toolkit tool definition list response model."""

    items: list[ToolkitResponse]
