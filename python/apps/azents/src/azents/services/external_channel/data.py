"""Provider-generic External Channel connection contracts.

These models are internal service contracts. They deliberately separate
provider identity and redacted operational state from encrypted credentials.
"""

import datetime
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from azents.core.enums import (
    ExternalChannelConnectionStatus,
    ExternalChannelProvider,
    ExternalChannelTransport,
)


def _require_non_blank(value: str) -> str:
    """Reject blank identifiers and credentials without modifying their value."""
    if not value.strip():
        raise ValueError("Value must not be blank.")
    return value


@dataclass(frozen=True)
class ExternalChannelProviderIdentity:
    """Validated non-secret identity for one installed provider application."""

    provider: ExternalChannelProvider
    app_id: str
    tenant_id: str
    bot_user_id: str | None

    def __post_init__(self) -> None:
        _require_non_blank(self.app_id)
        _require_non_blank(self.tenant_id)
        if self.bot_user_id is not None:
            _require_non_blank(self.bot_user_id)


class SlackConnectionCredentials(BaseModel):
    """Validated secret payload for one Slack App connection."""

    model_config = ConfigDict(frozen=True)

    provider: Literal[ExternalChannelProvider.SLACK] = Field(
        default=ExternalChannelProvider.SLACK
    )
    bot_token: str = Field(description="Slack bot user OAuth token")
    signing_secret: str = Field(description="Slack request signing secret")
    app_token: str | None = Field(description="Slack Socket Mode app-level token")

    @field_validator("bot_token", "signing_secret", "app_token")
    @classmethod
    def _validate_secret(cls, value: str | None) -> str | None:
        """Reject blank configured secrets."""
        if value is not None:
            _require_non_blank(value)
        return value


type ExternalChannelConnectionCredentials = SlackConnectionCredentials


class ExternalChannelConnectionCredentialPayload(BaseModel):
    """Validated connection credential payload before encrypted persistence."""

    model_config = ConfigDict(frozen=True)

    provider: ExternalChannelProvider = Field(description="Provider credential owner")
    transport: ExternalChannelTransport = Field(
        description="Connection inbound transport"
    )
    credentials: ExternalChannelConnectionCredentials = Field(
        description="Provider-specific credential payload"
    )

    @model_validator(mode="after")
    def _validate_provider_and_transport(
        self,
    ) -> "ExternalChannelConnectionCredentialPayload":
        """Validate the credential shape required by the provider and transport."""
        if self.provider is not self.credentials.provider:
            raise ValueError("Credential provider does not match connection provider.")
        if (
            self.transport is ExternalChannelTransport.SOCKET
            and self.credentials.app_token is None
        ):
            raise ValueError("Slack Socket Mode requires an app token.")
        return self


class ExternalChannelCredentialSnapshot(BaseModel):
    """Redacted indication of which encrypted credential fields are present."""

    model_config = ConfigDict(frozen=True)

    provider: ExternalChannelProvider = Field(description="Credential provider")
    configured_fields: tuple[str, ...] = Field(
        description="Configured secret field names without secret values"
    )


class ExternalChannelCapabilitySnapshot(BaseModel):
    """Redacted provider capabilities resolved for one connection."""

    model_config = ConfigDict(frozen=True)

    provider: ExternalChannelProvider = Field(description="Provider")
    transport: ExternalChannelTransport = Field(description="Configured transport")
    inbound_events: bool = Field(description="Whether inbound events are supported")
    thread_history: bool = Field(description="Whether thread history can be collected")
    post_messages: bool = Field(description="Whether messages can be posted")
    update_messages: bool = Field(description="Whether owned messages can be updated")
    delete_messages: bool = Field(description="Whether owned messages can be deleted")
    download_files: bool = Field(description="Whether provider files can be downloaded")
    upload_files: bool = Field(description="Whether Runtime files can be uploaded")


class ExternalChannelConnectionStatusSnapshot(BaseModel):
    """Redacted current connection status for service and future API projection."""

    model_config = ConfigDict(frozen=True)

    status: ExternalChannelConnectionStatus = Field(
        description="Current operational status"
    )
    code: str | None = Field(description="Stable machine-readable status code")
    message: str | None = Field(description="Operator-safe status explanation")
    action_hint: str | None = Field(description="Operator-safe remediation hint")
    checked_at: datetime.datetime | None = Field(
        description="Most recent status observation time"
    )
    identity: ExternalChannelProviderIdentity | None = Field(
        description="Validated non-secret provider identity"
    )
    credentials: ExternalChannelCredentialSnapshot = Field(
        description="Redacted credential configuration state"
    )
    capabilities: ExternalChannelCapabilitySnapshot | None = Field(
        description="Resolved provider capabilities when available"
    )
