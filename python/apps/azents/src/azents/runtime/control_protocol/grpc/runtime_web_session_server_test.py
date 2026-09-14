"""Persistent Runtime Web Control data-plane tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import AsyncContextManager

import pytest
from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_capacity import CapacityProfile
from azents_runtime_control.runtime_web_session import (
    APPROVED_SESSION_PROFILE,
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    OwnerSessionEpoch,
)
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.repos.runtime_web.data import RuntimeWebSessionRoute
from azents.repos.runtime_web.session_route_repository import (
    RuntimeWebSessionRouteRepository,
)
from azents.runtime.control_protocol.grpc.runtime_web_session_server import (
    RuntimeWebCapacityBackend,
    RuntimeWebCapacityConfig,
    RuntimeWebCapacityRegistry,
    RuntimeWebControlDataPlane,
    RuntimeWebGatewaySessionGrpcServicer,
    RuntimeWebTrustedPeerAuthenticator,
    _BoundedEnvelopeQueue,
    _renew_owner_session,
    _RunnerConnection,
    _SourceSession,
)
from azents.runtime.coordination.data import RuntimeSystemMetricsSample
from azents.runtime.web_session_owner import (
    RuntimeWebAcceptedRunnerSession,
    RuntimeWebOwnedSession,
)
from azents.runtime.web_session_relay import (
    PersistentRelayConnection,
    RelaySessionKey,
    RuntimeWebRelayPool,
)
from azents.testing.grpc import FakeGrpcContext


class _Redis:
    def __init__(self, *, failed: bool = False) -> None:
        self.failed = failed
        self.values: dict[str, str] = {}

    async def get(self, name: str) -> bytes | str | None:
        if self.failed:
            raise RedisConnectionError("unavailable")
        return self.values.get(name)

    async def set(self, name: str, value: str, *, ex: int) -> object:
        del ex
        if self.failed:
            raise RedisConnectionError("unavailable")
        self.values[name] = value
        return True


class _UnusedSessionManager:
    def __call__(self) -> AsyncContextManager[AsyncSession]:
        return _unused_session()


@asynccontextmanager
async def _unused_session() -> AsyncIterator[AsyncSession]:
    raise AssertionError("database access was not expected")
    yield AsyncSession()


class _UnusedRelayConnector:
    async def __call__(
        self,
        key: RelaySessionKey,
    ) -> PersistentRelayConnection:
        del key
        raise AssertionError("relay connection was not expected")


class _RunnerMetrics:
    async def read_runner_system_metrics(
        self,
        *,
        runtime_id: str,
        generation: int,
        current_time: datetime,
    ) -> list[RuntimeSystemMetricsSample]:
        del runtime_id, generation, current_time
        return []


class _OwnerLifecycle:
    def __init__(self, *, renew_results: tuple[bool, ...] = ()) -> None:
        self.renew_results = list(renew_results)
        self.renewed: list[OwnerSessionEpoch] = []
        self.draining: list[OwnerSessionEpoch] = []
        self.released: list[OwnerSessionEpoch] = []

    async def owned_for_runner(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
    ) -> RuntimeWebOwnedSession | None:
        del runtime_id, runner_generation
        return None

    async def renew_owner(self, owner: OwnerSessionEpoch) -> bool:
        self.renewed.append(owner)
        return self.renew_results.pop(0) if self.renew_results else True

    async def mark_owner_draining(self, owner: OwnerSessionEpoch) -> bool:
        self.draining.append(owner)
        return True

    async def release_owner(self, owner: OwnerSessionEpoch) -> bool:
        self.released.append(owner)
        return True


class _RouteRepository(RuntimeWebSessionRouteRepository):
    def __init__(self, route: RuntimeWebSessionRoute) -> None:
        self.route = route

    async def resolve(
        self,
        session: AsyncSession,
        *,
        runtime_id: str,
        desired_generation: int,
        runner_generation: int,
        protocol_fingerprint: str,
    ) -> RuntimeWebSessionRoute | None:
        del session
        if (
            runtime_id,
            desired_generation,
            runner_generation,
            protocol_fingerprint,
        ) != (
            self.route.runtime_id,
            self.route.desired_generation,
            self.route.runner_generation,
            self.route.protocol_fingerprint,
        ):
            return None
        return self.route


class _RouteSessionManager:
    def __call__(self) -> AsyncContextManager[AsyncSession]:
        return _route_session()


@asynccontextmanager
async def _route_session() -> AsyncIterator[AsyncSession]:
    yield AsyncSession()


def _capacity_config(
    backend: RuntimeWebCapacityBackend = RuntimeWebCapacityBackend.MEMORY,
    *,
    burst_bytes: int = 64 * 1024 * 1024,
) -> RuntimeWebCapacityConfig:
    return RuntimeWebCapacityConfig(
        backend=backend,
        profile=CapacityProfile(
            maximum_active_streams=64,
            maximum_sse_streams=8,
            maximum_websocket_streams=8,
            maximum_pending_opens=64,
            maximum_buffer_bytes=64 * 1024 * 1024,
            inbound_bytes_per_second=1024 * 1024 * 1024,
            outbound_bytes_per_second=1024 * 1024 * 1024,
            burst_bytes=burst_bytes,
        ),
        redis_namespace="runtime-web-test",
        redis_ttl_seconds=30,
    )


def _owner() -> OwnerSessionEpoch:
    return OwnerSessionEpoch(
        owner_boot_id="owner-boot",
        session_lease_id="owner-lease",
        lease_generation=1,
        runtime_id="runtime",
        desired_generation=1,
        runner_generation=1,
    )


def _data_plane() -> RuntimeWebControlDataPlane:
    capacity = RuntimeWebCapacityRegistry(
        config=_capacity_config(),
        redis=_Redis(),
        monotonic_clock_milliseconds=lambda: 0,
        recoverable_errors=(RedisConnectionError,),
    )
    relay = RuntimeWebRelayPool(
        connector=_UnusedRelayConnector(),
        maximum_sessions=1,
        peer_boot_id="control-boot",
    )
    return RuntimeWebControlDataPlane(
        session_manager=_UnusedSessionManager(),
        route_repository=RuntimeWebSessionRouteRepository(),
        owner_replica_id="control-a",
        control_boot_id="control-boot",
        capacity_registry=capacity,
        relay_pool=relay,
        runner_metrics=_RunnerMetrics(),
        clock=lambda: datetime.now(UTC),
        metrics_recoverable_errors=(RedisConnectionError,),
        owner_lifecycle=_OwnerLifecycle(),
        long_lived_grace_seconds=0.01,
        finite_grace_seconds=0.02,
    )


def _local_data_plane(
    *,
    lifecycle: _OwnerLifecycle | None = None,
    capacity_config: RuntimeWebCapacityConfig | None = None,
) -> tuple[RuntimeWebControlDataPlane, _OwnerLifecycle]:
    owner = _owner()
    route = RuntimeWebSessionRoute(
        runtime_id=owner.runtime_id,
        desired_generation=owner.desired_generation,
        runner_generation=owner.runner_generation,
        owner_replica_id="control-a",
        owner_boot_id=owner.owner_boot_id,
        owner_address="control-a:8032",
        session_lease_id=owner.session_lease_id,
        lease_generation=owner.lease_generation,
        join_nonce_hash="a" * 64,
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
        draining_at=None,
    )
    capacity = RuntimeWebCapacityRegistry(
        config=capacity_config or _capacity_config(),
        redis=_Redis(),
        monotonic_clock_milliseconds=lambda: 0,
        recoverable_errors=(RedisConnectionError,),
    )
    relay = RuntimeWebRelayPool(
        connector=_UnusedRelayConnector(),
        maximum_sessions=1,
        peer_boot_id="control-boot",
    )
    effective_lifecycle = lifecycle or _OwnerLifecycle()
    return (
        RuntimeWebControlDataPlane(
            session_manager=_RouteSessionManager(),
            route_repository=_RouteRepository(route),
            owner_replica_id="control-a",
            control_boot_id="control-boot",
            capacity_registry=capacity,
            relay_pool=relay,
            runner_metrics=_RunnerMetrics(),
            clock=lambda: datetime.now(UTC),
            metrics_recoverable_errors=(RedisConnectionError,),
            owner_lifecycle=effective_lifecycle,
            long_lived_grace_seconds=0.01,
            finite_grace_seconds=0.02,
        ),
        effective_lifecycle,
    )


def _open_envelope(
    *,
    session_id: str,
    peer_boot_id: str,
    stream_id: int,
) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    now = datetime.now(UTC)
    authority = runtime_web_session_pb2.RuntimeWebSessionAuthority(
        correlation_id="correlation",
        endpoint_id="endpoint",
        cycle_id="cycle",
        endpoint_authority_revision=1,
        close_barrier=1,
        identity_id="identity",
        authentication_session_id="authentication",
        user_id="user",
        agent_session_id="agent-session",
        runtime_id="runtime",
        desired_generation=1,
        runner_generation=1,
        port=8765,
    )
    authority.open_deadline_at.FromDatetime(now + timedelta(seconds=10))
    authority.transport_deadline_at.FromDatetime(now + timedelta(minutes=1))
    authority.approval_deadline_at.FromDatetime(now + timedelta(hours=1))
    return runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=session_id,
        peer_boot_id=peer_boot_id,
        stream_id=stream_id,
        open=runtime_web_session_pb2.RuntimeWebSessionOpen(
            authority=authority,
            request_head=runtime_web_session_pb2.RuntimeWebSessionRequestHead(
                protocol=runtime_web_session_pb2.RUNTIME_WEB_SESSION_PROTOCOL_HTTP,
                method=b"GET",
                target=b"/",
            ),
        ),
    )


def _hello() -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    deadline = datetime.now(UTC) + timedelta(seconds=10)
    hello = runtime_web_session_pb2.RuntimeWebSessionHello(
        role=runtime_web_session_pb2.RUNTIME_WEB_SESSION_PEER_ROLE_GATEWAY,
        session_nonce="nonce",
        maximum_data_frame_bytes=APPROVED_SESSION_PROFILE.data_frame_bytes,
        request_stream_window_bytes=(
            APPROVED_SESSION_PROFILE.request_stream_window_bytes
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
    hello.deadline_at.FromDatetime(deadline)
    return runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        hello=hello,
    )


@pytest.mark.asyncio
async def test_gateway_servicer_accepts_exact_replacement_handshake() -> None:
    data_plane = _data_plane()
    servicer = RuntimeWebGatewaySessionGrpcServicer(
        data_plane=data_plane,
        peers=RuntimeWebTrustedPeerAuthenticator(
            allow_insecure=True,
            gateway_identities=frozenset(),
            control_identities=frozenset(),
        ),
        clock=lambda: datetime.now(UTC),
    )

    async def messages() -> AsyncIterator[
        runtime_web_session_pb2.RuntimeWebSessionEnvelope
    ]:
        yield _hello()
        await asyncio.Event().wait()

    responses = servicer.Connect(
        messages(),
        FakeGrpcContext[
            runtime_web_session_pb2.RuntimeWebSessionEnvelope,
            runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        ](),
    )
    accepted = await asyncio.wait_for(anext(responses), timeout=1)

    assert accepted.WhichOneof("payload") == "session_accepted"
    assert accepted.protocol_fingerprint == RUNTIME_WEB_PROTOCOL_FINGERPRINT
    assert accepted.session_id == "gateway-session"
    assert accepted.peer_boot_id == "control-boot"
    assert await data_plane.subready() is False
    source = next(iter(data_plane.sources.values()))
    await data_plane.unregister_source(source)
    with pytest.raises(StopAsyncIteration):
        await anext(responses)
    await data_plane.close()


@pytest.mark.asyncio
async def test_gateway_servicer_rejects_session_registered_after_global_drain() -> None:
    data_plane = _data_plane()
    await data_plane.begin_drain()
    servicer = RuntimeWebGatewaySessionGrpcServicer(
        data_plane=data_plane,
        peers=RuntimeWebTrustedPeerAuthenticator(
            allow_insecure=True,
            gateway_identities=frozenset(),
            control_identities=frozenset(),
        ),
        clock=lambda: datetime.now(UTC),
    )

    async def messages() -> AsyncIterator[
        runtime_web_session_pb2.RuntimeWebSessionEnvelope
    ]:
        yield _hello()

    responses = servicer.Connect(
        messages(),
        FakeGrpcContext[
            runtime_web_session_pb2.RuntimeWebSessionEnvelope,
            runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        ](),
    )

    with pytest.raises(
        RuntimeError,
        match="UNAVAILABLE: Runtime Web Control is draining",
    ):
        await anext(responses)
    assert data_plane.sources == {}
    assert data_plane.bindings == {}
    await data_plane.close()


@pytest.mark.asyncio
async def test_gateway_goaway_refuses_new_stream_without_database_access() -> None:
    data_plane = _data_plane()
    source = await data_plane.register_source(
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        owner=None,
    )
    go_away = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        go_away=runtime_web_session_pb2.RuntimeWebSessionGoAway(
            last_accepted_stream_id=0,
            reason=(
                runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_SERVICE_DRAIN
            ),
        ),
    )
    await data_plane.handle(source, go_away)
    opening = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        stream_id=1,
        open=runtime_web_session_pb2.RuntimeWebSessionOpen(),
    )
    await data_plane.handle(source, opening)
    responses = source.queue.__aiter__()
    rejected = await anext(responses)

    assert rejected.WhichOneof("payload") == "open_rejected"
    assert rejected.open_rejected.reason == (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_SERVICE_DRAIN
    )
    await data_plane.unregister_source(source)
    await data_plane.close()


@pytest.mark.asyncio
async def test_global_drain_wins_open_registration_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_plane, _lifecycle = _local_data_plane()
    owner = _owner()
    accepted = RuntimeWebAcceptedRunnerSession(
        owner=owner,
        runner_boot_id="runner-boot",
        profile=APPROVED_SESSION_PROFILE,
        connected_at=datetime.now(UTC),
    )
    runner = await data_plane.register_runner(accepted)
    source = await data_plane.register_source(
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        owner=None,
    )
    resolve_started = asyncio.Event()
    allow_resolve = asyncio.Event()
    original_resolve = data_plane._resolve_route

    async def gated_resolve(
        *,
        runtime_id: str,
        desired_generation: int,
        runner_generation: int,
    ) -> RuntimeWebSessionRoute | None:
        resolve_started.set()
        await allow_resolve.wait()
        return await original_resolve(
            runtime_id=runtime_id,
            desired_generation=desired_generation,
            runner_generation=runner_generation,
        )

    monkeypatch.setattr(data_plane, "_resolve_route", gated_resolve)
    opening = asyncio.create_task(
        data_plane.handle(
            source,
            _open_envelope(
                session_id="gateway-session",
                peer_boot_id="gateway-boot",
                stream_id=1,
            ),
        )
    )
    await resolve_started.wait()

    await data_plane.begin_drain()
    allow_resolve.set()
    await opening

    source_messages = source.queue.__aiter__()
    go_away = await anext(source_messages)
    rejected = await anext(source_messages)
    assert go_away.WhichOneof("payload") == "go_away"
    assert rejected.WhichOneof("payload") == "open_rejected"
    assert rejected.open_rejected.reason == (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_SERVICE_DRAIN
    )
    assert [queued.envelope.WhichOneof("payload") for queued in runner.queue.items] == [
        "go_away"
    ]
    assert data_plane.bindings == {}
    snapshots = await data_plane.capacity_registry.snapshots()
    assert all(snapshot.active_streams == 0 for snapshot in snapshots)

    await data_plane.unregister_source(source)
    await data_plane.unregister_runner(accepted)
    await data_plane.close()


@pytest.mark.asyncio
async def test_redis_capacity_loss_degrades_to_equivalent_memory_state() -> None:
    registry = RuntimeWebCapacityRegistry(
        config=_capacity_config(RuntimeWebCapacityBackend.REDIS),
        redis=_Redis(failed=True),
        monotonic_clock_milliseconds=lambda: 0,
        recoverable_errors=(RedisConnectionError,),
    )

    capacity = await registry.get(_owner())

    assert await capacity.begin_open(1)
    snapshot = await capacity.snapshot()
    assert snapshot.pending_opens == 1
    assert snapshot.degraded


@pytest.mark.asyncio
async def test_control_metrics_are_bounded_and_content_free() -> None:
    data_plane = _data_plane()
    first = await data_plane.register_source(
        session_id="gateway-a",
        peer_boot_id="gateway-boot-a",
        owner=None,
    )
    second = await data_plane.register_source(
        session_id="owner-lease",
        peer_boot_id="relay-boot",
        owner=_owner(),
    )

    rendered = await data_plane.metrics()

    assert 'role="gateway"} 1' in rendered
    assert 'role="relay"} 1' in rendered
    assert "runtime_web_control_capacity_degraded 0" in rendered
    for forbidden in ("runtime_id=", "session_id=", "path=", "query=", "user="):
        assert forbidden not in rendered
    await data_plane.unregister_source(first)
    await data_plane.unregister_source(second)
    await data_plane.close()


@pytest.mark.asyncio
async def test_multiple_relays_to_one_owner_use_distinct_composite_sources() -> None:
    data_plane = _data_plane()

    first = await data_plane.register_source(
        session_id="owner-lease",
        peer_boot_id="relay-a",
        owner=_owner(),
    )
    second = await data_plane.register_source(
        session_id="owner-lease",
        peer_boot_id="relay-b",
        owner=_owner(),
    )

    assert first.source_key != second.source_key
    await data_plane.unregister_source(first)
    await data_plane.unregister_source(second)
    await data_plane.close()


@pytest.mark.asyncio
async def test_runner_connection_translates_hop_local_session_credit() -> None:
    owner = _owner()
    accepted = RuntimeWebAcceptedRunnerSession(
        owner=owner,
        runner_boot_id="runner-boot",
        profile=APPROVED_SESSION_PROFILE,
        connected_at=datetime.now(UTC),
    )
    connection = _RunnerConnection(
        accepted=accepted,
        control_boot_id="control-boot",
    )
    first = _SourceSession(
        source_key="gateway-a",
        session_id="gateway-a",
        peer_boot_id="gateway-boot",
        owner=None,
        queue=connection.queue.__class__(),
    )
    second = _SourceSession(
        source_key="gateway-b",
        session_id="gateway-b",
        peer_boot_id="gateway-boot",
        owner=None,
        queue=connection.queue.__class__(),
    )
    first_runner_stream = await connection.send(
        first,
        _open_envelope(
            session_id="gateway-a", peer_boot_id="gateway-boot", stream_id=1
        ),
    )
    second_runner_stream = await connection.send(
        second,
        _open_envelope(
            session_id="gateway-b", peer_boot_id="gateway-boot", stream_id=2
        ),
    )
    runner_messages = connection.queue.__aiter__()
    await anext(runner_messages)
    await anext(runner_messages)

    first_response_credit = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id="gateway-a",
        peer_boot_id="gateway-boot",
        stream_id=1,
    )
    first_response_credit.window_update.direction = (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE
    )
    first_response_credit.window_update.stream_consumed_total = 5
    first_response_credit.window_update.session_consumed_total = 5
    await connection.send(first, first_response_credit)
    second_response_credit = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id="gateway-b",
        peer_boot_id="gateway-boot",
        stream_id=2,
    )
    second_response_credit.window_update.direction = (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE
    )
    second_response_credit.window_update.stream_consumed_total = 3
    second_response_credit.window_update.session_consumed_total = 3
    await connection.send(second, second_response_credit)

    assert (await anext(runner_messages)).window_update.session_consumed_total == 5
    assert (await anext(runner_messages)).window_update.session_consumed_total == 8

    first_request_credit = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=owner.session_lease_id,
        peer_boot_id="runner-boot",
        owner_boot_id=owner.owner_boot_id,
        session_lease_id=owner.session_lease_id,
        lease_generation=owner.lease_generation,
        stream_id=first_runner_stream,
    )
    first_request_credit.window_update.direction = (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
    )
    first_request_credit.window_update.stream_consumed_total = 5
    first_request_credit.window_update.session_consumed_total = 5
    await connection.receive(first_request_credit)
    second_request_credit = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=owner.session_lease_id,
        peer_boot_id="runner-boot",
        owner_boot_id=owner.owner_boot_id,
        session_lease_id=owner.session_lease_id,
        lease_generation=owner.lease_generation,
        stream_id=second_runner_stream,
    )
    second_request_credit.window_update.direction = (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
    )
    second_request_credit.window_update.stream_consumed_total = 3
    second_request_credit.window_update.session_consumed_total = 8
    await connection.receive(second_request_credit)

    assert (
        await anext(first.queue.__aiter__())
    ).window_update.session_consumed_total == 5
    assert (
        await anext(second.queue.__aiter__())
    ).window_update.session_consumed_total == 3
    await connection.close()
    await first.queue.close()
    await second.queue.close()


@pytest.mark.asyncio
async def test_runner_connection_enqueues_concurrent_opens_in_stream_id_order() -> None:
    class _FirstPutGateQueue(_BoundedEnvelopeQueue):
        def __init__(self) -> None:
            super().__init__()
            self.first_put_started = asyncio.Event()
            self.release_first_put = asyncio.Event()
            self.put_attempts = 0

        async def put(
            self,
            envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
            *,
            on_dequeued: Callable[[], Awaitable[None]] | None = None,
        ) -> None:
            self.put_attempts += 1
            if self.put_attempts == 1:
                self.first_put_started.set()
                await self.release_first_put.wait()
            await super().put(envelope, on_dequeued=on_dequeued)

    owner = _owner()
    connection = _RunnerConnection(
        accepted=RuntimeWebAcceptedRunnerSession(
            owner=owner,
            runner_boot_id="runner-boot",
            profile=APPROVED_SESSION_PROFILE,
            connected_at=datetime.now(UTC),
        ),
        control_boot_id="control-boot",
    )
    queue = _FirstPutGateQueue()
    connection.queue = queue
    first = _SourceSession(
        source_key="gateway-a",
        session_id="gateway-a",
        peer_boot_id="gateway-boot",
        owner=None,
        queue=_BoundedEnvelopeQueue(),
    )
    second = _SourceSession(
        source_key="gateway-b",
        session_id="gateway-b",
        peer_boot_id="gateway-boot",
        owner=None,
        queue=_BoundedEnvelopeQueue(),
    )

    first_send = asyncio.create_task(
        connection.send(
            first,
            _open_envelope(
                session_id="gateway-a",
                peer_boot_id="gateway-boot",
                stream_id=1,
            ),
        )
    )
    await queue.first_put_started.wait()

    second_send_started = asyncio.Event()

    async def send_second() -> int:
        second_send_started.set()
        return await connection.send(
            second,
            _open_envelope(
                session_id="gateway-b",
                peer_boot_id="gateway-boot",
                stream_id=1,
            ),
        )

    second_send = asyncio.create_task(send_second())
    await second_send_started.wait()
    assert queue.put_attempts == 1

    queue.release_first_put.set()
    first_stream_id, second_stream_id = await asyncio.gather(first_send, second_send)
    runner_messages = queue.__aiter__()
    first_message = await anext(runner_messages)
    second_message = await anext(runner_messages)

    assert (first_stream_id, second_stream_id) == (1, 2)
    assert (first_message.stream_id, second_message.stream_id) == (1, 2)

    await connection.close()
    await first.queue.close()
    await second.queue.close()


@pytest.mark.asyncio
async def test_relay_runner_round_trip_restores_source_stream_and_epoch() -> None:
    data_plane, _lifecycle = _local_data_plane()
    owner = _owner()
    accepted = RuntimeWebAcceptedRunnerSession(
        owner=owner,
        runner_boot_id="runner-boot",
        profile=APPROVED_SESSION_PROFILE,
        connected_at=datetime.now(UTC),
    )
    runner = await data_plane.register_runner(accepted)
    source = await data_plane.register_source(
        session_id=owner.session_lease_id,
        peer_boot_id="accepting-control",
        owner=owner,
    )
    await data_plane.handle(
        source,
        _open_envelope(
            session_id=owner.session_lease_id,
            peer_boot_id="accepting-control",
            stream_id=41,
        ),
    )
    runner_messages = runner.queue.__aiter__()
    forwarded = await anext(runner_messages)
    response = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=owner.session_lease_id,
        peer_boot_id="runner-boot",
        owner_boot_id=owner.owner_boot_id,
        session_lease_id=owner.session_lease_id,
        lease_generation=owner.lease_generation,
        stream_id=forwarded.stream_id,
        open_accepted=runtime_web_session_pb2.RuntimeWebSessionOpenAccepted(
            data_frame_bytes=APPROVED_SESSION_PROFILE.data_frame_bytes,
            request_credit_bytes=1024,
            response_credit_bytes=1024,
        ),
    )
    await data_plane.runner_response(response)
    source_messages = source.queue.__aiter__()
    translated = await anext(source_messages)

    assert translated.stream_id == 41
    assert translated.session_id == owner.session_lease_id
    assert translated.peer_boot_id == owner.owner_boot_id
    assert translated.owner_boot_id == owner.owner_boot_id
    assert translated.session_lease_id == owner.session_lease_id
    assert translated.lease_generation == owner.lease_generation

    await data_plane.unregister_runner(accepted)
    reset = await anext(source_messages)
    assert reset.stream_id == 41
    assert reset.owner_boot_id == owner.owner_boot_id
    assert reset.session_lease_id == owner.session_lease_id
    assert reset.lease_generation == owner.lease_generation
    await data_plane.unregister_source(source)
    await data_plane.close()


@pytest.mark.asyncio
async def test_runner_late_response_to_closed_source_releases_only_its_stream() -> None:
    data_plane, _lifecycle = _local_data_plane()
    owner = _owner()
    accepted = RuntimeWebAcceptedRunnerSession(
        owner=owner,
        runner_boot_id="runner-boot",
        profile=APPROVED_SESSION_PROFILE,
        connected_at=datetime.now(UTC),
    )
    runner = await data_plane.register_runner(accepted)
    source = await data_plane.register_source(
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        owner=None,
    )
    await data_plane.handle(
        source,
        _open_envelope(
            session_id="gateway-session",
            peer_boot_id="gateway-boot",
            stream_id=1,
        ),
    )
    forwarded = await anext(runner.queue.__aiter__())
    await source.queue.close()
    response = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=owner.session_lease_id,
        peer_boot_id="runner-boot",
        owner_boot_id=owner.owner_boot_id,
        session_lease_id=owner.session_lease_id,
        lease_generation=owner.lease_generation,
        stream_id=forwarded.stream_id,
        open_accepted=runtime_web_session_pb2.RuntimeWebSessionOpenAccepted(
            data_frame_bytes=APPROVED_SESSION_PROFILE.data_frame_bytes,
            request_credit_bytes=(APPROVED_SESSION_PROFILE.request_stream_window_bytes),
            response_credit_bytes=(
                APPROVED_SESSION_PROFILE.response_stream_window_bytes
            ),
        ),
    )

    await data_plane.runner_response(response)

    assert owner in data_plane.runners
    assert data_plane.bindings == {}
    await data_plane.unregister_source(source)
    await data_plane.unregister_runner(accepted)
    await data_plane.close()


@pytest.mark.asyncio
async def test_relay_late_response_to_closed_source_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_plane = _data_plane()
    source = await data_plane.register_source(
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        owner=None,
    )
    translated = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=source.session_id,
        peer_boot_id="control-boot",
        stream_id=1,
        open_accepted=runtime_web_session_pb2.RuntimeWebSessionOpenAccepted(
            data_frame_bytes=APPROVED_SESSION_PROFILE.data_frame_bytes,
            request_credit_bytes=(APPROVED_SESSION_PROFILE.request_stream_window_bytes),
            response_credit_bytes=(
                APPROVED_SESSION_PROFILE.response_stream_window_bytes
            ),
        ),
    )

    async def route_response(
        *,
        key: RelaySessionKey,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
        del key, envelope
        return translated

    monkeypatch.setattr(data_plane.relay_pool, "route_response", route_response)
    await source.queue.close()

    await data_plane.relay_response(
        RelaySessionKey(_owner(), RUNTIME_WEB_PROTOCOL_FINGERPRINT),
        runtime_web_session_pb2.RuntimeWebSessionEnvelope(),
    )

    await data_plane.unregister_source(source)
    await data_plane.close()


@pytest.mark.asyncio
async def test_owner_capacity_tracks_buffer_until_runner_queue_dequeue() -> None:
    data_plane, _lifecycle = _local_data_plane()
    owner = _owner()
    accepted = RuntimeWebAcceptedRunnerSession(
        owner=owner,
        runner_boot_id="runner-boot",
        profile=APPROVED_SESSION_PROFILE,
        connected_at=datetime.now(UTC),
    )
    runner = await data_plane.register_runner(accepted)
    source = await data_plane.register_source(
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        owner=None,
    )
    await data_plane.handle(
        source,
        _open_envelope(
            session_id="gateway-session",
            peer_boot_id="gateway-boot",
            stream_id=1,
        ),
    )
    runner_messages = runner.queue.__aiter__()
    await anext(runner_messages)
    data = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        stream_id=1,
        frame_sequence=1,
        data=runtime_web_session_pb2.RuntimeWebSessionData(
            direction=runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST,
            data=b"x" * 512,
        ),
    )
    await data_plane.handle(source, data)
    snapshot = (await data_plane.capacity_registry.snapshots())[0]
    assert snapshot.buffer_bytes == 512
    await anext(runner_messages)
    snapshot = (await data_plane.capacity_registry.snapshots())[0]
    assert snapshot.buffer_bytes == 0
    await data_plane.unregister_source(source)
    await data_plane.unregister_runner(accepted)
    await data_plane.close()


@pytest.mark.asyncio
async def test_capacity_rejection_resets_runner_and_ignores_late_output() -> None:
    data_plane, _lifecycle = _local_data_plane(
        capacity_config=_capacity_config(burst_bytes=1)
    )
    owner = _owner()
    accepted = RuntimeWebAcceptedRunnerSession(
        owner=owner,
        runner_boot_id="runner-boot",
        profile=APPROVED_SESSION_PROFILE,
        connected_at=datetime.now(UTC),
    )
    runner = await data_plane.register_runner(accepted)
    source = await data_plane.register_source(
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        owner=None,
    )
    await data_plane.handle(
        source,
        _open_envelope(
            session_id="gateway-session",
            peer_boot_id="gateway-boot",
            stream_id=1,
        ),
    )
    runner_messages = runner.queue.__aiter__()
    forwarded = await anext(runner_messages)
    await data_plane.handle(
        source,
        runtime_web_session_pb2.RuntimeWebSessionEnvelope(
            protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
            session_id="gateway-session",
            peer_boot_id="gateway-boot",
            stream_id=1,
            frame_sequence=1,
            data=runtime_web_session_pb2.RuntimeWebSessionData(
                direction=(
                    runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_REQUEST
                ),
                data=b"x" * 512,
            ),
        ),
    )
    runner_reset = await anext(runner_messages)
    source_reset = await anext(source.queue.__aiter__())
    assert runner_reset.stream_id == forwarded.stream_id
    assert runner_reset.WhichOneof("payload") == "reset"
    assert source_reset.stream_id == 1
    assert source_reset.WhichOneof("payload") == "reset"

    late = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=owner.session_lease_id,
        peer_boot_id="runner-boot",
        owner_boot_id=owner.owner_boot_id,
        session_lease_id=owner.session_lease_id,
        lease_generation=owner.lease_generation,
        stream_id=forwarded.stream_id,
        frame_sequence=1,
        data=runtime_web_session_pb2.RuntimeWebSessionData(
            direction=(runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE),
            data=b"late",
        ),
    )
    await data_plane.runner_response(late)
    await data_plane.unregister_source(source)
    await data_plane.unregister_runner(accepted)
    await data_plane.close()


@pytest.mark.asyncio
async def test_late_terminal_credit_does_not_stop_sequential_opens() -> None:
    data_plane, _lifecycle = _local_data_plane()
    owner = _owner()
    accepted = RuntimeWebAcceptedRunnerSession(
        owner=owner,
        runner_boot_id="runner-boot",
        profile=APPROVED_SESSION_PROFILE,
        connected_at=datetime.now(UTC),
    )
    runner = await data_plane.register_runner(accepted)
    source = await data_plane.register_source(
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        owner=None,
    )
    runner_messages = runner.queue.__aiter__()
    await data_plane.handle(
        source,
        _open_envelope(
            session_id="gateway-session",
            peer_boot_id="gateway-boot",
            stream_id=1,
        ),
    )
    first = await anext(runner_messages)
    await data_plane.runner_response(
        runtime_web_session_pb2.RuntimeWebSessionEnvelope(
            protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
            session_id=owner.session_lease_id,
            peer_boot_id="runner-boot",
            owner_boot_id=owner.owner_boot_id,
            session_lease_id=owner.session_lease_id,
            lease_generation=owner.lease_generation,
            stream_id=first.stream_id,
            stream_end=runtime_web_session_pb2.RuntimeWebSessionStreamEnd(),
        )
    )
    await anext(source.queue.__aiter__())
    await data_plane.handle(
        source,
        runtime_web_session_pb2.RuntimeWebSessionEnvelope(
            protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
            session_id="gateway-session",
            peer_boot_id="gateway-boot",
            stream_id=1,
            window_update=runtime_web_session_pb2.RuntimeWebSessionWindowUpdate(
                direction=(
                    runtime_web_session_pb2.RUNTIME_WEB_SESSION_DIRECTION_RESPONSE
                ),
                stream_consumed_total=1,
                session_consumed_total=1,
            ),
        ),
    )
    await data_plane.handle(
        source,
        _open_envelope(
            session_id="gateway-session",
            peer_boot_id="gateway-boot",
            stream_id=2,
        ),
    )
    second = await anext(runner_messages)

    assert second.stream_id > first.stream_id
    assert second.WhichOneof("payload") == "open"
    await data_plane.unregister_source(source)
    await data_plane.unregister_runner(accepted)
    await data_plane.close()


@pytest.mark.asyncio
async def test_owner_renewal_failure_closes_exact_runner_session() -> None:
    lifecycle = _OwnerLifecycle(renew_results=(True, False))
    data_plane, _lifecycle = _local_data_plane(lifecycle=lifecycle)
    accepted = RuntimeWebAcceptedRunnerSession(
        owner=_owner(),
        runner_boot_id="runner-boot",
        profile=APPROVED_SESSION_PROFILE,
        connected_at=datetime.now(UTC),
    )
    runner = await data_plane.register_runner(accepted)

    await _renew_owner_session(
        provider=lifecycle,
        owner=accepted.owner,
        connection=runner,
        interval_seconds=0.001,
    )

    assert lifecycle.renewed == [accepted.owner, accepted.owner]
    assert runner.queue.closed
    await data_plane.unregister_runner(accepted)
    await data_plane.close()


@pytest.mark.asyncio
async def test_control_drain_marks_owner_and_resets_long_lived_stream() -> None:
    data_plane, lifecycle = _local_data_plane()
    owner = _owner()
    accepted = RuntimeWebAcceptedRunnerSession(
        owner=owner,
        runner_boot_id="runner-boot",
        profile=APPROVED_SESSION_PROFILE,
        connected_at=datetime.now(UTC),
    )
    runner = await data_plane.register_runner(accepted)
    source = await data_plane.register_source(
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        owner=None,
    )
    opening = _open_envelope(
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        stream_id=1,
    )
    opening.open.request_head.protocol = (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_PROTOCOL_WEBSOCKET
    )
    await data_plane.handle(source, opening)
    runner_messages = runner.queue.__aiter__()
    forwarded = await anext(runner_messages)

    await data_plane.begin_drain()

    assert lifecycle.draining == [owner]
    assert not await data_plane.subready()
    source_messages = source.queue.__aiter__()
    assert (await anext(source_messages)).WhichOneof("payload") == "go_away"
    reset = await anext(source_messages)
    assert reset.WhichOneof("payload") == "reset"
    assert reset.reset.reason == (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_SERVICE_DRAIN
    )
    runner_go_away = await anext(runner_messages)
    runner_reset = await anext(runner_messages)
    assert runner_go_away.WhichOneof("payload") == "go_away"
    assert runner_reset.WhichOneof("payload") == "reset"
    assert runner_reset.stream_id == forwarded.stream_id
    await data_plane.unregister_source(source)
    await data_plane.unregister_runner(accepted)
    await data_plane.close()
