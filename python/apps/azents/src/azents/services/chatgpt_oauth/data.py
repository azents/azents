"""ChatGPT OAuth service data models."""

import dataclasses
import datetime

from pydantic import BaseModel, Field

from azents.core.chatgpt_oauth import (
    ChatGPTOAuthConnectionMethod,
    ChatGPTOAuthSessionStatus,
)
from azents.repos.llm_provider_integration.data import LLMProviderIntegration


class ChatGPTOAuthExchangeOutput(BaseModel):
    """OAuth exchange completion result."""

    integration: LLMProviderIntegration = Field(
        description="Stored provider integration"
    )


class ChatGPTOAuthDeviceStartOutput(BaseModel):
    """Device OAuth start result."""

    session_id: str = Field(description="OAuth session ID")
    user_code: str = Field(description="Device user code")
    verification_uri: str = Field(description="Device verification URI")
    interval_seconds: int = Field(description="Provider polling interval")
    expires_at: datetime.datetime = Field(description="Session expiry")


class ChatGPTOAuthDeviceStatusOutput(BaseModel):
    """Device OAuth status result."""

    session_id: str = Field(description="OAuth session ID")
    status: ChatGPTOAuthSessionStatus = Field(description="Session status")
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
class ProviderRejected:
    """Provider rejected request."""

    reason: str


@dataclasses.dataclass(frozen=True)
class ProviderUnavailable:
    """Provider call failed temporarily."""

    reason: str


@dataclasses.dataclass(frozen=True)
class SessionTransitionFailed:
    """Session status transition failed."""

    session_id: str


ChatGPTOAuthError = (
    SessionNotFound
    | InvalidSession
    | ProviderPending
    | ProviderRejected
    | ProviderUnavailable
    | SessionTransitionFailed
)


class DeviceUserCode(BaseModel):
    """ChatGPT device user-code response."""

    device_auth_id: str
    user_code: str
    interval_seconds: int


class DeviceAuthorizationCode(BaseModel):
    """ChatGPT device polling completion response."""

    authorization_code: str
    code_verifier: str


class TokenSet(BaseModel):
    """ChatGPT OAuth token response."""

    access_token: str
    refresh_token: str
    id_token: str | None = None
    expires_at: datetime.datetime
    account_id: str | None = None
    email: str | None = None
    plan_type: str | None = None
    connection_method: ChatGPTOAuthConnectionMethod
