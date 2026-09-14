"""Runtime Web Gateway inactive operational contract tests."""

import asyncio

import pytest
from azents_runtime_control.runtime_web_session import (
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    CloseReason,
)

from azents.runtime_web_gateway.operations import (
    RuntimeWebCapacityBackend,
    RuntimeWebDrainCallbackPhase,
    RuntimeWebDrainCoordinator,
    RuntimeWebDrainPolicy,
    RuntimeWebDrainStreamKind,
    RuntimeWebGatewayDependencyEvidence,
    RuntimeWebGatewayHardLimits,
    RuntimeWebGatewayHealth,
    RuntimeWebGatewayOperationalState,
    RuntimeWebGatewayOperationsCoordinator,
    RuntimeWebGatewayPressure,
    RuntimeWebGatewayResourceTracker,
    render_openmetrics,
)


def _limits(*, active_exchanges: int = 2) -> RuntimeWebGatewayHardLimits:
    return RuntimeWebGatewayHardLimits(
        maximum_active_exchanges=active_exchanges,
        maximum_application_buffer_bytes=10,
        maximum_scheduler_waiters=1,
        maximum_event_loop_lag_milliseconds=100,
        maximum_resident_memory_bytes=1000,
    )


def _health() -> RuntimeWebGatewayHealth:
    return RuntimeWebGatewayHealth(
        configuration_valid=True,
        maintenance=False,
        draining=False,
        authority_query_available=True,
        replacement_protocol_compatible=True,
        local_pressure_acceptable=True,
        event_loop_responsive=True,
        redis_available=False,
    )


def _operational_state(
    resources: RuntimeWebGatewayResourceTracker | None = None,
) -> RuntimeWebGatewayOperationalState:
    if resources is None:
        resources = RuntimeWebGatewayResourceTracker(_limits())
    return RuntimeWebGatewayOperationalState(
        health=_health(),
        pressure=RuntimeWebGatewayPressure(0, 0, 0, 0, 0),
        backend=RuntimeWebCapacityBackend.MEMORY,
        capacity_degraded=True,
        resources=resources,
        local_open_count=0,
        relay_open_count=0,
        event_loop_lag_milliseconds=0,
        resident_memory_bytes=0,
    )


def test_pressure_uses_only_local_gateway_inputs() -> None:
    pressure = RuntimeWebGatewayPressure(0.2, 0.7, 0.4, 0.3, 0.6)

    assert pressure.value == 0.7


@pytest.mark.parametrize("value", [-0.1, 1.1, float("inf"), float("nan")])
def test_pressure_rejects_unbounded_values(value: float) -> None:
    with pytest.raises(ValueError):
        RuntimeWebGatewayPressure(value, 0, 0, 0, 0)


def test_readiness_requires_authority_query_and_exact_replacement_fingerprint() -> None:
    state = _operational_state()

    state.update_dependencies(
        evidence=RuntimeWebGatewayDependencyEvidence.from_observation(
            authority_query_succeeded=True,
            control_protocol_fingerprints={"wrong"},
        ),
        redis_available=True,
    )
    assert not state.health.ready

    state.update_dependencies(
        evidence=RuntimeWebGatewayDependencyEvidence.from_observation(
            authority_query_succeeded=False,
            control_protocol_fingerprints={RUNTIME_WEB_PROTOCOL_FINGERPRINT},
        ),
        redis_available=True,
    )
    assert not state.health.ready

    state.update_dependencies(
        evidence=RuntimeWebGatewayDependencyEvidence.from_observation(
            authority_query_succeeded=True,
            control_protocol_fingerprints={RUNTIME_WEB_PROTOCOL_FINGERPRINT},
        ),
        redis_available=False,
    )
    assert state.health.ready
    assert state.health.live


def test_dependency_failure_lowers_readiness_not_liveness() -> None:
    health = _health()
    unavailable = RuntimeWebGatewayHealth(
        configuration_valid=health.configuration_valid,
        maintenance=health.maintenance,
        draining=health.draining,
        authority_query_available=False,
        replacement_protocol_compatible=health.replacement_protocol_compatible,
        local_pressure_acceptable=health.local_pressure_acceptable,
        event_loop_responsive=health.event_loop_responsive,
        redis_available=health.redis_available,
    )

    assert not unavailable.ready
    assert unavailable.live


def test_drain_policy_uses_approved_bounds() -> None:
    assert RuntimeWebDrainPolicy() == RuntimeWebDrainPolicy(
        finite_http_grace_seconds=120,
        long_lived_grace_seconds=5,
        termination_grace_seconds=150,
        scale_down_stabilization_seconds=300,
    )


