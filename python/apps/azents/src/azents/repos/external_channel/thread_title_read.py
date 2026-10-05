"""Completed exact read-only authority for one Discord thread title attempt."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelRouteCatalogStatus,
)
from azents.core.external_channel_title import DISCORD_INITIAL_THREAD_TITLE_LABEL
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.repository import ExternalChannelRepository


@dataclasses.dataclass(frozen=True)
class DiscordThreadTitleSnapshot:
    """Detached current exact title authority with encrypted credentials."""

    encrypted_credentials: str
    guild_id: str
    channel_id: str
    provisional_title: str


@dataclasses.dataclass
class ExternalChannelThreadTitleReadRepository:
    """Close the exact authority observation before credential decoding or SDK I/O."""

    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    external_channel_repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]

    async def load_authority(
        self,
        *,
        session_id: str,
        resource_id: str,
        binding_id: str,
        provider_tenant_id: str,
    ) -> DiscordThreadTitleSnapshot | None:
        """Load current Session, Binding, route, connection, and Resource authority."""
        async with self.read_session_manager() as session:
            resource = await self.external_channel_repository.get_resource(
                session,
                resource_id=resource_id,
            )
            binding = await self.external_channel_repository.get_binding(
                session,
                binding_id=binding_id,
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
                or connection.provider_tenant_id != provider_tenant_id
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
                or labels.get("guild_id") != provider_tenant_id
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
            return DiscordThreadTitleSnapshot(
                encrypted_credentials=connection.encrypted_credentials,
                guild_id=provider_tenant_id,
                channel_id=channel_id,
                provisional_title=provisional_title,
            )
