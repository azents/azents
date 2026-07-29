"""Deterministic tests for typed discord.py lease-fenced admission."""

import asyncio
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from azcommon.di import Container
from cryptography.fernet import InvalidToken

from azents.core.config import Config
from azents.core.deps import get_config
from azents.rdb.deps import get_session_manager
from azents.repos.external_channel.data import (
    ExternalChannelEventCreate,
    ExternalChannelIngressLease,
    ExternalChannelIngressLeaseClaim,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.data import DiscordConnectionCredentials
from azents.services.external_channel.discord_gateway import (
    DiscordGatewayConnectionResult,
    DiscordGatewayError,
    DiscordGatewayEventHandler,
    DiscordGatewayIntentsError,
    DiscordGatewayMessageEvent,
)
from azents.services.external_channel.discord_gateway_manager import (
    DiscordGatewayLeaseLost,
    DiscordGatewayManagerService,
)


class _SessionManager:
    """Yield one mock session without database I/O."""

    def __init__(self) -> None:
        self.session = MagicMock()
        self.session.commit = AsyncMock()

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[MagicMock]:
        yield self.session


class _Repository:
    """Capture lease-fenced Discord admission and lifecycle calls."""

    def __init__(self, admission: object | None = None) -> None:
        self.admission = admission
        self.admission_calls: list[dict[str, object]] = []
        self.reconnect_calls: list[dict[str, object]] = []
        self.gap_calls: list[dict[str, object]] = []
        self.release_calls: list[dict[str, object]] = []
        self.renew_calls: list[dict[str, object]] = []

    async def admit_discord_gateway_event(
        self,
        _session: object,
        **kwargs: object,
    ) -> object | None:
        self.admission_calls.append(kwargs)
        return self.admission

    async def mark_discord_gateway_reconnect_required(
        self,
        _session: object,
        **kwargs: object,
    ) -> bool:
        self.reconnect_calls.append(kwargs)
        return True

    async def record_discord_gateway_gap(
        self,
        _session: object,
        **kwargs: object,
    ) -> bool:
        self.gap_calls.append(kwargs)
        return True

    async def release_discord_gateway_lease(
        self,
        _session: object,
        **kwargs: object,
    ) -> bool:
        self.release_calls.append(kwargs)
        return True

    async def renew_discord_gateway_lease(
        self,
        _session: object,
        **kwargs: object,
    ) -> bool:
        self.renew_calls.append(kwargs)
        return True


class _OwnedRepository(_Repository):
    """Return one owned Discord connection for manager lifecycle tests."""

    async def claim_discord_gateway_lease(
        self,
        _session: object,
        **_kwargs: object,
    ) -> ExternalChannelIngressLeaseClaim:
        return ExternalChannelIngressLeaseClaim(lease=_lease())

    async def get_owned_discord_gateway_configuration(
        self,
        _session: object,
        **_kwargs: object,
    ) -> MagicMock:
        return MagicMock(
            encrypted_credentials="ciphertext",
            provider_app_id="app-1",
            provider_tenant_id="300",
        )


class _IntentsFailureRunner:
    """Surface one public SDK privileged-intent rejection."""

    async def run_connection(
        self,
        **_kwargs: object,
    ) -> DiscordGatewayConnectionResult:
        raise DiscordGatewayIntentsError("rejected")


class _EventRunner:
    """Exercise the manager callback with one typed SDK event."""

    def __init__(self) -> None:
        self.bot_token: str | None = None
        self.target_guild_id: str | None = None

    async def run_connection(
        self,
        *,
        bot_token: str,
        target_guild_id: str,
        handle_event: DiscordGatewayEventHandler,
    ) -> DiscordGatewayConnectionResult:
        self.bot_token = bot_token
        self.target_guild_id = target_guild_id
        await handle_event(_event())
        return DiscordGatewayConnectionResult(
            reconnect=False,
            reason="gateway_client_closed",
        )


def _lease() -> ExternalChannelIngressLease:
    return ExternalChannelIngressLease(
        id="lease-1",
        connection_id="connection-1",
        lease_owner="manager-1",
        lease_generation=3,
        lease_until=datetime.datetime(2026, 7, 28, 1, tzinfo=datetime.UTC),
        heartbeat_at=datetime.datetime(2026, 7, 28, tzinfo=datetime.UTC),
        required_configuration_generation=2,
        required_app_claim_generation=4,
        gap_detected_at=None,
        gap_reason=None,
        created_at=datetime.datetime(2026, 7, 28, tzinfo=datetime.UTC),
        updated_at=datetime.datetime(2026, 7, 28, tzinfo=datetime.UTC),
    )


def _event(
    *,
    guild_id: int = 300,
    event_type: Literal["message_create", "message_update", "message_delete"] = (
        "message_create"
    ),
) -> DiscordGatewayMessageEvent:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 200
    channel.guild = guild
    channel.name = "general"
    author = MagicMock(spec=discord.User)
    author.id = 400
    author.name = "participant"
    author.global_name = None
    author.bot = False
    author.system = False
    message = MagicMock(spec=discord.Message)
    message.id = 100
    message.guild = guild
    message.channel = channel
    message.content = "Hello"
    message.created_at = datetime.datetime(2026, 7, 28, tzinfo=datetime.UTC)
    message.edited_at = None
    message.author = author
    message.mentions = []
    message.attachments = []
    return DiscordGatewayMessageEvent(
        event_type=event_type,
        channel=channel,
        message=message,
    )


def _service(
    *,
    repository: _Repository,
    sessions: _SessionManager,
    gateway_client: object | None = None,
    credentials_codec: object | None = None,
    config: Config | None = None,
) -> DiscordGatewayManagerService:
    return DiscordGatewayManagerService(
        session_manager=sessions,
        repository=repository,  # type: ignore[arg-type]
        credentials_codec=(
            credentials_codec if credentials_codec is not None else MagicMock()
        ),
        manager_id="manager-1",
        gateway_client=(gateway_client if gateway_client is not None else MagicMock()),
        config=config,
    )


def _mock_dependency() -> MagicMock:
    return MagicMock()


def _test_session_manager() -> _SessionManager:
    return _SessionManager()


@pytest.mark.asyncio
async def test_gateway_manager_dependency_graph_is_resolvable() -> None:
    """The worker resolves the discord.py-backed manager through DI."""
    config = MagicMock()
    config.external_channel_conversation.quiesce.discord_gateway = False
    overrides = {
        get_session_manager: _test_session_manager,
        get_config: lambda: config,
        ExternalChannelRepository: _mock_dependency,
        get_external_channel_credentials_codec: _mock_dependency,
    }
    async with Container(dependency_overrides=overrides) as container:
        service = await container.solve(DiscordGatewayManagerService)

    assert service.gateway_client is not None


@pytest.mark.asyncio
async def test_admits_typed_event_under_current_lease() -> None:
    """A typed SDK message commits under the current lease fence."""
    sessions = _SessionManager()
    repository = _Repository(admission=object())
    service = _service(repository=repository, sessions=sessions)

    await service._admit_gateway_event(  # pyright: ignore[reportPrivateUsage]
        connection_id="connection-1",
        lease=_lease(),
        provider_app_id="app-1",
        target_guild_id="300",
        event=_event(),
    )

    call = repository.admission_calls[0]
    assert call["connection_id"] == "connection-1"
    assert call["lease_generation"] == 3
    assert "sequence" not in call
    assert "encrypted_checkpoint" not in call
    create = call["create"]
    assert isinstance(create, ExternalChannelEventCreate)
    assert create.provider_event_id == "discord:discord_message_create:300:200:100"
    sessions.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_quiesced_gateway_rejects_message_create_before_legacy_admission() -> (
    None
):
    """Quiesce blocks normal message ingress without changing the legacy owner."""
    sessions = _SessionManager()
    repository = _Repository(admission=object())
    config = MagicMock()
    config.external_channel_conversation.quiesce.discord_gateway = True
    service = _service(repository=repository, sessions=sessions, config=config)

    with pytest.raises(DiscordGatewayError, match="temporarily quiesced"):
        await service._admit_gateway_event(  # pyright: ignore[reportPrivateUsage]
            connection_id="connection-1",
            lease=_lease(),
            provider_app_id="app-1",
            target_guild_id="300",
            event=_event(),
        )

    assert repository.admission_calls == []
    sessions.session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_quiesced_gateway_keeps_message_update_lifecycle_available() -> None:
    """Quiesce does not disable lifecycle callbacks owned by the legacy path."""
    sessions = _SessionManager()
    repository = _Repository(admission=object())
    config = MagicMock()
    config.external_channel_conversation.quiesce.discord_gateway = True
    service = _service(repository=repository, sessions=sessions, config=config)

    await service._admit_gateway_event(  # pyright: ignore[reportPrivateUsage]
        connection_id="connection-1",
        lease=_lease(),
        provider_app_id="app-1",
        target_guild_id="300",
        event=_event(event_type="message_update"),
    )

    assert len(repository.admission_calls) == 1


@pytest.mark.asyncio
async def test_cross_guild_event_is_not_admitted() -> None:
    sessions = _SessionManager()
    repository = _Repository(admission=object())
    service = _service(repository=repository, sessions=sessions)

    await service._admit_gateway_event(  # pyright: ignore[reportPrivateUsage]
        connection_id="connection-1",
        lease=_lease(),
        provider_app_id="app-1",
        target_guild_id="300",
        event=_event(guild_id=301),
    )

    assert repository.admission_calls == []


@pytest.mark.asyncio
async def test_stale_lease_stops_typed_event_admission() -> None:
    sessions = _SessionManager()
    repository = _Repository(admission=None)
    service = _service(repository=repository, sessions=sessions)

    with pytest.raises(DiscordGatewayLeaseLost):
        await service._admit_gateway_event(  # pyright: ignore[reportPrivateUsage]
            connection_id="connection-1",
            lease=_lease(),
            provider_app_id="app-1",
            target_guild_id="300",
            event=_event(),
        )

    sessions.session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_persisted_credential_terminalizes_connection() -> None:
    sessions = _SessionManager()
    repository = _OwnedRepository()
    credentials_codec = MagicMock()
    credentials_codec.decrypt.side_effect = InvalidToken
    service = _service(
        repository=repository,
        sessions=sessions,
        credentials_codec=credentials_codec,
    )

    await service._run_owned_connection(  # pyright: ignore[reportPrivateUsage]
        connection_id="connection-1",
        shutdown_event=asyncio.Event(),
    )

    assert repository.reconnect_calls[0]["reason"] == "gateway_credentials_invalid"
    assert repository.release_calls == []


@pytest.mark.asyncio
async def test_library_intent_rejection_terminalizes_connection() -> None:
    sessions = _SessionManager()
    repository = _OwnedRepository()
    credentials_codec = MagicMock()
    credentials_codec.decrypt.return_value = DiscordConnectionCredentials(
        bot_token="test-token"
    )
    service = _service(
        repository=repository,
        sessions=sessions,
        credentials_codec=credentials_codec,
        gateway_client=_IntentsFailureRunner(),
    )

    await service._run_owned_connection(  # pyright: ignore[reportPrivateUsage]
        connection_id="connection-1",
        shutdown_event=asyncio.Event(),
    )

    assert repository.reconnect_calls[0]["reason"] == "intents_disallowed"
    assert repository.release_calls == []


@pytest.mark.asyncio
async def test_manager_passes_typed_handler_and_target_guild_to_sdk() -> None:
    sessions = _SessionManager()
    repository = _Repository(admission=object())
    runner = _EventRunner()
    service = _service(
        repository=repository,
        sessions=sessions,
        gateway_client=runner,
    )

    result = await service._run_connection_with_lease(  # pyright: ignore[reportPrivateUsage]
        connection_id="connection-1",
        lease=_lease(),
        bot_token="test-token",
        provider_app_id="app-1",
        target_guild_id="300",
        shutdown_event=asyncio.Event(),
    )

    assert result == DiscordGatewayConnectionResult(
        reconnect=False,
        reason="gateway_client_closed",
    )
    assert runner.bot_token == "test-token"
    assert runner.target_guild_id == "300"
    assert len(repository.admission_calls) == 1


@pytest.mark.asyncio
async def test_reconnect_backoff_renews_gateway_lease() -> None:
    sessions = _SessionManager()
    repository = _Repository(admission=object())
    service = _service(repository=repository, sessions=sessions)
    service.renew_interval = datetime.timedelta(milliseconds=1)

    retained = await service._sleep_or_shutdown(  # pyright: ignore[reportPrivateUsage]
        asyncio.Event(),
        connection_id="connection-1",
        lease=_lease(),
        delay=datetime.timedelta(milliseconds=5),
    )

    assert retained is True
    assert repository.renew_calls


def test_rate_limit_reconnect_uses_bounded_library_backoff() -> None:
    service = _service(
        repository=_Repository(admission=object()),
        sessions=_SessionManager(),
    )

    assert service._reconnect_delay(  # pyright: ignore[reportPrivateUsage]
        reason="gateway_rate_limited",
        attempt=1,
    ) == datetime.timedelta(minutes=1)
    assert service._reconnect_delay(  # pyright: ignore[reportPrivateUsage]
        reason="gateway_rate_limited",
        attempt=10,
    ) == datetime.timedelta(minutes=5)