def test_hard_limits_require_positive_process_ceilings() -> None:
    assert _limits().maximum_active_exchanges == 2
    with pytest.raises(ValueError, match="maximum_active_exchanges"):
        RuntimeWebGatewayHardLimits(
            maximum_active_exchanges=0,
            maximum_application_buffer_bytes=1,
            maximum_scheduler_waiters=1,
            maximum_event_loop_lag_milliseconds=1,
            maximum_resident_memory_bytes=1,
        )


def test_resource_tracker_rejects_and_updates_live_pressure_before_oom() -> None:
    state = _operational_state()
    tracker = state.resources

    assert tracker.try_open_exchange()
    assert tracker.try_open_exchange()
    assert not tracker.try_open_exchange()
    assert tracker.try_reserve_application_buffer(10)
    assert not tracker.try_reserve_application_buffer(1)
    tracker.reserve_control_buffer(7)
    assert tracker.snapshot().control_buffer_bytes == 7
    tracker.release_control_buffer(7)
    assert tracker.try_add_scheduler_waiter()
    assert not tracker.try_add_scheduler_waiter()

    state.update_process_pressure(
        event_loop_lag_milliseconds=25,
        resident_memory_bytes=500,
    )
    assert state.pressure.value == 1.0
    assert not state.health.ready
    assert state.health.live

    state.update_process_pressure(
        event_loop_lag_milliseconds=100,
        resident_memory_bytes=500,
    )
    assert not state.health.live


@pytest.mark.asyncio
async def test_drain_coordinator_refuses_new_work_and_closes_gracefully() -> None:
    resources = RuntimeWebGatewayResourceTracker(_limits())
    state = _operational_state(resources)
    events: list[tuple[str, CloseReason]] = []

    async def begin_session_drain(reason: CloseReason) -> None:
        assert not state.health.ready
        events.append(("goaway", reason))

    coordinator = RuntimeWebDrainCoordinator(
        policy=RuntimeWebDrainPolicy(
            finite_http_grace_seconds=1,
            long_lived_grace_seconds=0.5,
            termination_grace_seconds=2,
            scale_down_stabilization_seconds=1,
        ),
        resources=resources,
        begin_session_drain=begin_session_drain,
    )
    operations = RuntimeWebGatewayOperationsCoordinator(
        state=state,
        drain=coordinator,
    )
    finite = None
    long_lived = None

    async def graceful_finite(reason: CloseReason) -> None:
        events.append(("finite", reason))

    async def graceful_long_lived(reason: CloseReason) -> None:
        events.append(("long", reason))
        assert long_lived is not None
        assert await coordinator.release(long_lived)

    async def force(reason: CloseReason) -> None:
        raise AssertionError(f"force close was not expected: {reason}")

    finite = await coordinator.register(
        kind=RuntimeWebDrainStreamKind.FINITE_HTTP,
        request_graceful_close=graceful_finite,
        force_close=force,
    )
    long_lived = await coordinator.register(
        kind=RuntimeWebDrainStreamKind.LONG_LIVED,
        request_graceful_close=graceful_long_lived,
        force_close=force,
    )
    assert finite is not None
    assert long_lived is not None

    async def finish_http() -> None:
        await asyncio.sleep(0)
        assert finite is not None
        assert await coordinator.release(finite)

    completion = asyncio.create_task(finish_http())
    result = await operations.drain()
    await completion

    assert result.force_closed == ()
    assert result.callback_failures == ()
    assert result.gracefully_closed == tuple(
        sorted((finite.registration_id, long_lived.registration_id))
    )
    assert events == [
        ("goaway", CloseReason.SERVICE_DRAIN),
        ("long", CloseReason.SERVICE_DRAIN),
    ]
    assert resources.snapshot().active_exchanges == 0
    assert (
        await coordinator.register(
            kind=RuntimeWebDrainStreamKind.FINITE_HTTP,
            request_graceful_close=graceful_finite,
            force_close=force,
        )
        is None
    )


@pytest.mark.asyncio
async def test_drain_coordinator_force_closes_after_each_bounded_grace() -> None:
    resources = RuntimeWebGatewayResourceTracker(_limits())
    forced: list[CloseReason] = []

    async def graceful(reason: CloseReason) -> None:
        assert reason is CloseReason.SERVICE_DRAIN

    async def force(reason: CloseReason) -> None:
        forced.append(reason)

    coordinator = RuntimeWebDrainCoordinator(
        policy=RuntimeWebDrainPolicy(
            finite_http_grace_seconds=0.04,
            long_lived_grace_seconds=0.01,
            termination_grace_seconds=0.1,
            scale_down_stabilization_seconds=1,
        ),
        resources=resources,
        begin_session_drain=graceful,
    )

    finite = await coordinator.register(
        kind=RuntimeWebDrainStreamKind.FINITE_HTTP,
        request_graceful_close=graceful,
        force_close=force,
    )
    long_lived = await coordinator.register(
        kind=RuntimeWebDrainStreamKind.LONG_LIVED,
        request_graceful_close=graceful,
        force_close=force,
    )
    assert finite is not None
    assert long_lived is not None

    result = await coordinator.drain()

    assert result.force_closed == tuple(
        sorted((finite.registration_id, long_lived.registration_id))
    )
    assert result.callback_failures == ()
    assert forced == [CloseReason.SERVICE_DRAIN, CloseReason.SERVICE_DRAIN]
    assert resources.snapshot().active_exchanges == 0


