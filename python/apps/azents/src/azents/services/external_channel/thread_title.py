"""One-shot best-effort Discord thread title projection."""

import dataclasses
import logging
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStatus,
    EventKind,
    ExternalChannelConnectionStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelRouteCatalogStatus,
)
from azents.core.external_channel_title import (
    DISCORD_INITIAL_THREAD_TITLE_LABEL,
    normalize_discord_thread_title,
)
from azents.engine.events.types import Event, ExternalChannelMessagePayload
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.channel_action import (
    get_discord_delivery_client,
)
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import DiscordConnectionCredentials
from azents.services.external_channel.discord_delivery import DiscordDeliveryClient

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class _DiscordThreadTitleAuthority:
    """Current exact authority for one title attempt."""

    bot_token: str
    guild_id: str
    channel_id: str
    provisional_title: str


@dataclasses.dataclass
class ExternalChannelThreadTitleService:
    """Attempt one eligible Discord thread rename without durable attempt state."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    external_channel_repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    discord_client: Annotated[
        DiscordDeliveryClient,
        Depends(get_discord_delivery_client),
    ]

    async def project_generated_title(
        self,
        *,
        session_id: str,
        event: Event,
        title: str,
    ) -> None:
        """Perform one GET and at most one adjacent PATCH for an eligible thread."""
        normalized_title = normalize_discord_thread_title(title)
        payload = event.payload
        if (
            normalized_title is None
            or event.kind is not EventKind.EXTERNAL_CHANNEL_MESSAGE
            or not isinstance(payload, ExternalChannelMessagePayload)
            or payload.provider is not ExternalChannelProvider.DISCORD
            or payload.resource_type is not ExternalChannelResourceType.THREAD
            or payload.authorization != "authorized_invocation"
            or payload.author_type is not ExternalChannelPrincipalAuthorType.HUMAN
        ):
            return
        authority = await self._load_authority(
            session_id=session_id,
            payload=payload,
        )
        if authority is None:
            return
        read = await self.discord_client.read_thread_title(
            bot_token=authority.bot_token,
            guild_id=authority.guild_id,
            channel_id=authority.channel_id,
        )
        if read.status != "present" or read.name is None:
            return
        if read.name == normalized_title:
            return
        if read.name != authority.provisional_title:
            return
        result = await self.discord_client.update_thread_title(
            bot_token=authority.bot_token,
            guild_id=authority.guild_id,
            channel_id=authority.channel_id,
            name=normalized_title,
        )
        if result.status != "delivered":
            logger.info(
                "Discord automatic thread title attempt did not complete",
                extra={
                    "session_id": session_id,
                    "event_id": event.id,
                    "external_channel_provider": ExternalChannelProvider.DISCORD.value,
                    "provider_failure_category": result.error_kind,
                },
            )

    async def _load_authority(
        self,
        *,
        session_id: str,
        payload: ExternalChannelMessagePayload,
    ) -> _DiscordThreadTitleAuthority | None:
        """Load current Session, Binding, route, connection, and Resource authority."""
        async with self.session_manager() as session:
            resource = await self.external_channel_repository.get_resource(
                session,
                resource_id=payload.resource_id,
            )
            binding = await self.external_channel_repository.get_binding(
                session,
                binding_id=payload.binding_id,
            )
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if (
                resource is None
                or resource.status is not ExternalChannelResourceStatus.ACTIVE
                or resource.resource_type is not ExternalChannelResourceType.THREAD
                or binding is None
                or binding.resource_id != resource.id
                or binding.agent_session_id != session_id
                or binding.disconnected_at is not None
                or agent_session is None
                or agent_session.status is not AgentSessionStatus.ACTIVE
                or agent_session.stop_requested_at is not None
                or agent_session.ended_at is not None
            ):
                return None
            route = await self.external_channel_repository.get_agent_route(
                session,
                route_id=binding.route_id,
            )
            connection = (
                await self.external_channel_repository.get_connection_configuration(
                    session,
                    connection_id=resource.connection_id,
                )
            )
            if (
                route is None
                or route.connection_id != resource.connection_id
                or route.agent_id != agent_session.agent_id
                or route.catalog_status
                is not ExternalChannelRouteCatalogStatus.AVAILABLE
                or connection is None
                or connection.provider is not ExternalChannelProvider.DISCORD
                or connection.status
                not in {
                    ExternalChannelConnectionStatus.ACTIVE,
                    ExternalChannelConnectionStatus.DEGRADED,
                }
                or connection.disconnected_at is not None
                or connection.provider_tenant_id != payload.provider_tenant_id
                or connection.app_mode is not route.connection_app_mode
                or connection.encrypted_credentials is None
            ):
                return None
            agent = await self.agent_repository.get_by_id(
                session,
                agent_session.agent_id,
            )
            if (
                agent is None
                or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            ):
                return None
            labels = resource.labels or {}
            if (
                labels.get("provider") != ExternalChannelProvider.DISCORD.value
                or labels.get("guild_id") != payload.provider_tenant_id
            ):
                return None
            channel_id = labels.get("delivery_channel_id")
            provisional_title = labels.get(DISCORD_INITIAL_THREAD_TITLE_LABEL)
            if (
                not isinstance(channel_id, str)
                or not channel_id.isdigit()
                or not isinstance(provisional_title, str)
                or not provisional_title
            ):
                return None
            try:
                credentials = self.credentials_codec.decrypt(
                    connection.encrypted_credentials
                )
            except ValueError:
                return None
            if not isinstance(credentials, DiscordConnectionCredentials):
                return None
            return _DiscordThreadTitleAuthority(
                bot_token=credentials.bot_token,
                guild_id=payload.provider_tenant_id,
                channel_id=channel_id,
                provisional_title=provisional_title,
            )
