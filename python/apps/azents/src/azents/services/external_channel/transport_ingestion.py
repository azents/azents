"""Authenticated transport projection for synchronous conversation ingestion."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelConversationScopeKind,
    ExternalChannelMessageRevisionKind,
    ExternalChannelProvider,
    ExternalChannelResourceType,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelResource,
    ExternalChannelTrigger,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.conversation import (
    ExternalChannelConversationScope,
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.discord_events import (
    DiscordEventExcluded,
    DiscordEventNormalizationError,
    DiscordMessageContentUnavailable,
    normalize_projected_discord_event,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelConversationIngestionService,
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelTriggerLocator,
)
from azents.services.external_channel.ingestion_deps import (
    get_external_channel_conversation_ingestion_service,
)
from azents.services.external_channel.slack_events import (
    SlackConnectionRevocation,
    SlackEventExcluded,
    SlackEventNormalizationError,
    normalize_projected_slack_event,
)

_TRANSPORT_OPERATION_BUDGET = datetime.timedelta(seconds=2.5)


type SlackTransportIngestionResult = (
    ExternalChannelIngestionOutcome | SlackConnectionRevocation | None
)


@dataclasses.dataclass
class ExternalChannelTransportIngestionService:
    """Project authenticated callbacks into the shared ingestion boundary."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ]
    ingestion_service: Annotated[
        ExternalChannelConversationIngestionService,
        Depends(get_external_channel_conversation_ingestion_service),
    ]

    async def ingest_slack_event(
        self,
        *,
        event: ExternalChannelTrigger,
        connected_bot_user_id: str | None,
        authority: ExternalChannelIngressAuthority,
        deadline: ExternalChannelOperationDeadline,
    ) -> SlackTransportIngestionResult:
        """Ingest one authenticated Slack create trigger or classify it terminally."""
        try:
            normalized = normalize_projected_slack_event(
                event_type=event.event_type,
                tenant_id=_required_tenant(event),
                envelope=event.envelope,
                connected_bot_user_id=connected_bot_user_id,
            )
        except SlackEventExcluded:
            return None
        except SlackEventNormalizationError:
            return _terminal_rejection()
        if isinstance(normalized, SlackConnectionRevocation):
            return normalized
        if normalized.revision_kind is not ExternalChannelMessageRevisionKind.ORIGINAL:
            return None
        thread_scope = normalized.root_thread_ts != normalized.message_ts
        provider_thread_key = normalized.root_thread_ts if thread_scope else None
        request = ExternalChannelIngestionRequest(
            locator=ExternalChannelTriggerLocator(
                connection_id=event.connection_id,
                provider=ExternalChannelProvider.SLACK,
                provider_event_type=normalized.source_event_type,
                provider_tenant_id=normalized.tenant_id,
                provider_channel_id=normalized.channel_id,
                provider_parent_channel_id=None,
                provider_thread_key=provider_thread_key,
                delivery_thread_key=normalized.root_thread_ts,
                provider_resource_key=normalized.provider_resource_key,
                trigger_provider_message_key=normalized.provider_message_key,
                trigger_provider_message_id=normalized.message_ts,
                trigger_position=normalized.provider_position,
                provider_user_id=normalized.provider_user_id,
                invocation=normalized.invocation,
            ),
            scope=ExternalChannelConversationScope(
                connection_id=event.connection_id,
                kind=(
                    ExternalChannelConversationScopeKind.THREAD
                    if thread_scope
                    else ExternalChannelConversationScopeKind.PARENT_CHANNEL
                ),
                provider_channel_id=normalized.channel_id,
                provider_thread_key=provider_thread_key,
            ),
            authority=authority,
            deadline=deadline,
            operation=ExternalChannelIngestionOperation.CURRENT_TRIGGER,
            selected_route_id=None,
            replay_boundary=None,
            initial_title_eligible=False,
        )
        return await self.ingestion_service.ingest(request)

    async def ingest_discord_event(
        self,
        *,
        event: ExternalChannelTrigger,
        authority: ExternalChannelIngressAuthority,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelIngestionOutcome | None:
        """Resolve and ingest one authenticated Discord create trigger."""
        if event.event_type != "discord_message_create":
            return None
        if (
            authority.kind is not ExternalChannelIngressAuthorityKind.LEASE
            or authority.lease_owner is None
            or authority.lease_generation is None
        ):
            return _retryable_failure()
        async with self.session_manager() as session:
            configuration = (
                await self.repository.get_owned_discord_gateway_configuration(
                    session,
                    connection_id=event.connection_id,
                    lease_owner=authority.lease_owner,
                    lease_generation=authority.lease_generation,
                    now=datetime.datetime.now(datetime.UTC),
                )
            )
        if (
            configuration is None
            or configuration.configuration_generation
            != authority.configuration_generation
            or configuration.provider is not ExternalChannelProvider.DISCORD
            or configuration.provider_tenant_id is None
            or configuration.provider_tenant_id != event.provider_tenant_id
        ):
            return _retryable_failure()
        if configuration.ingress_profile is not authority.ingress_profile:
            return _retryable_failure()
        try:
            normalized = normalize_projected_discord_event(
                event_type=event.event_type,
                tenant_id=configuration.provider_tenant_id,
                envelope=event.envelope,
                connected_bot_user_id=configuration.provider_bot_user_id,
            )
        except DiscordEventExcluded:
            return None
        except DiscordMessageContentUnavailable:
            return _retryable_failure()
        except DiscordEventNormalizationError:
            return _terminal_rejection()

        resource = await self._discord_resource(
            connection_id=event.connection_id,
            guild_id=normalized.tenant_id,
            thread_id=normalized.thread_id,
            message_id=normalized.message_id,
        )
        if normalized.thread_id is not None:
            if normalized.parent_channel_id is None:
                return _terminal_rejection()
            provider_resource_key = (
                resource.provider_resource_key
                if resource is not None
                else _discord_resource_key(
                    guild_id=normalized.tenant_id,
                    conversation_id=normalized.thread_id,
                )
            )
            provider_channel_id = normalized.thread_id
            provider_thread_key = normalized.thread_id
            delivery_thread_key = normalized.thread_id
            scope_kind = ExternalChannelConversationScopeKind.THREAD
        else:
            provider_resource_key = (
                resource.provider_resource_key
                if resource is not None
                else _discord_resource_key(
                    guild_id=normalized.tenant_id,
                    conversation_id=normalized.message_id,
                )
            )
            provider_channel_id = normalized.channel_id
            provider_thread_key = None
            delivery_thread_key = (
                _discord_delivery_channel(resource) or normalized.message_id
            )
            scope_kind = ExternalChannelConversationScopeKind.PARENT_CHANNEL

        request = ExternalChannelIngestionRequest(
            locator=ExternalChannelTriggerLocator(
                connection_id=event.connection_id,
                provider=ExternalChannelProvider.DISCORD,
                provider_event_type=event.event_type,
                provider_tenant_id=normalized.tenant_id,
                provider_channel_id=provider_channel_id,
                provider_parent_channel_id=(
                    normalized.parent_channel_id
                    if normalized.thread_id is not None
                    else normalized.channel_id
                ),
                provider_thread_key=provider_thread_key,
                delivery_thread_key=delivery_thread_key,
                provider_resource_key=provider_resource_key,
                trigger_provider_message_key=normalized.provider_message_key,
                trigger_provider_message_id=normalized.message_id,
                trigger_position=normalized.provider_position,
                provider_user_id=normalized.provider_user_id,
                invocation=normalized.invocation,
            ),
            scope=ExternalChannelConversationScope(
                connection_id=event.connection_id,
                kind=scope_kind,
                provider_channel_id=provider_channel_id,
                provider_thread_key=provider_thread_key,
            ),
            authority=authority,
            deadline=deadline,
            operation=ExternalChannelIngestionOperation.CURRENT_TRIGGER,
            selected_route_id=None,
            replay_boundary=None,
            initial_title_eligible=False,
        )
        return await self.ingestion_service.ingest(request)

    async def _discord_resource(
        self,
        *,
        connection_id: str,
        guild_id: str,
        thread_id: str | None,
        message_id: str,
    ) -> ExternalChannelResource | None:
        """Resolve an existing Discord resource by canonical or delivery identity."""
        conversation_id = thread_id or message_id
        async with self.session_manager() as session:
            resource = await self.repository.get_resource_by_provider_key(
                session,
                connection_id=connection_id,
                resource_type=ExternalChannelResourceType.THREAD,
                provider_resource_key=_discord_resource_key(
                    guild_id=guild_id,
                    conversation_id=conversation_id,
                ),
            )
            if resource is not None or thread_id is None:
                return resource
            return await self.repository.get_discord_resource_by_delivery_channel(
                session,
                connection_id=connection_id,
                guild_id=guild_id,
                delivery_channel_id=thread_id,
            )


def transport_outcome_acknowledgeable(
    outcome: ExternalChannelIngestionOutcome,
) -> bool:
    """Return whether a transport may acknowledge the completed closed outcome."""
    return outcome.kind is not ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE


def external_channel_transport_deadline(
    received_at: datetime.datetime,
) -> ExternalChannelOperationDeadline:
    """Reserve provider response time with one shared absolute ingress deadline."""
    return ExternalChannelOperationDeadline(
        expires_at=received_at + _TRANSPORT_OPERATION_BUDGET
    )


def _required_tenant(event: ExternalChannelTrigger) -> str:
    tenant_id = event.provider_tenant_id
    if tenant_id is None:
        raise SlackEventNormalizationError("Slack tenant identity is missing.")
    return tenant_id


def _discord_resource_key(*, guild_id: str, conversation_id: str) -> str:
    return f"discord:{guild_id}:{conversation_id}"


def _discord_delivery_channel(resource: ExternalChannelResource | None) -> str | None:
    if resource is None or resource.labels is None:
        return None
    value = resource.labels.get("delivery_channel_id")
    return value if isinstance(value, str) and value else None


def _retryable_failure() -> ExternalChannelIngestionOutcome:
    return ExternalChannelIngestionOutcome(
        kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
        reason=ExternalChannelIngestionReason.HISTORY_UNAVAILABLE,
        mailbox_item_id=None,
        control_plans=(),
        connection_id=None,
    )


def _terminal_rejection() -> ExternalChannelIngestionOutcome:
    return ExternalChannelIngestionOutcome(
        kind=ExternalChannelIngestionOutcomeKind.TERMINAL_REJECTION,
        reason=ExternalChannelIngestionReason.CONVERSATION_UNAVAILABLE,
        mailbox_item_id=None,
        control_plans=(),
        connection_id=None,
    )
