"""WorkspaceUser repository data models."""

import dataclasses
import datetime

from pydantic import BaseModel, Field
from typing_extensions import Self, TypedDict

from azents.core.enums import WorkspaceUserRole


class WorkspaceUser(BaseModel):
    """WorkspaceUser domain model."""

    id: str = Field(description="WorkspaceUser ID (UUID7 hex)")
    workspace_id: str = Field(description="Owning Workspace ID")
    user_id: str = Field(description="User ID")
    name: str = Field(description="Workspace display name")
    role: WorkspaceUserRole = Field(description="Role (owner, manager, member)")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def convert_from(cls, data: "WorkspaceUser") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


class WorkspaceUserCreate(BaseModel):
    """WorkspaceUser create schema for repository, using workspace_id."""

    workspace_id: str = Field(description="Owning Workspace ID")
    user_id: str = Field(description="User ID")
    name: str = Field(description="Workspace display name")
    role: WorkspaceUserRole = Field(description="Role (owner, manager, member)")


class WorkspaceUserUpdate(TypedDict, total=False):
    """WorkspaceUser update schema (partial update)."""

    name: str


class WorkspaceUserList(BaseModel):
    """WorkspaceUser list."""

    items: list[WorkspaceUser] = Field(description="WorkspaceUser list")


@dataclasses.dataclass(frozen=True)
class NotFound:
    """WorkspaceUser not found."""

    workspace_user_id: str


@dataclasses.dataclass(frozen=True)
class WorkspaceNotFound:
    """Workspace not found."""

    workspace_id: str
