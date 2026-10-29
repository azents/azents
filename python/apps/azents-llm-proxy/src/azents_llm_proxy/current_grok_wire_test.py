"""Current Grok subscription credentials and incremental native Responses wire."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import httpx
import litellm
import pytest
import respx
from azents_llm_contract.authority import XaiCredential
from pydantic import SecretStr
from starlette.types import Message, Scope

from azents_llm_proxy import bootstrap
from azents_llm_proxy.authority import AuthorityClient
from azents_llm_proxy.authority_test import AGENT, SERVICE, binding
from azents_llm_proxy.observability import LOGGER
from azents_llm_proxy.proxy_test import RESULT, payload, setup_proxy

pytestmark = pytest.mark.usefixtures("protected_provider_clients")


@pytest.mark.parametrize("model", ["grok-4.5", "grok-4.6", "grok-4.7"])
@pytest.mark.parametrize("stream", [False, True])
async def test_current_grok_explicit_subscription_and_native_progress(
    model: str, stream: bool, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER.name)
    assert litellm.utils.supports_native_streaming(
        model=model, custom_llm_provider="xai"
    )
    selected = binding().model_copy(
        update={
            "public_model": model,
            "model_identifier": model,
            "credential": XaiCredential(
                kind="xai_oauth", access_token=SecretStr("current-grok-token")
            ),
        }
    )
    result = {**RESULT, "model": model}
    delivered = asyncio.Event()
    complete = False
    closed = False
    text = "native-progress-sentinel"
    messages: list[Message] = []

    def frame(event: dict[str, object]) -> bytes:
        return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()

    class ProviderStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            nonlocal complete
            yield frame(
                {
                    "type": "response.created",
                    "sequence_number": 0,
                    "response": {**result, "status": "in_progress"},
                }
            )
            yield frame(
                {
                    "type": "response.output_text.delta",
                    "sequence_number": 1,
                    "item_id": "msg_fixture",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": text,
                }
            )
            # A whole-response buffer/synthesized stream cannot pass this gate.
            await asyncio.wait_for(delivered.wait(), timeout=5)
            complete = True
            yield frame(
                {"type": "response.completed", "sequence_number": 2, "response": result}
            )

        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    def authority(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=selected.protected_json())

    def provider(request: httpx.Request) -> httpx.Response:
        wire = json.loads(request.content)
        assert wire["model"] == model and wire.get("stream", False) is stream
        assert request.headers["authorization"] == "Bearer current-grok-token"
        if stream:
            return httpx.Response(
                200,
                stream=ProviderStream(),
                headers={"Content-Type": "text/event-stream"},
            )
        return httpx.Response(200, json=result)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(authority),
        base_url="https://authority/internal/llm/",
    ) as authority_http:
        bootstrap.configure(AuthorityClient(authority_http, SecretStr(SERVICE)))
        app = await setup_proxy()
        with respx.mock(assert_all_called=False) as router:
            route = router.post("https://api.x.ai/v1/responses").mock(
                side_effect=provider
            )
            if stream:
                consumed = False

                async def receive() -> Message:
                    nonlocal consumed
                    if not consumed:
                        consumed = True
                        return {
                            "type": "http.request",
                            "body": json.dumps(
                                {**payload(), "model": model, "stream": True}
                            ).encode(),
                            "more_body": False,
                        }
                    await asyncio.Event().wait()
                    raise AssertionError("Disconnect was not requested.")

                async def send(message: Message) -> None:
                    messages.append(message)
                    if message[
                        "type"
                    ] == "http.response.body" and text.encode() in message.get(
                        "body", b""
                    ):
                        assert not complete
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
                async with asyncio.timeout(10):
                    await app(scope, receive, send)
                assert (
                    next(m for m in messages if m["type"] == "http.response.start")[
                        "status"
                    ]
                    == 200
                )
                body = b"".join(
                    m.get("body", b"")
                    for m in messages
                    if m["type"] == "http.response.body"
                )
                assert (
                    b"response.output_text.delta" in body
                    and b"response.completed" in body
                )
                assert b"response.failed" not in body
                assert delivered.is_set() and complete and closed
            else:
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="https://proxy"
                ) as client:
                    response = await client.post(
                        "/v1/responses",
                        headers={"Authorization": "Bearer " + AGENT},
                        json={**payload(), "model": model, "stream": False},
                    )
                assert response.status_code == 200, response.text
                body = response.content
            assert route.call_count == 1
    assert b"current-grok-token" not in body
    assert bootstrap.context.current.get() is None
    events = [r.__dict__ for r in caplog.records if r.name == LOGGER.name]
    assert len(events) == 1
    assert events[0]["outcome"] == "success"
    assert events[0]["input_tokens"] == 2
    assert events[0]["output_tokens"] == 1
    assert events[0]["total_tokens"] == 3
