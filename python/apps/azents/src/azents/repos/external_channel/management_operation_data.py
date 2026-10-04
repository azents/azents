"""Completed External Channel management operation contracts."""

from typing import NamedTuple

from azents.core.external_channel_management import (
    ManagedBlock,
    ManagedConnection,
    ManagedGrant,
)
from azents.core.external_channel_provider_effect import ProviderEffectPlan


class ManagedConnectionDisconnectResult(NamedTuple):
    """Completed two-stage disconnect and post-commit provider cleanup."""

    connection: ManagedConnection
    cleanup_plans: tuple[ProviderEffectPlan, ...]


class ManagedAgentAccess(NamedTuple):
    """Detached Agent-level access grants and blocks."""

    grants: list[ManagedGrant]
    blocks: list[ManagedBlock]
