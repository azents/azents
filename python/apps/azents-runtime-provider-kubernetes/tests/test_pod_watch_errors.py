"""Pod-watch reconnect boundaries preserve unexpected failures."""

import asyncio
import contextlib
import json
import socket
from collections.abc import AsyncGenerator, AsyncIterator, Mapping

import aiohttp
import pytest
from aiohttp import web
from azents_runtime_control.provider import ProviderRunLoop, RuntimeProviderReport

from azents_runtime_provider_kubernetes import main as provider_main
from azents_runtime_provider_kubernetes.kubernetes_http import (
    KubernetesApiRequestError,
    KubernetesHttpApi,
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


class _StreamLifecycle(KubernetesRuntimeProvider):
    """Lifecycle fake that exercises the actual HTTP watch decoder."""

    def __init__(self, api: KubernetesHttpApi) -> None:
        self.api = api

    async def watch_known_runtimes(self) -> AsyncIterator[RuntimeProviderReport]:
        """Expose raw watch errors without manufacturing a Provider report."""
        async for _ in self.api.watch_pods({}, "workload"):
            raise AssertionError("A Status stream emitted a Pod")
        raise AssertionError("A Status stream completed without an error")
        yield


@contextlib.asynccontextmanager
async def _watch_api(
    event: Mapping[str, object],
) -> AsyncIterator[KubernetesHttpApi]:
    """Serve one actual HTTP 200 watch event without fixed timing delays."""
    app = web.Application()

    async def serve(request: web.Request) -> web.Response:
        assert request.query["watch"] == "true"
        return web.Response(
            body=(json.dumps(event) + "\n").encode(),
            content_type="application/json",
        )

    app.router.add_get("/api/v1/namespaces/workload/pods", serve)
    runner = web.AppRunner(app)
    with socket.socket() as listener:
        await runner.setup()
        try:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            site = web.SockSite(runner, listener)
            await site.start()
            async with aiohttp.ClientSession(
                base_url=f"http://127.0.0.1:{port}"
            ) as session:
                yield KubernetesHttpApi(session)
        finally:
            await runner.cleanup()


def _status_event(code: int | str) -> Mapping[str, object]:
    """Return a Kubernetes watch Status fixture at the wire boundary."""
    return {
        "type": "ERROR",
        "object": {
            "kind": "Status",
            "apiVersion": "v1",
            "status": "Failure",
            "reason": "Expired",
            "message": "too old resource version",
            "code": code,
        },
    }


@pytest.mark.parametrize("code", [410, 500])
async def test_http_200_status_becomes_api_failure(code: int) -> None:
    """In-stream errors are API failures rather than invalid Pod objects."""
    async with _watch_api(_status_event(code)) as api:
        stream = api.watch_pods({}, "workload")
        assert isinstance(stream, AsyncGenerator)
        try:
            with pytest.raises(KubernetesApiRequestError) as raised:
                await anext(stream)
            assert raised.value.status == code
            assert raised.value.reason == "Expired"
            assert raised.value.body == "too old resource version"
        finally:
            await stream.aclose()


async def test_expired_http_200_watch_status_reconnects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The standalone retry-boundary fix recovers from real 410 wire events."""
    stop = asyncio.Event()
    reconnect_calls = 0

    async def reconnect(event: asyncio.Event) -> None:
        nonlocal reconnect_calls
        reconnect_calls += 1
        event.set()

    monkeypatch.setattr(provider_main, "_wait_for_reconnect", reconnect)
    async with _watch_api(_status_event(410)) as api:
        await provider_main._report_pod_watch_events(
            _StreamLifecycle(api), _UnusedRunLoop(), stop=stop
        )
    assert reconnect_calls == 1


@pytest.mark.parametrize("code", ["410", 200])
async def test_malformed_watch_status_propagates(
    monkeypatch: pytest.MonkeyPatch, code: int | str
) -> None:
    """Malformed watch payloads never become operational reconnect attempts."""
    stop = asyncio.Event()

    async def reconnect(event: asyncio.Event) -> None:
        raise AssertionError("Malformed Status triggered reconnect")

    monkeypatch.setattr(provider_main, "_wait_for_reconnect", reconnect)
    async with _watch_api(_status_event(code)) as api:
        with pytest.raises(RuntimeError, match="watch Status"):
            await provider_main._report_pod_watch_events(
                _StreamLifecycle(api), _UnusedRunLoop(), stop=stop
            )


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
