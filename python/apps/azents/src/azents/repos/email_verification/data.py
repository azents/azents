"""EmailVerification repository data models."""

import dataclasses
import datetime

from pydantic import BaseModel, Field
from typing_extensions import Self


class EmailVerification(BaseModel):
    """EmailVerification domain model."""

    id: str = Field(description="Verification ID (UUID7 hex)")
    email: str = Field(description="Email address")
    code: str = Field(description="Six-digit verification code")
    csrf_token: str = Field(description="CSRF token")
    expires_at: datetime.datetime = Field(description="Expiration time")
    verified_at: datetime.datetime | None = Field(
        None, description="Verification completion time"
    )
    created_at: datetime.datetime = Field(description="Created time")

    @classmethod
    def convert_from(cls, data: "EmailVerification") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


class EmailVerificationCreate(BaseModel):
    """EmailVerification create schema."""

    email: str = Field(description="Email address")
    code: str = Field(description="Six-digit verification code")
    csrf_token: str = Field(description="CSRF token")
    expires_at: datetime.datetime = Field(description="Expiration time")


class EmailVerificationList(BaseModel):
    """EmailVerification list."""

    items: list[EmailVerification] = Field(description="Verification record list")
    total: int = Field(description="Total record count")


@dataclasses.dataclass(frozen=True)
class NotFound:
    """Verification not found."""

    verification_id: str


@dataclasses.dataclass(frozen=True)
class AlreadyVerified:
    """Already verified."""

    verification_id: str


@dataclasses.dataclass(frozen=True)
class Expired:
    """Verification code expired."""

    verification_id: str
