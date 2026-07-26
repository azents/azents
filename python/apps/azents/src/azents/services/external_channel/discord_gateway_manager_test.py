"""Deterministic Discord Gateway manager admission tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from azcommon.di import Container

from azents.core.deps import get_config, get_credential_cipher
from azents.rdb.deps import get_session_manager
from azents.repos.external_channel.data import (
    ExternalChannelEventCreate,
    ExternalChannelIngressLease,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.connection import (
    get_external_channel_credentials_codec,
)
from azents.services.external_channel.discord_gateway import DiscordGatewayDispatch
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

    async def admit_discord_gateway_event(
        self,
        _session: object,
        **kwargs: object,
    ) -> object | None:
        self.calls.append(kwargs)
        return self.admission


def _service(
    *,
    repository: _Repository,
    session_manager: _SessionManager,
) -> DiscordGatewayManagerService:
    """Build a manager with only its admission dependencies exercised."""
    return DiscordGatewayManagerService(
        config=MagicMock(),
        session_manager=session_manager,
        repository=repository,  # type: ignore[arg-type]
        credentials_codec=MagicMock(),
        cipher=MagicMock(),
        http_client=MagicMock(),
        manager_id="manager-1",
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
