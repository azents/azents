"""UserEmail Admin API v1 request/response schemas."""

from pydantic import BaseModel, Field

from azents.services.user_email.data import UserEmailOutput as UserEmail


class UserEmailResponse(UserEmail):
    """UserEmail response schema."""

    pass


class UserEmailListResponse(BaseModel):
    """UserEmail list response schema."""

    items: list[UserEmailResponse] = Field(description="UserEmail list")
    total: int = Field(description="Total record count")


class UserEmailCreateRequest(BaseModel):
    """UserEmail creation request schema."""

    email: str = Field(description="Email address")
