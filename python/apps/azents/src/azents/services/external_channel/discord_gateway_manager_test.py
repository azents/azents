"""Deterministic tests for typed discord.py lease-fenced admission."""

import asyncio
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from azcommon.di import Container
from cryptography.fernet import InvalidToken

from azents.core.config import Config
from azents.core.deps import get_config
from azents.rdb.deps import get_session_manager
from azents.repos.external_channel.data import (
    ExternalChannelIngressLease,
    ExternalChannelIngressLeaseClaim,
    ExternalChannelTrigger,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.data import DiscordConnectionCredentials
from azents.services.external_channel.discord_gateway import (
    DiscordGatewayError,
    DiscordGatewayEventHandler,
    DiscordGatewayIntentsError,
    DiscordGatewayLifecycleHandler,
    DiscordGatewayMessageEvent,
    DiscordGatewayTerminalError,
)
from azents.services.external_channel.discord_gateway_manager import (
    DiscordGatewayLeaseLost,
    DiscordGatewayManagerService,
)
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
    ExternalChannelIngressAuthority,
)
from azents.services.external_channel.provider_control import (
    ExternalChannelProviderControlService,
    get_external_channel_provider_control_service,
)
from azents.services.external_channel.provider_effect import ProviderEffectPlan
from azents.services.external_channel.transport_ingestion import (
    ExternalChannelTransportIngestionService,
)
from azents.testing.external_channel import make_provider_effect_plan


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

    def __init__(
        self,
        admission: object | None = None,
        *,
        control_plans: tuple[ProviderEffectPlan, ...] = (),
    ) -> None:
        self.admission = admission
        self.control_plans = control_plans
        self.admission_calls: list[dict[str, object]] = []
        self.reconnect_calls: list[dict[str, object]] = []
        self.gap_calls: list[dict[str, object]] = []
        self.active_calls: list[dict[str, object]] = []
        self.release_calls: list[dict[str, object]] = []
        self.renew_calls: list[dict[str, object]] = []

    async def ingest_discord_event(
        self,
        **kwargs: object,
    ) -> ExternalChannelIngestionOutcome:
        self.admission_calls.append(kwargs)
        return ExternalChannelIngestionOutcome(
            kind=(
                ExternalChannelIngestionOutcomeKind.ACCEPTED
                if self.admission is not None
                else ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE
            ),
            reason=(
                ExternalChannelIngestionReason.ACCEPTED
                if self.admission is not None
                else ExternalChannelIngestionReason.HISTORY_UNAVAILABLE
            ),
            mailbox_item_id="batch-1" if self.admission is not None else None,
            control_plans=self.control_plans,
            connection_id="connection-1" if self.control_plans else None,
        )

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

    async def mark_discord_gateway_active(
        self,
        _session: object,
        **kwargs: object,
    ) -> bool:
        self.active_calls.append(kwargs)
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


class _RetryThenAcceptRepository(_Repository):
    """Return one transient ingestion result before accepting the same event."""

    async def ingest_discord_event(
        self,
        **kwargs: object,
    ) -> ExternalChannelIngestionOutcome:
        self.admission_calls.append(kwargs)
        if len(self.admission_calls) == 1:
            return ExternalChannelIngestionOutcome(
                kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
                reason=ExternalChannelIngestionReason.HISTORY_UNAVAILABLE,
                mailbox_item_id=None,
                control_plans=(),
                connection_id=None,
            )
        return ExternalChannelIngestionOutcome(
            kind=ExternalChannelIngestionOutcomeKind.ACCEPTED,
            reason=ExternalChannelIngestionReason.ACCEPTED,
            mailbox_item_id="batch-1",
            control_plans=(),
            connection_id=None,
        )


class _StaleAuthorityRepository(_Repository):
    """Return one fenced stale-authority outcome."""

    async def ingest_discord_event(
        self,
        **kwargs: object,
    ) -> ExternalChannelIngestionOutcome:
        self.admission_calls.append(kwargs)
        return ExternalChannelIngestionOutcome(
            kind=ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE,
            reason=ExternalChannelIngestionReason.INGRESS_AUTHORITY_STALE,
            mailbox_item_id=None,
            control_plans=(),
            connection_id=None,
        )


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
            provider_bot_user_id="900",
            configuration_generation=2,
        )


