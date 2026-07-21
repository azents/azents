"""User API v1 request/response schemas (Public)."""

import datetime
from typing import Literal

from pydantic import BaseModel, Field

from azents.core.enums import SystemUserRole

SupportedLocale = Literal["en-US", "ko-KR", "ja-JP", "fr-FR"]


class MeResponse(BaseModel):
    """Current user information response."""

    email: str = Field(description="Primary email address")
    locale: str = Field(description="Account locale (BCP 47)")
    created_at: datetime.datetime = Field(description="Signup time")


class UpdateMyUserRequest(BaseModel):
    """Current user update request."""

    locale: SupportedLocale = Field(description="Account locale (BCP 47)")


class MySystemRolesResponse(BaseModel):
    """Current User system role response."""

    roles: list[SystemUserRole] = Field(description="Current User system roles")
