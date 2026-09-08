"""External Channel connection setup and validation tests."""

import datetime
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.core.external_channel_provider import (
    DiscordConnectionConfiguration,
    DiscordConnectionCredentials,
    ExternalChannelCapabilitySnapshot,
    ExternalChannelProviderIdentity,
    SlackConnectionCredentials,
    decode_discord_connection_configuration,
)
from azents.repos.external_channel.connection import (
    ExternalChannelConnectionRepository,
)
from azents.repos.external_channel.data import (
    ExternalChannelConnection,
    ExternalChannelConnectionConfiguration,
    ExternalChannelConnectionCreate,
    ExternalChannelConnectionHealthUpdate,
)
from azents.services.external_channel.connection import (
    ExternalChannelConnectionNotFound,
    ExternalChannelConnectionService,
    ExternalChannelConnectionStateChanged,
    external_channel_capabilities_from_storage,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.slack_http import (
    SlackConnectionValidation,
    SlackWebAPIClient,
)


def test_discord_persisted_configuration_defaults_url_preview_suppression() -> None:
    """Existing connection JSON adopts the connection-level default."""
    configuration = decode_discord_connection_configuration(
        {
            "provider": "discord",
            "target_guild_id": "guild-1",
            "thread_auto_archive_duration_minutes": 1440,
        }
    )

    assert configuration.suppress_url_previews is True


def test_discord_new_configuration_defaults_url_preview_suppression() -> None:
    """New connection input adopts the connection-level default."""
    configuration = DiscordConnectionConfiguration(
        target_guild_id="guild-1",
        thread_auto_archive_duration_minutes=1440,
    )

    assert configuration.suppress_url_previews is True


_NOW = datetime.datetime(2026, 7, 22, 1, 0, tzinfo=datetime.UTC)


class _ConnectionRepositoryDouble(ExternalChannelConnectionRepository):
    """Return completed connection operations without exposing a live transaction."""

    def __init__(self) -> None:
        self.create: ExternalChannelConnectionCreate | None = None
        self.configuration: ExternalChannelConnectionConfiguration | None = None
        self.health_status: ExternalChannelConnectionStatus | None = None
        self.health_tenant_id: str | None = None
        self.health_bot_user_id: str | None = None
        self.health_capabilities: dict[str, object] | None = None
        self.health_expected_encrypted_credentials: str | None = None
        self.health_expected_configuration_generation: int | None = None
        self.apply_health_update = True
        self.connection_exists = True
        self.active_operation = False

    async def create_connection(
        self,
        *,
        create: ExternalChannelConnectionCreate,
    ) -> ExternalChannelConnection:
        assert not self.active_operation
        self.active_operation = True
        try:
            self.create = create
            return _connection_from_create(create)
        finally:
            self.active_operation = False

    async def load_connection_configuration(
        self,
        *,
        workspace_id: str,
        connection_id: str,
    ) -> ExternalChannelConnectionConfiguration | None:
        del connection_id
        assert not self.active_operation
        self.active_operation = True
        try:
            if (
                self.configuration is None
                or self.configuration.workspace_id != workspace_id
            ):
                return None
            return self.configuration
        finally:
            self.active_operation = False

    async def update_connection_health(
        self,
        *,
        connection_id: str,
        status: ExternalChannelConnectionStatus,
        provider_tenant_id: str | None,
        provider_bot_user_id: str | None,
        capabilities: dict[str, object] | None,
        checked_at: datetime.datetime,
        expected_encrypted_credentials: str,
        expected_configuration_generation: int,
    ) -> ExternalChannelConnectionHealthUpdate:
        del connection_id
        assert self.configuration is not None
        assert not self.active_operation
        self.active_operation = True
        try:
            self.health_expected_encrypted_credentials = expected_encrypted_credentials
            self.health_expected_configuration_generation = (
                expected_configuration_generation
            )
            if not self.apply_health_update:
                return ExternalChannelConnectionHealthUpdate(
                    connection=None,
                    connection_exists=self.connection_exists,
                )
            self.health_status = status
            self.health_tenant_id = provider_tenant_id
            self.health_bot_user_id = provider_bot_user_id
            self.health_capabilities = capabilities
            tenant_id = provider_tenant_id or self.configuration.provider_tenant_id
            bot_user_id = (
                provider_bot_user_id or self.configuration.provider_bot_user_id
            )
            return ExternalChannelConnectionHealthUpdate(
                connection=ExternalChannelConnection(
                    id=self.configuration.id,
                    workspace_id=self.configuration.workspace_id,
                    provider=self.configuration.provider,
                    transport=self.configuration.transport,
                    ingress_profile=self.configuration.ingress_profile,
                    configuration_generation=(
                        self.configuration.configuration_generation
                    ),
                    status=status,
                    app_mode=self.configuration.app_mode,
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
                    socket_lease_owner=self.configuration.socket_lease_owner,
                    socket_lease_until=self.configuration.socket_lease_until,
                    socket_heartbeat_at=self.configuration.socket_heartbeat_at,
                    socket_gap_detected_at=(self.configuration.socket_gap_detected_at),
                    socket_gap_reason=self.configuration.socket_gap_reason,
                    created_at=self.configuration.created_at,
                    updated_at=checked_at,
                ),
                connection_exists=True,
            )
        finally:
            self.active_operation = False


class _SlackClientDouble:
    """Return one configured sanitized Slack validation result."""

    def __init__(
        self,
        result: SlackConnectionValidation,
        repository: _ConnectionRepositoryDouble,
    ) -> None:
        self.result = result
        self.repository = repository
        self.bot_tokens: list[str] = []

    async def validate_connection(
        self,
        *,
        bot_token: str,
        app_id: str,
        transport: ExternalChannelTransport,
    ) -> SlackConnectionValidation:
        assert not self.repository.active_operation
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
        ingress_profile=create.ingress_profile,
        configuration_generation=create.configuration_generation,
        status=create.status,
        app_mode=create.app_mode,
        provider_app_id=create.provider_app_id,
        provider_tenant_id=create.provider_tenant_id,
        provider_bot_user_id=create.provider_bot_user_id,
        http_callback_selector_hash=create.http_callback_selector_hash,
        capabilities=create.capabilities,
        provider_config=create.provider_config,
        last_verified_at=create.last_verified_at,
        last_health_at=create.last_health_at,
        last_health_code=create.last_health_code,
        disconnected_at=create.disconnected_at,
        socket_lease_owner=create.socket_lease_owner,
        socket_lease_until=create.socket_lease_until,
        socket_heartbeat_at=create.socket_heartbeat_at,
        socket_gap_detected_at=create.socket_gap_detected_at,
        socket_gap_reason=create.socket_gap_reason,
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
        ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
        configuration_generation=7,
        app_mode=ExternalChannelAppMode.SINGLE,
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
        socket_lease_owner=None,
        socket_lease_until=None,
        socket_heartbeat_at=None,
        socket_gap_detected_at=None,
        socket_gap_reason=None,
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
    repository: _ConnectionRepositoryDouble,
    codec: ExternalChannelCredentialsCodec,
    slack_client: _SlackClientDouble,
) -> ExternalChannelConnectionService:
    return ExternalChannelConnectionService(
        connection_repository=repository,
        credentials_codec=codec,
        slack_client=MagicMock(spec=SlackWebAPIClient, wraps=slack_client),
    )


