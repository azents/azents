"""Discord callback configuration and fenced connection activation."""

import datetime
import hashlib
import logging
import secrets
from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import urljoin

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import ExternalChannelConnectionStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import ExternalChannelConnectionConfiguration
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import (
    DiscordConnectionCredentials,
    ExternalChannelConnectionStatusSnapshot,
    ExternalChannelCredentialSnapshot,
    ExternalChannelProviderIdentity,
)
from azents.services.external_channel.discord_api import (
    DiscordAPIClient,
    DiscordAPIConfigurationInvalid,
    DiscordAPICredentialsInvalid,
    DiscordAPIError,
    DiscordAPIUnavailable,
    get_discord_api_client,
)

logger = logging.getLogger(__name__)

type DiscordActivationFailureCode = Literal[
    "discord_credentials_invalid",
    "discord_callback_configuration_invalid",
    "discord_api_unavailable",
    "discord_callback_url_missing",
    "discord_credentials_unavailable",
    "discord_target_guild_missing",
    "discord_target_guild_invalid",
    "discord_application_id_mismatch",
    "discord_authority_changed",
]


class DiscordActivationConfigurationError(ValueError):
    """A controlled local Discord activation failure without provider data."""

    def __init__(self, code: DiscordActivationFailureCode) -> None:
        self.code: DiscordActivationFailureCode = code
        super().__init__(code)


def discord_activation_failure_code(
    error: DiscordAPIError | DiscordActivationConfigurationError,
) -> DiscordActivationFailureCode:
    """Map one controlled activation exception to its durable safe code."""
    if isinstance(error, DiscordAPICredentialsInvalid):
        return "discord_credentials_invalid"
    if isinstance(error, DiscordAPIConfigurationInvalid):
        return "discord_callback_configuration_invalid"
    if isinstance(error, DiscordAPIUnavailable):
        return "discord_api_unavailable"
    assert isinstance(error, DiscordActivationConfigurationError)
    return error.code


