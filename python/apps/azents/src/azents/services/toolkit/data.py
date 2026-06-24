"""Toolkit service data models."""

import dataclasses
from typing import Annotated, Any

from pydantic import BaseModel, Field, computed_field
from typing_extensions import TypedDict

from azents.repos.mcp_oauth_connection.data import MCPOAuthConnectionSummary
from azents.repos.toolkit.data import AgentToolkit, ToolkitConfig, ToolkitScope

TOOLKIT_SLUG_PATTERN = r"^[a-z0-9_]+$"
TOOLKIT_SLUG_DESCRIPTION = (
    "Workspace-unique slug. Use lowercase letters, numbers, and underscores only."
)
ToolkitSlug = Annotated[
    str,
    Field(
        min_length=1,
        max_length=100,
        pattern=TOOLKIT_SLUG_PATTERN,
        description=TOOLKIT_SLUG_DESCRIPTION,
    ),
]


class ToolkitOutput(ToolkitConfig):
    """Toolkit output model."""

    oauth_connection: MCPOAuthConnectionSummary | None = Field(
        default=None, description="MCP OAuth connection summary"
    )

    # pyright cannot infer type for Pydantic computed_field + property combination
    @computed_field
    @property
    def has_credentials(self) -> bool:
        """Credential existence flag."""
        return self.credentials is not None


class ToolkitScopeOutput(ToolkitScope):
    """ToolkitScope output model."""

    pass


class AgentToolkitOutput(AgentToolkit):
    """AgentToolkit output model."""

    pass


class ToolkitListOutput(BaseModel):
    """Toolkit list output model."""

    items: list[ToolkitOutput] = Field(description="Toolkit list")


class ToolkitScopeListOutput(BaseModel):
    """ToolkitScope list output model."""

    items: list[ToolkitScopeOutput] = Field(description="ToolkitScope list")


class AgentToolkitListOutput(BaseModel):
    """AgentToolkit list output model."""

    items: list[AgentToolkitOutput] = Field(description="AgentToolkit list")


class ToolkitCreateInput(BaseModel):
    """Toolkit create input model."""

    workspace_id: str = Field(description="Workspace ID")
    toolkit_type: str = Field(description="Tool type")
    slug: ToolkitSlug | None = Field(
        default=None,
        description=(
            "Unique slug within workspace (uses toolkit_type when unspecified). "
            "Use lowercase letters, numbers, and underscores only."
        ),
    )
    name: str = Field(description="Display name")
    description: str | None = Field(default=None, description="Description")
    config: dict[str, object] = Field(description="Tool settings")
    prompt: str | None = Field(default=None, description="Custom prompt")
    credentials: dict[str, object] | None = Field(
        default=None, description="Credentials JSON object"
    )
    enabled: bool = Field(default=True, description="Enabled flag")


class ToolkitUpdateInput(TypedDict, total=False):
    """Toolkit update input model.

    Credentials type differs from repo ToolkitUpdate (dict vs str).
    Defined as separate TypedDict because service needs json.dumps() conversion.
    """

    slug: ToolkitSlug
    name: Annotated[str, Field(description="Display name")]
    description: Annotated[str | None, Field(description="Description")]
    config: Annotated[dict[str, Any], Field(description="Tool settings")]
    prompt: Annotated[str | None, Field(description="Custom prompt")]
    credentials: Annotated[
        dict[str, object] | None,
        Field(description="Credentials JSON object (delete when None)"),
    ]
    enabled: Annotated[bool, Field(description="Enabled flag")]


class ToolkitScopeCreateInput(BaseModel):
    """ToolkitScope create input model."""

    toolkit_id: str = Field(description="Toolkit ID")


class AgentToolkitCreateInput(BaseModel):
    """AgentToolkit create input model."""

    agent_id: str = Field(description="Agent ID")
    toolkit_id: str = Field(description="Toolkit ID")


@dataclasses.dataclass(frozen=True)
class NotBelongToWorkspace:
    """Resource does not belong to requested workspace."""

    toolkit_id: str


@dataclasses.dataclass(frozen=True)
class ScopeNotBelongToToolkit:
    """Scope does not belong to requested Toolkit."""

    scope_id: str


@dataclasses.dataclass(frozen=True)
class AgentToolkitNotBelongToAgent:
    """AgentToolkit does not belong to requested agent."""

    agent_toolkit_id: str


@dataclasses.dataclass(frozen=True)
class ToolkitNotAvailable:
    """Attempted to mount Toolkit not exposed to user."""

    toolkit_id: str


@dataclasses.dataclass(frozen=True)
class DuplicateSlug:
    """Same slug already exists in workspace."""

    slug: str


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
class InvalidCredentials:
    """Provider-specific credentials validation failed."""

    detail: str


@dataclasses.dataclass(frozen=True)
class AgentNotBelongToWorkspace:
    """Agent does not belong to requested workspace."""

    agent_id: str
