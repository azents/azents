"""AgentSubagent service data models."""

import dataclasses
import datetime

from pydantic import BaseModel, Field

from azents.repos.agent_subagent.data import AgentSubagentUpdate


class AgentSubagentOutput(BaseModel):
    """AgentSubagent output model."""

    id: str = Field(description="AgentSubagent ID")
    agent_id: str = Field(description="Parent agent ID")
    subagent_id: str = Field(description="Subagent ID")
    description: str = Field(description="Description exposed to LLM")
    enabled: bool = Field(description="Enabled flag")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class AgentSubagentCreateInput(BaseModel):
    """AgentSubagent create input model."""

    agent_id: str = Field(description="Parent agent ID")
    subagent_id: str = Field(description="Subagent ID")
    description: str = Field(description="Description exposed to LLM")
    enabled: bool = Field(default=True, description="Enabled flag")


class AgentSubagentUpdateInput(AgentSubagentUpdate):
    """AgentSubagent update input model."""

    pass


class AgentSubagentListOutput(BaseModel):
    """AgentSubagent list output model."""

    items: list[AgentSubagentOutput] = Field(description="subagent link list")


# --- Error types ---


@dataclasses.dataclass(frozen=True)
class AgentNotFound:
    """Parent agent not found."""

    agent_id: str


@dataclasses.dataclass(frozen=True)
class SubagentNotFound:
    """Subagent not found."""

    subagent_id: str


@dataclasses.dataclass(frozen=True)
class InvalidAgentRole:
    """Agent role differs from expected role."""

    agent_id: str
    expected: str
    actual: str


@dataclasses.dataclass(frozen=True)
class CrossWorkspace:
    """Agent and subagent belong to different workspaces."""

    agent_id: str
    subagent_id: str
