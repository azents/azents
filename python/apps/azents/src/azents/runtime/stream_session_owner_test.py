"""Inactive Runtime Web Owner session lifecycle tests."""

import asyncio
import dataclasses
import datetime
from collections.abc import Callable
from typing import NamedTuple
from unittest.mock import Mock

import pytest
from azents_runtime_control.proto import runtime_stream_session_pb2
from azents_runtime_control.runtime_stream_session import (
    APPROVED_SESSION_PROFILE,
    MANDATORY_DATA_FRAME_BYTES,
)

from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.runtime_stream_route import RuntimeStreamRouteOperationRepository
from azents.repos.runtime_stream_route_data import RuntimeStreamRouteEpoch
from azents.repos.runtime_stream_route_test import (
    consume,
    route_fixture,
    stored_route,
)
from azents.repos.runtime_web.data import RuntimeWebSessionRoute
from azents.repos.runtime_web.repository_test import _authority_fixture
from azents.repos.runtime_web.session_route_repository import (
    RuntimeWebSessionRouteConflict,
    RuntimeWebSessionRouteRepository,
)
from azents.runtime.stream_session_owner import (
    RuntimeStreamAcceptedRunnerSession,
    RuntimeStreamAuthenticatedRunnerConnection,
    RuntimeStreamOwnedSession,
    RuntimeStreamOwnerSessionRegistry,
    RuntimeStreamSessionOwnerManager,
)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class _OwnedSession(NamedTuple):
    manager: RuntimeStreamSessionOwnerManager
    session: RuntimeStreamOwnedSession


