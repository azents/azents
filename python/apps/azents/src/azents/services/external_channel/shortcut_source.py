"""Synchronous route-neutral materialization for provider shortcuts."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConversationScopeKind,
    ExternalChannelInteractionType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConversationPositionCreate,
    ExternalChannelInteraction,
    ExternalChannelResourceCreate,
    ExternalChannelTrigger,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.discord_events import (
    normalize_projected_discord_event,
)
from azents.services.external_channel.selector_state import (
    ExternalChannelSelectorState,
    projection_with_selector_state,
    selector_state_from_interaction,
)
from azents.services.external_channel.slack_events import (
    SlackConnectionRevocation,
    SlackEventExcluded,
    normalize_projected_slack_event,
)


@dataclass(frozen=True)
class ExternalChannelShortcutSourceMaterialization:
    """Shortcut-owned selector state available before modal opening."""

    selector_interaction: ExternalChannelInteraction | None


@dataclass
class ExternalChannelShortcutSourceService:
    """Resolve a shortcut source and attach typed selector state to its interaction."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ]

    async def ensure(
        self,
        *,
        shortcut_source_event: ExternalChannelTrigger,
        interaction_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelShortcutSourceMaterialization:
        """Commit one content-free selector boundary before opening the modal."""
        async with self.session_manager() as session:
            interaction = await self.repository.lock_interaction(
                session,
                interaction_id=interaction_id,
            )
            if (
                interaction is None
                or interaction.connection_id != shortcut_source_event.connection_id
                or interaction.interaction_type
                is not ExternalChannelInteractionType.SHORTCUT
                or interaction.principal_id is None
                or shortcut_source_event.provider_tenant_id is None
            ):
                raise ValueError("Shortcut source is unavailable.")
            connection = await self.repository.lock_connection_for_routing(
                session,
                connection_id=shortcut_source_event.connection_id,
            )
            if (
                connection is None
                or connection.app_mode is not ExternalChannelAppMode.MULTI
            ):
                raise SlackEventExcluded("Shortcut selection is unavailable.")
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
                labels: dict[str, object] = {
                    "provider": "slack",
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
                parent_channel_id = (
                    normalized.parent_channel_id or normalized.channel_id
                )
                provider_resource_key = f"discord:{normalized.tenant_id}:{thread_id}"
                if normalized.thread_id is None:
                    position_scope_kind = (
                        ExternalChannelConversationScopeKind.PARENT_CHANNEL
                    )
                    position_provider_channel_id = normalized.channel_id
                    position_provider_thread_key = None
                else:
                    position_scope_kind = ExternalChannelConversationScopeKind.THREAD
                    position_provider_channel_id = normalized.thread_id
                    position_provider_thread_key = normalized.thread_id
                labels = {
                    "provider": "discord",
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
            position = await self.repository.create_conversation_position_idempotent(
                session,
                ExternalChannelConversationPositionCreate(
                    connection_id=connection.id,
                    scope_kind=position_scope_kind,
                    provider_channel_id=position_provider_channel_id,
                    provider_thread_key=position_provider_thread_key,
                    read_through_position=None,
                ),
            )
            resource = await self.repository.create_resource_idempotent(
                session,
                ExternalChannelResourceCreate(
                    connection_id=connection.id,
                    resource_type=ExternalChannelResourceType.THREAD,
                    provider_resource_key=provider_resource_key,
                    labels=labels,
                    status=ExternalChannelResourceStatus.ACTIVE,
                    latest_activity_at=normalized.provider_created_at,
                    unavailable_at=None,
                    deleted_at=None,
                ),
            )
            resource = await self.repository.lock_resource(
                session,
                resource_id=resource.id,
            )
            if (
                resource is None
                or resource.status is not ExternalChannelResourceStatus.ACTIVE
            ):
                raise SlackEventExcluded("Shortcut source is unavailable.")
            binding = await self.repository.lock_connected_binding_by_resource(
                session,
                resource_id=resource.id,
            )
            if binding is not None:
                await session.commit()
                return ExternalChannelShortcutSourceMaterialization(
                    selector_interaction=None
                )
            selector_state = ExternalChannelSelectorState(
                connection_id=connection.id,
                resource_id=resource.id,
                principal_id=interaction.principal_id,
                conversation_position_id=position.id,
                trigger_provider_message_key=normalized.provider_message_key,
                range_start_position=position.read_through_position,
                trigger_position=normalized.provider_position,
                selected_route_id=None,
            )
            try:
                existing_state = selector_state_from_interaction(interaction)
            except ValueError:
                existing_state = None
            if existing_state is not None:
                expected_state = selector_state.model_copy(
                    update={"selected_route_id": existing_state.selected_route_id}
                )
                if existing_state != expected_state:
                    raise ValueError("Shortcut selector state is incompatible.")
                await session.commit()
                return ExternalChannelShortcutSourceMaterialization(
                    selector_interaction=interaction
                )
            updated = await self.repository.replace_interaction_projection(
                session,
                interaction_id=interaction.id,
                projection=projection_with_selector_state(
                    interaction.projection,
                    selector_state,
                ),
            )
            if updated is None:
                raise RuntimeError("Shortcut interaction disappeared.")
            await session.commit()
            return ExternalChannelShortcutSourceMaterialization(
                selector_interaction=updated
            )
