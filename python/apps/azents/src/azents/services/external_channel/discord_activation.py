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
    DiscordAPIError,
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
        """Configure one callback after persisting its PING verification material."""
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
        bot_user_id = await self.discord_client.get_current_bot_user_id(
            bot_token=credentials.bot_token
        )
        selector = secrets.token_urlsafe(32)
        selector_hash = hashlib.sha256(selector.encode()).hexdigest()
        endpoint_url = urljoin(
            self.config.external_channel_discord_callback_url.rstrip("/") + "/",
            f"external-channel/v1/discord/interactions/{selector}",
        )
        async with self.session_manager() as session:
            prepared = await self.repository.prepare_discord_callback(
                session,
                connection_id=connection_id,
                expected_encrypted_credentials=connection.encrypted_credentials,
                expected_configuration_generation=connection.configuration_generation,
                provider_app_id=metadata.application_id,
                interaction_public_key=metadata.verify_key,
                callback_selector_hash=selector_hash,
            )
            if not prepared:
                raise ValueError(
                    "Discord connection authority changed during activation."
                )
            await session.commit()
        try:
            await self.discord_client.configure_interactions_endpoint(
                bot_token=credentials.bot_token,
                application_id=metadata.application_id,
                endpoint_url=endpoint_url,
            )
        except DiscordAPIError:
            await self._clear_prepared_callback(
                connection_id=connection_id,
                expected_encrypted_credentials=connection.encrypted_credentials,
                expected_configuration_generation=connection.configuration_generation,
                callback_selector_hash=selector_hash,
            )
            raise
        async with self.session_manager() as session:
            activated = await self.repository.activate_discord_connection(
                session,
                connection_id=connection_id,
                expected_encrypted_credentials=connection.encrypted_credentials,
                expected_configuration_generation=connection.configuration_generation,
                provider_app_id=metadata.application_id,
                provider_tenant_id=target_guild_id,
                provider_bot_user_id=bot_user_id,
                interaction_public_key=metadata.verify_key,
                callback_selector_hash=selector_hash,
                checked_at=datetime.datetime.now(datetime.UTC),
            )
            if activated is not None:
                await session.commit()
        if activated is None:
            await self._clear_prepared_callback(
                connection_id=connection_id,
                expected_encrypted_credentials=connection.encrypted_credentials,
                expected_configuration_generation=connection.configuration_generation,
                callback_selector_hash=selector_hash,
            )
            raise ValueError("Discord connection authority changed during activation.")
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
                bot_user_id=bot_user_id,
            ),
            credentials=self.credentials_codec.snapshot(credentials),
            capabilities=None,
        )

    async def _clear_prepared_callback(
        self,
        *,
        connection_id: str,
        expected_encrypted_credentials: str,
        expected_configuration_generation: int,
        callback_selector_hash: str,
    ) -> None:
        """Clear one fenced provisional callback without retaining its selector."""
        async with self.session_manager() as session:
            await self.repository.clear_prepared_discord_callback(
                session,
                connection_id=connection_id,
                expected_encrypted_credentials=expected_encrypted_credentials,
                expected_configuration_generation=expected_configuration_generation,
                callback_selector_hash=callback_selector_hash,
                checked_at=datetime.datetime.now(datetime.UTC),
            )
            await session.commit()


def _target_guild_id(provider_config: dict[str, object] | None) -> str:
    """Return the stored Discord target Guild ID without accepting caller input."""
    if provider_config is None:
        raise ValueError("Discord target Guild configuration is missing.")
    target_guild_id = provider_config.get("target_guild_id")
    if not isinstance(target_guild_id, str) or not target_guild_id:
        raise ValueError("Discord target Guild configuration is invalid.")
    return target_guild_id
