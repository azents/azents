"""Content-free Runtime Web Gateway operational state and pressure metrics."""

from __future__ import annotations

import asyncio
import dataclasses
import enum
import math
from collections.abc import Awaitable, Callable, Collection

from azents_runtime_control.runtime_web_session import (
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    CloseReason,
)


class RuntimeWebCapacityBackend(enum.StrEnum):
    """Capacity backend labels allowed by the metrics contract."""

    MEMORY = "memory"
    REDIS = "redis"


@dataclasses.dataclass(frozen=True)
class RuntimeWebGatewayPressure:
    """Bounded local pressure inputs used by autoscaling."""

    active_exchange_ratio: float
    application_buffer_ratio: float
    scheduler_wait_ratio: float
    event_loop_lag_ratio: float
    resident_memory_ratio: float

    def __post_init__(self) -> None:
        values = (
            ("active_exchange_ratio", self.active_exchange_ratio),
            ("application_buffer_ratio", self.application_buffer_ratio),
            ("scheduler_wait_ratio", self.scheduler_wait_ratio),
            ("event_loop_lag_ratio", self.event_loop_lag_ratio),
            ("resident_memory_ratio", self.resident_memory_ratio),
        )
        for name, value in values:
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between zero and one")

    @property
    def value(self) -> float:
        """Return HPA pressure without including Runtime soft quota."""
        return max(
            self.active_exchange_ratio,
            self.application_buffer_ratio,
            self.scheduler_wait_ratio,
            self.event_loop_lag_ratio,
            self.resident_memory_ratio,
        )


@dataclasses.dataclass(frozen=True)
class RuntimeWebGatewayHealth:
    """Dependency-aware readiness and process-only liveness evidence."""

    configuration_valid: bool
    maintenance: bool
    draining: bool
    authority_query_available: bool
    replacement_protocol_compatible: bool
    local_pressure_acceptable: bool
    event_loop_responsive: bool
    redis_available: bool

    @property
    def ready(self) -> bool:
        """Return whether the Gateway may receive new public work."""
        return (
            self.configuration_valid
            and not self.maintenance
            and not self.draining
            and self.authority_query_available
            and self.replacement_protocol_compatible
            and self.local_pressure_acceptable
        )

    @property
    def live(self) -> bool:
        """Return process liveness without dependency restart coupling."""
        return self.event_loop_responsive


@dataclasses.dataclass(frozen=True)
class RuntimeWebGatewayDependencyEvidence:
    """Exact authority-query and replacement-Control readiness evidence."""

    authority_query_succeeded: bool
    control_protocol_fingerprints: frozenset[str]

    @classmethod
    def from_observation(
        cls,
        *,
        authority_query_succeeded: bool,
        control_protocol_fingerprints: Collection[str],
    ) -> RuntimeWebGatewayDependencyEvidence:
        """Normalize one bounded dependency observation."""
        return cls(
            authority_query_succeeded=authority_query_succeeded,
            control_protocol_fingerprints=frozenset(control_protocol_fingerprints),
        )

    @property
    def replacement_protocol_compatible(self) -> bool:
        """Require one Control with the exact approved replacement fingerprint."""
        return RUNTIME_WEB_PROTOCOL_FINGERPRINT in self.control_protocol_fingerprints


@dataclasses.dataclass(frozen=True)
class RuntimeWebDrainPolicy:
    """Approved bounded drain timing."""

    finite_http_grace_seconds: float = 120
    long_lived_grace_seconds: float = 5
    termination_grace_seconds: float = 150
    scale_down_stabilization_seconds: float = 300

    def __post_init__(self) -> None:
        if self.finite_http_grace_seconds <= 0:
            raise ValueError("finite HTTP drain grace must be positive")
        if self.long_lived_grace_seconds <= 0:
            raise ValueError("long-lived drain grace must be positive")
        if self.termination_grace_seconds <= self.finite_http_grace_seconds:
            raise ValueError("termination grace must include cleanup margin")
        if self.scale_down_stabilization_seconds <= 0:
            raise ValueError("scale-down stabilization must be positive")