class _IntentsFailureRunner:
    """Surface one public SDK privileged-intent rejection."""

    async def run_connection(self, **_kwargs: object) -> None:
        raise DiscordGatewayIntentsError("rejected")


class _TerminalFailureRunner:
    """Surface one SDK-declared non-recoverable close."""

    async def run_connection(self, **_kwargs: object) -> None:
        raise DiscordGatewayTerminalError("gateway_connection_rejected")


class _EventRunner:
    """Exercise typed lifecycle and message callbacks before terminal exit."""

    def __init__(self) -> None:
        self.bot_token: str | None = None
        self.target_guild_id: str | None = None

    async def run_connection(
        self,
        *,
        bot_token: str,
        target_guild_id: str,
        handle_event: DiscordGatewayEventHandler,
        handle_lifecycle: DiscordGatewayLifecycleHandler,
    ) -> None:
        self.bot_token = bot_token
        self.target_guild_id = target_guild_id
        await handle_lifecycle("ready")
        await handle_event(_event())
        raise DiscordGatewayTerminalError("gateway_connection_rejected")


class _BlockingRunner:
    """Keep one SDK lifecycle active until manager cancellation."""

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run_connection(self, **_kwargs: object) -> None:
        self.started.set()
        await asyncio.Event().wait()


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


def _event(*, guild_id: int = 300) -> DiscordGatewayMessageEvent:
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
    message.role_mentions = []
    message.attachments = []
    return DiscordGatewayMessageEvent(
        event_type="message_create",
        channel=channel,
        message=message,
    )


def _service(
    *,
    repository: _Repository,
    sessions: _SessionManager,
    gateway_client: object | None = None,
    credentials_codec: object | None = None,
    provider_control: object | None = None,
    config: Config | None = None,
) -> DiscordGatewayManagerService:
    return DiscordGatewayManagerService(
        session_manager=sessions,
        repository=repository,  # ty: ignore[invalid-argument-type] — test fake exposes only the lease-fenced repository surface exercised by this manager.
        credentials_codec=(
            credentials_codec if credentials_codec is not None else MagicMock()
        ),  # ty: ignore[invalid-argument-type] — test fake supplies only the codec calls exercised by this manager.
        transport_ingestion_service=cast(
            ExternalChannelTransportIngestionService,
            repository,
        ),
        provider_control=cast(
            ExternalChannelProviderControlService,
            provider_control if provider_control is not None else MagicMock(),
        ),
        manager_id="manager-1",
        gateway_client=(gateway_client if gateway_client is not None else MagicMock()),  # ty: ignore[invalid-argument-type] — test fixture supplies the public runner methods exercised by the manager.
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
        ExternalChannelTransportIngestionService: _mock_dependency,
        get_external_channel_provider_control_service: _mock_dependency,
    }
    async with Container(
        dependency_overrides=overrides  # ty: ignore[invalid-argument-type] — dynamic DI override map intentionally substitutes narrow deterministic test fakes.
    ) as container:
        service = await container.solve(DiscordGatewayManagerService)

    assert service.gateway_client is not None