@pytest.fixture
def codec() -> ExternalChannelCredentialsCodec:
    """Return a real encrypted credential codec."""
    return ExternalChannelCredentialsCodec(
        CredentialCipher(Fernet.generate_key().decode())
    )


@pytest.mark.asyncio
async def test_http_setup_uses_fixed_callback_and_encrypts_credentials(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """Persist no selector while keeping provider credentials encrypted."""
    repository = _ConnectionRepositoryDouble()
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
            ),
            repository,
        ),
    )

    setup = await service.create_slack_connection(
        workspace_id="workspace-1",
        app_id="A-1",
        transport=ExternalChannelTransport.HTTP,
        credentials=_credentials(),
    )

    assert setup.connection.id == "connection-1"
    assert repository.create is not None
    assert repository.create.http_callback_selector_hash is None
    assert "xoxb-secret" not in repr(repository.create)
    assert repository.create.encrypted_credentials is not None
    assert not repository.active_operation


@pytest.mark.asyncio
async def test_discord_setup_uses_fixed_gateway_http_ingress_and_redacts_token(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """Persist Discord Guild configuration without treating it as tenant identity."""
    repository = _ConnectionRepositoryDouble()
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
            ),
            repository,
        ),
    )

    await service.create_discord_connection(
        workspace_id="workspace-1",
        app_id="discord-app-1",
        configuration=DiscordConnectionConfiguration(
            target_guild_id="guild-1",
            suppress_url_previews=True,
            thread_auto_archive_duration_minutes=1440,
        ),
        credentials=DiscordConnectionCredentials(bot_token="discord-bot-token"),
        app_mode=ExternalChannelAppMode.MULTI,
    )

    assert repository.create is not None
    assert repository.create.provider is ExternalChannelProvider.DISCORD
    assert repository.create.transport is ExternalChannelTransport.HTTP
    assert (
        repository.create.ingress_profile
        is ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
    )
    assert repository.create.app_mode is ExternalChannelAppMode.MULTI
    assert repository.create.provider_tenant_id is None
    assert repository.create.provider_config == {
        "provider": "discord",
        "target_guild_id": "guild-1",
        "suppress_url_previews": True,
        "thread_auto_archive_duration_minutes": 1440,
    }
    assert "discord-bot-token" not in repr(repository.create)
    assert not repository.active_operation


