"""System Admin API v1 schemas."""

from pydantic import BaseModel, Field

from azents.core.enums import SystemUserRole
from azents.services.system_user_role.data import SystemUserRoleAssignmentOutput


class SystemAdminMeResponse(BaseModel):
    """Current system administrator response."""

    user_id: str = Field(description="Current User ID")
    roles: list[SystemUserRole] = Field(description="Current system roles")


class SystemUserRoleAssignmentResponse(SystemUserRoleAssignmentOutput):
    """System role assignment response."""

    pass


class SystemUserRoleAssignmentListResponse(BaseModel):
    """System role assignment list response."""

    items: list[SystemUserRoleAssignmentResponse] = Field(
        description="System role assignments"
    )
    total: int = Field(description="Total assignment count")
