"""WorkspaceUser API v1 request/response schemas."""

from typing import Sequence

from pydantic import BaseModel, Field

from azents.services.workspace_user.data import (
    WorkspaceUserCreateInput,
    WorkspaceUserOutput,
    WorkspaceUserUpdateInput,
)


class WorkspaceUserResponse(WorkspaceUserOutput):
    """WorkspaceUser response schema."""

    pass


class WorkspaceUserCreateRequest(WorkspaceUserCreateInput):
    """WorkspaceUser creation request schema."""

    pass


class WorkspaceUserUpdateRequest(WorkspaceUserUpdateInput):
    """WorkspaceUser update request schema."""

    pass


class WorkspaceUserListResponse(BaseModel):
    """WorkspaceUser list response schema."""

    items: Sequence[WorkspaceUserResponse] = Field(description="WorkspaceUser list")


class TransferOwnershipRequest(BaseModel):
    """Owner transfer request schema."""

    new_owner_workspace_user_id: str = Field(description="New Owner WorkspaceUser ID")
