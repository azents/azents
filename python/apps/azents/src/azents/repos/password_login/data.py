"""PasswordLogin repository data models."""

import dataclasses
import datetime

from pydantic import BaseModel, Field


class PasswordLogin(BaseModel):
    """PasswordLogin domain model."""

    id: str = Field(description="PasswordLogin ID (UUID7 hex)")
    user_id: str = Field(description="Owning User ID")
    password_hash: str = Field(description="Hashed password")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")


class PasswordLoginCreate(BaseModel):
    """PasswordLogin create schema."""

    user_id: str = Field(description="Owning User ID")
    password_hash: str = Field(description="Hashed password")


@dataclasses.dataclass(frozen=True)
class NotFound:
    """PasswordLogin not found."""

    user_id: str


@dataclasses.dataclass(frozen=True)
class AlreadyExists:
    """Password already set."""

    user_id: str