@pytest.mark.asyncio
async def test_valid_connection_activation_persists_identity_after_completed_read(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """Call the provider only after the completed configuration operation ends."""
    capabilities = ExternalChannelCapabilitySnapshot(
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        inbound_events=True,
        thread_history=True,
        post_messages=True,
        update_messages=True,
        delete_messages=True,
        download_files=True,
        upload_files=False,
    )
    repository = _ConnectionRepositoryDouble()
    repository.configuration = _configuration(codec)
    slack_client = _SlackClientDouble(
        SlackConnectionValidation(
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
            customize_messages=True,
        ),
        repository,
    )
    service = _service(
        repository=repository,
        codec=codec,
        slack_client=slack_client,
    )

    snapshot = await service.validate_connection(
        workspace_id="workspace-1",
        connection_id="connection-1",
    )

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
    assert repository.health_capabilities is not None
    assert repository.health_capabilities["customize_messages"] is True
    assert snapshot.capabilities is not None
    assert "customize_messages" not in snapshot.capabilities.model_dump()
    assert repository.configuration is not None
    assert repository.health_expected_encrypted_credentials == (
        repository.configuration.encrypted_credentials
    )
    assert repository.health_expected_configuration_generation == 7
    assert slack_client.bot_tokens == ["xoxb-secret"]
    assert "xoxb-secret" not in repr(snapshot)
    assert not repository.active_operation


@pytest.mark.asyncio
async def test_validation_hides_connection_in_another_workspace(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """Treat a cross-Workspace connection as absent before provider validation."""
    repository = _ConnectionRepositoryDouble()
    repository.configuration = _configuration(codec)
    slack_client = _SlackClientDouble(
        SlackConnectionValidation(
            status="valid",
            code=None,
            message=None,
            action_hint=None,
            identity=None,
            capabilities=None,
        ),
        repository,
    )
    service = _service(
        repository=repository,
        codec=codec,
        slack_client=slack_client,
    )

    with pytest.raises(ExternalChannelConnectionNotFound):
        await service.validate_connection(
            workspace_id="workspace-2",
            connection_id="connection-1",
        )

    assert slack_client.bot_tokens == []


def test_legacy_capability_snapshot_defaults_file_directions_to_unavailable() -> None:
    """Existing stored capability JSON remains readable after file fields are added."""
    connection = _connection_from_create(
        ExternalChannelConnectionCreate(
            workspace_id="workspace-1",
            provider=ExternalChannelProvider.SLACK,
            transport=ExternalChannelTransport.HTTP,
            app_mode=ExternalChannelAppMode.SINGLE,
            status=ExternalChannelConnectionStatus.ACTIVE,
            provider_app_id="A-1",
            provider_tenant_id="T-1",
            provider_bot_user_id="B-1",
            http_callback_selector_hash=None,
            encrypted_credentials="encrypted",
            capabilities={
                "provider": "slack",
                "transport": "http",
                "inbound_events": True,
                "thread_history": True,
                "post_messages": True,
                "update_messages": True,
                "delete_messages": True,
            },
            provider_config=None,
            last_verified_at=_NOW,
            last_health_at=_NOW,
            disconnected_at=None,
            socket_lease_owner=None,
            socket_lease_until=None,
            socket_heartbeat_at=None,
            socket_gap_detected_at=None,
            socket_gap_reason=None,
        )
    )

    capabilities = external_channel_capabilities_from_storage(connection)

    assert capabilities is not None
    assert capabilities.download_files is False
    assert capabilities.upload_files is False
    assert connection.capabilities is not None
    assert "download_files" not in connection.capabilities
    assert "upload_files" not in connection.capabilities


@pytest.mark.asyncio
async def test_stale_generation_validation_cannot_overwrite_newer_connection_state(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """Reject a provider result when the connection changed during validation."""
    repository = _ConnectionRepositoryDouble()
    repository.configuration = _configuration(codec)
    repository.apply_health_update = False
    service = _service(
        repository=repository,
        codec=codec,
        slack_client=_SlackClientDouble(
            SlackConnectionValidation(
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
                capabilities=None,
            ),
            repository,
        ),
    )

    with pytest.raises(
        ExternalChannelConnectionStateChanged,
        match="changed during validation",
    ):
        await service.validate_connection(
            workspace_id="workspace-1",
            connection_id="connection-1",
        )

    assert repository.configuration is not None
    assert repository.health_expected_encrypted_credentials == (
        repository.configuration.encrypted_credentials
    )
    assert repository.health_expected_configuration_generation == 7
