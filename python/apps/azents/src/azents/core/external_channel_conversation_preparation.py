"""Detached provider conversation preparation and sanitized failure contracts."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class ExternalChannelConversationProvisioningError(Exception):
    """Sanitized provider conversation preparation failure."""

    category: str
    retryable: bool


@dataclasses.dataclass(frozen=True)
class ExternalChannelConversationPreparation:
    """Content-free provider result awaiting one atomic database transition."""

    target_resource_id: str
    delivery_channel_id: str | None
    initial_thread_title: str | None
