"""AgentSubagent repository data models."""

import dataclasses
import datetime
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class SubagentToolkitInheritMode(str, Enum):
    """Subagent toolkit inherit mode.

    Stored at Agent row (agents table) level (DP1 A). Consistent with Model
    inherit at the same level.

    - ``NONE``: Use only subagent own ``agent_toolkits`` (existing behavior).
    - ``ALL``: Use only parent toolkit and ignore subagent own toolkit.
      (DP6 exclusive).
    """

    NONE = "none"
    ALL = "all"


class AgentSubagent(BaseModel):
    """AgentSubagent domain model."""

    id: str = Field(description="AgentSubagent ID")
    agent_id: str = Field(description="Parent agent ID")
    subagent_id: str = Field(description="Subagent ID")
    description: str = Field(description="Description exposed to LLM")
    enabled: bool = Field(description="Enabled flag")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class AgentSubagentCreate(BaseModel):
    """AgentSubagent create schema."""

    agent_id: str = Field(description="Parent agent ID")
    subagent_id: str = Field(description="Subagent ID")
    description: str = Field(description="Description exposed to LLM")
    enabled: bool = Field(default=True, description="Enabled flag")


class AgentSubagentUpdate(TypedDict, total=False):
    """AgentSubagent update schema (partial update)."""

    description: Annotated[str, Field(description="Description exposed to LLM")]
    enabled: Annotated[bool, Field(description="Enabled flag")]


@dataclasses.dataclass(frozen=True)
class NotFound:
    """AgentSubagent not found."""

    agent_subagent_id: str


@dataclasses.dataclass(frozen=True)
class DuplicateAgentSubagent:
    """Same agent-subagent link already exists."""

    agent_id: str
    subagent_id: str
