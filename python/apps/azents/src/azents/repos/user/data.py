"""User repository data models."""

import dataclasses
import datetime

from pydantic import BaseModel, Field
from typing_extensions import Self, TypedDict


class User(BaseModel):
    """User domain model."""

    id: str = Field(description="User ID (UUID7 hex)")
    primary_email_id: str = Field(description="Primary email ID")
    primary_email: str = Field(description="Primary email address")
    locale: str = Field(description="Account locale (BCP 47)")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def convert_from(cls, data: "User") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


class UserCreate(BaseModel):
    """User create schema.

    Receives email and creates User + UserEmail together.
    """

    email: str = Field(description="Primary email address")


class UserUpdate(TypedDict, total=False):
    """User update schema (partial update)."""

    locale: str


class UserList(BaseModel):
    """User list."""

    items: list[User] = Field(description="User list")
    total: int = Field(description="Total record count")


@dataclasses.dataclass(frozen=True)
class NotFound:
    """User not found."""

    user_id: str
