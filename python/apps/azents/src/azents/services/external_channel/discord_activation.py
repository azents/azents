"""Discord callback configuration and fenced connection activation."""

import datetime
import hashlib
import secrets
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urljoin

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import (
    DiscordConnectionCredentials,
    ExternalChannelConnectionStatusSnapshot,
    ExternalChannelProviderIdentity,
)
from azents.services.external_channel.discord_api import (
    DiscordAPIClient,
    get_discord_api_client,
)


@dataclass
class DiscordConnectionActivationService:
    """Configure a Discord callback and activate its durable authority fences."""

    config: Annotated[Config, Depends(get_config)]
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    repository: Annotated[
        ExternalChannelRepository,
        Depends(ExternalChannelRepository),
    ]
    credentials_codec: Annotated[
        ExternalChannelCredentialsCodec,
        Depends(get_external_channel_credentials_codec),
    ]
    discord_client: Annotated[DiscordAPIClient, Depends(get_discord_api_client)]

    async def activate(
        self,
        *,
        connection_id: str,
    ) -> ExternalChannelConnectionStatusSnapshot:
        """Configure one callback before committing its current App authority."""
        if not self.config.external_channel_discord_callback_url:
            raise ValueError("Discord callback URL is not configured.")
        async with self.session_manager() as session:
            connection = await self.repository.get_connection_configuration(
                session,
                connection_id=connection_id,
            )
        if connection is None or connection.encrypted_credentials is None:
            raise ValueError("Discord connection is not configured.")
        credentials = self.credentials_codec.decrypt(connection.encrypted_credentials)
        if not isinstance(credentials, DiscordConnectionCredentials):
            raise ValueError("Discord connection credentials are unavailable.")
        target_guild_id = _target_guild_id(connection.provider_config)
        metadata = await self.discord_client.get_current_application(
            bot_token=credentials.bot_token
        )
        if connection.provider_app_id != metadata.application_id:
            raise ValueError("Discord Application ID does not match the Bot Token.")
        selector = secrets.token_urlsafe(32)
        endpoint_url = urljoin(
            self.config.external_channel_discord_callback_url.rstrip("/") + "/",
            f"external-channel/v1/discord/interactions/{selector}",
        )
        await self.discord_client.configure_interactions_endpoint(
            bot_token=credentials.bot_token,
            application_id=metadata.application_id,
            endpoint_url=endpoint_url,
        )
        async with self.session_manager() as session:
            activated = await self.repository.activate_discord_connection(
                session,
                connection_id=connection_id,
                expected_encrypted_credentials=connection.encrypted_credentials,
                provider_app_id=metadata.application_id,
                provider_tenant_id=target_guild_id,
                provider_bot_user_id=None,
                interaction_public_key=metadata.verify_key,
                callback_selector_hash=hashlib.sha256(selector.encode()).hexdigest(),
                checked_at=datetime.datetime.now(datetime.UTC),
            )
            if activated is None:
                raise ValueError(
                    "Discord connection authority changed during activation."
                )
            await session.commit()
        return ExternalChannelConnectionStatusSnapshot(
            status=activated.status,
            code="valid",
            message="Discord callback is configured.",
            action_hint=None,
            checked_at=activated.last_health_at,
            identity=ExternalChannelProviderIdentity(
                provider=activated.provider,
                app_id=metadata.application_id,
                tenant_id=target_guild_id,
                bot_user_id=activated.provider_bot_user_id,
            ),
            credentials=self.credentials_codec.snapshot(credentials),
            capabilities=None,
        )


def _target_guild_id(provider_config: dict[str, object] | None) -> str:
    """Return the stored Discord target Guild ID without accepting caller input."""
    if provider_config is None:
        raise ValueError("Discord target Guild configuration is missing.")
    target_guild_id = provider_config.get("target_guild_id")
    if not isinstance(target_guild_id, str) or not target_guild_id:
        raise ValueError("Discord target Guild configuration is invalid.")
    return target_guild_id
