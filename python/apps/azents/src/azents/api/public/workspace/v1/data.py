"""Workspace API v1 response schemas (Public)."""

from pydantic import BaseModel, Field

from azents.services.workspace.data import (
    CreateWithOwnerOutput,
    WorkspaceOutput,
)


class WorkspaceResponse(WorkspaceOutput):
    """Workspace response schema."""

    pass


class WorkspaceListResponse(BaseModel):
    """Workspace list response schema."""

    items: list[WorkspaceResponse] = Field(description="Workspace list")


class CreateWorkspaceRequest(BaseModel):
    """Workspace creation request."""

    workspace_name: str = Field(description="Workspace name")
    workspace_handle: str = Field(description="Workspace handle")
    owner_name: str = Field(description="Owner display name")


class CreateWorkspaceResponse(CreateWithOwnerOutput):
    """Workspace creation response."""

    pass
