"""Agent repository data models."""

import dataclasses
import datetime
from typing import Annotated

from pydantic import BaseModel, Field
from typing_extensions import Self, TypedDict

from azents.core.agent import AgentModelSelection, ModelParameters
from azents.core.enums import AgentRole, AgentType
from azents.repos.agent_subagent.data import SubagentToolkitInheritMode
from azents.services.uploads.schema import StoredImage


class Agent(BaseModel):
    """Agent domain model."""

    id: str = Field(description="Agent ID")
    workspace_id: str = Field(description="Workspace ID")
    name: str = Field(description="Agent name")
    description: str | None = Field(default=None, description="Agent description")
    model_selection: AgentModelSelection = Field(
        description="Main model selection snapshot"
    )
    lightweight_model_selection: AgentModelSelection = Field(
        description="Lightweight model selection snapshot"
    )
    model_parameters: ModelParameters | None = Field(
        default=None, description="Model parameters"
    )
    system_prompt: str | None = Field(default=None, description="System prompt")
    enabled: bool = Field(description="Enabled flag")
    type: AgentType = Field(description="Visibility scope")
    role: AgentRole = Field(description="Role (agent/subagent)")
    runtime_provider_id: str | None = Field(
        default=None, description="Runtime Provider logical ID"
    )
    shell_enabled: bool = Field(default=True, description="Shell Enabled flag")
    memory_enabled: bool = Field(default=True, description="Memory enabled flag")
    max_turns: int | None = Field(default=None, description="Maximum agent turn count")
    toolkit_inherit_mode: SubagentToolkitInheritMode = Field(
        default=SubagentToolkitInheritMode.ALL,
        description="Toolkit inherit mode (meaningful when agent row role=subagent)",
    )
    avatar: StoredImage | None = Field(
        default=None,
        description="Profile image storage schema including S3 key. None when unset",
    )
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def convert_from(cls, data: "Agent") -> Self:
        """Convert from domain model."""
        return cls.model_validate(data, from_attributes=True)


class AgentCreate(BaseModel):
    """Agent create schema."""

    workspace_id: str = Field(description="Workspace ID")
    name: str = Field(description="Agent name")
    model_selection: AgentModelSelection = Field(
        description="Main model selection snapshot"
    )
    lightweight_model_selection: AgentModelSelection = Field(
        description="Lightweight model selection snapshot"
    )
    description: str | None = Field(default=None, description="Agent description")
    model_parameters: ModelParameters | None = Field(
        default=None, description="Model parameters"
    )
    system_prompt: str | None = Field(default=None, description="System prompt")
    enabled: bool = Field(default=True, description="Enabled flag")
    type: AgentType = Field(default=AgentType.PUBLIC, description="Visibility scope")
    role: AgentRole = Field(
        default=AgentRole.AGENT, description="Role (agent/subagent)"
    )
    runtime_provider_id: str | None = Field(
        default=None, description="Runtime Provider logical ID"
    )
    shell_enabled: bool = Field(default=True, description="Shell Enabled flag")
    memory_enabled: bool = Field(default=True, description="Memory enabled flag")
    max_turns: int | None = Field(default=None, description="Maximum agent turn count")
    toolkit_inherit_mode: SubagentToolkitInheritMode = Field(
        default=SubagentToolkitInheritMode.ALL,
        description="Toolkit inherit mode (default 'all' — opt-out, DP2 B)",
    )


class AgentUpdate(TypedDict, total=False):
    """Agent update schema (partial update)."""

    name: Annotated[str, Field(description="Agent name")]
    description: Annotated[str | None, Field(description="Agent description")]
    model_selection: Annotated[
        AgentModelSelection, Field(description="Main model selection snapshot")
    ]
    lightweight_model_selection: Annotated[
        AgentModelSelection,
        Field(description="Lightweight model selection snapshot"),
    ]
    model_parameters: Annotated[
        ModelParameters | None, Field(description="Model parameters")
    ]
    system_prompt: Annotated[str | None, Field(description="System prompt")]
    enabled: Annotated[bool, Field(description="Enabled flag")]
    type: Annotated[AgentType, Field(description="Visibility scope")]
    role: Annotated[AgentRole, Field(description="Role (agent/subagent)")]
    runtime_provider_id: Annotated[
        str | None, Field(description="Runtime Provider logical ID")
    ]
    shell_enabled: Annotated[bool, Field(description="Shell Enabled flag")]
    memory_enabled: Annotated[bool, Field(description="Memory enabled flag")]
    max_turns: Annotated[int | None, Field(description="Maximum agent turn count")]
    toolkit_inherit_mode: Annotated[
        SubagentToolkitInheritMode,
        Field(description="Toolkit inherit mode"),
    ]


class AgentList(BaseModel):
    """Agent list."""

    items: list[Agent] = Field(description="Agent list")


@dataclasses.dataclass(frozen=True)
class NotFound:
    """Agent not found."""

    agent_id: str
