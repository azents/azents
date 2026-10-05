"""Completed read-only Discord transport authority and resource snapshots."""

import datetime
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from azents.core.enums import ExternalChannelResourceType
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelResource,
)
from azents.repos.external_channel.repository import ExternalChannelRepository


@dataclass(frozen=True, kw_only=True)
class ExternalChannelTransportReadRepository:
    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ]

    async def get_owned_discord_configuration(
        self,
        *,
        connection_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
    ) -> ExternalChannelConnectionConfiguration | None:
        async with self.session_manager() as session:
            result = await self.repository.get_owned_discord_gateway_configuration(
                session,
                connection_id=connection_id,
                lease_owner=lease_owner,
                lease_generation=lease_generation,
                now=now,
            )
        return result

    async def get_discord_resource(
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
                provider_resource_key=f"discord:{guild_id}:{conversation_id}",
            )
            if resource is not None or thread_id is None:
                return resource
            return await self.repository.get_discord_resource_by_delivery_channel(
                session,
                connection_id=connection_id,
                guild_id=guild_id,
                delivery_channel_id=thread_id,
            )
