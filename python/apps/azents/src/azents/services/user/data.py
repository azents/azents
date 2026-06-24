"""User service data models."""

from pydantic import BaseModel, Field

from azents.repos.user.data import User


class UserOutput(User):
    """User output model."""

    pass


class UserListOutput(BaseModel):
    """User list output model."""

    items: list[UserOutput] = Field(description="User list")
    total: int = Field(description="Total record count")


__all__: list[str] = []
