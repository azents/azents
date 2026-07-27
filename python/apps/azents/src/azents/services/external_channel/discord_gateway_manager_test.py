"""Deterministic Discord Gateway manager admission tests."""

import asyncio
import datetime
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from azcommon.di import Container
from cryptography.fernet import InvalidToken

from azents.core.deps import get_config, get_credential_cipher
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
    DiscordGatewayCheckpoint,
    DiscordGatewayConnectionResult,
    DiscordGatewayDispatch,
    DiscordGatewayInvalidPayload,
)
from azents.services.external_channel.discord_gateway_manager import (
    DiscordGatewayLeaseLost,
    DiscordGatewayManagerService,
    get_discord_gateway_http_client,
)


class _SessionManager:
    """Yield one mock session for a manager method without database I/O."""

    def __init__(self) -> None:
        self.session = MagicMock()
        self.session.commit = AsyncMock()

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[MagicMock]:
        yield self.session


class _Repository:
    """Capture one lease-fenced admission request."""

    def __init__(self, admission: object | None) -> None:
        self.admission = admission
        self.calls: list[dict[str, object]] = []
        self.checkpoint_calls: list[dict[str, object]] = []
        self.reconnect_required_calls: list[dict[str, object]] = []

    async def admit_discord_gateway_event(
        self,
        _session: object,
        **kwargs: object,
    ) -> object | None:
        self.calls.append(kwargs)
        return self.admission

    async def update_discord_gateway_checkpoint(
        self,
        _session: object,
        **kwargs: object,
    ) -> bool:
        """Capture one checkpoint update."""
        self.checkpoint_calls.append(kwargs)
        return True

    async def mark_discord_gateway_reconnect_required(
        self,
        _session: object,
        **kwargs: object,
    ) -> bool:
        """Capture one fenced terminal Gateway transition."""
        self.reconnect_required_calls.append(kwargs)
        return True


class _CredentialFailureRepository(_Repository):
    """Provide one owned connection whose persisted credential cannot decrypt."""

    def __init__(self) -> None:
        super().__init__(admission=object())
        self.gap_calls: list[dict[str, object]] = []
        self.release_calls: list[dict[str, object]] = []

    async def claim_discord_gateway_lease(
        self,
        _session: object,
        **_kwargs: object,
    ) -> ExternalChannelIngressLeaseClaim:
        """Return one current lease snapshot."""
        return ExternalChannelIngressLeaseClaim(lease=_lease())

    async def get_owned_discord_gateway_configuration(
        self,
        _session: object,
        **_kwargs: object,
    ) -> MagicMock:
        """Return the minimum owned configuration surface for credential decoding."""
        return MagicMock(
            encrypted_credentials="ciphertext",
            provider_app_id="app-1",
            provider_tenant_id="guild-1",
        )

    async def release_discord_gateway_lease(
        self,
        _session: object,
        **kwargs: object,
    ) -> bool:
        """Capture an unexpected ordinary lease release."""
        self.release_calls.append(kwargs)
        return True

    async def record_discord_gateway_gap(
        self,
        _session: object,
        **kwargs: object,
    ) -> bool:
        """Capture a retryable Gateway gap without mutating authority."""
        self.gap_calls.append(kwargs)
        return True


class _ReconnectGatewayClient:
    """Return a repeated reconnect result without opening a WebSocket."""

    def __init__(self, *, reason: str = "connection_closed") -> None:
        self.calls = 0
        self.reason = reason

    async def run_connection(
        self,
        **_kwargs: object,
    ) -> DiscordGatewayConnectionResult:
        self.calls += 1
        return DiscordGatewayConnectionResult(
            reconnect=True,
            can_resume=False,
            reason=self.reason,
            checkpoint=None,
        )


class _ErrorGatewayClient:
    """Raise one controlled Gateway protocol error before a session starts."""

    def __init__(self, error: DiscordGatewayInvalidPayload) -> None:
        self.calls = 0
        self.error = error

    async def run_connection(self, **_kwargs: object) -> DiscordGatewayConnectionResult:
        self.calls += 1
        raise self.error


def _service(
    *,
    repository: _Repository,
    session_manager: _SessionManager,
    credentials_codec: MagicMock | None = None,
    http_client: MagicMock | None = None,
    gateway_client: MagicMock | None = None,
) -> DiscordGatewayManagerService:
    """Build a manager with only its admission dependencies exercised."""
    return DiscordGatewayManagerService(
        config=MagicMock(),
        session_manager=session_manager,
        repository=repository,  # type: ignore[arg-type]
        credentials_codec=credentials_codec or MagicMock(),
        cipher=MagicMock(),
        http_client=http_client or MagicMock(),
        manager_id="manager-1",
        gateway_client=gateway_client or MagicMock(),
    )