@pytest.mark.asyncio
async def test_admits_typed_event_under_current_lease() -> None:
    """A typed SDK message commits under the current lease fence."""
    sessions = _SessionManager()
    repository = _Repository(admission=object())
    service = _service(repository=repository, sessions=sessions)

    await service._admit_gateway_event(
        connection_id="connection-1",
        lease=_lease(),
        provider_app_id="app-1",
        target_guild_id="300",
        connected_bot_user_id="900",
        configuration_generation=2,
        event=_event(),
    )

    call = repository.admission_calls[0]
    authority = call["authority"]
    assert isinstance(authority, ExternalChannelIngressAuthority)
    assert authority.lease_generation == 3
    assert "sequence" not in call
    assert "encrypted_checkpoint" not in call
    create = call["event"]
    assert isinstance(create, ExternalChannelTrigger)
    assert create.connection_id == "connection-1"
    assert create.provider_event_id == "discord:discord_message_create:300:200:100"
    sessions.session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_gateway_schedules_every_control_without_waiting_for_completion() -> None:
    """Gateway admission settles while every committed control runs in background."""
    plans = (
        make_provider_effect_plan("gateway-presence"),
        make_provider_effect_plan("gateway-progress"),
    )
    repository = _Repository(admission=object(), control_plans=plans)
    release = asyncio.Event()

    async def attempt(_plan: object) -> None:
        await release.wait()

    provider_control = MagicMock()
    provider_control.attempt = AsyncMock(side_effect=attempt)
    service = _service(
        repository=repository,
        sessions=_SessionManager(),
        provider_control=provider_control,
    )

    await service._admit_gateway_event(
        connection_id="connection-1",
        lease=_lease(),
        provider_app_id="app-1",
        target_guild_id="300",
        connected_bot_user_id="900",
        configuration_generation=2,
        event=_event(),
    )
    await asyncio.sleep(0)

    assert [call.args[0] for call in provider_control.attempt.await_args_list] == list(
        plans
    )
    assert len(service.control_tasks) == 2
    release.set()
    await asyncio.gather(*tuple(service.control_tasks))
    await asyncio.sleep(0)
    assert service.control_tasks == set()


