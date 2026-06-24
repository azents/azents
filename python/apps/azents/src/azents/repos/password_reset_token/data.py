"""Password reset token repository data models."""

import dataclasses
import datetime
from typing import Self

from pydantic import BaseModel, Field


class PasswordResetToken(BaseModel):
    """Password reset token domain model."""

    id: str = Field(description="Password reset token ID")
    token_hash: str = Field(description="Password reset token hash")
    user_id: str = Field(description="Reset target User ID")
    created_by_user_id: str | None = Field(description="Token creator User ID")
    expires_at: datetime.datetime = Field(description="Expiration time")
    used_at: datetime.datetime | None = Field(description="Used time")
    revoked_at: datetime.datetime | None = Field(description="Revocation time")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def convert_from(cls, token: "PasswordResetToken") -> Self:
        """Convert to domain model."""
        return cls.model_validate(token, from_attributes=True)


class PasswordResetTokenCreate(BaseModel):
    """Password reset token create data."""

    token_hash: str = Field(description="Password reset token hash")
    user_id: str = Field(description="Reset target User ID")
    created_by_user_id: str | None = Field(description="Token creator User ID")
    expires_at: datetime.datetime = Field(description="Expiration time")


class PasswordResetTokenList(BaseModel):
    """Password reset token list."""

    items: list[PasswordResetToken] = Field(description="Password reset token list")
    total: int = Field(description="Total record count")


class PasswordResetTokenRedemption(BaseModel):
    """Password reset token redemption record."""

    id: str = Field(description="Redemption ID")
    password_reset_token_id: str = Field(description="Password reset token ID")
    user_id: str = Field(description="User ID")
    ip_address: str | None = Field(description="Request IP")
    user_agent: str | None = Field(description="User agent")
    redeemed_at: datetime.datetime = Field(description="Used time")


class PasswordResetTokenRedemptionCreate(BaseModel):
    """Password reset token redemption create data."""

    password_reset_token_id: str = Field(description="Password reset token ID")
    user_id: str = Field(description="User ID")
    ip_address: str | None = Field(description="Request IP")
    user_agent: str | None = Field(description="User agent")
    redeemed_at: datetime.datetime = Field(description="Used time")


@dataclasses.dataclass(frozen=True)
class PasswordResetTokenUnavailable:
    """Password reset token cannot be used."""

    pass