def _lease() -> ExternalChannelIngressLease:
    """Build one claimed lease snapshot."""
    return ExternalChannelIngressLease(
        id="lease-1",
        connection_id="connection-1",
        lease_owner="manager-1",
        lease_generation=3,
        lease_until=datetime.datetime(2026, 7, 26, 1, tzinfo=datetime.UTC),
        heartbeat_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
        required_configuration_generation=2,
        required_app_claim_generation=4,
        gap_detected_at=None,
        gap_reason=None,
        encrypted_checkpoint=None,
        checkpoint_version=None,
        checkpoint_session_fingerprint=None,
        last_handled_dispatch_sequence=None,
        created_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
        updated_at=datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC),
    )


def _dispatch(*, guild_id: str = "guild-1") -> DiscordGatewayDispatch:
    """Build one minimal supported Message Create Dispatch."""
    return DiscordGatewayDispatch(
        session_id="session-1",
        resume_gateway_url="wss://gateway.discord.gg",
        sequence=5,
        event_name="MESSAGE_CREATE",
        data={
            "id": "message-1",
            "channel_id": "channel-1",
            "guild_id": guild_id,
            "content": "Hello",
        },
    )


def _mock_dependency() -> MagicMock:
    """Provide one inert dependency for DI graph construction."""
    return MagicMock()


def _test_session_manager() -> _SessionManager:
    """Provide one inert session manager for DI graph construction."""
    return _SessionManager()


@pytest.mark.asyncio
async def test_gateway_manager_dependency_graph_is_resolvable() -> None:
    """The worker can resolve its manager through the production DI container."""
    overrides = {
        get_config: _mock_dependency,
        get_session_manager: _test_session_manager,
        ExternalChannelRepository: _mock_dependency,
        get_external_channel_credentials_codec: _mock_dependency,
        get_credential_cipher: _mock_dependency,
        get_discord_gateway_http_client: _mock_dependency,
    }
    async with Container(dependency_overrides=overrides) as container:
        service = await container.solve(DiscordGatewayManagerService)

    assert service.gateway_client is not None


@pytest.mark.asyncio
async def test_admits_supported_dispatch_under_current_lease() -> None:
    """A supported target-Guild message commits admission before checkpointing."""
    sessions = _SessionManager()
    repository = _Repository(admission=object())
    service = _service(repository=repository, session_manager=sessions)

    await service._admit_dispatch(  # pyright: ignore[reportPrivateUsage]
        connection_id="connection-1",
        lease=_lease(),
        provider_app_id="app-1",
        target_guild_id="guild-1",
        dispatch=_dispatch(),
    )

    assert len(repository.calls) == 1
    call = repository.calls[0]
    assert call["connection_id"] == "connection-1"
    assert call["lease_owner"] == "manager-1"
    assert call["lease_generation"] == 3
    assert call["sequence"] == 5
    assert call["checkpoint_version"] == 1
    create = call["create"]
    assert isinstance(create, ExternalChannelEventCreate)
    assert create.provider_event_id == "discord-gateway:session-1:5"
    sessions.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_checkpoint_fingerprints_discord_session_id() -> None:
    """Checkpoint fencing receives a non-reversible Discord session identifier."""
    sessions = _SessionManager()
    repository = _Repository(admission=object())
    cipher = MagicMock()
    cipher.encrypt.return_value = "checkpoint-ciphertext"
    service = _service(repository=repository, session_manager=sessions)
    service.cipher = cipher

    persisted = await service._persist_checkpoint(  # pyright: ignore[reportPrivateUsage]
        connection_id="connection-1",
        lease=_lease(),
        checkpoint=DiscordGatewayCheckpoint(
            session_id="session-1",
            resume_gateway_url="wss://gateway.discord.gg",
            sequence=1,
        ),
    )

    assert persisted is True
    assert repository.checkpoint_calls[0]["checkpoint_session_fingerprint"] == (
        hashlib.sha256(b"session-1").hexdigest()
    )
    assert "session-1" not in repository.checkpoint_calls[0].values()
    sessions.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_ignores_cross_guild_dispatch_without_admission() -> None:
    """Cross-Guild traffic cannot enter a connection's durable event stream."""
    sessions = _SessionManager()
    repository = _Repository(admission=object())
    service = _service(repository=repository, session_manager=sessions)

    await service._admit_dispatch(  # pyright: ignore[reportPrivateUsage]
        connection_id="connection-1",
        lease=_lease(),
        provider_app_id="app-1",
        target_guild_id="guild-1",
        dispatch=_dispatch(guild_id="guild-2"),
    )

    assert repository.calls == []
    sessions.session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_authority_fence_stops_gateway_checkpoint_progress() -> None:
    """Failed repository admission is surfaced so the protocol never checkpoints it."""
    sessions = _SessionManager()
    repository = _Repository(admission=None)
    service = _service(repository=repository, session_manager=sessions)

    with pytest.raises(DiscordGatewayLeaseLost):
        await service._admit_dispatch(  # pyright: ignore[reportPrivateUsage]
            connection_id="connection-1",
            lease=_lease(),
            provider_app_id="app-1",
            target_guild_id="guild-1",
            dispatch=_dispatch(),
        )

    assert len(repository.calls) == 1
    sessions.session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_persisted_credential_terminalizes_current_gateway_lease() -> (
    None
):
    """A credential decode failure stops future scheduler claims for this connection."""
    sessions = _SessionManager()
    repository = _CredentialFailureRepository()
    credentials_codec = MagicMock()
    credentials_codec.decrypt = MagicMock(side_effect=InvalidToken)
    service = _service(
        repository=repository,
        session_manager=sessions,
        credentials_codec=credentials_codec,
    )

    await service._run_owned_connection(  # pyright: ignore[reportPrivateUsage]  # Exercise terminal credential handling from the owned-session boundary.
        connection_id="connection-1",
        shutdown_event=asyncio.Event(),
    )

    assert len(repository.reconnect_required_calls) == 1
    call = repository.reconnect_required_calls[0]
    assert call["connection_id"] == "connection-1"
    assert call["lease_owner"] == "manager-1"
    assert call["lease_generation"] == 3
    assert call["reason"] == "gateway_credentials_invalid"
    assert repository.release_calls == []
    assert sessions.session.commit.await_count == 2


