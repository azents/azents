"""Pod-watch reconnect boundaries preserve unexpected failures."""

import asyncio
from collections.abc import AsyncIterator

import aiohttp
import pytest
from azents_runtime_control.provider import ProviderRunLoop, RuntimeProviderReport

from azents_runtime_provider_kubernetes import main as provider_main
from azents_runtime_provider_kubernetes.kubernetes_http import (
    KubernetesApiRequestError,
)
from azents_runtime_provider_kubernetes.provider import KubernetesRuntimeProvider


class _FailingLifecycle(KubernetesRuntimeProvider):
    """Typed lifecycle fake whose watch fails before emitting a report."""

    def __init__(self, failure: BaseException) -> None:
        self.failure = failure
        self.watch_calls = 0

    async def watch_known_runtimes(self) -> AsyncIterator[RuntimeProviderReport]:
        """Expose exactly one controlled watch failure."""
        self.watch_calls += 1
        raise self.failure
        yield


class _UnusedRunLoop(ProviderRunLoop):
    """Typed reporter fake that must not receive an absent report."""

    def __init__(self) -> None:
        pass

    async def report_provider_state(
        self, report: RuntimeProviderReport
    ) -> RuntimeProviderReport:
        """Fail if a broken watch attempts to send a report."""
        raise AssertionError("A failed watch emitted a report")


@pytest.mark.parametrize(
    "failure",
    [
        aiohttp.ClientConnectionError("watch connection closed"),
        KubernetesApiRequestError(
            method="GET",
            path="/api/v1/namespaces/workload/pods",
            status=410,
            reason="Gone",
            body="watch resource version expired",
        ),
    ],
)
async def test_expected_watch_failure_reconnects(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure: Exception,
) -> None:
    """Operational API failures retain bounded reconnect and traceback logging."""
    stop = asyncio.Event()
    lifecycle = _FailingLifecycle(failure)
    reconnect_calls = 0

    async def reconnect(event: asyncio.Event) -> None:
        nonlocal reconnect_calls
        reconnect_calls += 1
        assert event is stop
        event.set()

    monkeypatch.setattr(provider_main, "_wait_for_reconnect", reconnect)
    await provider_main._report_pod_watch_events(lifecycle, _UnusedRunLoop(), stop=stop)

    assert lifecycle.watch_calls == 1
    assert reconnect_calls == 1
    record = next(
        record
        for record in caplog.records
        if "Pod watch disconnected" in record.message
    )
    assert record.exc_info is not None


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("unexpected watch failure"),
        ValueError("invalid report"),
        AssertionError("broken invariant"),
        TimeoutError("control timeout"),
        asyncio.CancelledError(),
    ],
)
async def test_unexpected_watch_failure_propagates(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    """Programming errors and shutdown/control signals do not become retries."""
    stop = asyncio.Event()
    lifecycle = _FailingLifecycle(failure)
    reconnect_calls = 0

    async def reconnect(event: asyncio.Event) -> None:
        nonlocal reconnect_calls
        reconnect_calls += 1
        event.set()

    monkeypatch.setattr(provider_main, "_wait_for_reconnect", reconnect)
    with pytest.raises(type(failure)) as raised:
        await provider_main._report_pod_watch_events(
            lifecycle, _UnusedRunLoop(), stop=stop
        )

    assert raised.value is failure
    assert lifecycle.watch_calls == 1
    assert reconnect_calls == 0
