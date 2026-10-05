"""Native PostgreSQL completed lease scopes, races, fences and rollback."""

import asyncio
import datetime
from collections.abc import AsyncIterator
from typing import NamedTuple
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.enums import ExternalChannelConnectionStatus, ExternalChannelTransport
from azents.rdb.models.external_channel import RDBExternalChannelConnection
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import (
    ReadSession,
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.external_channel.data import ExternalChannelConnectionConfiguration
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.repository_test import (
    _connection_create,
    _create_workspace,
)
from azents.repos.external_channel.slack_presence_operations import (
    SlackPresenceOperationRepository,
)
from azents.repos.external_channel.slack_socket_operations import (
    SlackSocketOperationRepository,
)

_NOW = datetime.datetime(2026, 10, 5, tzinfo=datetime.UTC)


@pytest_asyncio.fixture
async def lease_connection(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> AsyncIterator[str]:
    """Commit an isolated actual connection; remove it after concurrent sessions."""
    writes = create_read_write_session_manager(rdb_engine)
    repository = ExternalChannelRepository()
    async with writes() as session:
        workspace_id = await _create_workspace(session, f"lease-{uuid4().hex}")
        connection = await repository.create_connection(
            session,
            _connection_create(workspace_id).model_copy(
                update={"transport": ExternalChannelTransport.SOCKET}
            ),
        )
    try:
        yield connection.id
    finally:
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBExternalChannelConnection).where(
                    RDBExternalChannelConnection.id == connection.id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
            )


class _LeaseOperations(NamedTuple):
    """Both completed repository dependencies for the same isolated database."""

    presence: SlackPresenceOperationRepository
    socket: SlackSocketOperationRepository


def _operations(
    engine: AsyncEngine, repository: ExternalChannelRepository
) -> _LeaseOperations:
    reads = create_read_only_session_manager(engine)
    writes = create_read_write_session_manager(engine)
    return _LeaseOperations(
        SlackPresenceOperationRepository(reads, writes, repository),
        SlackSocketOperationRepository(reads, writes, repository),
    )


class _ConcurrentRepository(ExternalChannelRepository):
    """Synchronize only the two database callers before actual PostgreSQL CAS."""

    def __init__(self) -> None:
        self.barrier = asyncio.Barrier(2)

    async def claim_socket_connection(
        self,
        session: WriteSession,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
        lease_until: datetime.datetime,
    ) -> ExternalChannelConnectionConfiguration | None:
        await self.barrier.wait()
        return await super().claim_socket_connection(
            session,
            connection_id=connection_id,
            lease_owner=lease_owner,
            now=now,
            lease_until=lease_until,
        )

    async def claim_slack_presence_connection(
        self,
        session: WriteSession,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
        lease_until: datetime.datetime,
    ) -> ExternalChannelConnectionConfiguration | None:
        await self.barrier.wait()
        return await super().claim_slack_presence_connection(
            session,
            connection_id=connection_id,
            lease_owner=lease_owner,
            now=now,
            lease_until=lease_until,
        )


@pytest.mark.parametrize("presence", [False, True])
async def test_concurrent_claims_have_one_durable_winner(
    rdb_engine: AsyncEngine,
    lease_connection: str,
    presence: bool,
) -> None:
    repository = _ConcurrentRepository()
    presence_operations, socket_operations = _operations(rdb_engine, repository)
    operations = presence_operations if presence else socket_operations
    results = await asyncio.wait_for(
        asyncio.gather(
            *(
                operations.claim(
                    connection_id=lease_connection,
                    lease_owner=owner,
                    now=_NOW,
                    lease_until=_NOW + datetime.timedelta(seconds=45),
                )
                for owner in ["manager-a", "manager-b"]
            )
        ),
        timeout=10,
    )
    assert sum(result is not None for result in results) == 1
    winner = next(
        owner
        for owner, result in zip(["manager-a", "manager-b"], results, strict=True)
        if result is not None
    )
    async with create_read_only_session_manager(rdb_engine)() as session:
        row = await session.read_session.get(
            RDBExternalChannelConnection, lease_connection
        )
        assert row is not None
        assert (
            row.slack_presence_lease_owner if presence else row.socket_lease_owner
        ) == winner


class _ModeRepository(ExternalChannelRepository):
    """Record native database mode without replacing the actual lease queries."""

    def __init__(self) -> None:
        self.modes: list[str] = []

    async def list_socket_connection_ids(self, session: ReadSession) -> list[str]:
        self.modes.append(
            str(
                await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
            )
        )
        return await super().list_socket_connection_ids(session)

    async def list_slack_presence_connection_ids(
        self, session: ReadSession
    ) -> list[str]:
        self.modes.append(
            str(
                await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
            )
        )
        return await super().list_slack_presence_connection_ids(session)


async def test_read_only_discovery_and_socket_health_fences(
    rdb_engine: AsyncEngine,
    lease_connection: str,
) -> None:
    repository = _ModeRepository()
    presence, socket = _operations(rdb_engine, repository)
    assert lease_connection in await socket.list_connection_ids()
    assert lease_connection in await presence.list_connection_ids()
    assert repository.modes == ["on", "on"]
    claim = await socket.claim(
        connection_id=lease_connection,
        lease_owner="owner",
        now=_NOW,
        lease_until=_NOW + datetime.timedelta(seconds=45),
    )
    assert claim is not None
    assert await socket.owned_active(
        connection_id=lease_connection, lease_owner="owner", now=_NOW
    )
    assert not await socket.record_gap(
        connection_id=lease_connection,
        lease_owner="stale",
        now=_NOW,
        reason="not-owner",
    )
    assert await socket.record_gap(
        connection_id=lease_connection,
        lease_owner="owner",
        now=_NOW,
        reason="socket-replacement",
    )
    assert await socket.mark_active(
        connection_id=lease_connection, lease_owner="owner", now=_NOW
    )
    assert not await socket.renew(
        connection_id=lease_connection,
        lease_owner="stale",
        now=_NOW,
        lease_until=_NOW + datetime.timedelta(seconds=60),
    )
    assert await socket.release(
        connection_id=lease_connection,
        lease_owner="owner",
        now=_NOW,
        reason="connection_closed",
        status=ExternalChannelConnectionStatus.DEGRADED,
    )
    async with create_read_only_session_manager(rdb_engine)() as session:
        row = await session.read_session.get(
            RDBExternalChannelConnection, lease_connection
        )
        assert row is not None
        assert row.socket_lease_owner is None
        assert row.status is ExternalChannelConnectionStatus.DEGRADED
        assert row.socket_gap_reason == "connection_closed"


async def test_presence_generation_and_socket_expiry_fence(
    rdb_engine: AsyncEngine,
    lease_connection: str,
) -> None:
    presence, socket = _operations(rdb_engine, ExternalChannelRepository())
    claim = await presence.claim(
        connection_id=lease_connection,
        lease_owner="presence",
        now=_NOW,
        lease_until=_NOW + datetime.timedelta(seconds=45),
    )
    assert claim is not None
    assert (
        await presence.load_targets(
            connection_id=lease_connection,
            lease_owner="presence",
            configuration_generation=claim.configuration_generation,
            now=_NOW,
        )
        == ()
    )
    writes = create_read_write_session_manager(rdb_engine)
    async with writes() as session:
        await session.write_session.execute(
            sa.update(RDBExternalChannelConnection)
            .where(RDBExternalChannelConnection.id == lease_connection)
            .values(configuration_generation=claim.configuration_generation + 1)
        )
    assert not await presence.renew(
        connection_id=lease_connection,
        lease_owner="presence",
        configuration_generation=claim.configuration_generation,
        now=_NOW,
        lease_until=_NOW + datetime.timedelta(seconds=60),
    )
    assert (
        await presence.load_targets(
            connection_id=lease_connection,
            lease_owner="presence",
            configuration_generation=claim.configuration_generation,
            now=_NOW,
        )
        is None
    )
    assert not await presence.release(
        connection_id=lease_connection, lease_owner="stale", now=_NOW
    )
    assert await presence.release(
        connection_id=lease_connection, lease_owner="presence", now=_NOW
    )
    assert (
        await socket.claim(
            connection_id=lease_connection,
            lease_owner="old",
            now=_NOW,
            lease_until=_NOW + datetime.timedelta(seconds=1),
        )
        is not None
    )
    later = _NOW + datetime.timedelta(seconds=2)
    assert not await socket.renew(
        connection_id=lease_connection,
        lease_owner="old",
        now=later,
        lease_until=later + datetime.timedelta(seconds=45),
    )
    assert (
        await socket.claim(
            connection_id=lease_connection,
            lease_owner="new",
            now=later,
            lease_until=later + datetime.timedelta(seconds=45),
        )
        is not None
    )
    assert not await socket.release(
        connection_id=lease_connection,
        lease_owner="old",
        now=later,
        reason="stale",
        status=ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
    )


class _ClaimFailure(RuntimeError):
    """Failure injected after the actual conditional claim, before scope exit."""


class _FailingRepository(ExternalChannelRepository):
    async def claim_socket_connection(
        self,
        session: WriteSession,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
        lease_until: datetime.datetime,
    ) -> ExternalChannelConnectionConfiguration | None:
        await super().claim_socket_connection(
            session,
            connection_id=connection_id,
            lease_owner=lease_owner,
            now=now,
            lease_until=lease_until,
        )
        raise _ClaimFailure("rollback actual claim")


async def test_failed_completed_mutation_rolls_back_actual_claim(
    rdb_engine: AsyncEngine,
    lease_connection: str,
) -> None:
    _, failing = _operations(rdb_engine, _FailingRepository())
    with pytest.raises(_ClaimFailure):
        await failing.claim(
            connection_id=lease_connection,
            lease_owner="failed",
            now=_NOW,
            lease_until=_NOW + datetime.timedelta(seconds=45),
        )
    async with create_read_only_session_manager(rdb_engine)() as session:
        row = await session.read_session.get(
            RDBExternalChannelConnection, lease_connection
        )
        assert row is not None and row.socket_lease_owner is None
    _, actual = _operations(rdb_engine, ExternalChannelRepository())
    assert (
        await actual.claim(
            connection_id=lease_connection,
            lease_owner="accepted",
            now=_NOW,
            lease_until=_NOW + datetime.timedelta(seconds=45),
        )
        is not None
    )