@pytest.mark.asyncio
async def test_drain_callback_failures_are_reported_after_force_cleanup() -> None:
    resources = RuntimeWebGatewayResourceTracker(_limits())

    async def session_failure(reason: CloseReason) -> None:
        assert reason is CloseReason.SERVICE_DRAIN
        raise RuntimeError("session callback failed")

    async def graceful_failure(reason: CloseReason) -> None:
        assert reason is CloseReason.SERVICE_DRAIN
        raise ValueError("graceful callback failed")

    async def force_failure(reason: CloseReason) -> None:
        assert reason is CloseReason.SERVICE_DRAIN
        raise LookupError("force callback failed")

    coordinator = RuntimeWebDrainCoordinator(
        policy=RuntimeWebDrainPolicy(
            finite_http_grace_seconds=0.04,
            long_lived_grace_seconds=0.01,
            termination_grace_seconds=0.1,
            scale_down_stabilization_seconds=1,
        ),
        resources=resources,
        begin_session_drain=session_failure,
    )
    finite = await coordinator.register(
        kind=RuntimeWebDrainStreamKind.FINITE_HTTP,
        request_graceful_close=graceful_failure,
        force_close=force_failure,
    )
    long_lived = await coordinator.register(
        kind=RuntimeWebDrainStreamKind.LONG_LIVED,
        request_graceful_close=graceful_failure,
        force_close=force_failure,
    )
    assert finite is not None
    assert long_lived is not None

    result = await coordinator.drain()

    assert result.force_closed == tuple(
        sorted((finite.registration_id, long_lived.registration_id))
    )
    assert {
        (failure.registration_id, failure.phase, failure.error_type)
        for failure in result.callback_failures
    } == {
        (None, RuntimeWebDrainCallbackPhase.SESSION, "RuntimeError"),
        (
            long_lived.registration_id,
            RuntimeWebDrainCallbackPhase.GRACEFUL,
            "ValueError",
        ),
        (
            long_lived.registration_id,
            RuntimeWebDrainCallbackPhase.FORCE,
            "LookupError",
        ),
        (
            finite.registration_id,
            RuntimeWebDrainCallbackPhase.FORCE,
            "LookupError",
        ),
    }
    assert coordinator.active == {}
    assert resources.snapshot().active_exchanges == 0


@pytest.mark.asyncio
async def test_drain_caller_cancellation_waits_for_force_cleanup() -> None:
    resources = RuntimeWebGatewayResourceTracker(_limits(active_exchanges=1))
    close_started = asyncio.Event()
    permit_close = asyncio.Event()

    async def close(reason: CloseReason) -> None:
        assert reason is CloseReason.SERVICE_DRAIN
        close_started.set()
        await permit_close.wait()

    coordinator = RuntimeWebDrainCoordinator(
        policy=RuntimeWebDrainPolicy(
            finite_http_grace_seconds=0.02,
            long_lived_grace_seconds=0.01,
            termination_grace_seconds=0.1,
            scale_down_stabilization_seconds=1,
        ),
        resources=resources,
        begin_session_drain=close,
    )
    registration = await coordinator.register(
        kind=RuntimeWebDrainStreamKind.FINITE_HTTP,
        request_graceful_close=close,
        force_close=close,
    )
    assert registration is not None

    drain = asyncio.create_task(coordinator.drain())
    await asyncio.wait_for(close_started.wait(), timeout=1)
    drain.cancel()
    permit_close.set()
    with pytest.raises(asyncio.CancelledError):
        await drain

    assert coordinator.active == {}
    assert resources.snapshot().active_exchanges == 0


def test_operational_state_drains_before_refusing_new_work() -> None:
    state = _operational_state()

    assert state.health.ready
    state.begin_drain()
    assert not state.health.ready
    assert state.health.live


def test_operational_state_recovers_immediately_after_resource_release() -> None:
    state = _operational_state()
    resources = state.resources
    assert resources.try_open_exchange()
    assert resources.try_open_exchange()
    state.refresh_resource_pressure()
    assert not state.health.local_pressure_acceptable

    resources.close_exchange()
    resources.close_exchange()
    assert not state.health.local_pressure_acceptable
    state.refresh_resource_pressure()

    assert state.health.local_pressure_acceptable
    assert state.pressure.active_exchange_ratio == 0


