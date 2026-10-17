"""Canonical Toolkit ownership and personal access policy."""

import dataclasses
from enum import StrEnum
from typing import Literal, assert_never

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


def toolkit_owner_from_fields(
    kind: ToolkitOwnerKind,
    *,
    workspace_id: str | None,
    agent_id: str | None,
    user_id: str | None,
) -> ToolkitOwner:
    """Decode the constrained canonical key shape once at a detached boundary."""
    match kind:
        case ToolkitOwnerKind.WORKSPACE:
            if workspace_id is None or agent_id is not None or user_id is not None:
                raise ValueError("Invalid Workspace Toolkit owner shape")
            return WorkspaceToolkitOwner(kind=kind, workspace_id=workspace_id)
        case ToolkitOwnerKind.AGENT:
            if workspace_id is None or agent_id is None or user_id is not None:
                raise ValueError("Invalid Agent Toolkit owner shape")
            return AgentToolkitOwner(
                kind=kind, workspace_id=workspace_id, agent_id=agent_id
            )
        case ToolkitOwnerKind.USER:
            if workspace_id is None or agent_id is not None or user_id is None:
                raise ValueError("Invalid User Toolkit owner shape")
            return UserToolkitOwner(
                kind=kind, user_id=user_id, workspace_id=workspace_id
            )
        case _:
            assert_never(kind)


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