@dataclasses.dataclass(frozen=True)
class RuntimeWebGatewayHardLimits:
    """Hard process ceilings that protect the Gateway before HPA reacts."""

    maximum_active_exchanges: int
    maximum_application_buffer_bytes: int
    maximum_scheduler_waiters: int
    maximum_event_loop_lag_milliseconds: int
    maximum_resident_memory_bytes: int

    def __post_init__(self) -> None:
        values = (
            ("maximum_active_exchanges", self.maximum_active_exchanges),
            (
                "maximum_application_buffer_bytes",
                self.maximum_application_buffer_bytes,
            ),
            ("maximum_scheduler_waiters", self.maximum_scheduler_waiters),
            (
                "maximum_event_loop_lag_milliseconds",
                self.maximum_event_loop_lag_milliseconds,
            ),
            ("maximum_resident_memory_bytes", self.maximum_resident_memory_bytes),
        )
        for name, value in values:
            if value <= 0:
                raise ValueError(f"{name} must be positive")


@dataclasses.dataclass(frozen=True)
class RuntimeWebGatewayResourceSnapshot:
    """Content-free current hard-limit usage."""

    active_exchanges: int
    application_buffer_bytes: int
    control_buffer_bytes: int
    scheduler_waiters: int


class RuntimeWebGatewayResourceTracker:
    """Reject local work synchronously before a hard ceiling is exceeded."""

    def __init__(self, limits: RuntimeWebGatewayHardLimits) -> None:
        self.limits = limits
        self.active_exchanges = 0
        self.application_buffer_bytes = 0
        self.control_buffer_bytes = 0
        self.scheduler_waiters = 0
        self.condition = asyncio.Condition()

    def try_open_exchange(self) -> bool:
        """Reserve one local exchange without waiting for HPA."""
        if self.active_exchanges >= self.limits.maximum_active_exchanges:
            return False
        self.active_exchanges += 1
        return True

    def close_exchange(self) -> None:
        """Release one exact local exchange reservation."""
        if self.active_exchanges <= 0:
            raise ValueError("Runtime Web active exchange reservation is absent")
        self.active_exchanges -= 1

    def try_reserve_application_buffer(self, size_bytes: int) -> bool:
        """Reserve bounded application bytes before reading more payload."""
        if size_bytes <= 0:
            raise ValueError(
                "Runtime Web application buffer reservation must be positive"
            )
        if (
            self.application_buffer_bytes + size_bytes
            > self.limits.maximum_application_buffer_bytes
        ):
            return False
        self.application_buffer_bytes += size_bytes
        return True

    async def reserve_application_buffer(self, size_bytes: int) -> bool:
        """Wait for bounded application-buffer capacity without excess waiters."""
        if size_bytes <= 0:
            raise ValueError(
                "Runtime Web application buffer reservation must be positive"
            )
        if size_bytes > self.limits.maximum_application_buffer_bytes:
            return False
        async with self.condition:
            if self.try_reserve_application_buffer(size_bytes):
                return True
            if not self.try_add_scheduler_waiter():
                return False
            try:
                await self.condition.wait_for(
                    lambda: (
                        self.application_buffer_bytes + size_bytes
                        <= self.limits.maximum_application_buffer_bytes
                    )
                )
                self.application_buffer_bytes += size_bytes
                return True
            finally:
                self.remove_scheduler_waiter()

    async def release_application_buffer(self, size_bytes: int) -> None:
        """Release previously reserved application bytes."""
        async with self.condition:
            if size_bytes <= 0 or size_bytes > self.application_buffer_bytes:
                raise ValueError("Runtime Web application buffer release is invalid")
            self.application_buffer_bytes -= size_bytes
            self.condition.notify_all()

    def reserve_control_buffer(self, size_bytes: int) -> None:
        """Record one bounded transport-control buffer reservation."""
        if size_bytes <= 0:
            raise ValueError("Runtime Web control buffer reservation must be positive")
        self.control_buffer_bytes += size_bytes

    def release_control_buffer(self, size_bytes: int) -> None:
        """Release one exact transport-control buffer reservation."""
        if size_bytes <= 0 or size_bytes > self.control_buffer_bytes:
            raise ValueError("Runtime Web control buffer release is invalid")
        self.control_buffer_bytes -= size_bytes

    def try_add_scheduler_waiter(self) -> bool:
        """Reserve one bounded scheduler waiter."""
        if self.scheduler_waiters >= self.limits.maximum_scheduler_waiters:
            return False
        self.scheduler_waiters += 1
        return True

    def remove_scheduler_waiter(self) -> None:
        """Release one scheduler waiter."""
        if self.scheduler_waiters <= 0:
            raise ValueError("Runtime Web scheduler waiter reservation is absent")
        self.scheduler_waiters -= 1

    def pressure(
        self,
        *,
        event_loop_lag_milliseconds: float,
        resident_memory_bytes: int,
    ) -> RuntimeWebGatewayPressure:
        """Project exact process usage into the bounded HPA pressure gauge."""
        if event_loop_lag_milliseconds < 0 or resident_memory_bytes < 0:
            raise ValueError("Runtime Web pressure inputs must not be negative")
        return RuntimeWebGatewayPressure(
            active_exchange_ratio=min(
                1.0,
                self.active_exchanges / self.limits.maximum_active_exchanges,
            ),
            application_buffer_ratio=min(
                1.0,
                self.application_buffer_bytes
                / self.limits.maximum_application_buffer_bytes,
            ),
            scheduler_wait_ratio=min(
                1.0,
                self.scheduler_waiters / self.limits.maximum_scheduler_waiters,
            ),
            event_loop_lag_ratio=min(
                1.0,
                event_loop_lag_milliseconds
                / self.limits.maximum_event_loop_lag_milliseconds,
            ),
            resident_memory_ratio=min(
                1.0,
                resident_memory_bytes / self.limits.maximum_resident_memory_bytes,
            ),
        )

    def snapshot(self) -> RuntimeWebGatewayResourceSnapshot:
        """Return content-free exact local usage."""
        return RuntimeWebGatewayResourceSnapshot(
            active_exchanges=self.active_exchanges,
            application_buffer_bytes=self.application_buffer_bytes,
            control_buffer_bytes=self.control_buffer_bytes,
            scheduler_waiters=self.scheduler_waiters,
        )


