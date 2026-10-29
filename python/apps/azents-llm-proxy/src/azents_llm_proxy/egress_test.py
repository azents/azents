"""Attempt counts, redirect/cookie isolation and ordinary SDK transport ownership."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Literal

import httpx
import pytest
import respx
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
from pydantic import SecretStr
from starlette.types import Message, Scope

from azents_llm_proxy import bootstrap
from azents_llm_proxy.authority import AuthorityClient
from azents_llm_proxy.authority_test import AGENT, SERVICE, binding
from azents_llm_proxy.egress import NoReplayTransport, NoReplayTransportError
from azents_llm_proxy.observability import LOGGER
from azents_llm_proxy.proxy_test import MODEL, RESULT, payload, setup_proxy

ENDPOINT = "https://provider.invalid/v1/responses"


def approved(method: str, url: str) -> None:
    assert method == "POST" and url == ENDPOINT


class FaultyStream(httpx.AsyncByteStream):
    def __init__(self, phase: Literal["read", "close"]) -> None:
        self.phase = phase
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        if self.phase == "read":
            raise httpx.ConnectError("transport-secret-sentinel")
        yield b"{}"

    async def aclose(self) -> None:
        self.closed = True
        if self.phase == "close":
            raise httpx.ConnectError("transport-secret-sentinel")


@pytest.mark.parametrize("phase", ["connect", "protocol", "read", "close"])
async def test_sdk_handler_never_replays_transport_failures(phase: str) -> None:
    calls = 0
    stream = FaultyStream("read" if phase == "read" else "close")

    async def provider(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if phase == "connect":
            raise httpx.ConnectError("transport-secret-sentinel")
        if phase == "protocol":
            raise httpx.RemoteProtocolError("transport-secret-sentinel")
        return httpx.Response(200, stream=stream)

    handler = AsyncHTTPHandler(
        transport=NoReplayTransport(httpx.MockTransport(provider), approved),
        follow_redirects=False,
    )
    try:
        with pytest.raises(NoReplayTransportError) as caught:
            await handler.post(ENDPOINT, json={"model": "synthetic"})
        assert "transport-secret-sentinel" not in str(caught.value)
        assert calls == 1
        if phase in {"read", "close"}:
            assert stream.closed
    finally:
        await handler.client.aclose()


async def test_sdk_handler_does_not_follow_provider_redirects_or_retain_cookies() -> (
    None
):
    calls: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            307,
            headers={
                "Location": "https://foreign.invalid/credential-sink",
                "Set-Cookie": "provider-session=account-a; Secure; Path=/",
            },
        )

    handler = AsyncHTTPHandler(
        transport=NoReplayTransport(httpx.MockTransport(provider), approved),
        follow_redirects=False,
    )
    try:
        for account in ("a", "b"):
            with pytest.raises(httpx.HTTPStatusError):
                await handler.post(
                    ENDPOINT,
                    json={"model": "synthetic"},
                    headers={"Authorization": f"Bearer account-{account}"},
                )
        assert len(calls) == 2
        assert not any("cookie" in request.headers for request in calls)
        assert not handler.client.follow_redirects
    finally:
        await handler.client.aclose()


async def test_transport_preserves_cancellation_and_stream_closure() -> None:
    started, never = asyncio.Event(), asyncio.Event()

    class WaitingStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            started.set()
            await never.wait()
            yield b"{}"

        async def aclose(self) -> None:
            self.closed = True

    stream = WaitingStream()
    calls = 0

    def provider(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=stream)

    async with httpx.AsyncClient(
        transport=NoReplayTransport(httpx.MockTransport(provider), approved)
    ) as client:
        task = asyncio.create_task(client.post(ENDPOINT, json={"model": "synthetic"}))
        async with asyncio.timeout(10):
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert stream.closed and calls == 1


@pytest.mark.usefixtures("protected_provider_clients")
@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.RemoteProtocolError])
async def test_real_proxy_transport_error_has_one_attempt_and_private_result(
    error: type[httpx.TransportError],
) -> None:
    selected = binding().model_copy(
        update={"public_model": MODEL, "model_identifier": MODEL}
    )

    def authority(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=selected.protected_json())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        with respx.mock(assert_all_called=False) as router:
            upstream = router.post("https://api.openai.com/v1/responses").mock(
                side_effect=error("provider-sentinel private-prompt")
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://proxy"
            ) as client:
                response = await client.post(
                    "/v1/responses",
                    headers={"Authorization": f"Bearer {AGENT}"},
                    json=payload(),
                )
            assert response.status_code >= 500
            assert upstream.call_count == 1
            assert (
                "provider-sentinel" not in response.text
                and "private-prompt" not in response.text
            )


@pytest.mark.usefixtures("protected_provider_clients")
async def test_real_proxy_midstream_failure_is_private_and_not_false_completion(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from azents_llm_proxy.privacy import install_vendor_diagnostics  # noqa: PLC0415

    install_vendor_diagnostics()
    selected = binding().model_copy(
        update={"public_model": MODEL, "model_identifier": MODEL}
    )

    class FailingResponse(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            created = {"type": "response.created", "response": RESULT}
            yield f"event: response.created\ndata: {json.dumps(created)}\n\n".encode()
            raise httpx.ReadError("midstream-provider-sentinel private-prompt")

        async def aclose(self) -> None:
            self.closed = True

    stream = FailingResponse()

    def authority(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=selected.protected_json())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        with respx.mock(assert_all_called=False) as router:
            upstream = router.post("https://api.openai.com/v1/responses").mock(
                return_value=httpx.Response(
                    200, stream=stream, headers={"Content-Type": "text/event-stream"}
                )
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://proxy"
            ) as client:
                response = await client.post(
                    "/v1/responses",
                    headers={"Authorization": f"Bearer {AGENT}"},
                    json={**payload(), "stream": True},
                )
            assert upstream.call_count == 1
    assert stream.closed
    assert response.status_code == 200
    assert "response.created" in response.text
    assert "response.completed" not in response.text
    frames = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: {")
    ]
    failed = next(frame for frame in frames if frame["type"] == "response.failed")
    assert failed["response"]["status"] == "failed"
    assert failed["response"]["model"] == MODEL
    assert failed["response"]["error"]["code"] == "server_error"
    captured = capsys.readouterr()
    for secret in ("midstream-provider-sentinel", "private-prompt", AGENT, SERVICE):
        assert secret not in response.text + caplog.text + captured.out + captured.err
    assert bootstrap.context.current.get() is None


@pytest.mark.usefixtures("protected_provider_clients")
async def test_real_proxy_disconnect_closes_provider_stream_without_replay(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER.name)
    selected = binding().model_copy(
        update={"public_model": MODEL, "model_identifier": MODEL}
    )
    emitted, never = asyncio.Event(), asyncio.Event()
    consumed = False

    class WaitingResponse(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            created = {"type": "response.created", "response": RESULT}
            yield f"event: response.created\ndata: {json.dumps(created)}\n\n".encode()
            await never.wait()

        async def aclose(self) -> None:
            self.closed = True

    stream = WaitingResponse()

    async def receive() -> Message:
        nonlocal consumed
        if not consumed:
            consumed = True
            return {
                "type": "http.request",
                "body": json.dumps({**payload(), "stream": True}).encode(),
                "more_body": False,
            }
        await emitted.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            emitted.set()

    def authority(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=selected.protected_json())

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/v1/responses",
        "raw_path": b"/v1/responses",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"authorization", f"Bearer {AGENT}".encode()),
            (b"content-type", b"application/json"),
        ],
        "server": ("proxy", 443),
        "client": ("127.0.0.1", 1),
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        with respx.mock(assert_all_called=False) as router:
            upstream = router.post("https://api.openai.com/v1/responses").mock(
                return_value=httpx.Response(
                    200, stream=stream, headers={"Content-Type": "text/event-stream"}
                )
            )
            async with asyncio.timeout(10):
                await app(scope, receive, send)
            assert upstream.call_count == 1
    assert emitted.is_set() and stream.closed
    assert bootstrap.context.current.get() is None
    events = [r.__dict__ for r in caplog.records if r.name == LOGGER.name]
    assert len(events) == 1
    assert events[0]["outcome"] == "disconnected"
