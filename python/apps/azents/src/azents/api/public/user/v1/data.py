"""User API v1 request/response schemas (Public)."""

import datetime

from pydantic import BaseModel, Field

from azents.core.enums import SystemUserRole
from azents.core.locale import SupportedLocale


class MeResponse(BaseModel):
    """Current user information response."""

    email: str = Field(description="Primary email address")
    locale: SupportedLocale = Field(description="Account locale (BCP 47)")
    created_at: datetime.datetime = Field(description="Signup time")


class UpdateMyUserRequest(BaseModel):
    """Current user update request."""

    locale: SupportedLocale = Field(description="Account locale (BCP 47)")


class MySystemRolesResponse(BaseModel):
    """Current User system role response."""

    roles: list[SystemUserRole] = Field(description="Current User system roles")
