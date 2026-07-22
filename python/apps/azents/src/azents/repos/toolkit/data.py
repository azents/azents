"""Toolkit repository data models."""

import dataclasses
import datetime
from typing import Annotated, Any

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from azents.core.enums import ToolkitScopeType


class ToolkitConfig(BaseModel):
    """Toolkit Config domain model (toolkit type + config stored in DB)."""

    id: str = Field(description="Toolkit ID")
    workspace_id: str = Field(description="Workspace ID")
    toolkit_type: str = Field(description="Tool type")
    slug: str = Field(description="Unique slug within workspace")
    name: str = Field(description="Display name")
    description: str | None = Field(default=None, description="Description")
    config: dict[str, Any] = Field(description="Tool settings")
    prompt: str | None = Field(default=None, description="Custom prompt")
    credentials: str | None = Field(
        default=None, description="Decrypted credentials JSON (MCP, etc.)"
    )
    enabled: bool = Field(description="Enabled flag")
    revision: int = Field(description="Persisted source revision")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class ToolkitScope(BaseModel):
    """ToolkitScope domain model."""

    id: str = Field(description="Scope ID")
    toolkit_id: str = Field(description="Toolkit ID")
    scope_type: ToolkitScopeType = Field(description="Scope type")
    scope_id: str = Field(description="Scope target ID")
    created_at: datetime.datetime = Field(description="Created time")


class AgentToolkit(BaseModel):
    """AgentToolkit domain model."""

    id: str = Field(description="AgentToolkit ID")
    agent_id: str = Field(description="Agent ID")
    toolkit_id: str = Field(description="Toolkit ID")
    toolkit_type: str = Field(description="Tool type (denormalized)")
    created_at: datetime.datetime = Field(description="Created time")


class ToolkitCreate(BaseModel):
    """Toolkit create schema."""

    workspace_id: str = Field(description="Workspace ID")
    toolkit_type: str = Field(description="Tool type")
    slug: str = Field(description="Unique slug within workspace")
    name: str = Field(description="Display name")
    description: str | None = Field(default=None, description="Description")
    config: dict[str, Any] = Field(description="Tool settings")
    prompt: str | None = Field(default=None, description="Custom prompt")
    credentials: str | None = Field(
        default=None, description="Credentials JSON (plaintext, encrypted by repo)"
    )
    enabled: bool = Field(default=True, description="Enabled flag")


class ToolkitUpdate(TypedDict, total=False):
    """Toolkit update schema (partial update)."""

    slug: Annotated[str, Field(description="Unique slug within workspace")]
    name: Annotated[str, Field(description="Display name")]
    description: Annotated[str | None, Field(description="Description")]
    config: Annotated[dict[str, Any], Field(description="Tool settings")]
    prompt: Annotated[str | None, Field(description="Custom prompt")]
    credentials: Annotated[str | None, Field(description="Credentials JSON string")]
    enabled: Annotated[bool, Field(description="Enabled flag")]


class ToolkitScopeCreate(BaseModel):
    """ToolkitScope create schema."""

    toolkit_id: str = Field(description="Toolkit ID")
    scope_type: ToolkitScopeType = Field(description="Scope type")
    scope_id: str = Field(description="Scope target ID")


class AgentToolkitCreate(BaseModel):
    """AgentToolkit create schema."""

    agent_id: str = Field(description="Agent ID")
    toolkit_id: str = Field(description="Toolkit ID")
    toolkit_type: str = Field(description="Tool type (denormalized)")


@dataclasses.dataclass(frozen=True)
class NotFound:
    """Toolkit not found."""

    toolkit_id: str


@dataclasses.dataclass(frozen=True)
class ScopeNotFound:
    """ToolkitScope not found."""

    scope_id: str


@dataclasses.dataclass(frozen=True)
class AgentToolkitNotFound:
    """AgentToolkit not found."""

    agent_toolkit_id: str


@dataclasses.dataclass(frozen=True)
class DuplicateScope:
    """Same scope already exists."""

    toolkit_id: str
    scope_type: ToolkitScopeType
    scope_id: str


@dataclasses.dataclass(frozen=True)
class DuplicateSlug:
    """Toolkit with same slug already exists in workspace."""

    workspace_id: str
    slug: str


@dataclasses.dataclass(frozen=True)
class DuplicateAgentToolkit:
    """Same Toolkit is already mounted on agent."""

    agent_id: str
    toolkit_id: str
