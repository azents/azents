"""Deterministic tests for typed discord.py lease-fenced admission."""

import asyncio
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from azcommon.di import Container
from cryptography.fernet import InvalidToken

from azents.core.config import Config, ExternalChannelGatewayLeaseConfig
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
from azents.services.external_channel.discord_events import (
    DiscordGatewayMessageEvent,
    project_discord_message,
)
from azents.services.external_channel.discord_gateway import (
    DiscordGatewayError,
    DiscordGatewayEventHandler,
    DiscordGatewayIntentsError,
    DiscordGatewayLifecycleHandler,
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

    def __init__(self, *, callback_selector_hash: str | None = "selector-hash") -> None:
        super().__init__()
        self.callback_selector_hash = callback_selector_hash

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
            http_callback_selector_hash=self.callback_selector_hash,
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
        interactions_callback_base_url: str,
        interactions_callback_selector_hash: str,
        connected_bot_user_id: str | None,
        handle_event: DiscordGatewayEventHandler,
        handle_lifecycle: DiscordGatewayLifecycleHandler,
    ) -> None:
        del (
            connected_bot_user_id,
            interactions_callback_base_url,
            interactions_callback_selector_hash,
        )
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
    guild = str(guild_id)
    return DiscordGatewayMessageEvent(
        event_type="message_create",
        guild_id=guild,
        channel_id="200",
        message=project_discord_message(
            guild_id=guild,
            message={
                "id": "100",
                "channel_id": "200",
                "channel_name": "general",
                "content": "Hello",
                "timestamp": "2026-07-28T00:00:00+00:00",
                "author": {"id": "400", "username": "participant"},
                "mentions": [],
                "attachments": [],
            },
        ),
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
    resolved_config = config
    if resolved_config is None:
        resolved_config = cast(
            Config,
            SimpleNamespace(
                external_channel_discord_callback_url=("https://callbacks.example/"),
                external_channel_conversation=SimpleNamespace(
                    quiesce=SimpleNamespace(discord_gateway=False)
                ),
                testenv_external_channel_gateway_lease=None,
            ),
        )
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
        config=resolved_config,
    )


def _mock_dependency() -> MagicMock:
    return MagicMock()


def _test_session_manager() -> _SessionManager:
    return _SessionManager()


def test_gateway_manager_uses_testenv_lease_override() -> None:
    """Testenv can shorten stale-lease takeover without changing defaults."""
    config = cast(
        Config,
        SimpleNamespace(
            testenv_external_channel_gateway_lease=(
                ExternalChannelGatewayLeaseConfig(
                    duration_seconds=5.0,
                    renewal_interval_seconds=1.0,
                )
            ),
        ),
    )
    service = _service(
        repository=_Repository(),
        sessions=_SessionManager(),
        config=config,
    )

    assert service._lease_duration() == datetime.timedelta(seconds=5)
    assert service._renew_interval() == datetime.timedelta(seconds=1)


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
    all_attempts_started = asyncio.Event()
    attempted_plans: list[object] = []

    async def attempt(plan: object) -> None:
        attempted_plans.append(plan)
        if len(attempted_plans) == len(plans):
            all_attempts_started.set()
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
    await all_attempts_started.wait()

    assert attempted_plans == list(plans)
    assert len(service.control_tasks) == 2
    scheduled_tasks = tuple(service.control_tasks)
    cleanup_complete = asyncio.Event()

    def mark_cleanup_complete(_: asyncio.Task[object]) -> None:
        if not service.control_tasks:
            cleanup_complete.set()

    for task in scheduled_tasks:
        task.add_done_callback(mark_cleanup_complete)
    release.set()
    await asyncio.gather(*scheduled_tasks)
    await cleanup_complete.wait()
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
async def test_missing_callback_authority_terminalizes_connection() -> None:
    """An active row without callback identity requires explicit reconnection."""
    repository = _OwnedRepository(callback_selector_hash=None)
    credentials_codec = MagicMock()
    credentials_codec.decrypt.return_value = DiscordConnectionCredentials(
        bot_token="test-token"
    )
    service = _service(
        repository=repository,
        sessions=_SessionManager(),
        credentials_codec=credentials_codec,
        gateway_client=_BlockingRunner(),
    )

    await service._run_owned_connection(
        connection_id="connection-1",
        shutdown_event=asyncio.Event(),
    )

    assert repository.reconnect_calls[0]["reason"] == "interaction_endpoint_drift"
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
            interactions_callback_base_url="https://callbacks.example/",
            interactions_callback_selector_hash="selector-hash",
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
            interactions_callback_base_url="https://callbacks.example/",
            interactions_callback_selector_hash="selector-hash",
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
