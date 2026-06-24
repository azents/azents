"""WorkspaceUser API v1 request/response schemas (Public)."""

from pydantic import BaseModel, Field

from azents.core.enums import WorkspaceUserRole
from azents.services.workspace_user.data import WorkspaceUserOutput


class WorkspaceUserResponse(WorkspaceUserOutput):
    """WorkspaceUser response schema."""

    pass


class WorkspaceUserListResponse(BaseModel):
    """WorkspaceUser list response schema."""

    items: list[WorkspaceUserResponse] = Field(description="WorkspaceUser list")


class UpdateWorkspaceUserRoleRequest(BaseModel):
    """WorkspaceUser role change request schema."""

    role: WorkspaceUserRole = Field(
        description="Role to change to (owner, manager, member)"
    )


class UpdateMyProfileRequest(BaseModel):
    """Own workspace profile update request schema."""

    name: str | None = Field(default=None, description="Display name to change to")
    locale: str | None = Field(default=None, description="Locale to change to (BCP 47)")


class CurrentMemberResponse(BaseModel):
    """Current user workspace member info response schema."""

    workspace_user_id: str = Field(description="Current user WorkspaceUser ID")
    role: WorkspaceUserRole = Field(description="Current user role")
