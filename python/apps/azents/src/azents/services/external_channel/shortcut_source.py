"""Synchronous route-neutral materialization for admitted Slack shortcuts."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConversationAdmissionOrigin,
    ExternalChannelConversationAdmissionStatus,
    ExternalChannelHydrationStatus,
    ExternalChannelInteractionType,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConversationAdmission,
    ExternalChannelConversationAdmissionCreate,
    ExternalChannelEventCreate,
    ExternalChannelMessageCreate,
    ExternalChannelMessageRevisionCreate,
    ExternalChannelPrincipalCreate,
    ExternalChannelResourceCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.slack_events import (
    SlackConnectionRevocation,
    SlackEventExcluded,
    normalize_projected_slack_event,
)

_SHORTCUT_ADMISSION_AGE = datetime.timedelta(days=7)


@dataclass(frozen=True)
class ExternalChannelShortcutSourceMaterialization:
    """Canonical source/admission durable result available before modal opening."""

    admission: ExternalChannelConversationAdmission | None


@dataclass
class ExternalChannelShortcutSourceService:
    """Materialize a shortcut source without route selection or provider I/O."""

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
        shortcut_source_event: ExternalChannelEventCreate,
        interaction_id: str,
        now: datetime.datetime,
    ) -> ExternalChannelShortcutSourceMaterialization:
        """Commit one canonical route-neutral source before claiming modal work."""
        async with self.session_manager() as session:
            event = await self.repository.get_event_by_provider_identity(
                session,
                connection_id=shortcut_source_event.connection_id,
                provider_event_id=shortcut_source_event.provider_event_id,
            )
            interaction = await self.repository.lock_interaction(
                session,
                interaction_id=interaction_id,
            )
            if (
                event is None
                or interaction is None
                or interaction.connection_id != shortcut_source_event.connection_id
                or interaction.interaction_type
                is not ExternalChannelInteractionType.SHORTCUT
                or interaction.principal_id is None
                or event.provider_tenant_id is None
            ):
                raise ValueError("Slack shortcut source is unavailable.")
            connection = await self.repository.lock_connection_for_routing(
                session,
                connection_id=event.connection_id,
            )
            if (
                connection is None
                or connection.app_mode is not ExternalChannelAppMode.MULTI
            ):
                raise SlackEventExcluded("Slack shortcut selection is unavailable.")
            normalized = normalize_projected_slack_event(
                event_type=event.event_type,
                tenant_id=event.provider_tenant_id,
                envelope=event.envelope,
            )
            if isinstance(normalized, SlackConnectionRevocation):
                raise ValueError("Slack shortcut source is unavailable.")
            resource = await self.repository.create_resource_idempotent(
                session,
                ExternalChannelResourceCreate(
                    connection_id=connection.id,
                    resource_type=ExternalChannelResourceType.THREAD,
                    provider_resource_key=normalized.provider_resource_key,
                    labels={
                        "provider": "slack",
                        "tenant_id": normalized.tenant_id,
                        "channel_id": normalized.channel_id,
                        "thread_ts": normalized.root_thread_ts,
                    },
                    status=ExternalChannelResourceStatus.ACTIVE,
                    hydration_status=ExternalChannelHydrationStatus.PENDING,
                    hydration_cursor=None,
                    hydration_high_watermark_position=None,
                    reconciliation_boundary_received_at=None,
                    reconciliation_boundary_event_id=None,
                    hydration_error_kind=None,
                    hydration_error_summary=None,
                    hydration_started_at=None,
                    hydration_completed_at=None,
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
                raise SlackEventExcluded("Slack shortcut source is unavailable.")
            binding = await self.repository.lock_active_binding_by_resource(
                session,
                resource_id=resource.id,
            )
            admission = (
                None
                if binding is not None
                else await self.repository.lock_open_conversation_admission(
                    session,
                    resource_id=resource.id,
                )
            )
            source_principal_id = None
            if normalized.provider_user_id is not None:
                source_principal = await self.repository.create_principal_idempotent(
                    session,
                    ExternalChannelPrincipalCreate(
                        provider=connection.provider,
                        provider_tenant_id=normalized.tenant_id,
                        provider_user_id=normalized.provider_user_id,
                        author_type=normalized.author_type,
                        display_name=None,
                        avatar_url=None,
                        profile=None,
                    ),
                )
                source_principal_id = source_principal.id
            message = await self.repository.create_message_idempotent(
                session,
                ExternalChannelMessageCreate(
                    resource_id=resource.id,
                    provider_message_key=normalized.provider_message_key,
                    provider_position=normalized.provider_position,
                    principal_id=source_principal_id,
                    author_type=normalized.author_type,
                    current_revision_id=None,
                    original_url=None,
                    lifecycle=normalized.lifecycle,
                    pending_size=normalized.normalized_size,
                    provider_created_at=normalized.provider_created_at,
                    provider_updated_at=normalized.provider_updated_at,
                ),
            )
            revision = await self.repository.create_message_revision_idempotent(
                session,
                ExternalChannelMessageRevisionCreate(
                    message_id=message.id,
                    revision_key=normalized.revision_key,
                    revision_kind=normalized.revision_kind,
                    normalized_body=normalized.normalized_body,
                    attachment_metadata=normalized.attachment_metadata,
                    reference_mappings=None,
                    source_event_id=event.id,
                    provider_occurred_at=(
                        normalized.provider_updated_at or normalized.provider_created_at
                    ),
                ),
            )
            message = await self.repository.apply_message_revision(
                session,
                message_id=message.id,
                revision_id=revision.id,
                principal_id=source_principal_id,
                author_type=normalized.author_type,
                lifecycle=normalized.lifecycle,
                pending_size=normalized.normalized_size,
                provider_created_at=normalized.provider_created_at,
                provider_updated_at=normalized.provider_updated_at,
                original_url=None,
            )
            if message is None:
                raise RuntimeError("Slack shortcut source disappeared.")
            if binding is None and admission is None:
                create = ExternalChannelConversationAdmissionCreate(
                    connection_id=connection.id,
                    resource_id=resource.id,
                    source_message_id=message.id,
                    initiating_principal_id=interaction.principal_id,
                    origin=ExternalChannelConversationAdmissionOrigin.SHORTCUT,
                    status=ExternalChannelConversationAdmissionStatus.PENDING_SELECTION,
                    selected_route_id=None,
                    interaction_id=interaction.id,
                    expires_at=now + _SHORTCUT_ADMISSION_AGE,
                )
                admission = (
                    await self.repository.create_conversation_admission_idempotent(
                        session,
                        create,
                    )
                )
            await session.commit()
            return ExternalChannelShortcutSourceMaterialization(admission=admission)
