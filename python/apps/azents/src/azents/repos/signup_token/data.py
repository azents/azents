"""Signup token repository data models."""

import dataclasses
import datetime
from typing import Self

from pydantic import BaseModel, Field

from azents.core.enums import SignupTokenDeliveryMethod


class SignupToken(BaseModel):
    """Signup token domain model."""

    id: str = Field(description="Signup token ID")
    token_hash: str = Field(description="Signup token hash")
    email: str = Field(description="Email fixed to token")
    created_by_user_id: str | None = Field(description="Token creator User ID")
    delivery_method: SignupTokenDeliveryMethod = Field(
        description="Token delivery method"
    )
    expires_at: datetime.datetime = Field(description="Expiration time")
    max_uses: int = Field(description="Maximum use count")
    used_count: int = Field(description="Use count")
    revoked_at: datetime.datetime | None = Field(description="Revocation time")
    created_at: datetime.datetime = Field(description="Created time")
    updated_at: datetime.datetime = Field(description="Updated time")

    @classmethod
    def convert_from(cls, token: "SignupToken") -> Self:
        """Convert to domain model."""
        return cls.model_validate(token, from_attributes=True)


class SignupTokenCreate(BaseModel):
    """Signup token create data."""

    token_hash: str = Field(description="Signup token hash")
    email: str = Field(description="Email fixed to token")
    created_by_user_id: str | None = Field(description="Token creator User ID")
    delivery_method: SignupTokenDeliveryMethod = Field(
        description="Token delivery method"
    )
    expires_at: datetime.datetime = Field(description="Expiration time")
    max_uses: int = Field(description="Maximum use count")


class SignupTokenList(BaseModel):
    """Signup token list."""

    items: list[SignupToken] = Field(description="Signup token list")
    total: int = Field(description="Total record count")


class SignupTokenRedemption(BaseModel):
    """Signup token usage record."""

    id: str = Field(description="Redemption ID")
    signup_token_id: str = Field(description="Signup token ID")
    user_id: str = Field(description="User ID")
    email: str = Field(description="Used email")
    ip_address: str | None = Field(description="Request IP")
    user_agent: str | None = Field(description="User agent")
    redeemed_at: datetime.datetime = Field(description="Used time")


class SignupTokenRedemptionCreate(BaseModel):
    """Signup token usage record create data."""

    signup_token_id: str = Field(description="Signup token ID")
    user_id: str = Field(description="User ID")
    email: str = Field(description="Used email")
    ip_address: str | None = Field(description="Request IP")
    user_agent: str | None = Field(description="User agent")
    redeemed_at: datetime.datetime = Field(description="Used time")


@dataclasses.dataclass(frozen=True)
class SignupTokenNotFound:
    """Signup token not found."""

    pass


@dataclasses.dataclass(frozen=True)
class SignupTokenUnavailable:
    """Signup token cannot be used."""

    pass