class RuntimeWebDrainStreamKind(enum.StrEnum):
    """Drain timing class for one active browser exchange."""

    FINITE_HTTP = "finite_http"
    LONG_LIVED = "long_lived"


@dataclasses.dataclass(frozen=True)
class RuntimeWebDrainRegistration:
    """Exact process-local drain registration token."""

    registration_id: int
    kind: RuntimeWebDrainStreamKind = dataclasses.field(compare=False)


class RuntimeWebDrainCallbackPhase(enum.StrEnum):
    """Bounded callback stage reported by drain cleanup."""

    SESSION = "session"
    GRACEFUL = "graceful"
    FORCE = "force"


@dataclasses.dataclass(frozen=True)
class RuntimeWebDrainCallbackFailure:
    """Content-free callback failure retained for operator diagnostics."""

    registration_id: int | None
    phase: RuntimeWebDrainCallbackPhase
    error_type: str


@dataclasses.dataclass(frozen=True)
class RuntimeWebDrainResult:
    """Bounded drain outcome without application content."""

    gracefully_closed: tuple[int, ...]
    force_closed: tuple[int, ...]
    callback_failures: tuple[RuntimeWebDrainCallbackFailure, ...]


@dataclasses.dataclass(frozen=True)
class _ActiveDrainStream:
    registration: RuntimeWebDrainRegistration
    request_graceful_close: Callable[[CloseReason], Awaitable[None]]
    force_close: Callable[[CloseReason], Awaitable[None]]