@pytest.mark.asyncio
async def test_sse_registration_reclassifies_before_drain() -> None:
    resources = RuntimeWebGatewayResourceTracker(_limits())

    async def ignore(reason: CloseReason) -> None:
        assert reason is CloseReason.SERVICE_DRAIN

    coordinator = RuntimeWebDrainCoordinator(
        policy=RuntimeWebDrainPolicy(
            finite_http_grace_seconds=0.02,
            long_lived_grace_seconds=0.01,
            termination_grace_seconds=1,
            scale_down_stabilization_seconds=1,
        ),
        resources=resources,
        begin_session_drain=ignore,
    )
    registration = await coordinator.register(
        kind=RuntimeWebDrainStreamKind.FINITE_HTTP,
        request_graceful_close=ignore,
        force_close=ignore,
    )
    assert registration is not None

    assert await coordinator.reclassify(
        registration,
        kind=RuntimeWebDrainStreamKind.LONG_LIVED,
    )
    assert coordinator.active[registration.registration_id].registration.kind is (
        RuntimeWebDrainStreamKind.LONG_LIVED
    )


@pytest.mark.asyncio
async def test_sse_reclassification_after_drain_start_uses_long_lived_grace() -> None:
    resources = RuntimeWebGatewayResourceTracker(_limits(active_exchanges=1))
    session_drain_started = asyncio.Event()
    finish_session_drain = asyncio.Event()
    graceful_close_called = asyncio.Event()
    registration = None

    async def begin_session_drain(reason: CloseReason) -> None:
        assert reason is CloseReason.SERVICE_DRAIN
        session_drain_started.set()
        await finish_session_drain.wait()

    async def graceful_close(reason: CloseReason) -> None:
        assert reason is CloseReason.SERVICE_DRAIN
        graceful_close_called.set()
        assert registration is not None
        await coordinator.release(registration)

    async def force_close(reason: CloseReason) -> None:
        raise AssertionError(f"force close was not expected: {reason}")

    coordinator = RuntimeWebDrainCoordinator(
        policy=RuntimeWebDrainPolicy(
            finite_http_grace_seconds=1,
            long_lived_grace_seconds=0.5,
            termination_grace_seconds=2,
            scale_down_stabilization_seconds=1,
        ),
        resources=resources,
        begin_session_drain=begin_session_drain,
    )
    registration = await coordinator.register(
        kind=RuntimeWebDrainStreamKind.FINITE_HTTP,
        request_graceful_close=graceful_close,
        force_close=force_close,
    )
    assert registration is not None

    draining = asyncio.create_task(coordinator.drain())
    await session_drain_started.wait()
    assert await coordinator.reclassify(
        registration,
        kind=RuntimeWebDrainStreamKind.LONG_LIVED,
    )
    await graceful_close_called.wait()
    finish_session_drain.set()
    result = await draining

    assert result.gracefully_closed == (registration.registration_id,)
    assert result.force_closed == ()
    assert result.callback_failures == ()


def test_openmetrics_uses_only_bounded_process_labels() -> None:
    rendered = render_openmetrics(
        pressure=RuntimeWebGatewayPressure(0.1, 0.2, 0.3, 0.4, 0.5),
        health=_health(),
        backend=RuntimeWebCapacityBackend.MEMORY,
        capacity_degraded=True,
        active_exchanges=0,
        local_open_count=2,
        relay_open_count=1,
        application_buffer_bytes=1024,
        application_buffer_limit_bytes=4096,
        control_buffer_bytes=128,
        scheduler_waiters=3,
        scheduler_waiter_limit=32,
        resident_memory_bytes=2048,
        resident_memory_limit_bytes=8192,
    )

    assert 'backend="memory"' in rendered
    assert "runtime_web_gateway_pressure 0.5" in rendered
    assert "runtime_web_gateway_active_exchanges 0" in rendered
    assert 'runtime_web_gateway_open_total{route="local"} 2' in rendered
    assert 'runtime_web_gateway_open_total{route="relay"} 1' in rendered
    assert "runtime_web_gateway_application_buffer_bytes 1024" in rendered
    assert "runtime_web_gateway_application_buffer_limit_bytes 4096" in rendered
    assert "runtime_web_gateway_control_buffer_bytes 128" in rendered
    assert "runtime_web_gateway_scheduler_waiters 3" in rendered
    assert "runtime_web_gateway_scheduler_waiter_limit 32" in rendered
    assert "runtime_web_gateway_resident_memory_bytes 2048" in rendered
    assert "runtime_web_gateway_resident_memory_limit_bytes 8192" in rendered
    assert "runtime_web_gateway_ready 1" in rendered
    for forbidden in ("runtime_id=", "user=", "session=", "path=", "query="):
        assert forbidden not in rendered
