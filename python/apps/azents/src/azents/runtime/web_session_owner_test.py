"""Inactive Runtime Web Owner session lifecycle tests."""

import asyncio
import contextlib
import datetime
from collections.abc import AsyncIterator, Callable
from typing import NamedTuple
from unittest.mock import AsyncMock

import pytest
from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_session import (
    APPROVED_SESSION_PROFILE,
    MANDATORY_DATA_FRAME_BYTES,
)
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.session import SessionManager
from azents.repos.runtime_web.data import RuntimeWebSessionRoute
from azents.repos.runtime_web.repository_test import _authority_fixture
from azents.repos.runtime_web.session_route_repository import (
    RuntimeWebSessionRouteConflict,
    RuntimeWebSessionRouteRepository,
)
from azents.runtime.web_session_owner import (
    RuntimeWebAuthenticatedRunnerConnection,
    RuntimeWebOwnedSession,
    RuntimeWebOwnerSessionRegistry,
    RuntimeWebSessionOwnerManager,
)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class _OwnedSession(NamedTuple):
    manager: RuntimeWebSessionOwnerManager
    session: RuntimeWebOwnedSession


async def _owned(
    session_manager: SessionManager[AsyncSession],
    *,
    clock: Callable[[], datetime.datetime] = _now,
) -> _OwnedSession:
    async with session_manager() as session:
        workspace_id, agent_id, _ = await _authority_fixture(session)
        runtime = RDBAgentRuntime(workspace_id=workspace_id, agent_id=agent_id)
        session.add(runtime)
        await session.flush()
        runtime.desired_generation = 3
        runtime.runner_generation = 4
        await session.flush()
        runtime_id = runtime.id
    manager = RuntimeWebSessionOwnerManager(
        session_manager=session_manager,
        repository=RuntimeWebSessionRouteRepository(),
        owner_replica_id="control-a",
        owner_boot_id="owner-boot-a",
        trusted_owner_address="control-a.internal:8032",
        lease_seconds=30,
        clock=clock,
    )
    return _OwnedSession(
        manager=manager,
        session=await manager.acquire(
            runtime_id=runtime_id,
            desired_generation=3,
            runner_generation=4,
        ),
    )


def _hello(
    owned: RuntimeWebOwnedSession,
    *,
    runner_boot_id: str = "runner-boot-a",
    maximum_data_frame_bytes: int = MANDATORY_DATA_FRAME_BYTES,
    deadline_at: datetime.datetime | None = None,
    request_stream_window_bytes: int | None = None,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    owner = owned.offer.owner
    hello = runtime_web_session_pb2.RuntimeWebSessionHello(
        role=runtime_web_session_pb2.RUNTIME_WEB_SESSION_PEER_ROLE_RUNNER,
        runtime_id=owner.runtime_id,
        desired_generation=owner.desired_generation,
        runner_generation=owner.runner_generation,
        session_nonce=owned.offer.session_nonce,
        maximum_data_frame_bytes=maximum_data_frame_bytes,
        request_stream_window_bytes=(
            APPROVED_SESSION_PROFILE.request_stream_window_bytes
            if request_stream_window_bytes is None
            else request_stream_window_bytes
        ),
        response_stream_window_bytes=(
            APPROVED_SESSION_PROFILE.response_stream_window_bytes
        ),
        request_session_window_bytes=(
            APPROVED_SESSION_PROFILE.request_session_window_bytes
        ),
        response_session_window_bytes=(
            APPROVED_SESSION_PROFILE.response_session_window_bytes
        ),
    )
    hello.deadline_at.FromDatetime(deadline_at or owned.offer.deadline_at)
    return runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=owned.offer.protocol_fingerprint,
        session_id=owner.session_lease_id,
        peer_boot_id=runner_boot_id,
        owner_boot_id=owner.owner_boot_id,
        session_lease_id=owner.session_lease_id,
        lease_generation=owner.lease_generation,
        hello=hello,
    )


def _evidence(
    owned: RuntimeWebOwnedSession,
    *,
    runner_boot_id: str = "runner-boot-a",
) -> RuntimeWebAuthenticatedRunnerConnection:
    owner = owned.offer.owner
    return RuntimeWebAuthenticatedRunnerConnection(
        runtime_id=owner.runtime_id,
        runner_boot_id=runner_boot_id,
        desired_generation=owner.desired_generation,
        runner_generation=owner.runner_generation,
    )


