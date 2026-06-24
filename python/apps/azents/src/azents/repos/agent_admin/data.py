"""AgentAdmin repository data models."""

import dataclasses
import datetime

from pydantic import BaseModel, Field


class AgentAdmin(BaseModel):
    """AgentAdmin domain model."""

    id: str = Field(description="AgentAdmin ID")
    agent_id: str = Field(description="Agent ID")
    workspace_user_id: str = Field(description="WorkspaceUser ID")
    created_at: datetime.datetime = Field(description="Created time")


class AgentAdminCreate(BaseModel):
    """AgentAdmin create schema."""

    agent_id: str = Field(description="Agent ID")
    workspace_user_id: str = Field(description="WorkspaceUser ID")


class AgentAdminList(BaseModel):
    """AgentAdmin list."""

    items: list[AgentAdmin] = Field(description="AgentAdmin list")


@dataclasses.dataclass(frozen=True)
class DuplicateAdmin:
    """Duplicate AgentAdmin."""

    agent_id: str
    workspace_user_id: str
