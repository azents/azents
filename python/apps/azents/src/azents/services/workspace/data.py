"""Workspace service data models."""

from pydantic import BaseModel, Field
from typing_extensions import Self

from azents.core.workspace import WorkspaceCreate, WorkspaceUpdate
from azents.repos.workspace.data import Workspace


class WorkspaceOutput(Workspace):
    """Workspace output model."""

    pass


class WorkspaceCreateInput(WorkspaceCreate):
    """Workspace create input model."""

    pass


class WorkspaceUpdateInput(WorkspaceUpdate):
    """Workspace update input model."""

    pass


class WorkspaceListOutput(BaseModel):
    """Workspace list output model."""

    items: list[WorkspaceOutput] = Field(description="Workspace list")


class CreateWithOwnerOutput(BaseModel):
    """Workspace + Owner create output model."""

    workspace_handle: str = Field(description="Created Workspace handle")

    @classmethod
    def convert_from(cls, data: "CreateWithOwnerOutput") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)