def discord_activation_failure_detail(
    code: DiscordActivationFailureCode,
) -> tuple[str, str]:
    """Return bounded operator-safe fallback text for a safe failure code."""
    details: dict[DiscordActivationFailureCode, tuple[str, str]] = {
        "discord_credentials_invalid": (
            "Discord rejected the Bot Token.",
            "Replace the Bot Token and try again.",
        ),
        "discord_callback_configuration_invalid": (
            "Discord rejected the interaction endpoint.",
            "Check the Application configuration and public callback URL, "
            "then try again.",
        ),
        "discord_api_unavailable": (
            "Discord is temporarily unavailable.",
            "Try again later.",
        ),
        "discord_callback_url_missing": (
            "The Discord callback URL is not configured.",
            "Ask an administrator to configure the public callback URL, "
            "then validate again.",
        ),
        "discord_credentials_unavailable": (
            "The stored Discord credentials cannot be used.",
            "Replace the Bot Token and try again.",
        ),
        "discord_target_guild_missing": (
            "The Discord Guild ID is missing.",
            "Edit the connection and provide the target Guild ID.",
        ),
        "discord_target_guild_invalid": (
            "The Discord Guild ID is invalid.",
            "Edit the connection and provide the correct target Guild ID.",
        ),
        "discord_application_id_mismatch": (
            "The Application ID does not match the Bot Token.",
            "Edit the connection and use the Application ID that owns this Bot Token.",
        ),
        "discord_authority_changed": (
            "The Discord connection changed while it was being validated.",
            "Validate again. If it continues, replace the credentials.",
        ),
    }
    return details[code]


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
        """Activate or persist a safe reason for one Discord connection failure."""
        async with self.session_manager() as session:
            connection = await self.repository.get_connection_configuration(
                session,
                connection_id=connection_id,
            )
        if connection is None or connection.encrypted_credentials is None:
            raise ValueError("Discord connection is not configured.")
        try:
            return await self._activate_configured_connection(connection_id, connection)
        except (DiscordAPIError, DiscordActivationConfigurationError) as error:
            return await self._record_failure(
                connection_id=connection_id,
                expected_encrypted_credentials=connection.encrypted_credentials,
                expected_configuration_generation=connection.configuration_generation,
                error=error,
            )

    async def _activate_configured_connection(
        self,
        connection_id: str,
        connection: ExternalChannelConnectionConfiguration,
    ) -> ExternalChannelConnectionStatusSnapshot:
        """Perform provider mutation after loading one durable configuration."""
        encrypted_credentials = connection.encrypted_credentials
        if encrypted_credentials is None:
            raise ValueError("Discord connection is not configured.")
        configuration_generation = connection.configuration_generation
        provider_config = connection.provider_config
        provider_app_id = connection.provider_app_id
        if not self.config.external_channel_discord_callback_url:
            raise DiscordActivationConfigurationError("discord_callback_url_missing")
        try:
            credentials = self.credentials_codec.decrypt(encrypted_credentials)
        except ValueError as error:
            raise DiscordActivationConfigurationError(
                "discord_credentials_unavailable"
            ) from error
        if not isinstance(credentials, DiscordConnectionCredentials):
            raise DiscordActivationConfigurationError("discord_credentials_unavailable")
        target_guild_id = _target_guild_id(provider_config)
        metadata = await self.discord_client.get_current_application(
            bot_token=credentials.bot_token
        )
        if provider_app_id != metadata.application_id:
            raise DiscordActivationConfigurationError("discord_application_id_mismatch")
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
                expected_encrypted_credentials=encrypted_credentials,
                expected_configuration_generation=configuration_generation,
                provider_app_id=metadata.application_id,
                interaction_public_key=metadata.verify_key,
                callback_selector_hash=selector_hash,
            )
            if not prepared:
                raise DiscordActivationConfigurationError("discord_authority_changed")
            await session.commit()
        try:
            await self.discord_client.configure_interactions_endpoint(
                bot_token=credentials.bot_token,
                application_id=metadata.application_id,
                endpoint_url=endpoint_url,
            )
        except DiscordAPIError as error:
            cleared = await self._clear_prepared_callback(
                connection_id=connection_id,
                expected_encrypted_credentials=encrypted_credentials,
                expected_configuration_generation=configuration_generation,
                callback_selector_hash=selector_hash,
            )
            if not cleared:
                raise DiscordActivationConfigurationError(
                    "discord_authority_changed"
                ) from error
            return await self._record_failure(
                connection_id=connection_id,
                expected_encrypted_credentials=encrypted_credentials,
                expected_configuration_generation=configuration_generation + 1,
                error=error,
            )
        async with self.session_manager() as session:
            activated = await self.repository.activate_discord_connection(
                session,
                connection_id=connection_id,
                expected_encrypted_credentials=encrypted_credentials,
                expected_configuration_generation=configuration_generation,
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
            error = DiscordActivationConfigurationError("discord_authority_changed")
            cleared = await self._clear_prepared_callback(
                connection_id=connection_id,
                expected_encrypted_credentials=encrypted_credentials,
                expected_configuration_generation=configuration_generation,
                callback_selector_hash=selector_hash,
            )
            if not cleared:
                raise error
            return await self._record_failure(
                connection_id=connection_id,
                expected_encrypted_credentials=encrypted_credentials,
                expected_configuration_generation=configuration_generation + 1,
                error=error,
            )
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

    async def _record_failure(
        self,
        *,
        connection_id: str,
        expected_encrypted_credentials: str,
        expected_configuration_generation: int,
        error: DiscordAPIError | DiscordActivationConfigurationError,
    ) -> ExternalChannelConnectionStatusSnapshot:
        """Fence and retain a safe failure code without retaining exception text."""
        failure_code = discord_activation_failure_code(error)
        checked_at = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            failed = await self.repository.record_discord_activation_failure(
                session,
                connection_id=connection_id,
                expected_encrypted_credentials=expected_encrypted_credentials,
                expected_configuration_generation=expected_configuration_generation,
                failure_code=failure_code,
                checked_at=checked_at,
            )
            if failed is not None:
                await session.commit()
        if failed is None:
            raise DiscordActivationConfigurationError(
                "discord_authority_changed"
            ) from error
        logger.error(
            "Discord External Channel activation failed",
            extra={
                "connection_id": connection_id,
                "failure_stage": _discord_activation_failure_stage(failure_code),
                "failure_code": failure_code,
                "error_type": type(error).__name__,
            },
        )
        message, action_hint = discord_activation_failure_detail(failure_code)
        return ExternalChannelConnectionStatusSnapshot(
            status=ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
            code=failure_code,
            message=message,
            action_hint=action_hint,
            checked_at=failed.last_health_at,
            identity=None,
            credentials=ExternalChannelCredentialSnapshot(
                provider=failed.provider,
                configured_fields=("bot_token",),
            ),
            capabilities=None,
        )

    async def _clear_prepared_callback(
        self,
        *,
        connection_id: str,
        expected_encrypted_credentials: str,
        expected_configuration_generation: int,
        callback_selector_hash: str,
    ) -> bool:
        """Clear one fenced provisional callback without retaining its selector."""
        async with self.session_manager() as session:
            cleared = await self.repository.clear_prepared_discord_callback(
                session,
                connection_id=connection_id,
                expected_encrypted_credentials=expected_encrypted_credentials,
                expected_configuration_generation=expected_configuration_generation,
                callback_selector_hash=callback_selector_hash,
                checked_at=datetime.datetime.now(datetime.UTC),
            )
            await session.commit()
        return cleared


def _target_guild_id(provider_config: dict[str, object] | None) -> str:
    """Return the stored Discord target Guild ID without accepting caller input."""
    if provider_config is None:
        raise DiscordActivationConfigurationError("discord_target_guild_missing")
    target_guild_id = provider_config.get("target_guild_id")
    if not isinstance(target_guild_id, str):
        raise DiscordActivationConfigurationError("discord_target_guild_invalid")
    if not target_guild_id:
        raise DiscordActivationConfigurationError("discord_target_guild_missing")
    return target_guild_id


def _discord_activation_failure_stage(code: DiscordActivationFailureCode) -> str:
    """Return a stable diagnostic stage for structured observability."""
    if code == "discord_credentials_invalid":
        return "provider_authentication"
    if code == "discord_callback_configuration_invalid":
        return "provider_callback"
    if code == "discord_api_unavailable":
        return "provider_api"
    return "configuration"
