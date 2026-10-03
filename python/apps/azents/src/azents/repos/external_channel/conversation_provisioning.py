"""Completed provider-conversation reads and shared DB retention primitives."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.external_channel_conversation_preparation import (
    ExternalChannelConversationPreparation,
    ExternalChannelConversationProvisioningError,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelBinding,
    ExternalChannelConnectionConfiguration,
    ExternalChannelResource,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository


@dataclasses.dataclass(frozen=True)
class ConversationProvisioningSnapshot:
    """One detached resource/configuration/current-binding read."""

    resource: ExternalChannelResource | None
    configuration: ExternalChannelConnectionConfiguration | None
    binding: ExternalChannelBinding | None


@dataclasses.dataclass(frozen=True)
class ExternalChannelConversationProvisioningRepository:
    """Own short persistence scopes around provider conversation preparation."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    repository: Annotated[
        ExternalChannelRepository, Depends(ExternalChannelRepository.create)
    ]
    work_repository: Annotated[
        ExternalChannelWorkRepository, Depends(ExternalChannelWorkRepository.create)
    ]

    async def prepare_snapshot(
        self, *, connection_id: str, target_resource_id: str
    ) -> ConversationProvisioningSnapshot:
        async with self.session_manager() as session:
            resource = await self.repository.get_resource(
                session, resource_id=target_resource_id
            )
            configuration = await self.repository.get_connection_configuration(
                session, connection_id=connection_id
            )
            binding = await self.repository.get_connected_binding_by_resource(
                session, resource_id=target_resource_id
            )
            return ConversationProvisioningSnapshot(
                resource=resource, configuration=configuration, binding=binding
            )

    async def apply_in_session(
        self,
        session: AsyncSession,
        *,
        target_resource_id: str,
        preparation: ExternalChannelConversationPreparation,
    ) -> None:
        """Retain prepared provider identity in the owning composition transaction."""
        if preparation.target_resource_id != target_resource_id:
            raise ExternalChannelConversationProvisioningError(
                category="ownership_stale", retryable=False
            )
        if preparation.delivery_channel_id is None:
            return
        retained = await self.work_repository.record_discord_delivery_channel(
            session,
            resource_id=target_resource_id,
            delivery_channel_id=preparation.delivery_channel_id,
            initial_thread_title=preparation.initial_thread_title,
        )
        if retained is None:
            raise ExternalChannelConversationProvisioningError(
                category="ownership_stale", retryable=False
            )
