"""Detached shortcut projection and content-free materialization contracts."""

import datetime
from dataclasses import dataclass

from azents.core.enums import ExternalChannelConversationScopeKind
from azents.repos.external_channel.data import ExternalChannelInteraction


@dataclass(frozen=True)
class ExternalChannelShortcutSourceMaterialization:
    """Committed shortcut-owned selector available before provider modal work."""

    selector_interaction: ExternalChannelInteraction | None


@dataclass(frozen=True)
class ShortcutSourceProjection:
    """Normalized source identity passed into the atomic repository admission."""

    provider_resource_key: str
    position_scope_kind: ExternalChannelConversationScopeKind
    position_provider_channel_id: str
    position_provider_thread_key: str | None
    provider_parent_channel_id: str
    delivery_thread_key: str
    trigger_provider_message_id: str
    labels: dict[str, object]
    provider_created_at: datetime.datetime | None
    provider_message_key: str
    provider_position: str


class ShortcutSelectionUnavailable(ValueError):
    """The source is no longer an available Multi App selection."""
