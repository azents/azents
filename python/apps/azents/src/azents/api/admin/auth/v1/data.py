"""Auth Admin API v1 request/response schemas."""

from pydantic import BaseModel, Field

from azents.core.enums import SignupTokenDeliveryMethod
from azents.services.email_verification.data import (
    EmailVerificationOutput as EmailVerification,
)
from azents.services.password_reset_token.data import (
    PasswordResetTokenOutput,
)
from azents.services.signup_token.data import (
    SignupTokenOutput,
)


class EmailVerificationResponse(EmailVerification):
    """EmailVerification response schema, including code."""

    pass


class EmailVerificationListResponse(BaseModel):
    """EmailVerification list response schema."""

    items: list[EmailVerificationResponse] = Field(
        description="Authentication record list"
    )
    total: int = Field(description="Total record count")


class CreateSignupTokenRequest(BaseModel):
    """Signup token creation request."""

    email: str = Field(description="Email to pin to the token")
    delivery_method: SignupTokenDeliveryMethod = Field(
        description="Token delivery method"
    )


class SignupTokenResponse(SignupTokenOutput):
    """Signup token metadata response."""

    pass


class CreateSignupTokenResponse(BaseModel):
    """Signup token creation response."""

    token: SignupTokenResponse = Field(description="Signup token metadata")
    plaintext_token: str = Field(description="Plaintext signup token")


class SignupTokenListResponse(BaseModel):
    """Signup token list response."""

    items: list[SignupTokenResponse] = Field(description="Signup token list")
    total: int = Field(description="Total record count")


class CreatePasswordResetTokenRequest(BaseModel):
    """Password reset token creation request."""

    user_id: str | None = Field(default=None, description="Reset target User ID")
    email: str | None = Field(default=None, description="Reset target email")


class PasswordResetTokenResponse(PasswordResetTokenOutput):
    """Password reset token metadata response."""

    pass


class CreatePasswordResetTokenResponse(BaseModel):
    """Password reset token creation response."""

    token: PasswordResetTokenResponse = Field(
        description="Password reset token metadata"
    )
    plaintext_token: str = Field(description="Plaintext password reset token")
    reset_url: str = Field(description="Password reset URL")


class PasswordResetTokenListResponse(BaseModel):
    """Password reset token list response."""

    items: list[PasswordResetTokenResponse] = Field(
        description="Password reset token list"
    )
    total: int = Field(description="Total record count")
