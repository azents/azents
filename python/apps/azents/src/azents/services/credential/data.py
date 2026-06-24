"""Credential service data models."""

from enum import StrEnum

from pydantic import BaseModel, Field
from typing_extensions import Self


class CredentialType(StrEnum):
    """Credential type."""

    EMAIL = "email"
    PASSWORD = "password"


class CredentialUnavailableReason(StrEnum):
    """Reason Credential cannot be used."""

    NOT_CONFIGURED = "not_configured"
    SMTP_NOT_CONFIGURED = "smtp_not_configured"
    LAST_VALID_CREDENTIAL = "last_valid_credential"
    RECOVERY_REQUIRED = "recovery_required"


class CredentialSummary(BaseModel):
    """Credential internal summary."""

    type: CredentialType = Field(description="Credential type")
    configured: bool = Field(description="Whether user configured credential")
    valid: bool = Field(description="Whether usable in current environment")
    can_login: bool = Field(description="Whether usable for login")
    can_elevate: bool = Field(description="Whether usable for elevation")
    can_remove: bool = Field(description="Whether removable")
    unavailable_reason: CredentialUnavailableReason | None = Field(
        default=None,
        description="Reason Credential cannot be used or removed",
    )

    @classmethod
    def convert_from(cls, data: "CredentialSummary") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


class CredentialProjection(BaseModel):
    """credential projection for authenticated API."""

    type: CredentialType = Field(description="Credential type")
    configured: bool = Field(description="Whether user configured credential")
    valid: bool = Field(description="Whether usable in current environment")
    enabled: bool = Field(description="Whether enabled for current API purpose")
    can_login: bool = Field(description="Whether usable for login")
    can_elevate: bool = Field(description="Whether usable for elevation")
    can_remove: bool = Field(description="Whether removable")
    unavailable_reason: CredentialUnavailableReason | None = Field(
        default=None,
        description="Reason Credential cannot be used or removed",
    )


class LoginCredentialProjection(BaseModel):
    """Public login methods projection."""

    has_password: bool = Field(description="Password setup flag")
    email_available: bool = Field(description="Email OTP login availability flag")


class CredentialRemoveCheck(BaseModel):
    """Credential removability."""

    allowed: bool = Field(description="Removal allowed flag")
    reason: CredentialUnavailableReason | None = Field(
        default=None,
        description="Reason removal is disallowed",
    )
