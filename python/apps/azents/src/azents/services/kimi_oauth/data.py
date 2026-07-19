"""Kimi OAuth service data models."""

import dataclasses
import datetime

from pydantic import BaseModel, Field

from azents.core.kimi_oauth import KimiOAuthConnectionMethod, KimiOAuthSessionStatus
from azents.repos.llm_provider_integration.data import LLMProviderIntegration


class KimiOAuthExchangeOutput(BaseModel):
    """OAuth exchange completion result."""

    integration: LLMProviderIntegration = Field(
        description="Stored provider integration"
    )


class KimiOAuthDeviceStartOutput(BaseModel):
    """Device OAuth start result."""

    session_id: str = Field(description="OAuth session ID")
    user_code: str = Field(description="Device user code")
    verification_uri: str = Field(description="Device verification URI")
    interval_seconds: int = Field(description="Provider polling interval")
    expires_at: datetime.datetime = Field(description="Session expiry")


class KimiOAuthDeviceStatusOutput(BaseModel):
    """Device OAuth status result."""

    session_id: str = Field(description="OAuth session ID")
    status: KimiOAuthSessionStatus = Field(description="Session status")
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
    """Provider permanently rejected the request."""

    reason: str


@dataclasses.dataclass(frozen=True)
class ProviderUnavailable:
    """Provider call failed temporarily."""

    reason: str


@dataclasses.dataclass(frozen=True)
class SessionTransitionFailed:
    """Session status transition failed."""

    session_id: str


KimiOAuthError = (
    SessionNotFound
    | InvalidSession
    | ProviderPending
    | ProviderSlowDown
    | ProviderRejected
    | ProviderUnavailable
    | SessionTransitionFailed
)


class DeviceUserCode(BaseModel):
    """Kimi device user-code response."""

    device_code: str
    user_code: str
    verification_uri: str
    interval_seconds: int
    expires_in_seconds: int


class TokenSet(BaseModel):
    """Kimi OAuth token response."""

    access_token: str
    refresh_token: str
    expires_at: datetime.datetime
    connection_method: KimiOAuthConnectionMethod