class RuntimeWebDrainCoordinator:
    """Refuse new work, signal graceful closure, and enforce drain deadlines."""

    def __init__(
        self,
        *,
        policy: RuntimeWebDrainPolicy,
        resources: RuntimeWebGatewayResourceTracker,
        begin_session_drain: Callable[[CloseReason], Awaitable[None]],
    ) -> None:
        self.policy = policy
        self.resources = resources
        self.begin_session_drain = begin_session_drain
        self.draining = False
        self.next_registration_id = 1
        self.active: dict[int, _ActiveDrainStream] = {}
        self.condition = asyncio.Condition()
        self.drain_started_at: float | None = None
        self.dynamic_force_closed: set[int] = set()
        self.dynamic_callback_failures: list[RuntimeWebDrainCallbackFailure] = []

    async def register(
        self,
        *,
        kind: RuntimeWebDrainStreamKind,
        request_graceful_close: Callable[[CloseReason], Awaitable[None]],
        force_close: Callable[[CloseReason], Awaitable[None]],
    ) -> RuntimeWebDrainRegistration | None:
        """Reserve one active exchange unless drain or a hard ceiling forbids it."""
        async with self.condition:
            if self.draining or not self.resources.try_open_exchange():
                return None
            registration = RuntimeWebDrainRegistration(
                registration_id=self.next_registration_id,
                kind=kind,
            )
            self.next_registration_id += 1
            self.active[registration.registration_id] = _ActiveDrainStream(
                registration=registration,
                request_graceful_close=request_graceful_close,
                force_close=force_close,
            )
            return registration

    async def release(self, registration: RuntimeWebDrainRegistration) -> bool:
        """Release only the exact active registration."""
        async with self.condition:
            active = self.active.get(registration.registration_id)
            if active is None or active.registration != registration:
                return False
            self.active.pop(registration.registration_id)
            self.resources.close_exchange()
            self.condition.notify_all()
            return True

    async def reclassify(
        self,
        registration: RuntimeWebDrainRegistration,
        *,
        kind: RuntimeWebDrainStreamKind,
    ) -> bool:
        """Reclassify an accepted response and preserve its drain-start deadline."""
        async with self.condition:
            active = self.active.get(registration.registration_id)
            if active is None or active.registration != registration:
                return False
            updated = dataclasses.replace(
                active,
                registration=dataclasses.replace(
                    active.registration,
                    kind=kind,
                ),
            )
            self.active[registration.registration_id] = updated
            drain_started_at = self.drain_started_at
        if (
            drain_started_at is not None
            and kind is RuntimeWebDrainStreamKind.LONG_LIVED
        ):
            await self._close_reclassified_long_lived(updated, drain_started_at)
        return True

    async def drain(self) -> RuntimeWebDrainResult:
        """Complete cleanup even when the caller is cancelled during drain."""
        cleanup = asyncio.create_task(
            self._drain(),
            name="runtime-web-gateway-drain",
        )
        try:
            return await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await asyncio.shield(cleanup)
            raise

    async def _drain(self) -> RuntimeWebDrainResult:
        """Run the approved 5-second and 120-second drain sequence."""
        loop = asyncio.get_running_loop()
        started_at = loop.time()
        async with self.condition:
            self.draining = True
            self.drain_started_at = started_at
            active_at_start = tuple(self.active.values())
            long_lived = tuple(
                active
                for active in active_at_start
                if active.registration.kind is RuntimeWebDrainStreamKind.LONG_LIVED
            )
            finite_http_ids = tuple(
                active.registration.registration_id
                for active in active_at_start
                if active.registration.kind is RuntimeWebDrainStreamKind.FINITE_HTTP
            )
        callback_failures = list(
            await _run_close(
                self.begin_session_drain,
                phase=RuntimeWebDrainCallbackPhase.SESSION,
                timeout_seconds=self.policy.long_lived_grace_seconds,
            )
        )
        remaining_long_lived_seconds = max(
            0.0,
            self.policy.long_lived_grace_seconds - (loop.time() - started_at),
        )
        callback_failures.extend(
            await _close_streams(
                long_lived,
                graceful=True,
                timeout_seconds=remaining_long_lived_seconds,
            )
        )
        remaining_long_lived_seconds = max(
            0.0,
            self.policy.long_lived_grace_seconds - (loop.time() - started_at),
        )
        await self._wait_for_release(
            tuple(item.registration.registration_id for item in long_lived),
            timeout_seconds=remaining_long_lived_seconds,
        )
        forced_long_lived, force_long_lived_failures = await self._force_remaining(
            tuple(item.registration.registration_id for item in long_lived)
        )
        callback_failures.extend(force_long_lived_failures)

        remaining_http_seconds = max(
            0.0,
            self.policy.finite_http_grace_seconds - (loop.time() - started_at),
        )
        await self._wait_for_release(
            finite_http_ids,
            timeout_seconds=remaining_http_seconds,
        )
        forced_http, force_http_failures = await self._force_remaining(finite_http_ids)
        callback_failures.extend(force_http_failures)
        async with self.condition:
            dynamic_forced = tuple(self.dynamic_force_closed)
            dynamic_failures = tuple(self.dynamic_callback_failures)
        forced = tuple(sorted({*forced_long_lived, *forced_http, *dynamic_forced}))
        async with self.condition:
            graceful = tuple(
                sorted(
                    registration_id
                    for registration_id in (
                        *(item.registration.registration_id for item in long_lived),
                        *finite_http_ids,
                    )
                    if registration_id not in forced
                )
            )
        return RuntimeWebDrainResult(
            gracefully_closed=graceful,
            force_closed=forced,
            callback_failures=tuple((*callback_failures, *dynamic_failures)),
        )

    async def _close_reclassified_long_lived(
        self,
        active: _ActiveDrainStream,
        drain_started_at: float,
    ) -> None:
        registration_id = active.registration.registration_id
        remaining = max(
            0.0,
            self.policy.long_lived_grace_seconds
            - (asyncio.get_running_loop().time() - drain_started_at),
        )
        failures = await _close_streams(
            (active,),
            graceful=True,
            timeout_seconds=remaining,
        )
        remaining = max(
            0.0,
            self.policy.long_lived_grace_seconds
            - (asyncio.get_running_loop().time() - drain_started_at),
        )
        await self._wait_for_release((registration_id,), timeout_seconds=remaining)
        forced, force_failures = await self._force_remaining((registration_id,))
        async with self.condition:
            self.dynamic_force_closed.update(forced)
            self.dynamic_callback_failures.extend((*failures, *force_failures))

    async def _wait_for_release(
        self,
        registration_ids: tuple[int, ...],
        *,
        timeout_seconds: float,
    ) -> None:
        if not registration_ids or timeout_seconds <= 0:
            return
        registration_id_set = frozenset(registration_ids)
        try:
            async with asyncio.timeout(timeout_seconds):
                async with self.condition:
                    await self.condition.wait_for(
                        lambda: registration_id_set.isdisjoint(self.active)
                    )
        except TimeoutError:
            return

    async def _force_remaining(
        self,
        registration_ids: tuple[int, ...],
    ) -> tuple[
        tuple[int, ...],
        tuple[RuntimeWebDrainCallbackFailure, ...],
    ]:
        registration_id_set = frozenset(registration_ids)
        async with self.condition:
            remaining = tuple(
                active
                for registration_id, active in self.active.items()
                if registration_id in registration_id_set
            )
        forced_ids = tuple(
            sorted(item.registration.registration_id for item in remaining)
        )
        failures: tuple[RuntimeWebDrainCallbackFailure, ...] = ()
        try:
            failures = await _close_streams(
                remaining,
                graceful=False,
                timeout_seconds=1.0,
            )
        finally:
            async with self.condition:
                for registration_id in forced_ids:
                    if self.active.pop(registration_id, None) is not None:
                        self.resources.close_exchange()
                self.condition.notify_all()
        return forced_ids, failures


