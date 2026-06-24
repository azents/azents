"""Auth API v1 request/response schemas (Public)."""

from pydantic import BaseModel, Field

from azents.services.auth.data import (
    PasswordLoginOutput,
    RefreshTokenOutput,
    SendCodeOutput,
    VerifyCodeOutput,
)
from azents.services.password_reset_token.data import PreviewPasswordResetTokenOutput
from azents.services.signup_token.data import (
    PreviewSignupTokenOutput,
    RedeemSignupTokenOutput,
)

# =============================================================================
# Send Code
# =============================================================================


class SendCodeRequest(BaseModel):
    """Authentication code send request."""

    email: str = Field(description="Email address")


class SendCodeResponse(SendCodeOutput):
    """Authentication code send response."""

    pass


# =============================================================================
# Verify Code
# =============================================================================


class VerifyCodeRequest(BaseModel):
    """Authentication code verification request."""

    email: str = Field(description="Email address")
    code: str = Field(description="6-digit authentication code")
    csrf_token: str = Field(description="CSRF token")


class VerifyCodeResponse(VerifyCodeOutput):
    """Authentication code verification response."""

    pass


# =============================================================================
# Refresh Token
# =============================================================================


class RefreshTokenRequest(BaseModel):
    """Token refresh request."""

    refresh_token: str = Field(description="Refresh token")


class RefreshTokenResponse(RefreshTokenOutput):
    """Token refresh response."""

    pass


# =============================================================================
# Password Login
# =============================================================================


class PasswordLoginRequest(BaseModel):
    """Password login request."""

    email: str = Field(description="Email address")
    password: str = Field(description="Password")


class PasswordLoginResponse(PasswordLoginOutput):
    """Password login response."""

    pass


# =============================================================================
# Login Methods
# =============================================================================


class LoginMethodsRequest(BaseModel):
    """Login method lookup request."""

    email: str = Field(description="Email address")


class LoginMethodsResponse(BaseModel):
    """Login method lookup response."""

    has_password: bool = Field(description="Whether password is set")
    email_available: bool = Field(description="Whether email OTP login is available")


# =============================================================================
# Signup Tokens
# =============================================================================


class PreviewSignupTokenRequest(BaseModel):
    """Signup token preview request."""

    token: str = Field(description="Signup token")


class PreviewSignupTokenResponse(PreviewSignupTokenOutput):
    """Signup token preview response."""

    pass


class RedeemSignupTokenRequest(BaseModel):
    """Signup token redeem request."""

    token: str = Field(description="Signup token")
    email: str = Field(description="Signup email")
    password: str = Field(description="Initial password")


class RedeemSignupTokenResponse(RedeemSignupTokenOutput):
    """Signup token redeem response."""

    pass


class RequestSignupEmailRequest(BaseModel):
    """Signup email request."""

    email: str = Field(description="Signup email")


class RequestSignupEmailResponse(BaseModel):
    """Signup email response."""

    sent: bool = Field(description="Whether email was sent")


class SignupStatusResponse(BaseModel):
    """Signup status response."""

    email_signup_available: bool = Field(
        description="Whether email signup link requests are available"
    )


# =============================================================================
# Password Reset Tokens
# =============================================================================


class PreviewPasswordResetTokenRequest(BaseModel):
    """Password reset token preview request."""

    token: str = Field(description="Password reset token")


class PreviewPasswordResetTokenResponse(PreviewPasswordResetTokenOutput):
    """Password reset token preview response."""

    pass


class RedeemPasswordResetTokenRequest(BaseModel):
    """Password reset token redeem request."""

    token: str = Field(description="Password reset token")
    password: str = Field(description="New password")


class RedeemPasswordResetTokenResponse(BaseModel):
    """Password reset token redeem response."""

    success: bool = Field(description="Success state")