async def _owned(
    session_manager: SessionManager[WriteSession],
    *,
    clock: Callable[[], datetime.datetime] = _now,
) -> _OwnedSession:
    async with session_manager() as session:
        workspace_id, agent_id, _ = await _authority_fixture(session)
        runtime = RDBAgentRuntime(workspace_id=workspace_id, agent_id=agent_id)
        session.write_session.add(runtime)
        await session.write_session.flush()
        runtime.desired_generation = 3
        runtime.runner_generation = 4
        await session.write_session.flush()
        runtime_id = runtime.id
    manager = RuntimeStreamSessionOwnerManager(
        repository=RuntimeStreamRouteOperationRepository(
            session_manager=session_manager,
            route_repository=RuntimeWebSessionRouteRepository(),
        ),
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
    owned: RuntimeStreamOwnedSession,
    *,
    runner_boot_id: str = "runner-boot-a",
    maximum_data_frame_bytes: int = MANDATORY_DATA_FRAME_BYTES,
    deadline_at: datetime.datetime | None = None,
    request_stream_window_bytes: int | None = None,
) -> runtime_stream_session_pb2.RuntimeStreamSessionEnvelope:
    owner = owned.offer.owner
    hello = runtime_stream_session_pb2.RuntimeStreamSessionHello(
        role=runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PEER_ROLE_RUNNER,
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
    return runtime_stream_session_pb2.RuntimeStreamSessionEnvelope(
        protocol_fingerprint=owned.offer.protocol_fingerprint,
        session_id=owner.session_lease_id,
        peer_boot_id=runner_boot_id,
        owner_boot_id=owner.owner_boot_id,
        session_lease_id=owner.session_lease_id,
        lease_generation=owner.lease_generation,
        hello=hello,
    )


def _evidence(
    owned: RuntimeStreamOwnedSession,
    *,
    runner_boot_id: str = "runner-boot-a",
) -> RuntimeStreamAuthenticatedRunnerConnection:
    owner = owned.offer.owner
    return RuntimeStreamAuthenticatedRunnerConnection(
        runtime_id=owner.runtime_id,
        runner_boot_id=runner_boot_id,
        desired_generation=owner.desired_generation,
        runner_generation=owner.runner_generation,
    )


async def test_owner_registry_binds_authenticated_runner_boot(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    _, owned = await _owned(rdb_session_manager)
    registry = RuntimeStreamOwnerSessionRegistry(
        repository=RuntimeStreamRouteOperationRepository(
            session_manager=rdb_session_manager,
            route_repository=RuntimeWebSessionRouteRepository(),
        ),
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
    rdb_session_manager: SessionManager[WriteSession],
    maximum_data_frame_bytes: int,
    request_stream_window_bytes: int | None,
) -> None:
    _, owned = await _owned(rdb_session_manager)
    registry = RuntimeStreamOwnerSessionRegistry(
        repository=RuntimeStreamRouteOperationRepository(
            session_manager=rdb_session_manager,
            route_repository=RuntimeWebSessionRouteRepository(),
        ),
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
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    _, owned = await _owned(rdb_session_manager)
    registry = RuntimeStreamOwnerSessionRegistry(
        repository=RuntimeStreamRouteOperationRepository(
            session_manager=rdb_session_manager,
            route_repository=RuntimeWebSessionRouteRepository(),
        ),
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
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager, draining_owned = await _owned(rdb_session_manager)
    registry = RuntimeStreamOwnerSessionRegistry(
        repository=RuntimeStreamRouteOperationRepository(
            session_manager=rdb_session_manager,
            route_repository=RuntimeWebSessionRouteRepository(),
        ),
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
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    manager, released_owned = await _owned(rdb_session_manager)
    registry = RuntimeStreamOwnerSessionRegistry(
        repository=RuntimeStreamRouteOperationRepository(
            session_manager=rdb_session_manager,
            route_repository=RuntimeWebSessionRouteRepository(),
        ),
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
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    _, owned = await _owned(rdb_session_manager)
    async with rdb_session_manager() as session:
        runtime = await session.read_session.get(
            RDBAgentRuntime, owned.offer.owner.runtime_id
        )
        assert runtime is not None
        runtime.runner_generation = 5
    registry = RuntimeStreamOwnerSessionRegistry(
        repository=RuntimeStreamRouteOperationRepository(
            session_manager=rdb_session_manager,
            route_repository=RuntimeWebSessionRouteRepository(),
        ),
        clock=_now,
    )

    with pytest.raises(RuntimeWebSessionRouteConflict):
        await registry.accept(owned, _hello(owned), _evidence(owned))


async def test_owner_registry_consumes_join_once_under_concurrency(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Completed-operation synchronization tests local acceptance, not PG locking."""
    _, owned = await _owned(rdb_session_manager)

    class CompletedJoin:
        def __init__(self) -> None:
            self.lock = asyncio.Lock()
            self.first_entered = asyncio.Event()
            self.release_first = asyncio.Event()
            self.consumed = False

        async def consume_join(
            self,
            *,
            epoch: RuntimeStreamRouteEpoch,
            protocol_fingerprint: str,
            join_nonce_hash: str,
            join_deadline_at: datetime.datetime,
        ) -> RuntimeWebSessionRoute:
            del epoch, protocol_fingerprint, join_nonce_hash, join_deadline_at
            async with self.lock:
                if self.consumed:
                    raise RuntimeWebSessionRouteConflict("join consumed")
                self.first_entered.set()
                await self.release_first.wait()
                self.consumed = True
                return owned.route

    completed = CompletedJoin()
    repository: RuntimeStreamRouteOperationRepository = Mock(
        spec=RuntimeStreamRouteOperationRepository,
        wraps=completed,
    )
    registry = RuntimeStreamOwnerSessionRegistry(repository=repository, clock=_now)
    first = asyncio.create_task(registry.accept(owned, _hello(owned), _evidence(owned)))
    second = asyncio.create_task(
        registry.accept(owned, _hello(owned), _evidence(owned))
    )
    await completed.first_entered.wait()
    completed.release_first.set()
    results = await asyncio.gather(first, second, return_exceptions=True)
    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert (
        sum(isinstance(result, RuntimeWebSessionRouteConflict) for result in results)
        == 1
    )


async def test_owner_registry_rechecks_deadline_after_nonce_consumption(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Local expiry follows real committed nonce consumption, never rollback."""
    _, owned = await _owned(rdb_session_manager)
    current = [owned.offer.deadline_at - datetime.timedelta(seconds=1)]
    operation = RuntimeStreamRouteOperationRepository(
        rdb_session_manager,
        RuntimeWebSessionRouteRepository(),
    )

    async def consume_join(
        *,
        epoch: RuntimeStreamRouteEpoch,
        protocol_fingerprint: str,
        join_nonce_hash: str,
        join_deadline_at: datetime.datetime,
    ) -> RuntimeWebSessionRoute:
        route = await operation.consume_join(
            epoch=epoch,
            protocol_fingerprint=protocol_fingerprint,
            join_nonce_hash=join_nonce_hash,
            join_deadline_at=join_deadline_at,
        )
        current[0] = owned.offer.deadline_at
        return route

    repository: RuntimeStreamRouteOperationRepository = Mock(
        spec=RuntimeStreamRouteOperationRepository,
        consume_join=Mock(side_effect=consume_join),
    )
    registry = RuntimeStreamOwnerSessionRegistry(
        repository=repository, clock=lambda: current[0]
    )
    with pytest.raises(ValueError, match="expired during join"):
        await registry.accept(owned, _hello(owned), _evidence(owned))
    assert not registry.sessions
    with pytest.raises(RuntimeWebSessionRouteConflict):
        await operation.consume_join(
            epoch=RuntimeStreamRouteEpoch(
                runtime_id=owned.route.runtime_id,
                owner_boot_id=owned.route.owner_boot_id,
                session_lease_id=owned.route.session_lease_id,
                lease_generation=owned.route.lease_generation,
            ),
            protocol_fingerprint=owned.route.protocol_fingerprint,
            join_nonce_hash=owned.route.join_nonce_hash,
            join_deadline_at=owned.offer.deadline_at,
        )


async def test_owner_offer_deadline_never_exceeds_durable_lease(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    def future_clock() -> datetime.datetime:
        return _now() + datetime.timedelta(hours=1)

    _, owned = await _owned(rdb_session_manager, clock=future_clock)

    assert owned.offer.deadline_at == owned.route.lease_expires_at


@pytest.mark.parametrize("different_route_snapshot", [False, True])
async def test_owner_clock_and_local_acceptance_follow_completed_route_operations(
    rdb_session_manager: SessionManager[WriteSession],
    different_route_snapshot: bool,
) -> None:
    """The offer's original epoch, not a route snapshot, authorizes the join."""
    fixture = await route_fixture(rdb_session_manager, "owner-clock-closure")
    clocks: list[int] = []

    def clock() -> datetime.datetime:
        fixture.manager.assert_closed()
        clocks.append(len(fixture.manager.sessions))
        return _now()

    manager = RuntimeStreamSessionOwnerManager(
        repository=fixture.repository,
        owner_replica_id="control-a",
        owner_boot_id="owner-a",
        trusted_owner_address="control-a.internal:8032",
        lease_seconds=30,
        clock=clock,
    )
    owned = await manager.acquire(
        runtime_id=fixture.runtime_id, desired_generation=3, runner_generation=4
    )
    renewed = await manager.renew(owned)
    assert renewed.offer == owned.offer
    registry = RuntimeStreamOwnerSessionRegistry(
        repository=fixture.repository, clock=clock
    )
    offered = (
        dataclasses.replace(
            owned, route=owned.route.model_copy(update={"owner_boot_id": "snapshot"})
        )
        if different_route_snapshot
        else owned
    )
    accepted = await registry.accept(offered, _hello(owned), _evidence(owned))
    assert accepted.owner == owned.offer.owner
    assert clocks == [1, 2, 3]
    assert registry.sessions == {accepted.owner: accepted}
    row = await stored_route(fixture)
    assert row is not None and row.join_nonce_hash != owned.route.join_nonce_hash
    assert await registry.release(accepted)
    assert await manager.release(owned)
    fixture.manager.assert_closed()


@pytest.mark.parametrize("clock_failure", ["expired", "naive", "error", "cancel"])
async def test_postcommit_clock_failure_preserves_consumed_nonce_and_empty_registry(
    rdb_session_manager: SessionManager[WriteSession],
    clock_failure: str,
) -> None:
    fixture = await route_fixture(
        rdb_session_manager, f"owner-postcommit-{clock_failure}"
    )
    manager = RuntimeStreamSessionOwnerManager(
        repository=fixture.repository,
        owner_replica_id="control-a",
        owner_boot_id="owner-a",
        trusted_owner_address="control-a.internal:8032",
        lease_seconds=30,
        clock=_now,
    )
    owned = await manager.acquire(
        runtime_id=fixture.runtime_id, desired_generation=3, runner_generation=4
    )
    calls = 0

    def clock() -> datetime.datetime:
        nonlocal calls
        fixture.manager.assert_closed()
        calls += 1
        if calls == 1:
            return owned.offer.deadline_at - datetime.timedelta(seconds=1)
        if clock_failure == "expired":
            return owned.offer.deadline_at
        if clock_failure == "naive":
            return owned.offer.deadline_at.replace(tzinfo=None)
        if clock_failure == "cancel":
            raise asyncio.CancelledError("after committed nonce")
        raise RuntimeError("after committed nonce")

    registry = RuntimeStreamOwnerSessionRegistry(
        repository=fixture.repository, clock=clock
    )
    expected = (
        asyncio.CancelledError
        if clock_failure == "cancel"
        else RuntimeError
        if clock_failure == "error"
        else ValueError
    )
    with pytest.raises(expected):
        await registry.accept(owned, _hello(owned), _evidence(owned))
    assert calls == 2 and not registry.sessions
    current = await stored_route(fixture)
    assert current is not None
    assert current.join_nonce_hash != owned.route.join_nonce_hash
    with pytest.raises(RuntimeWebSessionRouteConflict):
        await consume(fixture, owned.route)
    assert await manager.release(owned)
    fixture.manager.assert_closed()


async def test_acquire_clock_error_preserves_already_committed_owner_lease(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await route_fixture(rdb_session_manager, "owner-acquire-clock-error")

    def naive_clock() -> datetime.datetime:
        fixture.manager.assert_closed()
        return _now().replace(tzinfo=None)

    manager = RuntimeStreamSessionOwnerManager(
        repository=fixture.repository,
        owner_replica_id="control-a",
        owner_boot_id="owner-a",
        trusted_owner_address="control-a.internal:8032",
        lease_seconds=30,
        clock=naive_clock,
    )
    with pytest.raises(ValueError, match="Owner clock must be timezone-aware"):
        await manager.acquire(
            runtime_id=fixture.runtime_id, desired_generation=3, runner_generation=4
        )
    current = await stored_route(fixture)
    assert current is not None and current.owner_boot_id == "owner-a"
    fixture.manager.assert_closed()


async def test_duplicate_local_join_fails_after_committed_nonce_consumption(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    fixture = await route_fixture(rdb_session_manager, "owner-duplicate-join")
    manager = RuntimeStreamSessionOwnerManager(
        repository=fixture.repository,
        owner_replica_id="control-a",
        owner_boot_id="owner-a",
        trusted_owner_address="control-a.internal:8032",
        lease_seconds=30,
        clock=_now,
    )
    owned = await manager.acquire(
        runtime_id=fixture.runtime_id, desired_generation=3, runner_generation=4
    )
    registry = RuntimeStreamOwnerSessionRegistry(
        repository=fixture.repository, clock=_now
    )
    previous = RuntimeStreamAcceptedRunnerSession(
        owner=owned.offer.owner,
        runner_boot_id="previous-local-runner",
        profile=APPROVED_SESSION_PROFILE,
        connected_at=_now(),
    )
    registry.sessions[previous.owner] = previous
    with pytest.raises(ValueError, match="already joined"):
        await registry.accept(owned, _hello(owned), _evidence(owned))
    assert registry.sessions == {previous.owner: previous}
    current = await stored_route(fixture)
    assert current is not None
    assert current.join_nonce_hash != owned.route.join_nonce_hash
    fixture.manager.assert_closed()