async def _close_streams(
    streams: tuple[_ActiveDrainStream, ...],
    *,
    graceful: bool,
    timeout_seconds: float,
) -> tuple[RuntimeWebDrainCallbackFailure, ...]:
    if not streams or timeout_seconds <= 0:
        return ()
    callbacks = tuple(
        (stream.request_graceful_close if graceful else stream.force_close)(
            CloseReason.SERVICE_DRAIN
        )
        for stream in streams
    )
    try:
        async with asyncio.timeout(timeout_seconds):
            results = await asyncio.gather(*callbacks, return_exceptions=True)
    except TimeoutError:
        return tuple(
            RuntimeWebDrainCallbackFailure(
                registration_id=stream.registration.registration_id,
                phase=(
                    RuntimeWebDrainCallbackPhase.GRACEFUL
                    if graceful
                    else RuntimeWebDrainCallbackPhase.FORCE
                ),
                error_type=TimeoutError.__name__,
            )
            for stream in streams
        )
    phase = (
        RuntimeWebDrainCallbackPhase.GRACEFUL
        if graceful
        else RuntimeWebDrainCallbackPhase.FORCE
    )
    return tuple(
        RuntimeWebDrainCallbackFailure(
            registration_id=stream.registration.registration_id,
            phase=phase,
            error_type=type(result).__name__,
        )
        for stream, result in zip(streams, results, strict=True)
        if isinstance(result, BaseException)
    )


