"""User API v1 request/response schemas (Public)."""

import datetime

from pydantic import BaseModel, Field


class MeResponse(BaseModel):
    """Current user information response."""

    email: str = Field(description="Primary email address")
    created_at: datetime.datetime = Field(description="Signup time")
