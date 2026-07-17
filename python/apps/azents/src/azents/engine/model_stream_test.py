"""Tests for the application-owned model stream watchdog."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypeVar

import httpx
import pytest
from openai import APITimeoutError

from azents.engine.model_stream import (
    ModelStreamCallContext,
    ModelStreamCleanupRegistry,
    ModelStreamProviderPolicyOverride,
    ModelStreamSpecificPolicyOverride,
    ModelStreamTimeoutPolicy,
    ModelStreamTimeoutPolicyResolver,
    ModelStreamWatchdog,
    close_stream_response,
    connect_only_http_timeout,
)
from azents.engine.run.errors import ModelStreamTimeoutError
from azents.engine.run.types import USER_STOP_CANCEL_MESSAGE

T = TypeVar("T")


class ControlledClock:
    """Manually advance monotonic time and wake due sleepers."""

    def __init__(self) -> None:
        self.now = 0.0
        self._sleepers: list[tuple[float, asyncio.Future[None]]] = []

    def time(self) -> float:
        """Return the controlled monotonic time."""
        return self.now

    async def sleep(self, delay: float) -> None:
        """Wait until controlled time reaches the requested deadline."""
        if delay <= 0:
            return
        future = asyncio.get_running_loop().create_future()
        sleeper = (self.now + delay, future)
        self._sleepers.append(sleeper)
        try:
            await future
        finally:
            self._sleepers.remove(sleeper)

    def advance(self, seconds: float) -> None:
        """Advance controlled time and resolve due sleepers."""
        self.now += seconds
        for deadline, future in tuple(self._sleepers):
            if deadline <= self.now and not future.done():
                future.set_result(None)

    @property
    def sleeper_count(self) -> int:
        """Return the number of active controlled sleeps."""
        return len(self._sleepers)

    @property
    def sleeper_deadlines(self) -> tuple[float, ...]:
        """Return active controlled-sleep deadlines in ascending order."""
        return tuple(sorted(deadline for deadline, _ in self._sleepers))


class TimedStream:
    """Emit parsed events after advancing controlled time for each event."""

    def __init__(
        self,
        clock: ControlledClock,
        *,
        event_times: list[float],
    ) -> None:
        self.clock = clock
        self.event_times = iter(event_times)
        self.index = 0
        self.closed = False

    def __aiter__(self) -> AsyncIterator[int]:
        return self

    async def __anext__(self) -> int:
        try:
            delay = next(self.event_times)
        except StopIteration:
            raise StopAsyncIteration from None
        self.clock.advance(delay)
        event = self.index
        self.index += 1
        return event

    async def aclose(self) -> None:
        self.closed = True


class BlockingStream:
    """Block event delivery, optionally suppressing cancellation until released."""

    def __init__(self, *, suppress_cancellation: bool) -> None:
        self.suppress_cancellation = suppress_cancellation
        self.release = asyncio.Event()
        self.closed = False

    def __aiter__(self) -> AsyncIterator[str]:
        return self

    async def __anext__(self) -> str:
        while True:
            try:
                await self.release.wait()
                return "late-event"
            except asyncio.CancelledError:
                if not self.suppress_cancellation:
                    raise

    async def aclose(self) -> None:
        self.closed = True


class CloseableResponse:
    """Async response handle used to verify late-open cleanup."""

    def __init__(self) -> None:
        self.closed = False

    def __aiter__(self) -> AsyncIterator[object]:
        return self

    async def __anext__(self) -> object:
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


async def _wait_until(check: Callable[[], bool]) -> None:
    """Yield until an asynchronous test condition becomes true."""
    for _ in range(100):
        if check():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition did not become true")


def _policy(
    *,
    connect: float = 15,
    idle: float = 5,
    absolute: float = 30,
) -> ModelStreamTimeoutPolicy:
    return ModelStreamTimeoutPolicy(
        connect_timeout_seconds=connect,
        parsed_event_idle_timeout_seconds=idle,
        absolute_attempt_timeout_seconds=absolute,
    )


def _context(
    *,
    check_stop: Callable[[], Awaitable[bool]] | None = None,
) -> ModelStreamCallContext:
    return ModelStreamCallContext(
        call_kind="sampling",
        provider="test-provider",
        provider_integration_id=None,
        model="test-model",
        session_id="session-1",
        run_id="run-1",
        attempt_number=2,
        check_stop=check_stop,
    )


def _watchdog(
    clock: ControlledClock,
    *,
    policy: ModelStreamTimeoutPolicy,
    close_grace: float = 2,
) -> ModelStreamWatchdog:
    registry = ModelStreamCleanupRegistry(clock=clock)
    return ModelStreamWatchdog(
        resolver=ModelStreamTimeoutPolicyResolver(
            default=policy,
            provider_overrides=(),
            specific_overrides=(),
        ),
        cleanup_registry=registry,
        close_grace_seconds=close_grace,
        clock=clock,
    )


@pytest.mark.parametrize("field", ["connect", "idle", "absolute"])
def test_timeout_policy_requires_positive_finite_values(field: str) -> None:
    values = {"connect": 15.0, "idle": 300.0, "absolute": 1_800.0}
    values[field] = 0

    with pytest.raises(ValueError, match="finite and greater than zero"):
        _policy(**values)


def test_policy_resolver_prefers_specific_then_provider_then_default() -> None:
    default = _policy(idle=30)
    provider = _policy(idle=20)
    model = _policy(idle=10)
    profile = _policy(idle=5)
    resolver = ModelStreamTimeoutPolicyResolver(
        default=default,
        provider_overrides=(
            ModelStreamProviderPolicyOverride(
                provider="provider-a",
                policy=provider,
            ),
        ),
        specific_overrides=(
            ModelStreamSpecificPolicyOverride(
                model="model-a",
                inference_profile=None,
                policy=model,
            ),
            ModelStreamSpecificPolicyOverride(
                model=None,
                inference_profile="profile-a",
                policy=profile,
            ),
        ),
    )

    assert (
        resolver.resolve(
            provider="provider-a",
            model="model-a",
            inference_profile=None,
        )
        is model
    )
    assert (
        resolver.resolve(
            provider="provider-a",
            model="model-b",
            inference_profile=None,
        )
        is provider
    )
    assert (
        resolver.resolve(
            provider="provider-b",
            model="model-b",
            inference_profile="profile-a",
        )
        is profile
    )
    assert (
        resolver.resolve(
            provider="provider-b",
            model="model-b",
            inference_profile=None,
        )
        is default
    )


def test_connect_only_http_timeout_does_not_add_transport_idle_deadlines() -> None:
    timeout = connect_only_http_timeout(15)

    assert timeout.connect == 15
    assert timeout.read is None
    assert timeout.write is None
    assert timeout.pool is None


async def test_open_response_classifies_provider_connect_timeout() -> None:
    clock = ControlledClock()
    policy = _policy(connect=15)
    watchdog = _watchdog(clock, policy=policy)

    async def fail_connect() -> object:
        raise APITimeoutError(httpx.Request("POST", "https://example.test"))

    with pytest.raises(ModelStreamTimeoutError) as captured:
        await watchdog.open_response(
            fail_connect,
            policy=policy,
            context=_context(),
        )

    assert captured.value.timeout_kind == "connect"
    assert captured.value.failure_code == "model_connect_timeout"
    assert captured.value.deadline_seconds == 15
    assert captured.value.provider == "test-provider"
    assert captured.value.model == "test-model"


async def test_open_response_enforces_application_connect_deadline() -> None:
    """Response acquisition uses the configured application connect deadline."""
    clock = ControlledClock()
    policy = _policy(connect=5, idle=30, absolute=60)
    watchdog = _watchdog(clock, policy=policy)
    release = asyncio.Event()

    async def block_connect() -> object:
        await release.wait()
        return object()

    task = asyncio.create_task(
        watchdog.open_response(
            block_connect,
            policy=policy,
            context=_context(),
        )
    )
    await _wait_until(lambda: clock.sleeper_count == 2)
    clock.advance(5)

    with pytest.raises(ModelStreamTimeoutError) as captured:
        await task

    assert captured.value.timeout_kind == "connect"
    assert captured.value.failure_code == "model_connect_timeout"
    assert captured.value.deadline_seconds == 5
    assert watchdog.cleanup_registry.active_count == 0


async def test_parsed_event_idle_timeout_closes_cooperative_iterator() -> None:
    clock = ControlledClock()
    policy = _policy(idle=5, absolute=30)
    watchdog = _watchdog(clock, policy=policy)
    stream = BlockingStream(suppress_cancellation=False)

    async def consume() -> list[str]:
        return [
            event
            async for event in watchdog.watch_iterable(
                stream,
                policy=policy,
                context=_context(),
            )
        ]

    task = asyncio.create_task(consume())
    await _wait_until(lambda: clock.sleeper_count == 2)
    clock.advance(5)

    with pytest.raises(ModelStreamTimeoutError) as captured:
        await task

    assert captured.value.timeout_kind == "parsed_event_idle"
    assert captured.value.failure_code == "model_stream_idle_timeout"
    assert stream.closed
    assert watchdog.cleanup_registry.active_count == 0


async def test_all_parsed_events_reset_idle_deadline() -> None:
    clock = ControlledClock()
    policy = _policy(idle=5, absolute=30)
    watchdog = _watchdog(clock, policy=policy)
    stream = TimedStream(clock, event_times=[4, 4, 4])

    events = [
        event
        async for event in watchdog.watch_iterable(
            stream,
            policy=policy,
            context=_context(),
        )
    ]

    assert events == [0, 1, 2]
    assert clock.time() == 12


async def test_absolute_attempt_cap_wins_despite_continuous_events() -> None:
    clock = ControlledClock()
    policy = _policy(idle=5, absolute=10)
    watchdog = _watchdog(clock, policy=policy)
    stream = TimedStream(clock, event_times=[4, 4, 4])
    events: list[int] = []

    with pytest.raises(ModelStreamTimeoutError) as captured:
        async for event in watchdog.watch_iterable(
            stream,
            policy=policy,
            context=_context(),
        ):
            events.append(event)

    assert events == [0, 1, 2]
    assert captured.value.timeout_kind == "absolute_attempt"
    assert captured.value.failure_code == "model_attempt_timeout"
    assert captured.value.elapsed_seconds == 12
    assert stream.closed


async def test_consumer_close_releases_iterator_between_events() -> None:
    clock = ControlledClock()
    policy = _policy(idle=5, absolute=30)
    watchdog = _watchdog(clock, policy=policy)
    stream = TimedStream(clock, event_times=[1, 1])
    watched = watchdog.watch_iterable(
        stream,
        policy=policy,
        context=_context(),
    )

    assert await anext(watched) == 0
    await close_stream_response(watched)

    await _wait_until(lambda: stream.closed)
    assert watchdog.cleanup_registry.active_count == 0


async def test_user_stop_preempts_simultaneous_idle_timeout() -> None:
    clock = ControlledClock()
    policy = _policy(idle=5, absolute=30)
    watchdog = _watchdog(clock, policy=policy)
    stream = BlockingStream(suppress_cancellation=False)

    async def check_stop() -> bool:
        return True

    async def consume() -> None:
        async for _ in watchdog.watch_iterable(
            stream,
            policy=policy,
            context=_context(check_stop=check_stop),
        ):
            pass

    task = asyncio.create_task(consume())
    await _wait_until(lambda: clock.sleeper_count == 2)
    clock.advance(5)

    with pytest.raises(asyncio.CancelledError) as captured:
        await task

    assert captured.value.args == (USER_STOP_CANCEL_MESSAGE,)
    await _wait_until(lambda: stream.closed)
    await _wait_until(lambda: watchdog.cleanup_registry.active_count == 0)


async def test_timeout_adopts_non_cooperative_cleanup_and_closes_late_handle() -> None:
    clock = ControlledClock()
    policy = _policy(connect=5, idle=30, absolute=60)
    watchdog = _watchdog(clock, policy=policy, close_grace=2)
    release = asyncio.Event()
    response = CloseableResponse()

    async def open_late() -> object:
        while True:
            try:
                await release.wait()
                return response
            except asyncio.CancelledError:
                continue

    task = asyncio.create_task(
        watchdog.open_response(
            open_late,
            policy=policy,
            context=_context(),
        )
    )
    await _wait_until(lambda: clock.sleeper_count == 2)
    clock.advance(5)
    await _wait_until(lambda: clock.sleeper_deadlines == (7.0,))
    clock.advance(2)

    with pytest.raises(ModelStreamTimeoutError):
        await task

    assert watchdog.cleanup_registry.active_count == 1
    release.set()
    await _wait_until(lambda: response.closed)
    await _wait_until(lambda: watchdog.cleanup_registry.active_count == 0)


async def test_cleanup_registry_drain_returns_after_grace_for_stubborn_task() -> None:
    clock = ControlledClock()
    registry = ModelStreamCleanupRegistry(clock=clock)
    release = asyncio.Event()

    async def stubborn_cleanup() -> None:
        while True:
            try:
                await release.wait()
                return
            except asyncio.CancelledError:
                continue

    cleanup = asyncio.create_task(stubborn_cleanup())
    registry.adopt(
        cleanup,
        context=_context(),
        reason="shutdown",
    )
    drain = asyncio.create_task(registry.drain(grace_seconds=2))
    await _wait_until(lambda: clock.sleeper_count == 1)
    clock.advance(2)

    assert await drain == 1
    assert registry.active_count == 1
    release.set()
    await _wait_until(lambda: registry.active_count == 0)
