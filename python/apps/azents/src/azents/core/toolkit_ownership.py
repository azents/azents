"""Canonical Toolkit ownership and personal access policy."""

import dataclasses
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from typing_extensions import Annotated


class ToolkitOwnerKind(StrEnum):
    """Persisted canonical ownership discriminator constrained with owner keys."""

    WORKSPACE = "workspace"
    AGENT = "agent"
    USER = "user"


class PersonalToolkitAccessMode(StrEnum):
    """One connection-wide personal permission policy."""

    ALL = "all"
    SELECTED = "selected"


class WorkspaceToolkitOwner(BaseModel):
    """A connection shared within its Workspace."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal[ToolkitOwnerKind.WORKSPACE]
    workspace_id: str


class AgentToolkitOwner(BaseModel):
    """An Agent-owned connection within its canonical Workspace."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal[ToolkitOwnerKind.AGENT]
    workspace_id: str
    agent_id: str


class UserToolkitOwner(BaseModel):
    """A personal connection owned by one User within one real Workspace."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal[ToolkitOwnerKind.USER]
    user_id: str
    workspace_id: str


ToolkitOwner = Annotated[
    WorkspaceToolkitOwner | AgentToolkitOwner | UserToolkitOwner,
    Field(discriminator="kind"),
]
toolkit_owner_adapter: TypeAdapter[ToolkitOwner] = TypeAdapter(ToolkitOwner)


@dataclasses.dataclass(frozen=True, slots=True)
class PersonalToolkitAccess:
    """Detached permission snapshot; ordinary access remains independently required."""

    toolkit_id: str
    owner_user_id: str
    workspace_id: str
    mode: PersonalToolkitAccessMode
    selected_agent_ids: tuple[str, ...]

    def allows_agent(self, agent_id: str) -> bool:
        """Evaluate only the saved policy, not User or Workspace authorization."""
        return (
            self.mode is PersonalToolkitAccessMode.ALL
            or agent_id in self.selected_agent_ids
        )
