"""Toolkit v1 Public API data models."""

import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from azents.core.enums import MCPOAuthConnectionStatus, ToolkitScopeType
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppAuthorizationReason,
)
from azents.services.toolkit.data import (
    TOOLKIT_SLUG_PATTERN,
    ToolkitSlug,
    ToolkitUpdateInput,
)

AgentToolkitSlug = Annotated[
    str,
    Field(
        min_length=1,
        max_length=100,
        pattern=TOOLKIT_SLUG_PATTERN,
        description=(
            "Unique within the owning Agent's effective Toolkit namespace. "
            "Use lowercase letters, numbers, and underscores only."
        ),
    ),
]


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
    always_expose_tools: bool
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
    always_expose_tools: bool = Field(
        default=False,
        description="Expose every toolkit tool directly instead of through Tool Search",
    )


class AgentToolkitConfigCreateRequest(ToolkitConfigCreateRequest):
    """Agent-owned Toolkit Config creation request."""

    slug: AgentToolkitSlug | None = Field(
        default=None,
        description=(
            "Unique within the owning Agent's effective Toolkit namespace. "
            "Use lowercase letters, numbers, and underscores only."
        ),
    )


class ToolkitConfigUpdateRequest(ToolkitUpdateInput):
    """Toolkit Config update request, for partial updates."""

    pass


class AgentToolkitConfigUpdateRequest(TypedDict, total=False):
    """Agent-owned Toolkit Config partial update request."""

    slug: AgentToolkitSlug
    name: Annotated[str, Field(description="Display name")]
    description: Annotated[str | None, Field(description="Description")]
    config: Annotated[dict[str, Any], Field(description="Tool settings")]
    prompt: Annotated[str | None, Field(description="Custom prompt")]
    credentials: Annotated[
        dict[str, object] | None,
        Field(description="Credentials JSON object (delete when None)"),
    ]
    enabled: Annotated[bool, Field(description="Enabled flag")]
    always_expose_tools: Annotated[
        bool,
        Field(
            description="Whether every tool bypasses Tool Search and remains visible"
        ),
    ]


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


class AgentToolkitManagementItemResponse(BaseModel):
    """One Toolkit in the authorized Agent management projection."""

    ownership_scope: Literal["workspace_shared", "agent_only"]
    toolkit: ToolkitConfigResponse
    agent_toolkit_id: str | None
    readiness: Literal["ready", "authorization_required", "disabled"]


class AgentToolkitManagementResponse(BaseModel):
    """Authorized Agent Toolkit management projection."""

    items: list[AgentToolkitManagementItemResponse]
    available_shared: list[ToolkitConfigResponse]


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
