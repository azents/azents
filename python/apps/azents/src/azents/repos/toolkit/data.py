"""Toolkit repository data models."""

import dataclasses
import datetime
import enum
from typing import Annotated, Any

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class ToolkitConfig(BaseModel):
    """Toolkit Config domain model (toolkit type + config stored in DB)."""

    id: str = Field(description="Toolkit ID")
    workspace_id: str = Field(description="Workspace ID")
    owner_agent_id: str | None = Field(description="Owning Agent ID when Agent-only")
    toolkit_type: str = Field(description="Tool type")
    slug: str = Field(description="Unique slug within the ownership scope")
    name: str = Field(description="Display name")
    description: str | None = Field(default=None, description="Description")
    config: dict[str, Any] = Field(description="Tool settings")
    prompt: str | None = Field(default=None, description="Custom prompt")
    credentials: str | None = Field(
        default=None, description="Decrypted credentials JSON (MCP, etc.)"
    )
    enabled: bool = Field(description="Enabled flag")
    always_expose_tools: bool = Field(
        description="Whether every tool bypasses Tool Search and remains visible"
    )
    revision: int = Field(description="Persisted source revision")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


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
    owner_agent_id: str | None = Field(description="Owning Agent ID when Agent-only")
    toolkit_type: str = Field(description="Tool type")
    slug: str = Field(description="Unique slug within the ownership scope")
    name: str = Field(description="Display name")
    description: str | None = Field(default=None, description="Description")
    config: dict[str, Any] = Field(description="Tool settings")
    prompt: str | None = Field(default=None, description="Custom prompt")
    credentials: str | None = Field(
        default=None, description="Credentials JSON (plaintext, encrypted by repo)"
    )
    enabled: bool = Field(default=True, description="Enabled flag")
    always_expose_tools: bool = Field(
        description="Whether every tool bypasses Tool Search and remains visible",
    )


class ToolkitUpdate(TypedDict, total=False):
    """Toolkit update schema (partial update)."""

    slug: Annotated[str, Field(description="Unique slug within workspace")]
    name: Annotated[str, Field(description="Display name")]
    description: Annotated[str | None, Field(description="Description")]
    config: Annotated[dict[str, Any], Field(description="Tool settings")]
    prompt: Annotated[str | None, Field(description="Custom prompt")]
    credentials: Annotated[str | None, Field(description="Credentials JSON string")]
    enabled: Annotated[bool, Field(description="Enabled flag")]
    always_expose_tools: Annotated[
        bool,
        Field(
            description="Whether every tool bypasses Tool Search and remains visible"
        ),
    ]


class AgentToolkitCreate(BaseModel):
    """AgentToolkit create schema."""

    agent_id: str = Field(description="Agent ID")
    toolkit_id: str = Field(description="Toolkit ID")
    toolkit_type: str = Field(description="Tool type (denormalized)")


class EffectiveToolkitSource(enum.StrEnum):
    """Persisted source that makes a Toolkit effective for an Agent."""

    SHARED_ATTACHMENT = "shared_attachment"
    AGENT_OWNED = "agent_owned"


class EffectiveToolkitConfig(BaseModel):
    """One enabled ToolkitConfig effective for an Agent."""

    toolkit: ToolkitConfig
    source: EffectiveToolkitSource
    agent_toolkit_id: str | None
    namespace: str = Field(description="Durable Agent-local effective namespace")


class EffectiveToolkitNamespaceMissing(RuntimeError):
    """An effective persisted Toolkit has no active namespace authority."""

    def __init__(
        self,
        *,
        agent_id: str,
        toolkit_id: str,
    ) -> None:
        super().__init__(
            f"Missing effective Toolkit namespace for Agent {agent_id}: {toolkit_id}"
        )
        self.agent_id = agent_id
        self.toolkit_id = toolkit_id


class EffectiveToolkitNamespaceMismatch(RuntimeError):
    """An effective persisted Toolkit namespace was allocated from a stale Slug."""

    def __init__(
        self,
        *,
        agent_id: str,
        toolkit_id: str,
        toolkit_slug: str,
        reservation_base_slug: str,
    ) -> None:
        super().__init__(
            f"Mismatched effective Toolkit namespace for Agent {agent_id}: {toolkit_id}"
        )
        self.agent_id = agent_id
        self.toolkit_id = toolkit_id
        self.toolkit_slug = toolkit_slug
        self.reservation_base_slug = reservation_base_slug


@dataclasses.dataclass(frozen=True)
class AgentToolkitNotFound:
    """AgentToolkit not found."""

    agent_toolkit_id: str
