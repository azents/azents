"""Provider conversation preparation shared by ingress owners and durable replay."""

import dataclasses
from typing import Annotated

from cryptography.fernet import InvalidToken
from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelProvider,
    ExternalChannelResourceType,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.services.external_channel.channel_action import get_discord_delivery_client
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import DiscordConnectionCredentials
from azents.services.external_channel.discord_delivery import DiscordDeliveryClient


@dataclasses.dataclass(frozen=True)
class ExternalChannelConversationProvisioningError(Exception):
    """Sanitized provider conversation preparation failure."""

    category: str
    retryable: bool


@dataclasses.dataclass(frozen=True)
class ExternalChannelConversationPreparation:
    """Content-free provider result awaiting one atomic database transition."""

    target_resource_id: str
    delivery_channel_id: str | None
    initial_thread_title: str | None


@dataclasses.dataclass
class ExternalChannelConversationProvisioningService:
    """Prepare and retain one provider conversation before Session creation."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository.create),
    ]
    work_repository: Annotated[
        ExternalChannelWorkRepository,
        Depends(ExternalChannelWorkRepository.create),
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    discord_client: Annotated[
        DiscordDeliveryClient,
        Depends(get_discord_delivery_client),
    ]

    async def prepare(
        self,
        *,
        connection_id: str,
        target_resource_id: str,
    ) -> ExternalChannelConversationPreparation:
        """Perform provider I/O without creating any Azents Session state."""
        async with self.session_manager() as session:
            resource = await self.repository.get_resource(
                session,
                resource_id=target_resource_id,
            )
            configuration = await self.repository.get_connection_configuration(
                session,
                connection_id=connection_id,
            )
            binding = await self.repository.get_connected_binding_by_resource(
                session,
                resource_id=target_resource_id,
            )
        if resource is None or configuration is None or binding is not None:
            if resource is None or configuration is None:
                raise ExternalChannelConversationProvisioningError(
                    category="ownership_stale",
                    retryable=False,
                )
            return ExternalChannelConversationPreparation(
                target_resource_id=target_resource_id,
                delivery_channel_id=None,
                initial_thread_title=None,
            )
        if resource.connection_id != connection_id:
            raise ExternalChannelConversationProvisioningError(
                category="ownership_stale",
                retryable=False,
            )
        if configuration.encrypted_credentials is None:
            raise ExternalChannelConversationProvisioningError(
                category="credentials_invalid",
                retryable=False,
            )
        labels = resource.labels or {}
        delivery_channel_id = _label(labels, "delivery_channel_id")
        if (
            configuration.provider is ExternalChannelProvider.DISCORD
            and resource.resource_type is ExternalChannelResourceType.THREAD
            and delivery_channel_id is None
        ):
            try:
                credentials = self.credentials_codec.decrypt(
                    configuration.encrypted_credentials
                )
            except (InvalidToken, UnicodeDecodeError, ValidationError) as error:
                raise ExternalChannelConversationProvisioningError(
                    category="credentials_invalid",
                    retryable=False,
                ) from error
            if not isinstance(credentials, DiscordConnectionCredentials):
                raise ExternalChannelConversationProvisioningError(
                    category="credentials_invalid",
                    retryable=False,
                )
            guild_id = _label(labels, "guild_id")
            parent_channel_id = _label(labels, "parent_channel_id")
            root_message_id = _label(labels, "root_message_id")
            if guild_id is None or parent_channel_id is None or root_message_id is None:
                raise ExternalChannelConversationProvisioningError(
                    category="ownership_stale",
                    retryable=False,
                )
            result = await self.discord_client.ensure_thread(
                bot_token=credentials.bot_token,
                guild_id=guild_id,
                parent_channel_id=parent_channel_id,
                root_message_id=root_message_id,
                name=None,
            )
            if result.status != "delivered" or result.provider_message_key is None:
                raise ExternalChannelConversationProvisioningError(
                    category=result.error_kind or "temporary_failure",
                    retryable=result.status == "unknown",
                )
            delivery_channel_id = _discord_thread_id(result.provider_message_key)
            if delivery_channel_id is None:
                raise ExternalChannelConversationProvisioningError(
                    category="malformed_response",
                    retryable=False,
                )
            return ExternalChannelConversationPreparation(
                target_resource_id=target_resource_id,
                delivery_channel_id=delivery_channel_id,
                initial_thread_title=result.created_thread_name,
            )
        if (
            configuration.provider is ExternalChannelProvider.DISCORD
            and delivery_channel_id is not None
            and not delivery_channel_id.isdigit()
        ):
            raise ExternalChannelConversationProvisioningError(
                category="malformed_response",
                retryable=False,
            )
        return ExternalChannelConversationPreparation(
            target_resource_id=target_resource_id,
            delivery_channel_id=None,
            initial_thread_title=None,
        )

    async def apply(
        self,
        session: AsyncSession,
        *,
        target_resource_id: str,
        preparation: ExternalChannelConversationPreparation,
    ) -> None:
        """Retain a prepared provider identity in the caller-owned transaction."""
        if preparation.target_resource_id != target_resource_id:
            raise ExternalChannelConversationProvisioningError(
                category="ownership_stale",
                retryable=False,
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
                category="ownership_stale",
                retryable=False,
            )


def _label(labels: dict[str, object], key: str) -> str | None:
    value = labels.get(key)
    return value if isinstance(value, str) and value else None


def _discord_thread_id(provider_message_key: str) -> str | None:
    prefix = "discord-thread:"
    value = provider_message_key.removeprefix(prefix)
    if provider_message_key.startswith(prefix) and value.isdigit():
        return value
    return None
