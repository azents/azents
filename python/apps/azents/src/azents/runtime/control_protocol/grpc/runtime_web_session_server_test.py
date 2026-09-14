"""Persistent Runtime Web Control data-plane tests."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import AsyncContextManager

import pytest
from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_capacity import (
    CapacityProfile,
    CapacityProtocol,
)
from azents_runtime_control.runtime_web_session import (
    APPROVED_SESSION_PROFILE,
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    CloseReason,
    OwnerSessionEpoch,
    StreamDirection,
    StreamProtocol,
)
from azents_runtime_control.system_metrics import (
    RunnerRuntimeWebMetrics,
    RunnerRuntimeWebProtocolCount,
    RunnerRuntimeWebReasonCount,
    RunnerRuntimeWebTrafficCount,
    RunnerSystemMetricAvailability,
    RunnerSystemMetricObservation,
    RunnerSystemMetricsScope,
)
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.repos.runtime_web.data import RuntimeWebSessionRoute
from azents.repos.runtime_web.session_route_repository import (
    RuntimeWebSessionRouteRepository,
)
from azents.runtime.control_protocol.grpc import (
    runtime_web_session_server as runtime_web_session_server_module,
)
from azents.runtime.control_protocol.grpc.runtime_web_session_server import (
    RuntimeWebCapacityBackend,
    RuntimeWebCapacityConfig,
    RuntimeWebCapacityRegistry,
    RuntimeWebControlDataPlane,
    RuntimeWebControlHardLimits,
    RuntimeWebControlResourceTracker,
    RuntimeWebGatewaySessionGrpcServicer,
    RuntimeWebTrustedPeerAuthenticator,
    _BoundedEnvelopeQueue,
    _register_joined_runner,
    _renew_owner_session,
    _RunnerConnection,
    _SourceSession,
    _StreamBinding,
)
from azents.runtime.coordination.data import RuntimeSystemMetricsSample
from azents.runtime.web_session_broker import BrokerStreamKey, BrokerTarget
from azents.runtime.web_session_owner import (
    RuntimeWebAcceptedRunnerSession,
    RuntimeWebOwnedSession,
    RuntimeWebOwnerSessionRegistry,
)
from azents.runtime.web_session_relay import (
    PersistentRelayConnection,
    RelaySessionKey,
    RelaySourceStreamKey,
    RelayStreamBinding,
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
    def __init__(
        self,
        *,
        samples: Mapping[
            tuple[str, int],
            list[RuntimeSystemMetricsSample],
        ],
    ) -> None:
        self.samples = dict(samples)

    async def read_runner_system_metrics(
        self,
        *,
        runtime_id: str,
        generation: int,
        current_time: datetime,
    ) -> list[RuntimeSystemMetricsSample]:
        del current_time
        return list(self.samples.get((runtime_id, generation), ()))


class _OwnerLifecycle:
    def __init__(self, *, renew_results: tuple[bool, ...] = ()) -> None:
        self.renew_results = list(renew_results)
        self.renewed: list[OwnerSessionEpoch] = []
        self.joined: list[OwnerSessionEpoch] = []
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

    async def mark_owner_joined(self, owner: OwnerSessionEpoch) -> bool:
        self.joined.append(owner)
        return True

    async def mark_owner_draining(self, owner: OwnerSessionEpoch) -> bool:
        self.draining.append(owner)
        return True

    async def release_owner(self, owner: OwnerSessionEpoch) -> bool:
        self.released.append(owner)
        return True


class _FailingRegistrationDataPlane(RuntimeWebControlDataPlane):
    def __init__(self) -> None:
        pass

    async def register_runner(
        self,
        accepted: RuntimeWebAcceptedRunnerSession,
    ) -> _RunnerConnection:
        del accepted
        raise asyncio.CancelledError


class _RecordingOwnerRegistry(RuntimeWebOwnerSessionRegistry):
    def __init__(self) -> None:
        self.released: list[RuntimeWebAcceptedRunnerSession] = []

    async def release(self, accepted: RuntimeWebAcceptedRunnerSession) -> bool:
        self.released.append(accepted)
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


@pytest.mark.asyncio
async def test_joined_owner_registration_cancellation_rolls_back_offer() -> None:
    accepted = RuntimeWebAcceptedRunnerSession(
        owner=_owner(),
        runner_boot_id="runner-boot",
        profile=APPROVED_SESSION_PROFILE,
        connected_at=datetime.now(UTC),
    )
    lifecycle = _OwnerLifecycle()
    registry = _RecordingOwnerRegistry()

    with pytest.raises(asyncio.CancelledError):
        await _register_joined_runner(
            data_plane=_FailingRegistrationDataPlane(),
            offer_provider=lifecycle,
            registry=registry,
            accepted=accepted,
        )

    assert registry.released == [accepted]
    assert lifecycle.released == [accepted.owner]


def _runner_runtime_web_metrics(scale: int) -> RunnerRuntimeWebMetrics:
    return RunnerRuntimeWebMetrics(
        active_sessions=scale,
        active_streams=2 * scale,
        maximum_sessions=30 * scale,
        maximum_active_streams=31 * scale,
        application_buffer_bytes=3 * scale,
        application_buffer_limit_bytes=4 * scale,
        control_buffer_bytes=5 * scale,
        control_buffer_limit_bytes=6 * scale,
        queued_envelopes=7 * scale,
        queued_envelope_limit=8 * scale,
        pending_tasks=9 * scale,
        pending_task_limit=10 * scale,
        event_loop_lag_milliseconds=11.0 * scale,
        event_loop_lag_limit_milliseconds=12 * scale,
        resident_memory_bytes=13 * scale,
        resident_memory_limit_bytes=14 * scale,
        credit_stalls_total=15 * scale,
        credit_stall_seconds=16.0 * scale,
        request_consumed_bytes=17 * scale,
        response_sent_bytes=19 * scale,
        response_consumed_bytes=18 * scale,
        heartbeats_total=20 * scale,
        go_aways_total=21 * scale,
        epoch_transitions_total=22 * scale,
        setup_seconds_sum=23.0 * scale,
        setup_count=24 * scale,
        ttfb_seconds_sum=25.0 * scale,
        ttfb_count=26 * scale,
        duration_seconds_sum=2.0 * scale,
        duration_count=27 * scale,
        goodput_bytes=10 * scale,
        active_streams_by_protocol=tuple(
            RunnerRuntimeWebProtocolCount(
                protocol=protocol,
                value=(index + 1) * scale,
            )
            for index, protocol in enumerate(StreamProtocol)
        ),
        opens_accepted_by_protocol=tuple(
            RunnerRuntimeWebProtocolCount(
                protocol=protocol,
                value=(index + 3) * scale,
            )
            for index, protocol in enumerate(StreamProtocol)
        ),
        opens_rejected_by_reason=tuple(
            RunnerRuntimeWebReasonCount(
                reason=reason,
                value=(index + 1) * scale,
            )
            for index, reason in enumerate(CloseReason)
        ),
        resets_by_reason=tuple(
            RunnerRuntimeWebReasonCount(
                reason=reason,
                value=(index + 2) * scale,
            )
            for index, reason in enumerate(CloseReason)
        ),
        closes_by_reason=tuple(
            RunnerRuntimeWebReasonCount(
                reason=reason,
                value=(index + 3) * scale,
            )
            for index, reason in enumerate(CloseReason)
        ),
        traffic=tuple(
            RunnerRuntimeWebTrafficCount(
                protocol=protocol,
                direction=direction,
                frames=(protocol_index * 2 + direction_index + 1) * scale,
                bytes=(protocol_index * 2 + direction_index + 1) * scale * 10,
            )
            for protocol_index, protocol in enumerate(StreamProtocol)
            for direction_index, direction in enumerate(StreamDirection)
        ),
    )


def _runner_metrics_sample(
    *,
    sequence: int,
    runtime_web: RunnerRuntimeWebMetrics,
) -> RuntimeSystemMetricsSample:
    unavailable = RunnerSystemMetricObservation(
        availability=RunnerSystemMetricAvailability.UNAVAILABLE,
        used=None,
        total=None,
    )
    return RuntimeSystemMetricsSample(
        sequence=sequence,
        measured_at=datetime(2026, 9, 14, tzinfo=UTC),
        scope=RunnerSystemMetricsScope.CONTAINER,
        cpu=unavailable,
        memory=unavailable,
        disk=unavailable,
        runtime_web=runtime_web,
    )


def _hard_limits(
    *,
    maximum_sessions: int = 32,
    maximum_active_streams: int = 128,
    maximum_application_buffer_bytes: int = 128 * 1024 * 1024,
    maximum_control_buffer_bytes: int = 16 * 1024 * 1024,
    maximum_queued_envelopes: int = 1024,
    maximum_pending_tasks: int = 256,
    maximum_event_loop_lag_milliseconds: int = 250,
    maximum_resident_memory_bytes: int = 1024 * 1024 * 1024,
) -> RuntimeWebControlHardLimits:
    return RuntimeWebControlHardLimits(
        maximum_sessions=maximum_sessions,
        maximum_active_streams=maximum_active_streams,
        maximum_application_buffer_bytes=maximum_application_buffer_bytes,
        maximum_control_buffer_bytes=maximum_control_buffer_bytes,
        maximum_queued_envelopes=maximum_queued_envelopes,
        maximum_pending_tasks=maximum_pending_tasks,
        maximum_event_loop_lag_milliseconds=(maximum_event_loop_lag_milliseconds),
        maximum_resident_memory_bytes=maximum_resident_memory_bytes,
    )


def _data_plane(
    *,
    hard_limits: RuntimeWebControlHardLimits | None = None,
    resident_memory_bytes: Callable[[], int] = lambda: 1,
    runner_metrics: _RunnerMetrics | None = None,
) -> RuntimeWebControlDataPlane:
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
        runner_metrics=(
            runner_metrics if runner_metrics is not None else _RunnerMetrics(samples={})
        ),
        clock=lambda: datetime.now(UTC),
        metrics_recoverable_errors=(RedisConnectionError,),
        owner_lifecycle=_OwnerLifecycle(),
        long_lived_grace_seconds=0.01,
        finite_grace_seconds=0.02,
        hard_limits=hard_limits or _hard_limits(),
        resident_memory_bytes=resident_memory_bytes,
    )


def _local_data_plane(
    *,
    lifecycle: _OwnerLifecycle | None = None,
    capacity_config: RuntimeWebCapacityConfig | None = None,
    hard_limits: RuntimeWebControlHardLimits | None = None,
    resident_memory_bytes: Callable[[], int] = lambda: 1,
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
            runner_metrics=_RunnerMetrics(samples={}),
            clock=lambda: datetime.now(UTC),
            metrics_recoverable_errors=(RedisConnectionError,),
            owner_lifecycle=effective_lifecycle,
            long_lived_grace_seconds=0.01,
            finite_grace_seconds=0.02,
            hard_limits=hard_limits or _hard_limits(),
            resident_memory_bytes=resident_memory_bytes,
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
    assert data_plane.resources.snapshot().pending_tasks == 0
    await data_plane.close()


@pytest.mark.asyncio
async def test_gateway_servicer_rejects_reader_task_budget_without_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_plane = _data_plane(hard_limits=_hard_limits(maximum_pending_tasks=1))
    servicer = RuntimeWebGatewaySessionGrpcServicer(
        data_plane=data_plane,
        peers=RuntimeWebTrustedPeerAuthenticator(
            allow_insecure=True,
            gateway_identities=frozenset(),
            control_identities=frozenset(),
        ),
        clock=lambda: datetime.now(UTC),
    )
    original_try_begin_task = data_plane.resources.try_begin_task
    attempts = 0

    def try_begin_task() -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            return False
        return original_try_begin_task()

    monkeypatch.setattr(data_plane.resources, "try_begin_task", try_begin_task)

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

    with pytest.raises(
        RuntimeError,
        match="RESOURCE_EXHAUSTED: Runtime Web Control hard task limit is exhausted",
    ):
        await anext(responses)
    snapshot = data_plane.resources.snapshot()
    assert snapshot.active_sessions == 0
    assert snapshot.queued_envelopes == 0
    assert snapshot.pending_tasks == 0
    assert data_plane.sources == {}
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
    assert "runtime_web_control_hard_sessions 2" in rendered
    assert "runtime_web_control_event_loop_lag_milliseconds 0.0" in rendered
    for forbidden in ("runtime_id=", "session_id=", "path=", "query=", "user="):
        assert forbidden not in rendered
    await data_plane.unregister_source(first)
    await data_plane.unregister_source(second)
    await data_plane.close()


@pytest.mark.asyncio
async def test_control_metrics_aggregate_latest_active_runner_snapshots() -> None:
    first_owner = _owner()
    second_owner = OwnerSessionEpoch(
        owner_boot_id="owner-boot-b",
        session_lease_id="owner-lease-b",
        lease_generation=2,
        runtime_id="runtime-b",
        desired_generation=2,
        runner_generation=3,
    )
    runner_metrics = _RunnerMetrics(
        samples={
            (first_owner.runtime_id, first_owner.runner_generation): [
                _runner_metrics_sample(
                    sequence=1,
                    runtime_web=_runner_runtime_web_metrics(99),
                ),
                _runner_metrics_sample(
                    sequence=2,
                    runtime_web=dataclasses.replace(
                        _runner_runtime_web_metrics(2),
                        event_loop_lag_milliseconds=300.0,
                        event_loop_lag_limit_milliseconds=250,
                    ),
                ),
            ],
            (second_owner.runtime_id, second_owner.runner_generation): [
                _runner_metrics_sample(
                    sequence=1,
                    runtime_web=dataclasses.replace(
                        _runner_runtime_web_metrics(3),
                        event_loop_lag_milliseconds=0.0,
                        event_loop_lag_limit_milliseconds=250,
                    ),
                )
            ],
        }
    )
    data_plane = _data_plane(runner_metrics=runner_metrics)
    accepted = tuple(
        RuntimeWebAcceptedRunnerSession(
            owner=owner,
            runner_boot_id=f"runner-{index}",
            profile=APPROVED_SESSION_PROFILE,
            connected_at=datetime.now(UTC),
        )
        for index, owner in enumerate((first_owner, second_owner), start=1)
    )
    for item in accepted:
        await data_plane.register_runner(item)

    rendered = await data_plane.metrics()

    expected_lines = (
        "runtime_web_runner_sessions 5",
        "runtime_web_runner_session_limit 150",
        "runtime_web_runner_active_streams 10",
        "runtime_web_runner_active_stream_limit 155",
        "runtime_web_runner_application_buffer_bytes 15",
        "runtime_web_runner_application_buffer_limit_bytes 20",
        "runtime_web_runner_control_buffer_bytes 25",
        "runtime_web_runner_control_buffer_limit_bytes 30",
        "runtime_web_runner_queued_envelopes 35",
        "runtime_web_runner_queued_envelope_limit 40",
        "runtime_web_runner_pending_tasks 45",
        "runtime_web_runner_pending_task_limit 50",
        "runtime_web_runner_event_loop_lag_milliseconds 300.0",
        "runtime_web_runner_event_loop_lag_limit_milliseconds 250",
        "runtime_web_runner_event_loop_lag_pressure 1.2",
        "runtime_web_runner_resident_memory_bytes 65",
        "runtime_web_runner_resident_memory_limit_bytes 70",
        "runtime_web_runner_credit_stalls_total 75",
        "runtime_web_runner_credit_stall_seconds_total 80.0",
        "runtime_web_runner_request_consumed_bytes 85",
        "runtime_web_runner_response_sent_bytes 95",
        "runtime_web_runner_response_consumed_bytes 90",
        "runtime_web_runner_response_credit_outstanding_bytes 5",
        "runtime_web_runner_heartbeat_total 100",
        "runtime_web_runner_go_away_total 105",
        "runtime_web_runner_epoch_transition_total 110",
        "runtime_web_runner_setup_seconds_sum 115.0",
        "runtime_web_runner_setup_seconds_count 120",
        "runtime_web_runner_ttfb_seconds_sum 125.0",
        "runtime_web_runner_ttfb_seconds_count 130",
        "runtime_web_runner_duration_seconds_sum 10.0",
        "runtime_web_runner_duration_seconds_count 135",
        "runtime_web_runner_goodput_bytes 50",
        "runtime_web_runner_goodput_bytes_per_second 5.0",
        ('runtime_web_runner_active_streams_by_protocol{protocol="http"} 5'),
        ('runtime_web_runner_active_streams_by_protocol{protocol="websocket"} 10'),
        ('runtime_web_runner_open_total{protocol="http",outcome="accepted"} 15'),
        ('runtime_web_runner_open_rejected_total{reason="caller"} 5'),
        'runtime_web_runner_reset_total{reason="caller"} 10',
        'runtime_web_runner_close_total{reason="caller"} 15',
        ('runtime_web_runner_open_rejected_total{reason="transport_unavailable"} 55'),
        ('runtime_web_runner_frames_total{protocol="http",direction="request"} 5'),
        (
            "runtime_web_runner_bytes_total"
            '{protocol="websocket",direction="response"} 200'
        ),
    )
    for expected in expected_lines:
        assert expected in rendered
    for forbidden in (
        "runtime_web_runner_memory_bytes",
        "runtime_web_runner_memory_limit_bytes",
        "runtime_id=",
        "session_id=",
        "path=",
        "user=",
    ):
        assert forbidden not in rendered

    for item in accepted:
        await data_plane.unregister_runner(item)
    await data_plane.close()


def test_control_resource_tracker_rejects_and_releases_every_ceiling() -> None:
    tracker = RuntimeWebControlResourceTracker(
        limits=_hard_limits(
            maximum_sessions=1,
            maximum_active_streams=1,
            maximum_application_buffer_bytes=4,
            maximum_control_buffer_bytes=3,
            maximum_queued_envelopes=1,
            maximum_pending_tasks=1,
            maximum_resident_memory_bytes=8,
        ),
        resident_memory_bytes=lambda: 1,
    )

    assert tracker.try_open_session()
    assert not tracker.try_open_session()
    assert tracker.try_open_stream()
    assert not tracker.try_open_stream()
    assert tracker.try_begin_task()
    assert not tracker.try_begin_task()
    assert tracker.try_reserve_envelope(application_bytes=4, control_bytes=3)
    assert not tracker.try_reserve_envelope(application_bytes=1, control_bytes=0)
    tracker.release_envelope(application_bytes=4, control_bytes=3)
    tracker.end_task()
    tracker.close_stream()
    tracker.close_session()

    snapshot = tracker.snapshot()
    assert snapshot.active_sessions == 0
    assert snapshot.active_streams == 0
    assert snapshot.application_buffer_bytes == 0
    assert snapshot.control_buffer_bytes == 0
    assert snapshot.queued_envelopes == 0
    assert snapshot.pending_tasks == 0


def test_control_resource_tracker_rejects_lag_and_rss_pressure() -> None:
    resident_memory_bytes = 1
    tracker = RuntimeWebControlResourceTracker(
        limits=_hard_limits(
            maximum_event_loop_lag_milliseconds=10,
            maximum_resident_memory_bytes=8,
        ),
        resident_memory_bytes=lambda: resident_memory_bytes,
    )
    tracker.update_process_pressure(lag_milliseconds=10, resident_memory_bytes=1)
    assert not tracker.try_open_session()

    tracker.update_process_pressure(lag_milliseconds=0, resident_memory_bytes=8)
    assert not tracker.try_open_session()


@pytest.mark.asyncio
async def test_control_managed_task_releases_every_exit_path() -> None:
    tracker = RuntimeWebControlResourceTracker(
        limits=_hard_limits(maximum_pending_tasks=1),
        resident_memory_bytes=lambda: 1,
    )

    async def complete() -> int:
        return 7

    completed = runtime_web_session_server_module._create_control_task(
        tracker,
        complete,
    )
    assert tracker.snapshot().pending_tasks == 1
    assert await completed == 7
    assert tracker.snapshot().pending_tasks == 0

    async def fail() -> None:
        raise RuntimeError("task failed")

    failed = runtime_web_session_server_module._create_control_task(tracker, fail)
    with pytest.raises(RuntimeError, match="task failed"):
        await failed
    assert tracker.snapshot().pending_tasks == 0

    started = asyncio.Event()
    blocked = asyncio.Event()

    async def wait_until_cancelled() -> None:
        started.set()
        await blocked.wait()

    cancelled = runtime_web_session_server_module._create_control_task(
        tracker,
        wait_until_cancelled,
    )
    await started.wait()
    cancelled.cancel()
    await asyncio.gather(cancelled, return_exceptions=True)
    assert tracker.snapshot().pending_tasks == 0

    assert tracker.try_begin_task()
    called = False

    async def must_not_start() -> None:
        nonlocal called
        called = True

    with pytest.raises(
        runtime_web_session_server_module._RuntimeWebControlResourceExhausted
    ):
        runtime_web_session_server_module._create_control_task(
            tracker,
            must_not_start,
        )
    assert not called
    assert tracker.snapshot().pending_tasks == 1
    tracker.end_task()


def test_control_managed_task_releases_when_create_task_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = RuntimeWebControlResourceTracker(
        limits=_hard_limits(maximum_pending_tasks=1),
        resident_memory_bytes=lambda: 1,
    )

    def fail_create_task(
        coroutine: Awaitable[object],
        *,
        name: str | None = None,
    ) -> asyncio.Task[object]:
        del coroutine, name
        raise RuntimeError("create failed")

    monkeypatch.setattr(
        runtime_web_session_server_module.asyncio,
        "create_task",
        fail_create_task,
    )

    async def task() -> None:
        raise AssertionError("task must not start")

    with pytest.raises(RuntimeError, match="create failed"):
        runtime_web_session_server_module._create_control_task(tracker, task)
    assert tracker.snapshot().pending_tasks == 0


@pytest.mark.asyncio
async def test_control_queue_releases_process_bytes_on_dequeue_and_close() -> None:
    tracker = RuntimeWebControlResourceTracker(
        limits=_hard_limits(),
        resident_memory_bytes=lambda: 1,
    )
    queue = _BoundedEnvelopeQueue(tracker)
    data = runtime_web_session_pb2.RuntimeWebSessionEnvelope()
    data.data.data = b"payload"
    control = runtime_web_session_pb2.RuntimeWebSessionEnvelope()
    control.heartbeat.monotonic_sequence = 1

    await queue.put(data)
    await queue.put(control)
    queued = tracker.snapshot()
    assert queued.queued_envelopes == 2
    assert queued.application_buffer_bytes == len(b"payload")
    assert queued.control_buffer_bytes > 0

    iterator = queue.__aiter__()
    await anext(iterator)
    dequeued = tracker.snapshot()
    assert dequeued.queued_envelopes == 1
    assert dequeued.application_buffer_bytes == 0
    await queue.close()
    released = tracker.snapshot()
    assert released.queued_envelopes == 0
    assert released.control_buffer_bytes == 0


@pytest.mark.asyncio
async def test_control_session_and_stream_hard_limits_reject_without_leak() -> None:
    data_plane, _lifecycle = _local_data_plane(
        hard_limits=_hard_limits(maximum_sessions=2, maximum_active_streams=1),
    )
    owner = _owner()
    accepted = RuntimeWebAcceptedRunnerSession(
        owner=owner,
        runner_boot_id="runner-boot",
        profile=APPROVED_SESSION_PROFILE,
        connected_at=datetime.now(UTC),
    )
    await data_plane.register_runner(accepted)
    source = await data_plane.register_source(
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        owner=None,
    )
    with pytest.raises(RuntimeError):
        await data_plane.register_source(
            session_id="extra",
            peer_boot_id="extra-boot",
            owner=None,
        )

    await data_plane.handle(
        source,
        _open_envelope(
            session_id=source.session_id,
            peer_boot_id=source.peer_boot_id,
            stream_id=1,
        ),
    )
    await data_plane.handle(
        source,
        _open_envelope(
            session_id=source.session_id,
            peer_boot_id=source.peer_boot_id,
            stream_id=2,
        ),
    )
    rejected = await anext(source.queue.__aiter__())
    assert rejected.open_rejected.reason == (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_RESOURCE_EXHAUSTED
    )
    assert data_plane.resources.snapshot().active_streams == 1

    await data_plane.unregister_source(source)
    await data_plane.unregister_runner(accepted)
    assert data_plane.resources.snapshot().active_sessions == 0
    assert data_plane.resources.snapshot().active_streams == 0
    await data_plane.close()


@pytest.mark.asyncio
async def test_control_runner_heartbeat_ack_is_session_scoped_and_observable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_web_session_server_module,
        "_HEARTBEAT_INTERVAL_SECONDS",
        0.01,
    )
    data_plane, _lifecycle = _local_data_plane()
    owner = _owner()
    accepted = RuntimeWebAcceptedRunnerSession(
        owner=owner,
        runner_boot_id="runner-boot",
        profile=APPROVED_SESSION_PROFILE,
        connected_at=datetime.now(UTC),
    )
    connection = await data_plane.register_runner(accepted)
    connection.start_heartbeats()
    assert data_plane.resources.snapshot().pending_tasks == 1

    heartbeat = await asyncio.wait_for(
        anext(connection.queue.__aiter__()),
        timeout=1,
    )
    acknowledgement = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        session_id=owner.session_lease_id,
        peer_boot_id=accepted.runner_boot_id,
        owner_boot_id=owner.owner_boot_id,
        session_lease_id=owner.session_lease_id,
        lease_generation=owner.lease_generation,
    )
    acknowledgement.heartbeat_ack.monotonic_sequence = (
        heartbeat.heartbeat.monotonic_sequence
    )
    await data_plane.runner_response(acknowledgement)

    await data_plane.unregister_runner(accepted)
    assert data_plane.resources.snapshot().pending_tasks == 0
    rendered = await data_plane.metrics()
    assert "runtime_web_control_runner_heartbeats_sent_total 1" in rendered
    assert "runtime_web_control_runner_heartbeat_acknowledgements_total 1" in rendered
    await data_plane.close()


@pytest.mark.asyncio
async def test_control_runner_missed_heartbeat_closes_only_that_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_web_session_server_module,
        "_HEARTBEAT_INTERVAL_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        runtime_web_session_server_module,
        "_MAX_MISSED_HEARTBEATS",
        1,
    )
    data_plane, _lifecycle = _local_data_plane()
    owner = _owner()
    accepted = RuntimeWebAcceptedRunnerSession(
        owner=owner,
        runner_boot_id="runner-boot",
        profile=APPROVED_SESSION_PROFILE,
        connected_at=datetime.now(UTC),
    )
    connection = await data_plane.register_runner(accepted)
    connection.start_heartbeats()
    messages = connection.queue.__aiter__()

    heartbeat = await asyncio.wait_for(anext(messages), timeout=1)
    assert heartbeat.WhichOneof("payload") == "heartbeat"
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(messages), timeout=1)
    assert connection.missed_heartbeats == 1

    await data_plane.unregister_runner(accepted)
    assert data_plane.resources.snapshot().pending_tasks == 0
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
async def test_async_relay_disconnect_resets_and_releases_source_binding() -> None:
    data_plane = _data_plane()
    owner = _owner()
    source = await data_plane.register_source(
        session_id="gateway-session",
        peer_boot_id="gateway-boot",
        owner=None,
    )
    source_key = BrokerStreamKey(source.source_key, 7)
    data_plane.bindings[source_key] = _StreamBinding(
        source=source,
        key=source_key,
        target=BrokerTarget(owner=owner, local=False, relay_count=1),
        broker=None,
        capacity_stream_id=None,
        runner_stream_id=None,
        protocol=CapacityProtocol.HTTP,
    )
    assert data_plane.resources.try_open_stream()
    relay_binding = RelayStreamBinding(
        source=RelaySourceStreamKey(
            source_session_id=source.session_id,
            source_peer_boot_id=source.peer_boot_id,
            source_stream_id=7,
        ),
        relay_stream_id=1,
    )

    await data_plane.relay_disconnected(
        RelaySessionKey(owner, RUNTIME_WEB_PROTOCOL_FINGERPRINT),
        (relay_binding,),
    )
    reset = await anext(source.queue.__aiter__())

    assert reset.stream_id == 7
    assert reset.WhichOneof("payload") == "reset"
    assert reset.reset.reason == (
        runtime_web_session_pb2.RUNTIME_WEB_SESSION_CLOSE_REASON_TRANSPORT_UNAVAILABLE
    )
    assert data_plane.bindings == {}
    assert data_plane.resources.snapshot().active_streams == 0
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
