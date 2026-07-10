"""xAI OAuth service data models."""

import dataclasses
import datetime

from pydantic import BaseModel, Field

from azents.core.xai_oauth import (
    XaiOAuthConnectionMethod,
    XaiOAuthSessionStatus,
)
from azents.repos.llm_provider_integration.data import LLMProviderIntegration


class XaiOAuthExchangeOutput(BaseModel):
    """OAuth exchange completion result."""

    integration: LLMProviderIntegration = Field(
        description="Stored provider integration"
    )


class XaiOAuthDeviceStartOutput(BaseModel):
    """Device OAuth start result."""

    session_id: str = Field(description="OAuth session ID")
    user_code: str = Field(description="Device user code")
    verification_uri: str = Field(description="Device verification URI")
    interval_seconds: int = Field(description="Provider polling interval")
    expires_at: datetime.datetime = Field(description="Session expiry")


class XaiOAuthDeviceStatusOutput(BaseModel):
    """Device OAuth status result."""

    session_id: str = Field(description="OAuth session ID")
    status: XaiOAuthSessionStatus = Field(description="Session status")
    interval_seconds: int = Field(description="Current provider polling interval")
    integration: LLMProviderIntegration | None = Field(
        default=None, description="Integration stored when connection completes"
    )


@dataclasses.dataclass(frozen=True)
class SessionNotFound:
    """OAuth session not found."""

    session_id: str


@dataclasses.dataclass(frozen=True)
class InvalidSession:
    """OAuth session does not match request."""

    reason: str


@dataclasses.dataclass(frozen=True)
class ProviderPending:
    """Provider authentication is not completed yet."""

    session_id: str


@dataclasses.dataclass(frozen=True)
class ProviderSlowDown:
    """Provider requested a longer device polling interval."""

    session_id: str


@dataclasses.dataclass(frozen=True)
class ProviderRejected:
    """Provider rejected request."""

    reason: str


@dataclasses.dataclass(frozen=True)
class ProviderEntitlementDenied:
    """Provider accepted OAuth but denied API entitlement."""

    reason: str


@dataclasses.dataclass(frozen=True)
class ProviderUnavailable:
    """Provider call failed temporarily."""

    reason: str


@dataclasses.dataclass(frozen=True)
class SessionTransitionFailed:
    """Session status transition failed."""

    session_id: str


XaiOAuthError = (
    SessionNotFound
    | InvalidSession
    | ProviderPending
    | ProviderSlowDown
    | ProviderRejected
    | ProviderEntitlementDenied
    | ProviderUnavailable
    | SessionTransitionFailed
)


class DeviceUserCode(BaseModel):
    """xAI device user-code response."""

    device_code: str
    user_code: str
    verification_uri: str
    interval_seconds: int
    expires_in_seconds: int


class TokenSet(BaseModel):
    """xAI OAuth token response."""

    access_token: str
    refresh_token: str
    id_token: str | None = None
    expires_at: datetime.datetime
    account_id: str | None = None
    email: str | None = None
    connection_method: XaiOAuthConnectionMethod
