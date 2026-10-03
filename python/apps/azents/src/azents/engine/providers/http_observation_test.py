"""Contract tests for one SDK-decoded body and attempt-local observations."""

import asyncio
import gzip
import json
import zlib
from collections.abc import AsyncIterator
from concurrent.futures import CancelledError as ThreadEmissionCancelled

import httpx2
import pytest

from azents.engine.events.pydantic_ai_types import PydanticAIStreamEvent
from azents.engine.model_stream import ModelStreamCallContext, ModelStreamTimeoutPolicy
from azents.engine.provider_errors import map_model_provider_error
from azents.engine.providers.http_observation import ObservedHTTPX2Transport
from azents.engine.providers.observation_state import (
    NativeObservationState,
    UnauthorizedModelDispatchError,
)
from azents.engine.run.provider_failure import ModelProviderFailure


class CountedBody(httpx2.AsyncByteStream):
    """An unconsumed native transport body with observable resource ownership."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.iterations = 0
        self.close_count = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.iterations += 1
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.close_count += 1


def state_for_test() -> NativeObservationState:
    return NativeObservationState(
        protocol="responses",
        call_context=ModelStreamCallContext(
            call_kind="sampling",
            provider="xai",
            provider_integration_id="synthetic-integration",
            model="grok-test",
            session_id="synthetic-session",
            run_id="synthetic-run",
            attempt_number=1,
            check_stop=None,
        ),
        timeout_policy=ModelStreamTimeoutPolicy(
            connect_timeout_seconds=15,
            parsed_event_idle_timeout_seconds=300,
            absolute_attempt_timeout_seconds=1800,
        ),
        sdk_failure_mapper=map_model_provider_error,
    )


def sse(payload: dict[str, object]) -> bytes:
    return b"data: " + json.dumps(payload).encode() + b"\n\n"


@pytest.mark.parametrize("encoding", ["identity", "gzip", "deflate"])
async def test_sdk_decoded_payload_is_observed_once(encoding: str) -> None:
    payload = sse({"type": "response.in_progress"}) + sse(
        {"type": "response.completed", "response": {"status": "completed"}}
    )
    wire = (
        gzip.compress(payload)
        if encoding == "gzip"
        else zlib.compress(payload)
        if encoding == "deflate"
        else payload
    )
    body = CountedBody([wire[:7], wire[7:19], wire[19:]])
    state = state_for_test()

    def response(request: httpx2.Request) -> httpx2.Response:
        headers = {
            "content-type": "text/event-stream",
            "content-length": str(len(wire)),
        }
        if encoding != "identity":
            headers["content-encoding"] = encoding
        return httpx2.Response(200, headers=headers, stream=body, request=request)

    transport = ObservedHTTPX2Transport(
        delegate=httpx2.MockTransport(response), state=state
    )
    async with httpx2.AsyncClient(transport=transport) as client:
        async with client.stream(
            "POST", "https://synthetic.invalid/responses"
        ) as result:
            assert state.response_acquired.done()
            read = asyncio.create_task(result.aread())
            first = await state.queue.get()
            last = await state.queue.get()
            assert isinstance(first, PydanticAIStreamEvent)
            assert first.observation is not None
            assert first.observation.event_type == "response.in_progress"
            assert isinstance(last, PydanticAIStreamEvent)
            assert last.observation is not None
            assert last.observation.terminal == "success"
            assert await read == payload
    assert body.iterations == 1
    assert body.close_count >= 1
    assert state.dispatch_count == 1


async def test_hidden_http_dispatch_preserves_original_safe_failure() -> None:
    state = state_for_test()
    calls = 0
    body = CountedBody(
        [
            json.dumps(
                {
                    "error": {
                        "code": "rate_limit_exceeded",
                        "message": "Rate limit reached",
                        "type": "rate_limit_error",
                    }
                }
            ).encode()
        ]
    )

    def response(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(
            429,
            headers={"content-type": "application/json", "retry-after": "7"},
            stream=body,
            request=request,
        )

    transport = ObservedHTTPX2Transport(
        delegate=httpx2.MockTransport(response), state=state
    )
    async with httpx2.AsyncClient(transport=transport) as client:
        first = asyncio.create_task(client.post("https://synthetic.invalid/responses"))
        await state.queue.get()
        result = await first
        assert result.status_code == 429
        original = state.original_failure
        assert isinstance(original, ModelProviderFailure)
        with pytest.raises(ModelProviderFailure) as raised:
            await client.post("https://synthetic.invalid/responses")
        assert raised.value is original
        assert raised.value.provider_message == "Rate limit reached"
        assert raised.value.retry_hint_seconds == 7
    assert calls == 1


async def test_no_original_failure_is_an_internal_dispatch_violation() -> None:
    state = state_for_test()
    state.authorize_dispatch()
    with pytest.raises(UnauthorizedModelDispatchError):
        state.authorize_dispatch()
    assert state.original_failure is None


async def test_thread_backpressure_is_released_when_caller_closes() -> None:
    state = state_for_test()
    await state.observe({"type": "response.in_progress"})
    started = asyncio.Event()
    loop = asyncio.get_running_loop()

    def worker() -> bool:
        loop.call_soon_threadsafe(started.set)
        try:
            state.observe_from_thread({"type": "response.in_progress"})
        except ThreadEmissionCancelled:
            return True
        return False

    operation = asyncio.create_task(asyncio.to_thread(worker))
    await started.wait()
    state.begin_close()
    assert await operation
    assert not state.thread_emissions


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            b"Argument not supported: search_context_size",
            "Argument not supported: search_context_size",
        ),
        (b"Rejected api_key=sk-supersecret123", "Rejected api_key=[REDACTED]"),
        (b'"Unsupported option"', "Unsupported option"),
        (
            b"Service unavailable: Authorization: Bearer secret-token",
            "Service unavailable: Authorization=[REDACTED] [REDACTED]",
        ),
        (b"<html>" + b"private upstream debug " * 50 + b"</html>", None),
        (b"x" * 8193, None),
        (b"\xff\xfe", None),
        (b'["opaque body"]', None),
        (b"null", None),
    ],
)
async def test_http_error_scalar_body_reaches_safe_failure_once(
    payload: bytes, expected: str | None
) -> None:
    state = state_for_test()
    body = CountedBody([payload[:8], payload[8:]])

    def respond(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            400,
            headers={"content-type": "text/plain"},
            stream=body,
            request=request,
        )

    transport = ObservedHTTPX2Transport(
        delegate=httpx2.MockTransport(respond), state=state
    )
    async with httpx2.AsyncClient(transport=transport) as client:
        response = await client.post("https://synthetic.invalid/responses")
        assert response.content == payload
        failure = state.original_failure
        assert isinstance(failure, ModelProviderFailure)
        assert failure.status_code == 400
        assert failure.provider_message == expected
        assert "sk-supersecret123" not in str(failure)
        assert "secret-token" not in str(failure)
        assert state.queue.empty()
        assert state.dispatch_count == 1
    assert body.iterations == 1
    assert body.close_count >= 1
