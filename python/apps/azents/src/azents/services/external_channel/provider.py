"""Provider-local validation contracts without transport implementation."""

from typing import Protocol

from azents.core.enums import ExternalChannelProvider
from azents.services.external_channel.data import (
    ExternalChannelConnectionCredentialPayload,
    ExternalChannelConnectionCredentials,
)


class ExternalChannelProviderContract(Protocol):
    """Contract implemented by provider adapters in later delivery phases."""

    @property
    def provider(self) -> ExternalChannelProvider:
        """Return the provider represented by this contract."""
        ...

    def validate_connection_credentials(
        self,
        payload: ExternalChannelConnectionCredentialPayload,
    ) -> ExternalChannelConnectionCredentials:
        """Validate a provider-specific credential payload before persistence."""
        ...


class SlackExternalChannelProviderContract:
    """Slack credential contract with no HTTP, Socket Mode, or ingress behavior."""

    @property
    def provider(self) -> ExternalChannelProvider:
        """Return the provider represented by this contract."""
        return ExternalChannelProvider.SLACK

    def validate_connection_credentials(
        self,
        payload: ExternalChannelConnectionCredentialPayload,
    ) -> ExternalChannelConnectionCredentials:
        """Return validated Slack credentials for a Slack payload."""
        if payload.provider is not self.provider:
            raise ValueError("Slack contract cannot validate another provider.")
        return payload.credentials
