"""External Channel connection setup and provider health validation."""

import datetime
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, assert_never

import httpx
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.deps import get_credential_cipher
from azents.core.enums import (
    ExternalChannelConnectionStatus,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnection,
    ExternalChannelConnectionCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import (
    ExternalChannelCapabilitySnapshot,
    ExternalChannelConnectionCredentialPayload,
    ExternalChannelConnectionStatusSnapshot,
    ExternalChannelProviderIdentity,
    SlackConnectionCredentials,
)
from azents.services.external_channel.provider import (
    SlackExternalChannelProviderContract,
)
from azents.services.external_channel.slack_http import (
    SlackConnectionValidation,
    SlackWebAPIClient,
)


class ExternalChannelConnectionNotFound(LookupError):
    """The requested External Channel connection does not exist."""


class ExternalChannelConnectionStateChanged(RuntimeError):
    """The connection changed while provider validation was in flight."""


@dataclass(frozen=True)
class ExternalChannelConnectionSetup:
    """Created provider connection."""

    connection: ExternalChannelConnection


async def get_slack_validation_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """Provide a bounded HTTP client for Slack connection validation."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        yield client


def get_slack_web_api_client(
    http_client: Annotated[
        httpx.AsyncClient,
        Depends(get_slack_validation_http_client),
    ],
) -> SlackWebAPIClient:
    """Provide the Slack Web API adapter."""
    return SlackWebAPIClient(http_client)


def get_external_channel_credentials_codec(
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
) -> ExternalChannelCredentialsCodec:
    """Provide encrypted External Channel credential serialization."""
    return ExternalChannelCredentialsCodec(cipher)


@dataclass
class ExternalChannelConnectionService:
    """Create and validate provider connections without exposing secrets."""

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
    slack_client: Annotated[
        SlackWebAPIClient,
        Depends(get_slack_web_api_client),
    ]

    async def create_slack_connection(
        self,
        *,
        workspace_id: str,
        app_id: str,
        transport: ExternalChannelTransport,
        credentials: SlackConnectionCredentials,
    ) -> ExternalChannelConnectionSetup:
        """Persist one configuring Slack connection."""
        if not app_id.strip():
            raise ValueError("Slack App ID must not be blank.")
        payload = ExternalChannelConnectionCredentialPayload(
            provider=ExternalChannelProvider.SLACK,
            transport=transport,
            credentials=credentials,
        )
        contract = SlackExternalChannelProviderContract()
        validated = contract.validate_connection_credentials(payload)
        create = ExternalChannelConnectionCreate(
            workspace_id=workspace_id,
            provider=ExternalChannelProvider.SLACK,
            transport=transport,
            status=ExternalChannelConnectionStatus.CONFIGURING,
            provider_app_id=app_id,
            provider_tenant_id=None,
            provider_bot_user_id=None,
            http_callback_selector_hash=None,
            encrypted_credentials=self.credentials_codec.encrypt(validated),
            capabilities=None,
            provider_config=None,
            last_verified_at=None,
            last_health_at=None,
            disconnected_at=None,
            socket_lease_owner=None,
            socket_lease_until=None,
            socket_heartbeat_at=None,
            socket_gap_detected_at=None,
            socket_gap_reason=None,
        )
        async with self.session_manager() as session:
            connection = await self.repository.create_connection(session, create)
            await session.commit()
        return ExternalChannelConnectionSetup(connection=connection)

    async def validate_connection(
        self,
        *,
        connection_id: str,
    ) -> ExternalChannelConnectionStatusSnapshot:
        """Run Slack identity validation and persist a sanitized health result."""
        async with self.session_manager() as session:
            configuration = await self.repository.get_connection_configuration(
                session,
                connection_id=connection_id,
            )
        if configuration is None:
            raise ExternalChannelConnectionNotFound(connection_id)
        if configuration.provider is not ExternalChannelProvider.SLACK:
            raise RuntimeError("External Channel provider is not supported.")
        if configuration.encrypted_credentials is None:
            raise RuntimeError("External Channel credentials are not configured.")
        if configuration.provider_app_id is None:
            raise RuntimeError("Slack App identity is not configured.")
        credentials = self.credentials_codec.decrypt(
            configuration.encrypted_credentials
        )
        result = await self.slack_client.validate_connection(
            bot_token=credentials.bot_token,
            app_id=configuration.provider_app_id,
            transport=configuration.transport,
        )
        checked_at = datetime.datetime.now(datetime.UTC)
        status = _connection_status(result)
        identity = result.identity
        capabilities = (
            result.capabilities.model_dump(mode="json")
            if result.capabilities is not None
            else None
        )
        async with self.session_manager() as session:
            connection = await self.repository.update_connection_health(
                session,
                connection_id=connection_id,
                status=status,
                provider_tenant_id=(
                    identity.tenant_id if identity is not None else None
                ),
                provider_bot_user_id=(
                    identity.bot_user_id if identity is not None else None
                ),
                capabilities=capabilities,
                checked_at=checked_at,
                expected_encrypted_credentials=configuration.encrypted_credentials,
            )
            if connection is None:
                current = await self.repository.get_connection(
                    session,
                    connection_id=connection_id,
                )
                if current is None:
                    raise ExternalChannelConnectionNotFound(connection_id)
                raise ExternalChannelConnectionStateChanged(
                    "The connection changed during validation. Retry the operation."
                )
            await session.commit()
        return ExternalChannelConnectionStatusSnapshot(
            status=connection.status,
            code=result.code,
            message=result.message,
            action_hint=result.action_hint,
            checked_at=checked_at,
            identity=_connection_identity(connection),
            credentials=self.credentials_codec.snapshot(credentials),
            capabilities=_connection_capabilities(connection),
        )


def _connection_status(
    result: SlackConnectionValidation,
) -> ExternalChannelConnectionStatus:
    match result.status:
        case "valid":
            return ExternalChannelConnectionStatus.ACTIVE
        case "invalid":
            return ExternalChannelConnectionStatus.RECONNECT_REQUIRED
        case "unavailable":
            return ExternalChannelConnectionStatus.DEGRADED
        case _ as unreachable:
            assert_never(unreachable)


def _connection_identity(
    connection: ExternalChannelConnection,
) -> ExternalChannelProviderIdentity | None:
    if connection.provider_app_id is None or connection.provider_tenant_id is None:
        return None
    return ExternalChannelProviderIdentity(
        provider=connection.provider,
        app_id=connection.provider_app_id,
        tenant_id=connection.provider_tenant_id,
        bot_user_id=connection.provider_bot_user_id,
    )


def _connection_capabilities(
    connection: ExternalChannelConnection,
) -> ExternalChannelCapabilitySnapshot | None:
    if connection.capabilities is None:
        return None
    return ExternalChannelCapabilitySnapshot.model_validate(connection.capabilities)
