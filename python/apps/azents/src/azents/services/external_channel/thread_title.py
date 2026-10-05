"""One-shot best-effort Discord thread title projection."""

import dataclasses
import logging
from typing import Annotated

from fastapi import Depends

from azents.core.enums import (
    EventKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
)
from azents.core.external_channel_provider import DiscordConnectionCredentials
from azents.core.external_channel_title import (
    normalize_discord_thread_title,
)
from azents.engine.events.types import Event, ExternalChannelMessagePayload
from azents.repos.external_channel.thread_title_read import (
    ExternalChannelThreadTitleReadRepository,
)
from azents.services.external_channel.channel_action import (
    get_discord_delivery_client,
)
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.discord_delivery import DiscordDeliveryClient
from azents.services.external_channel.discord_sdk import DiscordSDKError

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

    repository: Annotated[
        ExternalChannelThreadTitleReadRepository,
        Depends(ExternalChannelThreadTitleReadRepository),
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
            or payload.prompt_role != "invocation"
            or payload.author_type is not ExternalChannelPrincipalAuthorType.HUMAN
        ):
            return
        authority = await self._load_authority(
            session_id=session_id,
            payload=payload,
        )
        if authority is None:
            return
        try:
            async with self.discord_client.open(
                bot_token=authority.bot_token
            ) as discord_client:
                read = await discord_client.read_thread_title(
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
                result = await discord_client.update_thread_title(
                    bot_token=authority.bot_token,
                    guild_id=authority.guild_id,
                    channel_id=authority.channel_id,
                    name=normalized_title,
                )
        except DiscordSDKError, TimeoutError:
            return
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
        self, *, session_id: str, payload: ExternalChannelMessagePayload
    ) -> _DiscordThreadTitleAuthority | None:
        """Decode credentials only after the current exact authority read closes."""
        snapshot = await self.repository.load_authority(
            session_id=session_id,
            resource_id=payload.resource_id,
            binding_id=payload.binding_id,
            provider_tenant_id=payload.provider_tenant_id,
        )
        if snapshot is None:
            return None
        try:
            credentials = self.credentials_codec.decrypt(snapshot.encrypted_credentials)
        except ValueError:
            return None
        if not isinstance(credentials, DiscordConnectionCredentials):
            return None
        return _DiscordThreadTitleAuthority(
            bot_token=credentials.bot_token,
            guild_id=snapshot.guild_id,
            channel_id=snapshot.channel_id,
            provisional_title=snapshot.provisional_title,
        )