@pytest.mark.asyncio
async def test_gateway_discovery_credential_rejection_terminalizes_current_lease() -> (
    None
):
    """A discovery 401 terminalizes ownership instead of entering the poll loop."""
    sessions = _SessionManager()
    repository = _CredentialFailureRepository()
    credentials_codec = MagicMock()
    credentials_codec.decrypt = MagicMock(
        return_value=DiscordConnectionCredentials(bot_token="test-token")
    )
    http_client = MagicMock()
    http_client.get = AsyncMock(return_value=MagicMock(status_code=401))
    service = _service(
        repository=repository,
        session_manager=sessions,
        credentials_codec=credentials_codec,
        http_client=http_client,
    )

    await service._run_owned_connection(  # pyright: ignore[reportPrivateUsage]  # Exercise terminal discovery handling from the owned-session boundary.
        connection_id="connection-1",
        shutdown_event=asyncio.Event(),
    )

    assert len(repository.reconnect_required_calls) == 1
    call = repository.reconnect_required_calls[0]
    assert call["lease_owner"] == "manager-1"
    assert call["lease_generation"] == 3
    assert call["reason"] == "gateway_credentials_invalid"
    assert repository.release_calls == []


@pytest.mark.asyncio
async def test_rate_limited_gateway_retries_with_backoff_without_terminalizing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rate limiting preserves the fenced lease and never requires reconnect."""
    sessions = _SessionManager()
    repository = _CredentialFailureRepository()
    credentials_codec = MagicMock()
    credentials_codec.decrypt = MagicMock(
        return_value=DiscordConnectionCredentials(bot_token="test-token")
    )
    http_client = MagicMock()
    http_client.get = AsyncMock(
        return_value=MagicMock(
            status_code=200,
            json=MagicMock(return_value={"url": "wss://gateway.discord.gg"}),
        )
    )
    gateway_client = _ReconnectGatewayClient(reason="gateway_rate_limited")
    service = _service(
        repository=repository,
        session_manager=sessions,
        credentials_codec=credentials_codec,
        http_client=http_client,
        gateway_client=gateway_client,  # type: ignore[arg-type]
    )
    delays: list[datetime.timedelta] = []

    async def sleep_and_stop(
        shutdown_event: asyncio.Event,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
        delay: datetime.timedelta,
    ) -> bool:
        assert connection_id == "connection-1"
        assert lease == _lease()
        delays.append(delay)
        shutdown_event.set()
        return True

    monkeypatch.setattr(service, "_sleep_or_shutdown", sleep_and_stop)

    await service._run_owned_connection(  # pyright: ignore[reportPrivateUsage]  # Exercise the lease-owned reconnect budget.
        connection_id="connection-1",
        shutdown_event=asyncio.Event(),
    )

    assert gateway_client.calls == 1
    assert len(repository.gap_calls) == 1
    assert repository.reconnect_required_calls == []
    assert delays == [datetime.timedelta(minutes=1)]
    assert len(repository.release_calls) == 1


@pytest.mark.asyncio
async def test_invalid_gateway_payload_retries_with_backoff_without_terminalizing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed retryable frame is observable without forcing reconnection."""
    sessions = _SessionManager()
    repository = _CredentialFailureRepository()
    credentials_codec = MagicMock()
    credentials_codec.decrypt = MagicMock(
        return_value=DiscordConnectionCredentials(bot_token="test-token")
    )
    http_client = MagicMock()
    http_client.get = AsyncMock(
        return_value=MagicMock(
            status_code=200,
            json=MagicMock(return_value={"url": "wss://gateway.discord.gg"}),
        )
    )
    gateway_client = _ErrorGatewayClient(DiscordGatewayInvalidPayload("invalid"))
    service = _service(
        repository=repository,
        session_manager=sessions,
        credentials_codec=credentials_codec,
        http_client=http_client,
        gateway_client=gateway_client,  # type: ignore[arg-type]
    )
    delays: list[datetime.timedelta] = []

    async def sleep_and_stop(
        shutdown_event: asyncio.Event,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
        delay: datetime.timedelta,
    ) -> bool:
        assert connection_id == "connection-1"
        assert lease == _lease()
        delays.append(delay)
        shutdown_event.set()
        return True

    monkeypatch.setattr(service, "_sleep_or_shutdown", sleep_and_stop)

    await service._run_owned_connection(  # pyright: ignore[reportPrivateUsage]  # Exercise recoverable protocol handling.
        connection_id="connection-1",
        shutdown_event=asyncio.Event(),
    )

    assert gateway_client.calls == 1
    assert len(repository.gap_calls) == 1
    assert repository.gap_calls[0]["reason"] == "gateway_protocol_invalid"
    assert repository.reconnect_required_calls == []
    assert delays == [datetime.timedelta(seconds=5)]
    assert len(repository.release_calls) == 1


