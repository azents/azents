"""UserEmail repository data models."""

import dataclasses
import datetime

from pydantic import BaseModel, Field
from typing_extensions import Self


class UserEmail(BaseModel):
    """UserEmail domain model."""

    id: str = Field(description="UserEmail ID (UUID7 hex)")
    user_id: str = Field(description="Owning User ID")
    email: str = Field(description="Email address")
    verified_at: datetime.datetime | None = Field(
        None, description="Verification completion time"
    )
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def convert_from(cls, data: "UserEmail") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


class UserEmailCreate(BaseModel):
    """UserEmail create schema."""

    user_id: str = Field(description="Owning User ID")
    email: str = Field(description="Email address")


class UserEmailList(BaseModel):
    """UserEmail list."""

    items: list[UserEmail] = Field(description="UserEmail list")
    total: int = Field(description="Total record count")


@dataclasses.dataclass(frozen=True)
class NotFound:
    """UserEmail not found."""

    email_id: str


@dataclasses.dataclass(frozen=True)
class DuplicateEmail:
    """Duplicate email."""

    email: str
