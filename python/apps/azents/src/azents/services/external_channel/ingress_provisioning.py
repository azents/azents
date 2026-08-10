"""Provider preparation and Session creation for ingress conversation owners."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelResourceStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import ExternalChannelBinding
from azents.repos.external_channel.ingress_queue_data import ExternalChannelIngressOwner
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.conversation_provisioning import (
    ExternalChannelConversationPreparation,
    ExternalChannelConversationProvisioningError,
    ExternalChannelConversationProvisioningService,
)
from azents.services.external_channel.mailbox_ingestion_store import (
    ExternalChannelMailboxIngestionStore,
)

ExternalChannelIngressProvisioningError = ExternalChannelConversationProvisioningError
ExternalChannelIngressProviderPreparation = ExternalChannelConversationPreparation


@dataclasses.dataclass
class ExternalChannelIngressProvisioningService:
    """Prepare one provider conversation before creating its Binding and Session."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ]
    conversation_provisioning: Annotated[
        ExternalChannelConversationProvisioningService,
        Depends(ExternalChannelConversationProvisioningService),
    ]
    mailbox_store: Annotated[
        ExternalChannelMailboxIngestionStore,
        Depends(ExternalChannelMailboxIngestionStore),
    ]

    async def prepare(
        self,
        *,
        owner: ExternalChannelIngressOwner,
    ) -> ExternalChannelIngressProviderPreparation:
        """Perform provider I/O without creating any Azents Session state."""
        return await self.conversation_provisioning.prepare(
            connection_id=owner.connection_id,
            target_resource_id=owner.target_resource_id,
        )

    async def complete(
        self,
        session: AsyncSession,
        *,
        owner: ExternalChannelIngressOwner,
        preparation: ExternalChannelIngressProviderPreparation,
    ) -> ExternalChannelBinding:
        """Atomically revalidate and create the configured Binding/Session state."""
        connection = await self.repository.lock_connection_for_routing(
            session,
            connection_id=owner.connection_id,
        )
        resource = await self.repository.lock_resource(
            session,
            resource_id=owner.target_resource_id,
        )
        route = await self.repository.get_routable_route_by_id(
            session,
            route_id=owner.route_id,
        )
        if (
            connection is None
            or resource is None
            or resource.connection_id != owner.connection_id
            or resource.status is not ExternalChannelResourceStatus.ACTIVE
            or route is None
            or route.connection_id != owner.connection_id
        ):
            raise ExternalChannelIngressProvisioningError(
                category="ownership_stale",
                retryable=False,
            )
        if owner.participation_setting_id is not None:
            parent_channel_id = _parent_channel_id(resource.labels or {})
            setting = (
                None
                if parent_channel_id is None
                else await self.repository.lock_active_participation_setting(
                    session,
                    connection_id=owner.connection_id,
                    provider_parent_channel_id=parent_channel_id,
                )
            )
            if (
                setting is None
                or setting.id != owner.participation_setting_id
                or setting.settings_generation
                != owner.participation_settings_generation
                or setting.route_id != owner.route_id
                or setting.response_mode is not owner.response_mode
            ):
                raise ExternalChannelIngressProvisioningError(
                    category="ownership_stale",
                    retryable=False,
                )
        await self.conversation_provisioning.apply(
            session,
            target_resource_id=resource.id,
            preparation=preparation,
        )
        try:
            return await self.mailbox_store.create_configured_binding(
                session,
                resource_id=owner.target_resource_id,
                route_id=owner.route_id,
                response_mode=owner.response_mode,
            )
        except ValueError as error:
            raise ExternalChannelIngressProvisioningError(
                category="ownership_stale",
                retryable=False,
            ) from error


def _parent_channel_id(labels: dict[str, object]) -> str | None:
    return _label(labels, "parent_channel_id") or _label(labels, "channel_id")


def _label(labels: dict[str, object], key: str) -> str | None:
    value = labels.get(key)
    return value if isinstance(value, str) and value else None
