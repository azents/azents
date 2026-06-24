"""Security API v1 request/response schemas (Public)."""

from pydantic import BaseModel, Field

from azents.services.security.data import (
    ElevateOutput,
    GetAuthMethodsOutput,
    SendElevationCodeOutput,
)

# =============================================================================
# Auth Methods
# =============================================================================


class GetAuthMethodsResponse(GetAuthMethodsOutput):
    """Authentication method lookup response."""

    pass


# =============================================================================
# Elevation
# =============================================================================


class SendElevationCodeResponse(SendElevationCodeOutput):
    """Elevation OTP send response."""

    pass


class ElevateWithEmailRequest(BaseModel):
    """Email OTP elevation request."""

    code: str = Field(description="6-digit authentication code")
    csrf_token: str = Field(description="CSRF token")


class ElevateWithPasswordRequest(BaseModel):
    """Password elevation request."""

    password: str = Field(description="Password")


class ElevateResponse(ElevateOutput):
    """Elevation response."""

    pass


# =============================================================================
# Password Management
# =============================================================================


class SetPasswordRequest(BaseModel):
    """Password set request."""

    password: str = Field(description="New password")