async def _run_close(
    close: Callable[[CloseReason], Awaitable[None]],
    *,
    phase: RuntimeWebDrainCallbackPhase,
    timeout_seconds: float,
) -> tuple[RuntimeWebDrainCallbackFailure, ...]:
    if timeout_seconds <= 0:
        return ()
    try:
        async with asyncio.timeout(timeout_seconds):
            await close(CloseReason.SERVICE_DRAIN)
    except TimeoutError:
        return (
            RuntimeWebDrainCallbackFailure(
                registration_id=None,
                phase=phase,
                error_type=TimeoutError.__name__,
            ),
        )
    except Exception as error:
        return (
            RuntimeWebDrainCallbackFailure(
                registration_id=None,
                phase=phase,
                error_type=type(error).__name__,
            ),
        )
    return ()


@dataclasses.dataclass
class RuntimeWebGatewayOperationalState:
    """Mutable process-local evidence exposed only on the internal port."""

    health: RuntimeWebGatewayHealth
    pressure: RuntimeWebGatewayPressure
    backend: RuntimeWebCapacityBackend
    capacity_degraded: bool
    resources: RuntimeWebGatewayResourceTracker
    local_open_count: int
    relay_open_count: int
    event_loop_lag_milliseconds: float
    resident_memory_bytes: int

    def update_dependencies(
        self,
        *,
        evidence: RuntimeWebGatewayDependencyEvidence,
        redis_available: bool,
    ) -> None:
        """Replace dependency evidence without changing process liveness."""
        self.health = dataclasses.replace(
            self.health,
            authority_query_available=evidence.authority_query_succeeded,
            replacement_protocol_compatible=(evidence.replacement_protocol_compatible),
            redis_available=redis_available,
        )

    def update_process_pressure(
        self,
        *,
        event_loop_lag_milliseconds: float,
        resident_memory_bytes: int,
    ) -> None:
        """Refresh live pressure and process-only health from hard-limit usage."""
        self.event_loop_lag_milliseconds = event_loop_lag_milliseconds
        self.resident_memory_bytes = resident_memory_bytes
        self.pressure = self.current_pressure()
        self.health = dataclasses.replace(
            self.health,
            local_pressure_acceptable=self.pressure.value < 1.0,
            event_loop_responsive=self.pressure.event_loop_lag_ratio < 1.0,
        )

    def refresh_resource_pressure(self) -> None:
        """Refresh mutable resource ratios using cached loop and RSS evidence."""
        self.update_process_pressure(
            event_loop_lag_milliseconds=self.event_loop_lag_milliseconds,
            resident_memory_bytes=self.resident_memory_bytes,
        )

    def current_pressure(self) -> RuntimeWebGatewayPressure:
        """Return current resource usage with the latest sampled process evidence."""
        return self.resources.pressure(
            event_loop_lag_milliseconds=self.event_loop_lag_milliseconds,
            resident_memory_bytes=self.resident_memory_bytes,
        )

    def begin_drain(self) -> None:
        """Make readiness false before new work is refused."""
        self.health = dataclasses.replace(self.health, draining=True)

    def record_route(self, route: str) -> None:
        """Record one bounded local or relay admission outcome."""
        if route == "local":
            self.local_open_count += 1
        elif route == "relay":
            self.relay_open_count += 1
        else:
            raise ValueError("Runtime Web route metric is invalid")


