"""Pure Workspace inputs and errors shared with API callers."""

import dataclasses

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class WorkspaceCreate(BaseModel):
    """Workspace create schema."""

    name: str = Field(description="Workspace name")
    handle: str = Field(description="Workspace unique handle")


class WorkspaceUpdate(TypedDict, total=False):
    """Workspace update schema (partial update)."""

    name: str
    handle: str


class CreateWithOwnerInput(BaseModel):
    """Workspace + Owner create input model."""

    user_id: str = Field(description="User ID")
    workspace_name: str = Field(description="Workspace name")
    workspace_handle: str = Field(description="Workspace handle")
    owner_name: str = Field(description="Owner display name")


@dataclasses.dataclass(frozen=True)
class HandleConflict:
    """Duplicate handle error."""

    handle: str


@dataclasses.dataclass(frozen=True)
class NotFound:
    """Workspace not found."""

    handle: str
