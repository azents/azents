"""Physical SDK gates await internal admission without altering foreground guards."""

import asyncio
from collections.abc import Awaitable, Callable

import httpx2
import pytest

from azents.engine.model_stream import (
    InternalModelCallIdentity,
    InternalModelStreamCallContext,
    ModelDispatchAdmissionError,
    ModelStreamCallContext,
    ModelStreamTimeoutPolicy,
)
from azents.engine.providers.http_observation import ObservedHTTPX2Transport
from azents.engine.providers.observation_state import (
    NativeObservationState,
    UnauthorizedModelDispatchError,
)
from azents.engine.run.provider_failure import ModelProviderFailure


def _state(admit: Callable[[], Awaitable[None]]) -> NativeObservationState:
    def unexpected_mapper(
        error: Exception, *, call_context: ModelStreamCallContext
    ) -> ModelProviderFailure:
        raise AssertionError("No SDK failure is expected in this admission test.")

    context = InternalModelStreamCallContext(
        call_kind="historical_memory",
        provider="xai",
        provider_integration_id=None,
        model="selected-model",
        session_id=None,
        run_id=None,
        attempt_number=1,
        check_stop=None,
        identity=InternalModelCallIdentity("a" * 32, "w" * 32, "u" * 32, "t" * 32),
        admit_dispatch=admit,
    )
    return NativeObservationState(
        protocol="responses",
        call_context=context,
        timeout_policy=ModelStreamTimeoutPolicy(5, 5, 10),
        sdk_failure_mapper=unexpected_mapper,
    )


async def test_async_http_send_occurs_only_after_admission_and_once() -> None:
    events: list[str] = []

    async def admit() -> None:
        events.append("admitted")

    def response(request: httpx2.Request) -> httpx2.Response:
        events.append("sent")
        return httpx2.Response(200, content=b"{}")

    state = _state(admit)
    transport = ObservedHTTPX2Transport(
        delegate=httpx2.MockTransport(response), state=state
    )
    async with httpx2.AsyncClient(transport=transport) as client:
        await client.post("https://synthetic.invalid/responses")
        with pytest.raises(UnauthorizedModelDispatchError):
            await client.post("https://synthetic.invalid/responses")
    assert events == ["admitted", "sent"]
    assert state.dispatch_count == 1


async def test_rejected_http_admission_sends_nothing_and_retains_safe_reason() -> None:
    sent = False

    async def admit() -> None:
        raise ModelDispatchAdmissionError("budget")

    def response(request: httpx2.Request) -> httpx2.Response:
        nonlocal sent
        sent = True
        return httpx2.Response(200, content=b"{}")

    state = _state(admit)
    transport = ObservedHTTPX2Transport(
        delegate=httpx2.MockTransport(response), state=state
    )
    async with httpx2.AsyncClient(transport=transport) as client:
        with pytest.raises(ModelDispatchAdmissionError) as failure:
            await client.post("https://synthetic.invalid/responses")
    assert failure.value.reason == "budget"
    assert not sent and state.dispatch_blocked
    assert state.admission_failure is failure.value


async def test_sync_sdk_waits_for_event_loop_admission_before_sending() -> None:
    started, release = asyncio.Event(), asyncio.Event()
    events: list[str] = []

    async def admit() -> None:
        started.set()
        await release.wait()
        events.append("admitted")

    state = _state(admit)

    def send() -> None:
        state.authorize_dispatch_from_thread()
        events.append("sent")

    worker = asyncio.create_task(asyncio.to_thread(send))
    await started.wait()
    assert events == [] and not worker.done()
    release.set()
    await worker
    assert events == ["admitted", "sent"]


async def test_closing_releases_thread_waiting_on_admission_without_dispatch() -> None:
    started, finished = asyncio.Event(), asyncio.Event()
    never = asyncio.Event()
    sent = False

    async def admit() -> None:
        started.set()
        try:
            await never.wait()
        finally:
            finished.set()

    state = _state(admit)

    def send() -> bool:
        nonlocal sent
        try:
            state.authorize_dispatch_from_thread()
        except asyncio.CancelledError:
            return False
        sent = True
        return True

    worker = asyncio.create_task(asyncio.to_thread(send))
    await started.wait()
    state.begin_close()
    assert not await worker
    await finished.wait()
    assert not sent and state.dispatch_blocked


async def test_foreground_sync_sdk_checks_stop_before_dispatch() -> None:
    """All synchronous providers honor common stop on the owning event loop."""
    loop = asyncio.get_running_loop()
    checked = asyncio.Event()
    sent = False

    async def admit() -> None:
        raise AssertionError("Foreground calls do not use internal admission.")

    async def check_stop() -> bool:
        assert asyncio.get_running_loop() is loop
        checked.set()
        return True

    state = _state(admit)
    state.call_context = ModelStreamCallContext(
        call_kind="sampling",
        provider="aws_bedrock",
        provider_integration_id=None,
        model="selected-model",
        session_id="s" * 32,
        run_id="r" * 32,
        attempt_number=1,
        check_stop=check_stop,
    )

    def send() -> None:
        nonlocal sent
        state.authorize_dispatch_from_thread()
        sent = True

    with pytest.raises(asyncio.CancelledError):
        await asyncio.to_thread(send)
    assert checked.is_set()
    assert not sent and state.dispatch_blocked
