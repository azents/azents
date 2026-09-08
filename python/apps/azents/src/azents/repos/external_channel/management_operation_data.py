"""Completed External Channel management operation contracts."""

from typing import NamedTuple

from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.repos.external_channel.management_data import (
    ManagedBlock,
    ManagedConnection,
    ManagedGrant,
)


class ManagedConnectionDisconnectResult(NamedTuple):
    """Completed two-stage disconnect and post-commit provider cleanup."""

    connection: ManagedConnection
    cleanup_plans: tuple[ProviderEffectPlan, ...]


class ExternalChannelManagementNotFound(LookupError):
    """A management resource is unavailable to the caller."""


class ExternalChannelManagementGenerationChanged(RuntimeError):
    """A destructive request observed a newer Multi App generation."""


class ManagedAgentAccess(NamedTuple):
    """Detached Agent-level access grants and blocks."""

    grants: list[ManagedGrant]
    blocks: list[ManagedBlock]
