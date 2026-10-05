"""Normalize shortcut source outside completed atomic selection operations."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConversationScopeKind,
    ExternalChannelProvider,
)
from azents.core.external_channel_shortcut_source import (
    ExternalChannelShortcutSourceMaterialization,
    ShortcutSelectionUnavailable,
    ShortcutSourceProjection,
)
from azents.repos.external_channel.data import (
    ExternalChannelTrigger,
)
from azents.repos.external_channel.shortcut_source_operations import (
    ExternalChannelShortcutSourceOperations,
)
from azents.services.external_channel.discord_events import (
    normalize_projected_discord_event,
)
from azents.services.external_channel.slack_events import (
    SlackConnectionRevocation,
    SlackEventExcluded,
    normalize_projected_slack_event,
)


@dataclass
class ExternalChannelShortcutSourceService:
    """Resolve a shortcut source and attach typed selector state to its interaction."""

    operations: Annotated[
        ExternalChannelShortcutSourceOperations,
        Depends(ExternalChannelShortcutSourceOperations),
    ]

    async def ensure(
        self,
        *,
        shortcut_source_event: ExternalChannelTrigger,
        interaction_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelShortcutSourceMaterialization:
        """Commit one content-free selector boundary before opening the modal."""
        connection = await self.operations.read_connection(
            shortcut_source_event.connection_id
        )
        if (
            connection is None
            or connection.app_mode is not ExternalChannelAppMode.MULTI
        ):
            raise SlackEventExcluded("Shortcut selection is unavailable.")
        if shortcut_source_event.provider_tenant_id is None:
            raise ValueError("Shortcut source is unavailable.")
        if connection.provider is ExternalChannelProvider.SLACK:
            normalized = normalize_projected_slack_event(
                event_type=shortcut_source_event.event_type,
                tenant_id=shortcut_source_event.provider_tenant_id,
                envelope=shortcut_source_event.envelope,
                connected_bot_user_id=connection.provider_bot_user_id,
            )
            if isinstance(normalized, SlackConnectionRevocation):
                raise ValueError("Shortcut source is unavailable.")
            provider_resource_key = normalized.provider_resource_key
            thread_scope = normalized.root_thread_ts != normalized.message_ts
            position_scope_kind = (
                ExternalChannelConversationScopeKind.THREAD
                if thread_scope
                else ExternalChannelConversationScopeKind.PARENT_CHANNEL
            )
            position_provider_channel_id = normalized.channel_id
            position_provider_thread_key = (
                normalized.root_thread_ts if thread_scope else None
            )
            provider_parent_channel_id = normalized.channel_id
            delivery_thread_key = normalized.root_thread_ts
            trigger_provider_message_id = normalized.message_ts
            labels: dict[str, object] = {
                "provider": "slack",
                "provider_event_type": normalized.source_event_type,
                "tenant_id": normalized.tenant_id,
                "channel_id": normalized.channel_id,
                "thread_ts": normalized.root_thread_ts,
            }
        elif connection.provider is ExternalChannelProvider.DISCORD:
            normalized = normalize_projected_discord_event(
                event_type=shortcut_source_event.event_type,
                tenant_id=shortcut_source_event.provider_tenant_id,
                envelope=shortcut_source_event.envelope,
                connected_bot_user_id=None,
            )
            thread_id = normalized.thread_id or normalized.message_id
            parent_channel_id = normalized.parent_channel_id or normalized.channel_id
            provider_resource_key = f"discord:{normalized.tenant_id}:{thread_id}"
            if normalized.thread_id is None:
                position_scope_kind = (
                    ExternalChannelConversationScopeKind.PARENT_CHANNEL
                )
                position_provider_channel_id = normalized.channel_id
                position_provider_thread_key = None
                delivery_thread_key = normalized.message_id
            else:
                position_scope_kind = ExternalChannelConversationScopeKind.THREAD
                position_provider_channel_id = normalized.thread_id
                position_provider_thread_key = normalized.thread_id
                delivery_thread_key = normalized.thread_id
            provider_parent_channel_id = parent_channel_id
            trigger_provider_message_id = normalized.message_id
            labels = {
                "provider": "discord",
                "provider_event_type": shortcut_source_event.event_type,
                "guild_id": normalized.tenant_id,
                "source_channel_id": normalized.channel_id,
                "channel_id": parent_channel_id,
                "thread_id": thread_id,
                "parent_channel_id": parent_channel_id,
                "root_message_id": thread_id,
                **(
                    {"thread_channel_id": normalized.thread_id}
                    if normalized.thread_id is not None
                    else {}
                ),
                **(
                    {"delivery_channel_id": normalized.thread_id}
                    if normalized.thread_id is not None
                    else {}
                ),
            }
        else:
            raise ValueError("Shortcut provider is unavailable.")
        projection = ShortcutSourceProjection(
            provider_resource_key=provider_resource_key,
            position_scope_kind=position_scope_kind,
            position_provider_channel_id=position_provider_channel_id,
            position_provider_thread_key=position_provider_thread_key,
            provider_parent_channel_id=provider_parent_channel_id,
            delivery_thread_key=delivery_thread_key,
            trigger_provider_message_id=trigger_provider_message_id,
            labels=labels,
            provider_created_at=normalized.provider_created_at,
            provider_message_key=normalized.provider_message_key,
            provider_position=normalized.provider_position,
        )
        try:
            return await self.operations.ensure(
                shortcut_source_event=shortcut_source_event,
                interaction_id=interaction_id,
                now=now,
                connection_snapshot=connection,
                projection=projection,
            )
        except ShortcutSelectionUnavailable as error:
            raise SlackEventExcluded(str(error)) from error
