"""Toolkit service data models."""

import dataclasses
import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, computed_field
from typing_extensions import TypedDict

from azents.core.github_user_oauth import GitHubUserConnectionSummary
from azents.repos.mcp_oauth_connection.data import (
    MCPOAuthConnection,
    MCPOAuthConnectionSummary,
)
from azents.repos.toolkit.data import AgentToolkit, ToolkitConfig
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppAuthorizationState,
)

ToolkitSlugInput = Annotated[
    str,
    Field(
        description=(
            "Optional base alias. Explicit values are normalized to lowercase ASCII "
            "letters, numbers, and underscores."
        ),
    ),
]
ToolkitNameInput = Annotated[str, Field(max_length=255, description="Display name")]


class ToolkitOutput(ToolkitConfig):
    """Toolkit output model."""

    oauth_connection: MCPOAuthConnectionSummary | None = Field(
        default=None, description="MCP OAuth connection summary"
    )
    authorization_state: PlatformGitHubAppAuthorizationState | None = Field(
        default=None,
        description="Redacted provider authorization state",
    )

    github_user_connection: GitHubUserConnectionSummary | None = Field(
        default=None, description="Redacted GitHub user-account connection metadata"
    )
    github_user_cleanup_pending: bool = Field(
        default=False,
        description="Whether retired GitHub user token cleanup is incomplete",
    )

    # The type checker cannot infer the Pydantic computed_field/property combination.
    @computed_field
    @property
    def has_credentials(self) -> bool:
        """Credential existence flag."""
        return self.credentials is not None


class AgentToolkitOutput(AgentToolkit):
    """AgentToolkit output model."""

    pass


class ToolkitListOutput(BaseModel):
    """Toolkit list output model."""

    items: list[ToolkitOutput] = Field(description="Toolkit list")


class AgentToolkitListOutput(BaseModel):
    """AgentToolkit list output model."""

    items: list[AgentToolkitOutput] = Field(description="AgentToolkit list")


ToolkitOwnershipScope = Literal["workspace_shared", "agent_only"]
ToolkitReadiness = Literal["ready", "authorization_required", "disabled"]


class AgentToolkitManagementItemOutput(BaseModel):
    """One Toolkit shown in the authorized Agent management projection."""

    ownership_scope: ToolkitOwnershipScope
    toolkit: ToolkitOutput
    agent_toolkit_id: str | None
    readiness: ToolkitReadiness


class AgentToolkitManagementOutput(BaseModel):
    """Authorized Agent Toolkit management projection."""

    items: list[AgentToolkitManagementItemOutput]
    available_shared: list[ToolkitOutput]


@dataclasses.dataclass(frozen=True)
class AgentToolkitOAuthContext:
    """Authorized Agent-owned Toolkit and its current OAuth connection."""

    toolkit: ToolkitOutput
    connection: MCPOAuthConnection | None


@dataclasses.dataclass(frozen=True)
class AgentToolkitOAuthConnectionInput:
    """OAuth connection values ready for encrypted persistence."""

    issuer: str | None
    resource: str | None
    server_url: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None
    client_id: str
    client_secret: str | None
    token_endpoint_auth_method: str
    scope: str | None
    access_token: str | None
    refresh_token: str | None
    expires_at: datetime.datetime | None


class ToolkitCreateInput(BaseModel):
    """Toolkit create input model."""

    workspace_id: str = Field(description="Workspace ID")
    toolkit_type: str = Field(description="Tool type")
    slug: ToolkitSlugInput | None = Field(
        default=None,
        description=(
            "Optional base alias; omitted or blank values use the Name default."
        ),
    )
    name: ToolkitNameInput | None = Field(
        default=None,
        description=(
            "Optional display name for registered Providers; generic MCP requires one."
        ),
    )
    description: str | None = Field(default=None, description="Description")
    config: dict[str, object] = Field(description="Tool settings")
    prompt: str | None = Field(default=None, description="Custom prompt")
    credentials: dict[str, object] | None = Field(
        default=None, description="Credentials JSON object"
    )
    enabled: bool = Field(default=True, description="Enabled flag")
    always_expose_tools: bool = Field(
        description="Whether every tool bypasses Tool Search and remains visible",
    )


class ToolkitUpdateInput(TypedDict, total=False):
    """Toolkit update input model.

    Credentials type differs from repo ToolkitUpdate (dict vs str).
    Defined as separate TypedDict because service needs json.dumps() conversion.
    """

    slug: ToolkitSlugInput
    name: ToolkitNameInput
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


class AgentToolkitCreateInput(BaseModel):
    """AgentToolkit create input model."""

    agent_id: str = Field(description="Agent ID")
    toolkit_id: str = Field(description="Toolkit ID")


@dataclasses.dataclass(frozen=True)
class NotBelongToWorkspace:
    """Resource does not belong to requested workspace."""

    toolkit_id: str


@dataclasses.dataclass(frozen=True)
class AgentToolkitNotBelongToAgent:
    """AgentToolkit does not belong to requested agent."""

    agent_toolkit_id: str


@dataclasses.dataclass(frozen=True)
class ToolkitNotAvailable:
    """Attempted to mount Toolkit not exposed to user."""

    toolkit_id: str


@dataclasses.dataclass(frozen=True)
class InvalidToolkitType:
    """Toolkit type absent from TOOL_REGISTRY."""

    toolkit_type: str


@dataclasses.dataclass(frozen=True)
class InvalidConfig:
    """config schema validation failed."""

    toolkit_type: str
    detail: str


@dataclasses.dataclass(frozen=True)
class InvalidIdentifier:
    """Name or Slug validation failed after default resolution."""

    field: Literal["name", "slug"]
    detail: str


@dataclasses.dataclass(frozen=True)
class InvalidCredentials:
    """Provider-specific credentials validation failed."""

    detail: str


@dataclasses.dataclass(frozen=True)
class AgentNotBelongToWorkspace:
    """Agent does not belong to requested workspace."""

    agent_id: str
