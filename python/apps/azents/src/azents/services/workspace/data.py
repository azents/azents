"""Workspace service data models."""

import dataclasses

from pydantic import BaseModel, Field
from typing_extensions import Self

from azents.repos.workspace.data import (
    Workspace,
    WorkspaceCreate,
    WorkspaceUpdate,
)


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


class CreateWithOwnerInput(BaseModel):
    """Workspace + Owner create input model."""

    user_id: str = Field(description="User ID")
    workspace_name: str = Field(description="Workspace name")
    workspace_handle: str = Field(description="Workspace handle")
    owner_name: str = Field(description="Owner display name")
    locale: str = Field(default="ko-KR", description="Locale (BCP 47)")


class BootstrapFirstOwnerInput(BaseModel):
    """First owner bootstrap input model."""

    email: str = Field(description="Owner email")
    password: str = Field(description="Owner initial password")
    owner_name: str = Field(description="Owner display name")
    workspace_name: str = Field(description="Workspace name")
    workspace_handle: str = Field(description="Workspace handle")
    locale: str = Field(default="ko-KR", description="Locale (BCP 47)")


class BootstrapFirstOwnerOutput(BaseModel):
    """First owner bootstrap output model."""

    workspace_handle: str = Field(description="Created Workspace handle")
    user_id: str = Field(description="Created Owner User ID")


class BootstrapStatusOutput(BaseModel):
    """First owner bootstrap status output model."""

    available: bool = Field(description="bootstrap availability flag")


@dataclasses.dataclass(frozen=True)
class BootstrapNotAvailable:
    """First owner bootstrap unavailable."""

    pass


@dataclasses.dataclass(frozen=True)
class WeakBootstrapPassword:
    """Weak bootstrap password."""

    message: str


class CreateWithOwnerOutput(BaseModel):
    """Workspace + Owner create output model."""

    workspace_handle: str = Field(description="Created Workspace handle")

    @classmethod
    def convert_from(cls, data: "CreateWithOwnerOutput") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)
