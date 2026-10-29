"""Counted failure/cancellation on Kimi's distinct OpenAI-SDK HTTPX2 stack."""

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import httpx2
import pytest
from azents_llm_contract.authority import KimiCredential, TargetBinding
from pydantic import SecretStr
from starlette.types import Message, Scope

from azents_llm_proxy import bootstrap
from azents_llm_proxy.authority import AuthorityClient
from azents_llm_proxy.authority_test import AGENT, SERVICE, binding
from azents_llm_proxy.proxy_test import setup_proxy

pytestmark = pytest.mark.usefixtures("protected_provider_clients")
MODEL = "kimi-for-coding"


def selected() -> TargetBinding:
    original = binding()
    return original.model_copy(
        update={
            "public_model": MODEL,
            "model_identifier": MODEL,
            "credential": KimiCredential(
                kind="kimi_oauth",
                access_token=SecretStr("kimi-secret-sentinel"),
                device_id=SecretStr("kimi-device-sentinel"),
            ),
            "configuration": original.configuration.model_copy(
                update={"protocol": "chat"}
            ),
        }
    )


def payload(stream: bool) -> dict[str, object]:
    return {
        "model": MODEL,
        "input": "kimi-private-prompt",
        "stream": stream,
        "metadata": {"azents_target_id": "a" * 64},
    }


def delta() -> bytes:
    value = {
        "id": "chatcmpl_fixture",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": MODEL,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": "kimi-progress"},
                "finish_reason": None,
            }
        ],
    }
    return f"data: {json.dumps(value)}\n\n".encode()


@pytest.mark.parametrize("phase", ["connect", "midstream"])
async def test_kimi_transport_failure_never_replays_or_leaks(
    phase: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = 0
    closed = False

    class FailureStream(httpx2.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield delta()
            raise httpx2.ReadError("kimi-provider-error-sentinel")

        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    def provider(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        if phase == "connect":
            raise httpx2.ConnectError("kimi-provider-error-sentinel")
        return httpx2.Response(
            200, stream=FailureStream(), headers={"Content-Type": "text/event-stream"}
        )

    def transport(**kwargs: object) -> httpx2.AsyncBaseTransport:
        return httpx2.MockTransport(provider)

    monkeypatch.setattr(httpx2, "AsyncHTTPTransport", transport)

    def authority(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=selected().protected_json())

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://proxy"
        ) as client:
            response = await client.post(
                "/v1/responses",
                headers={"Authorization": "Bearer " + AGENT},
                json=payload(phase == "midstream"),
            )
    assert calls == 1
    if phase == "connect":
        assert response.status_code >= 400
    else:
        assert response.status_code == 200 and closed
        assert "response.completed" not in response.text
    for sentinel in [
        "kimi-secret-sentinel",
        "kimi-device-sentinel",
        "kimi-private-prompt",
        "kimi-provider-error-sentinel",
    ]:
        assert sentinel not in response.text + caplog.text
    assert bootstrap.context.current.get() is None


async def test_kimi_downstream_disconnect_closes_provider_without_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivered = asyncio.Event()
    never = asyncio.Event()
    calls = 0
    closed = False
    consumed = False

    class WaitingStream(httpx2.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield delta()
            await never.wait()

        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    def provider(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(
            200, stream=WaitingStream(), headers={"Content-Type": "text/event-stream"}
        )

    def transport(**kwargs: object) -> httpx2.AsyncBaseTransport:
        return httpx2.MockTransport(provider)

    monkeypatch.setattr(httpx2, "AsyncHTTPTransport", transport)

    def authority(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=selected().protected_json())

    async def receive() -> Message:
        nonlocal consumed
        if not consumed:
            consumed = True
            return {
                "type": "http.request",
                "body": json.dumps(payload(True)).encode(),
                "more_body": False,
            }
        await delivered.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body" and b"kimi-progress" in message.get(
            "body", b""
        ):
            delivered.set()

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
            (b"authorization", ("Bearer " + AGENT).encode()),
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
        async with asyncio.timeout(10):
            await app(scope, receive, send)
    assert delivered.is_set() and closed and calls == 1
    assert bootstrap.context.current.get() is None
