"""UserEmail service data models."""

from pydantic import BaseModel, Field

from azents.repos.user_email.data import (
    UserEmail,
)


class UserEmailOutput(UserEmail):
    """UserEmail output model."""

    pass


class UserEmailListOutput(BaseModel):
    """UserEmail list output model."""

    items: list[UserEmailOutput] = Field(description="UserEmail list")
    total: int = Field(description="Total record count")


__all__: list[str] = []