async def test_owner_registry_binds_authenticated_runner_boot(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    _, owned = await _owned(rdb_session_manager)
    registry = RuntimeWebOwnerSessionRegistry(
        session_manager=rdb_session_manager,
        repository=RuntimeWebSessionRouteRepository(),
        clock=_now,
    )

    with pytest.raises(ValueError, match="stale"):
        await registry.accept(
            owned,
            _hello(owned, runner_boot_id="wrong-boot"),
            _evidence(owned),
        )


@pytest.mark.parametrize(
    ("maximum_data_frame_bytes", "request_stream_window_bytes"),
    (
        (MANDATORY_DATA_FRAME_BYTES - 1, None),
        (MANDATORY_DATA_FRAME_BYTES, 0),
    ),
)
async def test_owner_registry_rejects_invalid_profile(
    rdb_session_manager: SessionManager[AsyncSession],
    maximum_data_frame_bytes: int,
    request_stream_window_bytes: int | None,
) -> None:
    _, owned = await _owned(rdb_session_manager)
    registry = RuntimeWebOwnerSessionRegistry(
        session_manager=rdb_session_manager,
        repository=RuntimeWebSessionRouteRepository(),
        clock=_now,
    )

    with pytest.raises(ValueError):
        await registry.accept(
            owned,
            _hello(
                owned,
                maximum_data_frame_bytes=maximum_data_frame_bytes,
                request_stream_window_bytes=request_stream_window_bytes,
            ),
            _evidence(owned),
        )


async def test_owner_registry_rejects_extended_offer_deadline(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    _, owned = await _owned(rdb_session_manager)
    registry = RuntimeWebOwnerSessionRegistry(
        session_manager=rdb_session_manager,
        repository=RuntimeWebSessionRouteRepository(),
        clock=_now,
    )

    with pytest.raises(ValueError, match="stale"):
        await registry.accept(
            owned,
            _hello(
                owned,
                deadline_at=owned.offer.deadline_at + datetime.timedelta(seconds=1),
            ),
            _evidence(owned),
        )


async def test_owner_registry_rejects_stale_snapshot_after_drain(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    manager, draining_owned = await _owned(rdb_session_manager)
    registry = RuntimeWebOwnerSessionRegistry(
        session_manager=rdb_session_manager,
        repository=RuntimeWebSessionRouteRepository(),
        clock=_now,
    )
    await manager.mark_draining(draining_owned)
    with pytest.raises(RuntimeWebSessionRouteConflict):
        await registry.accept(
            draining_owned,
            _hello(draining_owned),
            _evidence(draining_owned),
        )


async def test_owner_registry_rejects_stale_snapshot_after_release(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    manager, released_owned = await _owned(rdb_session_manager)
    registry = RuntimeWebOwnerSessionRegistry(
        session_manager=rdb_session_manager,
        repository=RuntimeWebSessionRouteRepository(),
        clock=_now,
    )
    assert await manager.release(released_owned)
    with pytest.raises(RuntimeWebSessionRouteConflict):
        await registry.accept(
            released_owned,
            _hello(released_owned),
            _evidence(released_owned),
        )


async def test_owner_registry_rejects_generation_replacement(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    _, owned = await _owned(rdb_session_manager)
    async with rdb_session_manager() as session:
        runtime = await session.get(RDBAgentRuntime, owned.offer.owner.runtime_id)
        assert runtime is not None
        runtime.runner_generation = 5
    registry = RuntimeWebOwnerSessionRegistry(
        session_manager=rdb_session_manager,
        repository=RuntimeWebSessionRouteRepository(),
        clock=_now,
    )

    with pytest.raises(RuntimeWebSessionRouteConflict):
        await registry.accept(owned, _hello(owned), _evidence(owned))


async def test_owner_registry_consumes_join_once_under_concurrency(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    _, owned = await _owned(rdb_session_manager)

    class JoinRepository:
        def __init__(self) -> None:
            self.lock = asyncio.Lock()
            self.first_entered = asyncio.Event()
            self.release_first = asyncio.Event()
            self.consumed = False

        async def consume_join(
            self,
            session: AsyncSession,
            *,
            runtime_id: str,
            owner_boot_id: str,
            session_lease_id: str,
            lease_generation: int,
            protocol_fingerprint: str,
            join_nonce_hash: str,
            join_deadline_at: datetime.datetime,
        ) -> RuntimeWebSessionRoute:
            del (
                session,
                runtime_id,
                owner_boot_id,
                session_lease_id,
                lease_generation,
                protocol_fingerprint,
                join_nonce_hash,
                join_deadline_at,
            )
            async with self.lock:
                if self.consumed:
                    raise RuntimeWebSessionRouteConflict("join consumed")
                self.first_entered.set()
                await self.release_first.wait()
                self.consumed = True
                return owned.route

    @contextlib.asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        yield AsyncMock(spec=AsyncSession)

    repository = JoinRepository()
    registry = RuntimeWebOwnerSessionRegistry(
        session_manager=session_manager,
        repository=repository,
        clock=_now,
    )
    first = asyncio.create_task(registry.accept(owned, _hello(owned), _evidence(owned)))
    second = asyncio.create_task(
        registry.accept(owned, _hello(owned), _evidence(owned))
    )
    await repository.first_entered.wait()
    repository.release_first.set()
    results = await asyncio.gather(first, second, return_exceptions=True)

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert (
        sum(isinstance(result, RuntimeWebSessionRouteConflict) for result in results)
        == 1
    )


async def test_owner_registry_rechecks_deadline_after_nonce_consumption(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    _, owned = await _owned(rdb_session_manager)
    current = [owned.offer.deadline_at - datetime.timedelta(seconds=1)]

    class JoinRepository:
        async def consume_join(
            self,
            session: AsyncSession,
            *,
            runtime_id: str,
            owner_boot_id: str,
            session_lease_id: str,
            lease_generation: int,
            protocol_fingerprint: str,
            join_nonce_hash: str,
            join_deadline_at: datetime.datetime,
        ) -> RuntimeWebSessionRoute:
            del (
                session,
                runtime_id,
                owner_boot_id,
                session_lease_id,
                lease_generation,
                protocol_fingerprint,
                join_nonce_hash,
                join_deadline_at,
            )
            current[0] = owned.offer.deadline_at
            return owned.route

    @contextlib.asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        yield AsyncMock(spec=AsyncSession)

    registry = RuntimeWebOwnerSessionRegistry(
        session_manager=session_manager,
        repository=JoinRepository(),
        clock=lambda: current[0],
    )

    with pytest.raises(ValueError, match="expired during join"):
        await registry.accept(owned, _hello(owned), _evidence(owned))
    assert not registry.sessions


async def test_owner_offer_deadline_never_exceeds_durable_lease(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    def future_clock() -> datetime.datetime:
        return _now() + datetime.timedelta(hours=1)

    _, owned = await _owned(rdb_session_manager, clock=future_clock)

    assert owned.offer.deadline_at == owned.route.lease_expires_at
