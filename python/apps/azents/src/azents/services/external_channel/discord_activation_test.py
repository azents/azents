"""Discord callback activation tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.crypto import CredentialCipher
from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnection,
    ExternalChannelConnectionConfiguration,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.data import (
    DiscordConnectionCredentials,
    ExternalChannelCapabilitySnapshot,
)
from azents.services.external_channel.discord_activation import (
    DiscordConnectionActivationService,
)
from azents.services.external_channel.discord_api import (
    DiscordAPIClient,
    DiscordAPIConfigurationInvalid,
    DiscordAPIError,
    DiscordAPIUnavailable,
    DiscordApplicationMetadata,
    DiscordGuildCommandRole,
    DiscordGuildCommandSetCapability,
)

_NOW = datetime.datetime(2026, 7, 26, 1, 0, tzinfo=datetime.UTC)


class _SessionDouble:
    """Record durable activation transactions."""

    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def commit(self) -> None:
        self.events.append("commit")


class _RepositoryDouble:
    """Capture authority mutation inputs without persisting secrets."""

    def __init__(
        self,
        *,
        configuration: ExternalChannelConnectionConfiguration,
        events: list[str],
        activate_result: ExternalChannelConnection | None,
    ) -> None:
        self.configuration = configuration
        self.events = events
        self.activate_result = activate_result
        self.activation_kwargs: dict[str, object] | None = None
        self.prepare_kwargs: dict[str, object] | None = None
        self.clear_kwargs: dict[str, object] | None = None
        self.failure_kwargs: dict[str, object] | None = None

    async def get_connection_configuration(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnectionConfiguration:
        del session
        assert connection_id == self.configuration.id
        self.events.append("load")
        return self.configuration

    async def activate_discord_connection(
        self,
        session: AsyncSession,
        **kwargs: object,
    ) -> ExternalChannelConnection | None:
        del session
        self.events.append("activate")
        self.activation_kwargs = kwargs
        return self.activate_result

    async def prepare_discord_callback(
        self,
        session: AsyncSession,
        **kwargs: object,
    ) -> bool:
        """Record durable PING verification preparation."""
        del session
        self.events.append("prepare")
        self.prepare_kwargs = kwargs
        return True

    async def clear_prepared_discord_callback(
        self,
        session: AsyncSession,
        **kwargs: object,
    ) -> bool:
        """Record provisional callback cleanup without retaining its selector."""
        del session
        self.events.append("clear")
        self.clear_kwargs = kwargs
        return True

    async def record_discord_activation_failure(
        self,
        session: AsyncSession,
        **kwargs: object,
    ) -> ExternalChannelConnection:
        """Record the safe durable reason without exposing credentials."""
        del session
        self.events.append("failure")
        self.failure_kwargs = kwargs
        return ExternalChannelConnection.model_validate(
            self.configuration.model_dump()
            | {
                "status": ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
                "last_health_at": _NOW,
                "last_health_code": kwargs["failure_code"],
            }
        )


class _DiscordClientDouble:
    """Capture provider calls in their required order."""

    def __init__(
        self,
        events: list[str],
        *,
        fail_endpoint: bool = False,
        command_error: DiscordAPIError | None = None,
    ) -> None:
        self.events = events
        self.fail_endpoint = fail_endpoint
        self.command_error = command_error
        self.endpoint_url: str | None = None

    async def get_current_application(
        self,
        *,
        bot_token: str,
    ) -> DiscordApplicationMetadata:
        assert bot_token == "discord-bot-token"
        self.events.append("metadata")
        return DiscordApplicationMetadata(application_id="app-1", verify_key="ab" * 32)

    async def get_current_bot_user_id(self, *, bot_token: str) -> str:
        assert bot_token == "discord-bot-token"
        self.events.append("bot")
        return "bot-1"

    async def configure_interactions_endpoint(
        self,
        *,
        bot_token: str,
        application_id: str,
        endpoint_url: str,
    ) -> None:
        assert bot_token == "discord-bot-token"
        assert application_id == "app-1"
        self.events.append("endpoint")
        self.endpoint_url = endpoint_url
        if self.fail_endpoint:
            raise DiscordAPIUnavailable

    async def reconcile_required_guild_commands(
        self,
        *,
        bot_token: str,
        application_id: str,
        guild_id: str,
    ) -> DiscordGuildCommandSetCapability:
        assert bot_token == "discord-bot-token"
        assert application_id == "app-1"
        assert guild_id == "guild-1"
        self.events.append("command")
        if self.command_error is not None:
            raise self.command_error
        return DiscordGuildCommandSetCapability(
            schema_version=1,
            command_ids={
                DiscordGuildCommandRole.MESSAGE_ACTION: "101",
                DiscordGuildCommandRole.AZENTS_SETTINGS: "102",
                DiscordGuildCommandRole.CONVERSATION_SETTINGS: "103",
            },
        )


def _configuration(
    codec: ExternalChannelCredentialsCodec,
) -> ExternalChannelConnectionConfiguration:
    return ExternalChannelConnectionConfiguration(
        id="connection-1",
        workspace_id="workspace-1",
        provider=ExternalChannelProvider.DISCORD,
        transport=ExternalChannelTransport.HTTP,
        ingress_profile=ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
        configuration_generation=1,
        status=ExternalChannelConnectionStatus.CONFIGURING,
        app_mode=ExternalChannelAppMode.SINGLE,
        provider_app_id="app-1",
        provider_tenant_id=None,
        provider_bot_user_id=None,
        http_callback_selector_hash=None,
        encrypted_credentials=codec.encrypt(
            DiscordConnectionCredentials(bot_token="discord-bot-token")
        ),
        capabilities=None,
        provider_config={"target_guild_id": "guild-1"},
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


def _active_connection(
    configuration: ExternalChannelConnectionConfiguration,
) -> ExternalChannelConnection:
    capabilities = ExternalChannelCapabilitySnapshot(
        provider=ExternalChannelProvider.DISCORD,
        transport=ExternalChannelTransport.HTTP,
        inbound_events=True,
        thread_history=True,
        post_messages=True,
        update_messages=True,
        delete_messages=True,
        download_files=True,
        upload_files=True,
    )
    return ExternalChannelConnection.model_validate(
        configuration.model_dump()
        | {
            "status": ExternalChannelConnectionStatus.ACTIVE,
            "provider_tenant_id": "guild-1",
            "provider_bot_user_id": "bot-1",
            "http_callback_selector_hash": "selector-hash",
            "capabilities": capabilities.model_dump(mode="json")
            | {
                "interaction_public_key": "ab" * 32,
                "discord_command_set": {
                    "schema_version": 1,
                    "command_ids": {
                        DiscordGuildCommandRole.MESSAGE_ACTION: "101",
                        DiscordGuildCommandRole.AZENTS_SETTINGS: "102",
                        DiscordGuildCommandRole.CONVERSATION_SETTINGS: "103",
                    },
                },
            },
            "last_verified_at": _NOW,
            "last_health_at": _NOW,
        }
    )


def _service(
    *,
    callback_url: str,
    repository: _RepositoryDouble,
    codec: ExternalChannelCredentialsCodec,
    client: _DiscordClientDouble,
    events: list[str],
) -> DiscordConnectionActivationService:
    session = _SessionDouble(events)

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, session)

    return DiscordConnectionActivationService(
        config=cast(
            Config,
            SimpleNamespace(external_channel_discord_callback_url=callback_url),
        ),
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        repository=cast(ExternalChannelRepository, repository),
        credentials_codec=codec,
        discord_client=cast(DiscordAPIClient, client),
    )


@pytest.fixture
def codec() -> ExternalChannelCredentialsCodec:
    """Return a real encrypted credential codec."""
    return ExternalChannelCredentialsCodec(
        CredentialCipher(Fernet.generate_key().decode())
    )


@pytest.mark.asyncio
async def test_missing_callback_url_fails_before_repository_or_provider_io(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """An unconfigured callback base cannot activate durable ingress."""
    configuration = _configuration(codec)
    events: list[str] = []
    repository = _RepositoryDouble(
        configuration=configuration,
        events=events,
        activate_result=_active_connection(configuration),
    )
    service = _service(
        callback_url="",
        repository=repository,
        codec=codec,
        client=_DiscordClientDouble(events),
        events=events,
    )

    snapshot = await service.activate(connection_id=configuration.id)

    assert snapshot.status is ExternalChannelConnectionStatus.RECONNECT_REQUIRED
    assert snapshot.code == "discord_callback_url_missing"
    assert events == ["load", "failure", "commit"]
    assert repository.failure_kwargs is not None
    assert repository.failure_kwargs["failure_code"] == "discord_callback_url_missing"


@pytest.mark.asyncio
async def test_activation_prepares_callback_before_provider_validation(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """Only the selector hash reaches the durable activation mutation."""
    configuration = _configuration(codec)
    events: list[str] = []
    repository = _RepositoryDouble(
        configuration=configuration,
        events=events,
        activate_result=_active_connection(configuration),
    )
    client = _DiscordClientDouble(events)
    service = _service(
        callback_url="https://callbacks.example/",
        repository=repository,
        codec=codec,
        client=client,
        events=events,
    )

    snapshot = await service.activate(connection_id=configuration.id)

    assert events == [
        "load",
        "metadata",
        "bot",
        "prepare",
        "commit",
        "endpoint",
        "command",
        "activate",
        "commit",
    ]
    assert snapshot.status is ExternalChannelConnectionStatus.ACTIVE
    assert snapshot.identity is not None
    assert snapshot.identity.app_id == "app-1"
    assert client.endpoint_url is not None
    assert client.endpoint_url.startswith(
        "https://callbacks.example/external-channel/v1/discord/interactions/"
    )
    assert repository.activation_kwargs is not None
    assert repository.activation_kwargs["provider_bot_user_id"] == "bot-1"
    assert repository.activation_kwargs["command_set"] == {
        "schema_version": 1,
        "command_ids": {
            "message_action": "101",
            "azents_settings": "102",
            "conversation_settings": "103",
        },
    }
    assert repository.activation_kwargs["capabilities"] == {
        "provider": ExternalChannelProvider.DISCORD.value,
        "transport": ExternalChannelTransport.HTTP.value,
        "inbound_events": True,
        "thread_history": True,
        "post_messages": True,
        "update_messages": True,
        "delete_messages": True,
        "download_files": True,
        "upload_files": True,
    }
    assert snapshot.capabilities is not None
    assert snapshot.capabilities.download_files is True
    assert snapshot.capabilities.upload_files is True
    selector_hash = repository.activation_kwargs["callback_selector_hash"]
    assert isinstance(selector_hash, str)
    assert len(selector_hash) == 64
    assert repository.prepare_kwargs is not None
    assert repository.prepare_kwargs["callback_selector_hash"] == selector_hash
    assert client.endpoint_url.rsplit("/", maxsplit=1)[1] not in repr(
        repository.activation_kwargs
    )


@pytest.mark.asyncio
async def test_provider_endpoint_failure_does_not_activate(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """A provider configuration error leaves the connection configuring."""
    configuration = _configuration(codec)
    events: list[str] = []
    repository = _RepositoryDouble(
        configuration=configuration,
        events=events,
        activate_result=_active_connection(configuration),
    )
    service = _service(
        callback_url="https://callbacks.example",
        repository=repository,
        codec=codec,
        client=_DiscordClientDouble(events, fail_endpoint=True),
        events=events,
    )

    snapshot = await service.activate(connection_id=configuration.id)

    assert snapshot.status is ExternalChannelConnectionStatus.RECONNECT_REQUIRED
    assert snapshot.code == "discord_api_unavailable"
    assert events == [
        "load",
        "metadata",
        "bot",
        "prepare",
        "commit",
        "endpoint",
        "clear",
        "commit",
        "failure",
        "commit",
    ]
    assert repository.failure_kwargs is not None
    assert repository.failure_kwargs["failure_code"] == "discord_api_unavailable"
    assert repository.activation_kwargs is None
    assert repository.prepare_kwargs is not None
    assert repository.clear_kwargs is not None
    assert (
        repository.clear_kwargs["callback_selector_hash"]
        == repository.prepare_kwargs["callback_selector_hash"]
    )


@pytest.mark.asyncio
async def test_provider_message_command_failure_does_not_activate(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """A required Message Command failure clears provisional callback authority."""
    configuration = _configuration(codec)
    events: list[str] = []
    repository = _RepositoryDouble(
        configuration=configuration,
        events=events,
        activate_result=_active_connection(configuration),
    )
    service = _service(
        callback_url="https://callbacks.example",
        repository=repository,
        codec=codec,
        client=_DiscordClientDouble(
            events,
            command_error=DiscordAPIUnavailable(),
        ),
        events=events,
    )

    snapshot = await service.activate(connection_id=configuration.id)

    assert snapshot.status is ExternalChannelConnectionStatus.RECONNECT_REQUIRED
    assert snapshot.code == "discord_api_unavailable"
    assert events == [
        "load",
        "metadata",
        "bot",
        "prepare",
        "commit",
        "endpoint",
        "command",
        "clear",
        "commit",
        "failure",
        "commit",
    ]
    assert repository.activation_kwargs is None
    assert repository.clear_kwargs is not None


@pytest.mark.asyncio
async def test_invalid_command_set_failure_clears_provisional_callback(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """A command-set proof failure cannot leave callback authority configured."""
    configuration = _configuration(codec)
    events: list[str] = []
    repository = _RepositoryDouble(
        configuration=configuration,
        events=events,
        activate_result=_active_connection(configuration),
    )
    service = _service(
        callback_url="https://callbacks.example",
        repository=repository,
        codec=codec,
        client=_DiscordClientDouble(
            events,
            command_error=DiscordAPIConfigurationInvalid(),
        ),
        events=events,
    )

    snapshot = await service.activate(connection_id=configuration.id)

    assert snapshot.status is ExternalChannelConnectionStatus.RECONNECT_REQUIRED
    assert snapshot.code == "discord_callback_configuration_invalid"
    assert repository.activation_kwargs is None
    assert repository.clear_kwargs is not None


@pytest.mark.asyncio
async def test_lost_activation_fence_is_reported_without_commit(
    codec: ExternalChannelCredentialsCodec,
) -> None:
    """A credential or configuration race cannot silently activate stale authority."""
    configuration = _configuration(codec)
    events: list[str] = []
    repository = _RepositoryDouble(
        configuration=configuration,
        events=events,
        activate_result=None,
    )
    service = _service(
        callback_url="https://callbacks.example",
        repository=repository,
        codec=codec,
        client=_DiscordClientDouble(events),
        events=events,
    )

    snapshot = await service.activate(connection_id=configuration.id)

    assert snapshot.status is ExternalChannelConnectionStatus.RECONNECT_REQUIRED
    assert snapshot.code == "discord_authority_changed"
    assert events == [
        "load",
        "metadata",
        "bot",
        "prepare",
        "commit",
        "endpoint",
        "command",
        "activate",
        "clear",
        "commit",
        "failure",
        "commit",
    ]
    assert repository.failure_kwargs is not None
    assert repository.failure_kwargs["failure_code"] == "discord_authority_changed"
