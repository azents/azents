"""System User role repository data models."""

import dataclasses
import datetime

from pydantic import BaseModel, Field

from azents.core.enums import SystemUserRole


class SystemUserRoleAssignment(BaseModel):
    """Instance-wide role assignment."""

    user_id: str = Field(description="Assigned User ID")
    role: SystemUserRole = Field(description="System role")
    granted_by_user_id: str | None = Field(description="Granting User ID")
    granted_at: datetime.datetime = Field(description="Grant time")


class SystemUserRoleAssignmentCreate(BaseModel):
    """Instance-wide role assignment create data."""

    user_id: str = Field(description="Assigned User ID")
    role: SystemUserRole = Field(description="System role")
    granted_by_user_id: str | None = Field(description="Granting User ID")


class SystemUserRoleAssignmentList(BaseModel):
    """Instance-wide role assignment list."""

    items: list[SystemUserRoleAssignment] = Field(description="Role assignments")
    total: int = Field(description="Total assignment count")


@dataclasses.dataclass(frozen=True)
class SystemUserNotFound:
    """Target User does not exist."""

    user_id: str


@dataclasses.dataclass(frozen=True)
class SystemRoleAssignmentNotFound:
    """Target role assignment does not exist."""

    user_id: str
    role: SystemUserRole


@dataclasses.dataclass(frozen=True)
class LastSystemAdmin:
    """Operation would remove the final system administrator."""

    user_id: str
