"""Workspace API v1 response schemas (Public)."""

from pydantic import BaseModel, Field

from azents.services.workspace.data import (
    BootstrapFirstOwnerInput,
    BootstrapFirstOwnerOutput,
    BootstrapStatusOutput,
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
    locale: str = Field(default="ko-KR", description="Locale (BCP 47)")


class CreateWorkspaceResponse(CreateWithOwnerOutput):
    """Workspace creation response."""

    pass


class BootstrapStatusResponse(BootstrapStatusOutput):
    """First owner bootstrap status response."""

    pass


class BootstrapFirstOwnerRequest(BootstrapFirstOwnerInput):
    """First owner bootstrap request."""

    pass


class BootstrapFirstOwnerResponse(BootstrapFirstOwnerOutput):
    """First owner bootstrap response."""

    pass
