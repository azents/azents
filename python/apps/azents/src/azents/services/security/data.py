"""Security service data models."""

import dataclasses

from pydantic import BaseModel, Field
from typing_extensions import Self

# =============================================================================
# Auth Methods
# =============================================================================


class AuthMethod(BaseModel):
    """Auth method."""

    type: str = Field(description="Auth method type (email, password)")
    enabled: bool = Field(description="Enabled flag")
    configured: bool = Field(description="Whether user configured credential")
    valid: bool = Field(description="Whether usable in current environment")
    can_login: bool = Field(description="Whether usable for login")
    can_elevate: bool = Field(description="Whether usable for Elevation")
    can_remove: bool = Field(description="Whether removable")
    unavailable_reason: str | None = Field(
        default=None,
        description="Reason it cannot be used or removed",
    )


class GetAuthMethodsInput(BaseModel):
    """Auth method lookup input."""

    user_id: str = Field(description="User ID")


class GetAuthMethodsOutput(BaseModel):
    """Auth method lookup output."""

    methods: list[AuthMethod] = Field(description="Auth method list")

    @classmethod
    def convert_from(cls, data: "GetAuthMethodsOutput") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


# =============================================================================
# Elevation
# =============================================================================


class SendElevationCodeInput(BaseModel):
    """Elevation OTP send input."""

    user_id: str = Field(description="User ID")


class SendElevationCodeOutput(BaseModel):
    """Elevation OTP send output."""

    csrf_token: str = Field(description="CSRF token")

    @classmethod
    def convert_from(cls, data: "SendElevationCodeOutput") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


class ElevateWithEmailInput(BaseModel):
    """Elevation input with email OTP."""

    user_id: str = Field(description="User ID")
    session_id: str = Field(description="Session ID")
    code: str = Field(description="6-digit verification code")
    csrf_token: str = Field(description="CSRF token")


class ElevateWithPasswordInput(BaseModel):
    """Elevation input with password."""

    user_id: str = Field(description="User ID")
    session_id: str = Field(description="Session ID")
    password: str = Field(description="Password")


class ElevateOutput(BaseModel):
    """Elevation output."""

    access_token: str = Field(description="Elevated JWT access token")
    expires_in: int = Field(description="Access token expiration time (seconds)")

    @classmethod
    def convert_from(cls, data: "ElevateOutput") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


# =============================================================================
# Password Management
# =============================================================================


class SetPasswordInput(BaseModel):
    """Password setup input."""

    user_id: str = Field(description="User ID")
    password: str = Field(description="New password")


class RemovePasswordInput(BaseModel):
    """Password deletion input."""

    user_id: str = Field(description="User ID")


# =============================================================================
# Errors
# =============================================================================


@dataclasses.dataclass(frozen=True)
class InvalidElevationCode:
    """Invalid elevation code."""

    pass


@dataclasses.dataclass(frozen=True)
class InvalidPassword:
    """Invalid password."""

    pass


@dataclasses.dataclass(frozen=True)
class PasswordNotSet:
    """Password is not set."""

    pass


@dataclasses.dataclass(frozen=True)
class WeakPassword:
    """Password strength insufficient."""

    message: str


@dataclasses.dataclass(frozen=True)
class UserNotFound:
    """User not found."""

    user_id: str


@dataclasses.dataclass(frozen=True)
class LastCredentialRemovalDenied:
    """Last valid credential deletion rejected."""

    pass
