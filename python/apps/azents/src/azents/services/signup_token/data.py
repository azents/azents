"""Signup token service data models."""

from __future__ import annotations

import dataclasses
import datetime

from pydantic import BaseModel, Field
from typing_extensions import Self

from azents.core.enums import SignupTokenDeliveryMethod
from azents.repos.signup_token.data import SignupToken
from azents.services.auth.data import VerifyCodeOutput


class SignupTokenOutput(BaseModel):
    """Signup token output model."""

    id: str = Field(description="Signup token ID")
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
    def convert_from(cls, token: SignupToken | SignupTokenOutput) -> Self:
        """Convert to domain model."""
        return cls.model_validate(token, from_attributes=True)


class SignupTokenWithPlaintextOutput(BaseModel):
    """Create output including plaintext token."""

    token: SignupTokenOutput = Field(description="Signup token metadata")
    plaintext_token: str = Field(description="Plaintext signup token")


class SignupTokenListOutput(BaseModel):
    """Signup token list output."""

    items: list[SignupTokenOutput] = Field(description="Signup token list")
    total: int = Field(description="Total record count")


class CreateSignupTokenInput(BaseModel):
    """Signup token create input."""

    email: str = Field(description="Email to fix to token")
    created_by_user_id: str | None = Field(description="Token creator User ID")
    delivery_method: SignupTokenDeliveryMethod = Field(
        description="Token delivery method"
    )
    expires_at: datetime.datetime | None = Field(description="Expiration time")
    max_uses: int | None = Field(description="Maximum use count")


class PreviewSignupTokenInput(BaseModel):
    """Signup token preview input."""

    token: str = Field(description="Plaintext signup token")


class PreviewSignupTokenOutput(BaseModel):
    """Signup token preview output."""

    valid: bool = Field(description="Usability flag")
    email: str | None = Field(description="Email fixed to token hint")
    expires_at: datetime.datetime | None = Field(description="Expiration time")

    @classmethod
    def convert_from(cls, data: PreviewSignupTokenOutput) -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


class RedeemSignupTokenInput(BaseModel):
    """Signup token redeem input."""

    token: str = Field(description="Plaintext signup token")
    email: str = Field(description="Signup email")
    password: str = Field(description="Initial password")
    user_agent: str | None = Field(description="User agent")
    ip_address: str | None = Field(description="Request IP")


class RedeemSignupTokenOutput(VerifyCodeOutput):
    """Signup token redeem output."""

    pass


@dataclasses.dataclass(frozen=True)
class InvalidSignupToken:
    """Invalid signup token."""

    pass


@dataclasses.dataclass(frozen=True)
class SignupTokenEmailMismatch:
    """Signup token email mismatch."""

    pass


@dataclasses.dataclass(frozen=True)
class SignupTokenEmailAlreadyRegistered:
    """Email already signed up."""

    email: str


@dataclasses.dataclass(frozen=True)
class WeakSignupPassword:
    """Weak signup password."""

    message: str


@dataclasses.dataclass(frozen=True)
class SignupEmailDeliveryUnavailable:
    """Signup email delivery unavailable."""

    pass
