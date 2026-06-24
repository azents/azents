"""User Admin API v1 request/response schemas."""

from pydantic import BaseModel, Field

from azents.services.user.data import UserOutput as User


class UserResponse(User):
    """User response schema."""

    pass


class UserListResponse(BaseModel):
    """User list response schema."""

    items: list[UserResponse] = Field(description="User list")
    total: int = Field(description="Total record count")