@pytest.mark.asyncio
async def test_retries_same_typed_event_before_later_callback_can_advance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transient ingestion keeps the exact typed event until it is accepted."""
    sessions = _SessionManager()
    repository = _RetryThenAcceptRepository()
    service = _service(repository=repository, sessions=sessions)
    sleep = AsyncMock()
    monkeypatch.setattr(
        "azents.services.external_channel.discord_gateway_manager.asyncio.sleep",
        sleep,
    )

    await service._admit_gateway_event(
        connection_id="connection-1",
        lease=_lease(),
        provider_app_id="app-1",
        target_guild_id="300",
        connected_bot_user_id="900",
        configuration_generation=2,
        event=_event(),
    )

    assert len(repository.admission_calls) == 2
    assert (
        repository.admission_calls[0]["event"] is repository.admission_calls[1]["event"]
    )
    sleep.assert_awaited_once_with(1.0)


@pytest.mark.asyncio
async def test_quiesced_gateway_rejects_message_create() -> None:
    sessions = _SessionManager()
    repository = _Repository(admission=object())
    config = MagicMock()
    config.external_channel_conversation.quiesce.discord_gateway = True
    service = _service(repository=repository, sessions=sessions, config=config)

    with pytest.raises(DiscordGatewayError, match="temporarily quiesced"):
        await service._admit_gateway_event(
            connection_id="connection-1",
            lease=_lease(),
            provider_app_id="app-1",
            target_guild_id="300",
            connected_bot_user_id="900",
            configuration_generation=2,
            event=_event(),
        )

    assert repository.admission_calls == []


@pytest.mark.asyncio
async def test_cross_guild_event_is_not_admitted() -> None:
    repository = _Repository(admission=object())
    service = _service(repository=repository, sessions=_SessionManager())

    await service._admit_gateway_event(
        connection_id="connection-1",
        lease=_lease(),
        provider_app_id="app-1",
        target_guild_id="300",
        connected_bot_user_id="900",
        configuration_generation=2,
        event=_event(guild_id=301),
    )

    assert repository.admission_calls == []


@pytest.mark.asyncio
async def test_stale_lease_stops_typed_event_admission() -> None:
    sessions = _SessionManager()
    repository = _StaleAuthorityRepository()
    service = _service(repository=repository, sessions=sessions)

    with pytest.raises(DiscordGatewayLeaseLost):
        await service._admit_gateway_event(
            connection_id="connection-1",
            lease=_lease(),
            provider_app_id="app-1",
            target_guild_id="300",
            connected_bot_user_id="900",
            configuration_generation=2,
            event=_event(),
        )


@pytest.mark.asyncio
async def test_sdk_lifecycle_updates_fenced_gap_and_active_state() -> None:
    repository = _Repository(admission=object())
    service = _service(repository=repository, sessions=_SessionManager())

    await service._handle_gateway_lifecycle(
        connection_id="connection-1",
        lease=_lease(),
        state="disconnected",
    )
    await service._handle_gateway_lifecycle(
        connection_id="connection-1",
        lease=_lease(),
        state="resumed",
    )

    assert repository.gap_calls[0]["reason"] == "gateway_disconnected"
    assert repository.active_calls[0]["lease_generation"] == 3


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

    await service._run_owned_connection(
        connection_id="connection-1",
        shutdown_event=asyncio.Event(),
    )

    assert repository.reconnect_calls[0]["reason"] == "gateway_credentials_invalid"
    assert repository.release_calls == []


@pytest.mark.asyncio
async def test_library_intent_rejection_terminalizes_connection() -> None:
    repository = _OwnedRepository()
    credentials_codec = MagicMock()
    credentials_codec.decrypt.return_value = DiscordConnectionCredentials(
        bot_token="test-token"
    )
    service = _service(
        repository=repository,
        sessions=_SessionManager(),
        credentials_codec=credentials_codec,
        gateway_client=_IntentsFailureRunner(),
    )

    await service._run_owned_connection(
        connection_id="connection-1",
        shutdown_event=asyncio.Event(),
    )

    assert repository.reconnect_calls[0]["reason"] == "intents_disallowed"
    assert repository.release_calls == []


@pytest.mark.asyncio
async def test_sdk_terminal_close_terminalizes_connection() -> None:
    repository = _OwnedRepository()
    credentials_codec = MagicMock()
    credentials_codec.decrypt.return_value = DiscordConnectionCredentials(
        bot_token="test-token"
    )
    service = _service(
        repository=repository,
        sessions=_SessionManager(),
        credentials_codec=credentials_codec,
        gateway_client=_TerminalFailureRunner(),
    )

    await service._run_owned_connection(
        connection_id="connection-1",
        shutdown_event=asyncio.Event(),
    )

    assert repository.reconnect_calls[0]["reason"] == "gateway_connection_rejected"
    assert repository.release_calls == []


@pytest.mark.asyncio
async def test_manager_passes_typed_lifecycle_and_event_handlers_to_sdk() -> None:
    repository = _Repository(admission=object())
    runner = _EventRunner()
    service = _service(
        repository=repository,
        sessions=_SessionManager(),
        gateway_client=runner,
    )

    with pytest.raises(DiscordGatewayTerminalError):
        await service._run_connection_with_lease(
            connection_id="connection-1",
            lease=_lease(),
            bot_token="test-token",
            provider_app_id="app-1",
            target_guild_id="300",
            connected_bot_user_id="900",
            configuration_generation=2,
            shutdown_event=asyncio.Event(),
        )

    assert runner.bot_token == "test-token"
    assert runner.target_guild_id == "300"
    assert len(repository.active_calls) == 1
    assert len(repository.admission_calls) == 1


@pytest.mark.asyncio
async def test_active_sdk_lifecycle_renews_gateway_lease() -> None:
    repository = _Repository(admission=object())
    runner = _BlockingRunner()
    service = _service(
        repository=repository,
        sessions=_SessionManager(),
        gateway_client=runner,
    )
    service.renew_interval = datetime.timedelta(milliseconds=1)
    shutdown = asyncio.Event()
    task = asyncio.create_task(
        service._run_connection_with_lease(
            connection_id="connection-1",
            lease=_lease(),
            bot_token="test-token",
            provider_app_id="app-1",
            target_guild_id="300",
            connected_bot_user_id="900",
            configuration_generation=2,
            shutdown_event=shutdown,
        )
    )

    await runner.started.wait()
    while not repository.renew_calls:
        await asyncio.sleep(0.001)
    shutdown.set()
    await task

    assert repository.renew_calls
