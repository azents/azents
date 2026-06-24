"""Auth service data models."""

import dataclasses

from pydantic import BaseModel, Field
from typing_extensions import Self

# =============================================================================
# Send Code
# =============================================================================


class SendCodeInput(BaseModel):
    """Verification code send input."""

    email: str = Field(description="Email address")


class SendCodeOutput(BaseModel):
    """Verification code send output."""

    csrf_token: str = Field(description="CSRF token (used on verification)")

    @classmethod
    def convert_from(cls, data: "SendCodeOutput") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


# =============================================================================
# Verify Code
# =============================================================================


class VerifyCodeInput(BaseModel):
    """Verification code verify input."""

    email: str = Field(description="Email address")
    code: str = Field(description="6-digit verification code")
    csrf_token: str = Field(description="CSRF token")
    user_agent: str | None = Field(default=None, description="User agent")
    ip_address: str | None = Field(default=None, description="IP address")


class VerifyCodeOutput(BaseModel):
    """Verification code verify output."""

    access_token: str = Field(description="JWT access token")
    refresh_token: str = Field(description="Refresh token")
    expires_in: int = Field(description="Access token expiration time (seconds)")

    @classmethod
    def convert_from(cls, data: "VerifyCodeOutput") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


# =============================================================================
# Refresh Token
# =============================================================================


class RefreshTokenInput(BaseModel):
    """Token refresh input."""

    refresh_token: str = Field(description="Refresh token")


class RefreshTokenOutput(BaseModel):
    """Token refresh output."""

    access_token: str = Field(description="New JWT access token")
    refresh_token: str = Field(description="New Refresh token")
    expires_in: int = Field(description="Access token expiration time (seconds)")

    @classmethod
    def convert_from(cls, data: "RefreshTokenOutput") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


# =============================================================================
# Logout
# =============================================================================


class LogoutInput(BaseModel):
    """Logout input."""

    session_id: str = Field(description="Session ID")


# =============================================================================
# Errors
# =============================================================================


@dataclasses.dataclass(frozen=True)
class InvalidVerificationCode:
    """Invalid verification code."""

    pass


@dataclasses.dataclass(frozen=True)
class RegistrationRequired:
    """New signup attempt requiring signup token."""

    pass


@dataclasses.dataclass(frozen=True)
class InvalidRefreshToken:
    """Invalid refresh token."""

    pass


@dataclasses.dataclass(frozen=True)
class SessionNotFound:
    """Session not found."""

    session_id: str


# =============================================================================
# Password Login
# =============================================================================


class PasswordLoginInput(BaseModel):
    """Password login input."""

    email: str = Field(description="Email address")
    password: str = Field(description="Password")
    user_agent: str | None = Field(default=None, description="User agent")
    ip_address: str | None = Field(default=None, description="IP address")


class PasswordLoginOutput(BaseModel):
    """Password login output."""

    access_token: str = Field(description="JWT access token")
    refresh_token: str = Field(description="Refresh token")
    expires_in: int = Field(description="Access token expiration time (seconds)")

    @classmethod
    def convert_from(cls, data: "PasswordLoginOutput") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)


@dataclasses.dataclass(frozen=True)
class InvalidCredentials:
    """Invalid credentials."""

    pass


# =============================================================================
# Login Methods
# =============================================================================


class LoginMethodsInput(BaseModel):
    """Login method lookup input."""

    email: str = Field(description="Email address")


class LoginMethodsOutput(BaseModel):
    """Login method lookup output."""

    has_password: bool = Field(description="Password setup flag")
    email_available: bool = Field(description="Email OTP login availability flag")

    @classmethod
    def convert_from(cls, data: "LoginMethodsOutput") -> Self:
        """Convert to domain model."""
        return cls.model_validate(data, from_attributes=True)
