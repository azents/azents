"""Provider-local validation contracts without transport implementation."""

from dataclasses import dataclass
from typing import Protocol, assert_never

from azents.core.enums import ExternalChannelProvider
from azents.services.external_channel.data import (
    DiscordConnectionCredentials,
    ExternalChannelConnectionCredentialPayload,
    ExternalChannelConnectionCredentials,
    SlackConnectionCredentials,
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
        if not isinstance(payload.credentials, SlackConnectionCredentials):
            raise ValueError("Slack contract requires Slack credentials.")
        return payload.credentials


class DiscordExternalChannelProviderContract:
    """Discord credential contract without Gateway or HTTP implementation."""

    @property
    def provider(self) -> ExternalChannelProvider:
        """Return the provider represented by this contract."""
        return ExternalChannelProvider.DISCORD

    def validate_connection_credentials(
        self,
        payload: ExternalChannelConnectionCredentialPayload,
    ) -> ExternalChannelConnectionCredentials:
        """Return validated Discord credentials for a Discord payload."""
        if payload.provider is not self.provider:
            raise ValueError("Discord contract cannot validate another provider.")
        if not isinstance(payload.credentials, DiscordConnectionCredentials):
            raise ValueError("Discord contract requires Discord credentials.")
        return payload.credentials


@dataclass(frozen=True)
class ExternalChannelProviderRegistry:
    """Explicit provider contract registry for canonical External Channel services."""

    slack: ExternalChannelProviderContract
    discord: ExternalChannelProviderContract

    def contract_for(
        self,
        provider: ExternalChannelProvider,
    ) -> ExternalChannelProviderContract:
        """Return the explicitly registered contract for one provider."""
        match provider:
            case ExternalChannelProvider.SLACK:
                return self.slack
            case ExternalChannelProvider.DISCORD:
                return self.discord
            case _ as unreachable:
                assert_never(unreachable)