@pytest.mark.asyncio
async def test_rate_limited_discovery_retries_with_backoff_without_terminalizing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery rate limits stay under the fenced lease and do not terminalize."""
    sessions = _SessionManager()
    repository = _CredentialFailureRepository()
    credentials_codec = MagicMock()
    credentials_codec.decrypt = MagicMock(
        return_value=DiscordConnectionCredentials(bot_token="test-token")
    )
    http_client = MagicMock()
    http_client.get = AsyncMock(
        return_value=MagicMock(
            status_code=429,
            headers={"Retry-After": "120"},
        )
    )
    gateway_client = _ReconnectGatewayClient()
    service = _service(
        repository=repository,
        session_manager=sessions,
        credentials_codec=credentials_codec,
        http_client=http_client,
        gateway_client=gateway_client,  # type: ignore[arg-type]
    )
    delays: list[datetime.timedelta] = []

    async def sleep_and_stop(
        shutdown_event: asyncio.Event,
        *,
        connection_id: str,
        lease: ExternalChannelIngressLease,
        delay: datetime.timedelta,
    ) -> bool:
        assert connection_id == "connection-1"
        assert lease == _lease()
        delays.append(delay)
        shutdown_event.set()
        return True

    monkeypatch.setattr(service, "_sleep_or_shutdown", sleep_and_stop)

    await service._run_owned_connection(  # pyright: ignore[reportPrivateUsage]  # Exercise the lease-owned discovery retry.
        connection_id="connection-1",
        shutdown_event=asyncio.Event(),
    )

    assert gateway_client.calls == 0
    assert len(repository.gap_calls) == 1
    assert repository.gap_calls[0]["reason"] == "gateway_rate_limited"
    assert repository.reconnect_required_calls == []
    assert delays == [datetime.timedelta(minutes=2)]
    assert len(repository.release_calls) == 1


@pytest.mark.asyncio
async def test_reconnect_backoff_renews_gateway_lease() -> None:
    """Backoff keeps its current lease instead of allowing a competing owner."""
    sessions = _SessionManager()
    repository = _CredentialFailureRepository()
    service = _service(repository=repository, session_manager=sessions)
    service.renew_interval = datetime.timedelta(milliseconds=1)
    service._renew = AsyncMock(return_value=True)  # type: ignore[method-assign]

    retained = await service._sleep_or_shutdown(  # pyright: ignore[reportPrivateUsage]  # Exercise lease retention during retry backoff.
        asyncio.Event(),
        connection_id="connection-1",
        lease=_lease(),
        delay=datetime.timedelta(milliseconds=5),
    )

    assert retained is True
    service._renew.assert_awaited()  # pyright: ignore[reportPrivateUsage]