class RuntimeWebGatewayOperationsCoordinator:
    """Order readiness withdrawal before inactive transport drain."""

    def __init__(
        self,
        *,
        state: RuntimeWebGatewayOperationalState,
        drain: RuntimeWebDrainCoordinator,
    ) -> None:
        if state.resources is not drain.resources:
            raise ValueError("Runtime Web operations must share one resource tracker")
        self.state = state
        self.drain_coordinator = drain

    async def drain(self) -> RuntimeWebDrainResult:
        """Withdraw readiness before GOAWAY and bounded stream closure."""
        self.state.begin_drain()
        return await self.drain_coordinator.drain()


def render_openmetrics(
    *,
    pressure: RuntimeWebGatewayPressure,
    health: RuntimeWebGatewayHealth,
    backend: RuntimeWebCapacityBackend,
    capacity_degraded: bool,
    active_exchanges: int,
    local_open_count: int,
    relay_open_count: int,
    application_buffer_bytes: int,
    application_buffer_limit_bytes: int,
    control_buffer_bytes: int,
    scheduler_waiters: int,
    scheduler_waiter_limit: int,
    resident_memory_bytes: int,
    resident_memory_limit_bytes: int,
) -> str:
    """Render the bounded process-level OpenMetrics contract."""
    backend_label = f'backend="{backend.value}"'
    lines = [
        "# TYPE runtime_web_gateway_pressure gauge",
        f"runtime_web_gateway_pressure {pressure.value}",
        "# TYPE runtime_web_gateway_active_exchanges gauge",
        f"runtime_web_gateway_active_exchanges {active_exchanges}",
        "# TYPE runtime_web_gateway_open_total counter",
        f'runtime_web_gateway_open_total{{route="local"}} {local_open_count}',
        f'runtime_web_gateway_open_total{{route="relay"}} {relay_open_count}',
        "# TYPE runtime_web_gateway_application_buffer_bytes gauge",
        f"runtime_web_gateway_application_buffer_bytes {application_buffer_bytes}",
        "# TYPE runtime_web_gateway_application_buffer_limit_bytes gauge",
        (
            "runtime_web_gateway_application_buffer_limit_bytes "
            f"{application_buffer_limit_bytes}"
        ),
        "# TYPE runtime_web_gateway_control_buffer_bytes gauge",
        f"runtime_web_gateway_control_buffer_bytes {control_buffer_bytes}",
        "# TYPE runtime_web_gateway_scheduler_waiters gauge",
        f"runtime_web_gateway_scheduler_waiters {scheduler_waiters}",
        "# TYPE runtime_web_gateway_scheduler_waiter_limit gauge",
        f"runtime_web_gateway_scheduler_waiter_limit {scheduler_waiter_limit}",
        "# TYPE runtime_web_gateway_resident_memory_bytes gauge",
        f"runtime_web_gateway_resident_memory_bytes {resident_memory_bytes}",
        "# TYPE runtime_web_gateway_resident_memory_limit_bytes gauge",
        (
            "runtime_web_gateway_resident_memory_limit_bytes "
            f"{resident_memory_limit_bytes}"
        ),
        "# TYPE runtime_web_gateway_ready gauge",
        f"runtime_web_gateway_ready {int(health.ready)}",
        "# TYPE runtime_web_gateway_live gauge",
        f"runtime_web_gateway_live {int(health.live)}",
        "# TYPE runtime_web_capacity_backend_info gauge",
        f"runtime_web_capacity_backend_info{{{backend_label}}} 1",
        "# TYPE runtime_web_capacity_degraded gauge",
        f"runtime_web_capacity_degraded{{{backend_label}}} {int(capacity_degraded)}",
        "# EOF",
    ]
    return "\n".join(lines) + "\n"
