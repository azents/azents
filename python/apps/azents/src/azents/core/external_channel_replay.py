"""Detached external-channel replay evidence and shared replay failure."""

from dataclasses import dataclass

from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelConversationPosition,
    ExternalChannelParticipationSetting,
    ExternalChannelPrincipal,
    ExternalChannelResource,
    ExternalChannelSetupClaim,
)


class ExternalChannelIngestionReplayUnavailable(ValueError):
    """A retained selector or access boundary cannot be replayed safely."""


@dataclass(frozen=True)
class ExternalChannelReplaySource:
    """Content-free durable owners needed to reconstruct one replay."""

    configuration: ExternalChannelConnectionConfiguration
    position: ExternalChannelConversationPosition
    resource: ExternalChannelResource
    target_resource_id: str
    principal: ExternalChannelPrincipal
    route_id: str
    trigger_provider_message_key: str
    range_start_position: str | None
    trigger_position: str


@dataclass(frozen=True)
class ExternalChannelSetupReplaySource:
    """Validated detached setup owners; request projection occurs after completion."""

    configuration: ExternalChannelConnectionConfiguration
    claim: ExternalChannelSetupClaim
    setting: ExternalChannelParticipationSetting
    source_resource: ExternalChannelResource
    principal: ExternalChannelPrincipal
