"""Workspace API v1 request/response schemas."""

from typing import Sequence

from pydantic import BaseModel, Field

from azents.services.workspace.data import (
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
