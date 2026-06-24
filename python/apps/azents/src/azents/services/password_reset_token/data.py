"""Password reset token service data models."""

from __future__ import annotations

import dataclasses
import datetime

from pydantic import BaseModel, Field
from typing_extensions import Self

from azents.repos.password_reset_token.data import PasswordResetToken


class PasswordResetTokenOutput(BaseModel):
    """Password reset token output model."""

    id: str = Field(description="Password reset token ID")
    user_id: str = Field(description="Reset target User ID")
    created_by_user_id: str | None = Field(description="Token creator User ID")
    expires_at: datetime.datetime = Field(description="Expiration time")
    used_at: datetime.datetime | None = Field(description="Used time")
    revoked_at: datetime.datetime | None = Field(description="Revocation time")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def convert_from(
        cls,
        token: PasswordResetToken | PasswordResetTokenOutput,
    ) -> Self:
        """Convert to domain model."""
        return cls.model_validate(token, from_attributes=True)


class PasswordResetTokenWithPlaintextOutput(BaseModel):
    """Create output including plaintext token."""

    token: PasswordResetTokenOutput = Field(description="Password reset token metadata")
    plaintext_token: str = Field(description="Plaintext password reset token")
    reset_url: str = Field(description="Password reset URL")


class PasswordResetTokenListOutput(BaseModel):
    """Password reset token list output."""

    items: list[PasswordResetTokenOutput] = Field(
        description="Password reset token list"
    )
    total: int = Field(description="Total record count")


class CreatePasswordResetTokenInput(BaseModel):
    """Password reset token create input."""

    user_id: str | None = Field(description="Reset target User ID")
    email: str | None = Field(description="Reset target email")
    created_by_user_id: str | None = Field(description="Token creator User ID")
    expires_at: datetime.datetime | None = Field(description="Expiration time")


class PreviewPasswordResetTokenInput(BaseModel):
    """Password reset token preview input."""

    token: str = Field(description="Plaintext password reset token")


class PreviewPasswordResetTokenOutput(BaseModel):
    """Password reset token preview output."""

    valid: bool = Field(description="Usability flag")
    email: str | None = Field(description="Current User email hint")
    expires_at: datetime.datetime | None = Field(description="Expiration time")

    @classmethod
    def convert_from(cls, data: PreviewPasswordResetTokenOutput) -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


class RedeemPasswordResetTokenInput(BaseModel):
    """Password reset token redeem input."""

    token: str = Field(description="Plaintext password reset token")
    password: str = Field(description="New password")
    user_agent: str | None = Field(description="User agent")
    ip_address: str | None = Field(description="Request IP")


@dataclasses.dataclass(frozen=True)
class InvalidPasswordResetToken:
    """Invalid password reset token."""

    pass


@dataclasses.dataclass(frozen=True)
class PasswordResetUserNotFound:
    """Reset target user not found."""

    pass


@dataclasses.dataclass(frozen=True)
class WeakResetPassword:
    """Weak reset password."""

    message: str
