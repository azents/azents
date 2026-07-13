"""System User role service data models."""

from pydantic import BaseModel, Field

from azents.core.enums import SystemUserRole
from azents.repos.system_user_role.data import SystemUserRoleAssignment


class SystemUserRoleAssignmentOutput(SystemUserRoleAssignment):
    """System role assignment output."""

    @classmethod
    def convert_from(
        cls,
        assignment: SystemUserRoleAssignment,
    ) -> "SystemUserRoleAssignmentOutput":
        """Convert repository data to service output."""
        return cls.model_validate(assignment.model_dump())


class SystemUserRoleAssignmentListOutput(BaseModel):
    """System role assignment list output."""

    items: list[SystemUserRoleAssignmentOutput] = Field(description="Role assignments")
    total: int = Field(description="Total assignment count")


class CurrentSystemRolesOutput(BaseModel):
    """Current User system role projection."""

    roles: list[SystemUserRole] = Field(description="Current User system roles")
