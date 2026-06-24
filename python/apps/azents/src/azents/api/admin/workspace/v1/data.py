"""Workspace API v1 request/response schemas."""

from typing import Sequence

from pydantic import BaseModel, Field

from azents.services.workspace.data import (
    BootstrapFirstOwnerInput,
    BootstrapFirstOwnerOutput,
    BootstrapStatusOutput,
    WorkspaceCreateInput,
    WorkspaceOutput,
    WorkspaceUpdateInput,
)


class WorkspaceResponse(WorkspaceOutput):
    """Workspace response schema."""

    pass


class WorkspaceCreateRequest(WorkspaceCreateInput):
    """Workspace creation request schema."""

    pass


class WorkspaceUpdateRequest(WorkspaceUpdateInput):
    """Workspace update request schema."""

    pass


class WorkspaceListResponse(BaseModel):
    """Workspace list response schema."""

    items: Sequence[WorkspaceResponse] = Field(description="Workspace list")


class BootstrapStatusResponse(BootstrapStatusOutput):
    """First owner bootstrap status response."""

    pass


class BootstrapFirstOwnerRequest(BootstrapFirstOwnerInput):
    """First owner bootstrap request."""

    pass


class BootstrapFirstOwnerResponse(BootstrapFirstOwnerOutput):
    """First owner bootstrap response."""

    pass
