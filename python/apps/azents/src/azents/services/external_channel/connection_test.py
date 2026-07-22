"""External Channel connection setup and validation tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    ExternalChannelConnectionStatus,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnection,
    ExternalChannelConnectionConfiguration,
    ExternalChannelConnectionCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.connection import (
    ExternalChannelConnectionService,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import (
    ExternalChannelCapabilitySnapshot,
    ExternalChannelProviderIdentity,
    SlackConnectionCredentials,
)
from azents.services.external_channel.slack_http import (
    SlackConnectionValidation,
    SlackWebAPIClient,
    hash_callback_selector,
)

_NOW = datetime.datetime(2026, 7, 22, 1, 0, tzinfo=datetime.UTC)


class _SessionDouble:
    """Record connection transaction commits."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _RepositoryDouble:
    """Persist one in-memory connection projection."""

    def __init__(self) -> None:
        self.create: ExternalChannelConnectionCreate | None = None
        self.configuration: ExternalChannelConnectionConfiguration | None = None
        self.health_status: ExternalChannelConnectionStatus | None = None
        self.health_tenant_id: str | None = None
        self.health_bot_user_id: str | None = None
        self.health_capabilities: dict[str, object] | None = None

    async def create_connection(
        self,
        session: AsyncSession,
        create: ExternalChannelConnectionCreate,
    ) -> ExternalChannelConnection:
        del session
        self.create = create
        return _connection_from_create(create)

    async def get_connection_configuration(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnectionConfiguration | None:
        del session, connection_id
        return self.configuration

    async def update_connection_health(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        status: ExternalChannelConnectionStatus,
        provider_tenant_id: str | None,
        provider_bot_user_id: str | None,
        capabilities: dict[str, object] | None,
        checked_at: datetime.datetime,
    ) -> ExternalChannelConnection | None:
        del session, connection_id
        assert self.configuration is not None
        self.health_status = status
        self.health_tenant_id = provider_tenant_id
        self.health_bot_user_id = provider_bot_user_id
        self.health_capabilities = capabilities
        tenant_id = provider_tenant_id or self.configuration.provider_tenant_id
        bot_user_id = provider_bot_user_id or self.configuration.provider_bot_user_id
        return ExternalChannelConnection(
            id=self.configuration.id,
            workspace_id=self.configuration.workspace_id,
            provider=self.configuration.provider,
            transport=self.configuration.transport,
            status=status,
            provider_app_id=self.configuration.provider_app_id,
            provider_tenant_id=tenant_id,
            provider_bot_user_id=bot_user_id,
            http_callback_selector_hash=(
                self.configuration.http_callback_selector_hash
            ),
            capabilities=capabilities or self.configuration.capabilities,
            provider_config=self.configuration.provider_config,
            last_verified_at=(
                checked_at
                if status is ExternalChannelConnectionStatus.ACTIVE
                else self.configuration.last_verified_at
            ),
            last_health_at=checked_at,
            disconnected_at=self.configuration.disconnected_at,
            created_at=self.configuration.created_at,
            updated_at=checked_at,
        )


class _SlackClientDouble:
    """Return one configured sanitized Slack validation result."""

    def __init__(self, result: SlackConnectionValidation) -> None:
        self.result = result
        self.bot_tokens: list[str] = []

    async def validate_connection(
        self,
        *,
        bot_token: str,
        app_id: str,
        transport: ExternalChannelTransport,
    ) -> SlackConnectionValidation:
        assert app_id == "A-1"
        assert transport is ExternalChannelTransport.HTTP
        self.bot_tokens.append(bot_token)
        return self.result


def _connection_from_create(
    create: ExternalChannelConnectionCreate,
) -> ExternalChannelConnection:
    return ExternalChannelConnection(
        id="connection-1",
        workspace_id=create.workspace_id,
        provider=create.provider,
        transport=create.transport,
        status=create.status,
        provider_app_id=create.provider_app_id,
        provider_tenant_id=create.provider_tenant_id,
        provider_bot_user_id=create.provider_bot_user_id,
        http_callback_selector_hash=create.http_callback_selector_hash,
        capabilities=create.capabilities,
        provider_config=create.provider_config,
        last_verified_at=create.last_verified_at,
        last_health_at=create.last_health_at,
        disconnected_at=create.disconnected_at,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _configuration(
    codec: ExternalChannelCredentialsCodec,
) -> ExternalChannelConnectionConfiguration:
    return ExternalChannelConnectionConfiguration(
        id="connection-1",
        workspace_id="workspace-1",
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        status=ExternalChannelConnectionStatus.CONFIGURING,
        provider_app_id="A-1",
        provider_tenant_id=None,
        provider_bot_user_id=None,
        http_callback_selector_hash="selector-hash",
        encrypted_credentials=codec.encrypt(_credentials()),
        capabilities=None,
        provider_config=None,
        last_verified_at=None,
        last_health_at=None,
        disconnected_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _credentials() -> SlackConnectionCredentials:
    return SlackConnectionCredentials(
        bot_token="xoxb-secret",
        signing_secret="signing-secret",
        app_token=None,
    )


def _service(
    *,
    repository: _RepositoryDouble,
    codec: ExternalChannelCredentialsCodec,
    slack_client: _SlackClientDouble,
    session: _SessionDouble,
) -> ExternalChannelConnectionService:
    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, session)

    return ExternalChannelConnectionService(
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        repository=cast(ExternalChannelRepository, repository),
        credentials_codec=codec,
        slack_client=cast(SlackWebAPIClient, slack_client),
    )


@pytest.fixture
def codec() -> ExternalChannelCredentialsCodec:
    """Return a real encrypted credential codec."""
    return ExternalChannelCredentialsCodec(
        CredentialCipher(Fernet.generate_key().decode())
    )


@pytest.mark.asyncio
async def test_http_setup_returns_selector_once_and_persists_only_hash(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """Keep the callback routing secret out of persistent connection state."""
    repository = _RepositoryDouble()
    session = _SessionDouble()
    service = _service(
        repository=repository,
        codec=codec,
        slack_client=_SlackClientDouble(
            SlackConnectionValidation(
                status="unavailable",
                code="unused",
                message=None,
                action_hint=None,
                identity=None,
                capabilities=None,
            )
        ),
        session=session,
    )

    setup = await service.create_slack_connection(
        workspace_id="workspace-1",
        app_id="A-1",
        transport=ExternalChannelTransport.HTTP,
        credentials=_credentials(),
    )

    assert setup.callback_selector is not None
    assert repository.create is not None
    assert repository.create.http_callback_selector_hash == hash_callback_selector(
        setup.callback_selector
    )
    assert setup.callback_selector not in repr(repository.create)
    assert "xoxb-secret" not in repr(repository.create)
    assert repository.create.encrypted_credentials is not None
    assert session.commits == 1


@pytest.mark.asyncio
async def test_valid_connection_activation_persists_identity_and_redacts_secrets(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """Activate a verified Slack connection without exposing its bot token."""
    capabilities = ExternalChannelCapabilitySnapshot(
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        inbound_events=True,
        thread_history=True,
        post_messages=True,
        update_messages=True,
        delete_messages=True,
    )
    validation = SlackConnectionValidation(
        status="valid",
        code=None,
        message=None,
        action_hint=None,
        identity=ExternalChannelProviderIdentity(
            provider=ExternalChannelProvider.SLACK,
            app_id="A-1",
            tenant_id="T-1",
            bot_user_id="B-1",
        ),
        capabilities=capabilities,
    )
    repository = _RepositoryDouble()
    repository.configuration = _configuration(codec)
    session = _SessionDouble()
    slack_client = _SlackClientDouble(validation)
    service = _service(
        repository=repository,
        codec=codec,
        slack_client=slack_client,
        session=session,
    )

    snapshot = await service.validate_connection(connection_id="connection-1")

    assert snapshot.status is ExternalChannelConnectionStatus.ACTIVE
    assert snapshot.identity is not None
    assert snapshot.identity.tenant_id == "T-1"
    assert snapshot.credentials.configured_fields == (
        "bot_token",
        "signing_secret",
    )
    assert repository.health_status is ExternalChannelConnectionStatus.ACTIVE
    assert repository.health_tenant_id == "T-1"
    assert repository.health_bot_user_id == "B-1"
    assert slack_client.bot_tokens == ["xoxb-secret"]
    assert "xoxb-secret" not in repr(snapshot)
    assert session.commits == 1
