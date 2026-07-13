"""System bootstrap service data models."""

import dataclasses

from pydantic import BaseModel, Field


class SystemBootstrapInput(BaseModel):
    """First system administrator bootstrap input."""

    setup_token: str = Field(description="One-time operator setup token")
    email: str = Field(description="Initial administrator email")
    password: str = Field(description="Initial administrator password")
    user_agent: str | None = Field(description="Browser user agent")
    ip_address: str | None = Field(description="Client IP address")


class SystemBootstrapOutput(BaseModel):
    """Created administrator session tokens."""

    access_token: str = Field(description="JWT access token")
    refresh_token: str = Field(description="Refresh token")
    expires_in: int = Field(description="Access token expiration time in seconds")


class SystemBootstrapStatusOutput(BaseModel):
    """Public bootstrap availability projection."""

    available: bool = Field(description="Whether initial bootstrap is available")


@dataclasses.dataclass(frozen=True)
class BootstrapUnavailable:
    """Initial bootstrap is not currently available."""


@dataclasses.dataclass(frozen=True)
class InvalidSetupToken:
    """The submitted setup token is invalid."""


@dataclasses.dataclass(frozen=True)
class WeakBootstrapPassword:
    """The submitted password does not meet the password policy."""

    message: str
