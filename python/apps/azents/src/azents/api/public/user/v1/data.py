"""User API v1 request/response schemas (Public)."""

import datetime

from pydantic import BaseModel, Field

from azents.core.enums import SystemUserRole


class MeResponse(BaseModel):
    """Current user information response."""

    email: str = Field(description="Primary email address")
    created_at: datetime.datetime = Field(description="Signup time")


class MySystemRolesResponse(BaseModel):
    """Current User system role response."""

    roles: list[SystemUserRole] = Field(description="Current User system roles")
