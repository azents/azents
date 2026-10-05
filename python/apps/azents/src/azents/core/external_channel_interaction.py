"""Detached selector/processing ownership evidence for external interactions."""

from dataclasses import dataclass

from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelInteraction,
    ExternalChannelResource,
)


@dataclass(frozen=True)
class InteractionSelectorMetadata:
    """Verified opaque modal scope retained only in Slack private metadata."""

    connection_id: str
    resource_id: str
    selector_interaction_id: str
    interaction_id: str
    principal_id: str
    offset: int


@dataclass(frozen=True)
class ProcessingInteractionScope:
    """Authenticated processing interaction and its active connection."""

    interaction: ExternalChannelInteraction
    configuration: ExternalChannelConnectionConfiguration


@dataclass(frozen=True)
class SelectorOwners:
    """Validated connection and resource that own one selector."""

    configuration: ExternalChannelConnectionConfiguration
    resource: ExternalChannelResource


@dataclass(frozen=True)
class SelectorScope:
    """Validated scope required to open one selector."""

    interaction: ExternalChannelInteraction
    configuration: ExternalChannelConnectionConfiguration
    resource: ExternalChannelResource
    selector: ExternalChannelInteraction


@dataclass(frozen=True)
class SelectorSubmissionScope:
    """Validated scope required to process one selector submission."""

    interaction: ExternalChannelInteraction
    configuration: ExternalChannelConnectionConfiguration
    resource: ExternalChannelResource
    selector: ExternalChannelInteraction
    metadata: InteractionSelectorMetadata
