"""Focused real SDK/parser tests for model observation and lifecycle."""

import asyncio
import gzip
from collections.abc import AsyncIterator

import httpx2
import pytest
from pydantic_ai.messages import ModelRequest, TextPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters

from azents.core.enums import LLMProvider
from azents.engine.events.pydantic_ai_adapter import PydanticAIModelAdapter
from azents.engine.events.pydantic_ai_types import (
    PydanticAIRequest,
    PydanticAIStreamEvent,
)
from azents.engine.model_stream import (
    ModelStreamCallContext,
    ModelStreamCleanupRegistry,
    ModelStreamTimeoutPolicy,
    ModelStreamTimeoutPolicyResolver,
    ModelStreamWatchdog,
)
from azents.engine.model_stream_test import ControlledClock
from azents.engine.provider_errors import SDK_PROVIDER_ERRORS, map_model_provider_error
from azents.engine.providers.model_factory import (
    ProviderModelFactory,
    ProviderTransports,
)
from azents.engine.run.types import USER_STOP_CANCEL_MESSAGE
from azents.testing.provider_native_envelopes import core_native_response


class GatedSDKBody(httpx2.AsyncByteStream):
    """Expose actual SDK acquisition before allowing its first native event."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = asyncio.Event()
        self.iterations = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.iterations += 1
        self.started.set()
        await self.release.wait()
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed.set()


def request_for_test() -> PydanticAIRequest:
    return PydanticAIRequest(
        native_replay_context=None,
        assembly_metadata=None,
        provider="xai",
        model="grok-test",
        messages=[ModelRequest(parts=[UserPromptPart(content="Synthetic input")])],
        settings={},
        parameters=ModelRequestParameters(),
    )


def context_for_test() -> ModelStreamCallContext:
    return ModelStreamCallContext(
        call_kind="sampling",
        provider="xai",
        provider_integration_id="synthetic-integration",
        model="grok-test",
        session_id="synthetic-session",
        run_id="synthetic-run",
        attempt_number=1,
        check_stop=None,
    )


def watchdog_for_test(
    clock: ControlledClock, policy: ModelStreamTimeoutPolicy
) -> ModelStreamWatchdog:
    return ModelStreamWatchdog(
        resolver=ModelStreamTimeoutPolicyResolver(
            default=policy, provider_overrides=(), specific_overrides=()
        ),
        cleanup_registry=ModelStreamCleanupRegistry(clock=clock),
        close_grace_seconds=5,
        clock=clock,
    )


def adapter_for_test(body: GatedSDKBody, *, compressed: bool) -> PydanticAIModelAdapter:
    def response(request: httpx2.Request) -> httpx2.Response:
        headers = {"content-type": "text/event-stream"}
        if compressed:
            headers["content-encoding"] = "gzip"
        return httpx2.Response(200, headers=headers, stream=body, request=request)

    return PydanticAIModelAdapter(
        factory=ProviderModelFactory(
            provider=LLMProvider.XAI,
            credential_kwargs={
                "api_key": "synthetic-sdk-key",
                "base_url": "https://synthetic.invalid/v1",
            },
            sdk_failure_mapper=map_model_provider_error,
            sdk_error_types=SDK_PROVIDER_ERRORS,
            transports=ProviderTransports(httpx2=httpx2.MockTransport(response)),
        )
    )


async def collect(
    adapter: PydanticAIModelAdapter,
    watchdog: ModelStreamWatchdog,
    policy: ModelStreamTimeoutPolicy,
) -> list[PydanticAIStreamEvent]:
    return [
        event
        async for event in adapter.stream(
            request_for_test(),
            watchdog=watchdog,
            timeout_policy=policy,
            call_context=context_for_test(),
        )
    ]


@pytest.mark.parametrize("compressed", [False, True])
async def test_actual_sdk_header_acquisition_precedes_first_event(
    compressed: bool,
) -> None:
    envelope = core_native_response(
        protocol="responses", model="grok-test", text="Synthetic output"
    )
    wire = gzip.compress(envelope.body) if compressed else envelope.body
    body = GatedSDKBody([wire[:11], wire[11:]])
    adapter = adapter_for_test(body, compressed=compressed)
    clock = ControlledClock()
    policy = ModelStreamTimeoutPolicy(
        connect_timeout_seconds=2,
        parsed_event_idle_timeout_seconds=50,
        absolute_attempt_timeout_seconds=100,
    )
    watchdog = watchdog_for_test(clock, policy)
    operation = asyncio.create_task(collect(adapter, watchdog, policy))
    await body.started.wait()
    await clock.wait_until(lambda: 50 in clock.sleeper_deadlines)
    clock.advance(10)
    body.release.set()
    events = await operation
    assert any(
        item.observation is not None and item.observation.terminal == "success"
        for item in events
    )
    finals = [item.response for item in events if item.response is not None]
    assert len(finals) == 1
    assert any(
        isinstance(part, TextPart) and part.content == "Synthetic output"
        for part in finals[0].parts
    )
    assert body.iterations == 1
    assert body.closed.is_set()
    assert not adapter.active
    await adapter.close()


async def test_user_stop_closes_real_sdk_body_without_failed_run_error() -> None:
    envelope = core_native_response(
        protocol="responses", model="grok-test", text="Synthetic output"
    )
    body = GatedSDKBody([envelope.body])
    adapter = adapter_for_test(body, compressed=False)
    clock = ControlledClock()
    policy = ModelStreamTimeoutPolicy(
        connect_timeout_seconds=2,
        parsed_event_idle_timeout_seconds=50,
        absolute_attempt_timeout_seconds=100,
    )
    operation = asyncio.create_task(
        collect(adapter, watchdog_for_test(clock, policy), policy)
    )
    await body.started.wait()
    operation.cancel(USER_STOP_CANCEL_MESSAGE)
    with pytest.raises(asyncio.CancelledError):
        await operation
    await body.closed.wait()
    assert not adapter.active
    await adapter.close()


class NonCooperativeCloseBody(GatedSDKBody):
    """Keep a real SDK body close pending until an explicit ownership barrier."""

    def __init__(self, chunks: list[bytes]) -> None:
        super().__init__(chunks)
        self.close_requested = asyncio.Event()
        self.close_release = asyncio.Event()

    async def aclose(self) -> None:
        self.close_requested.set()
        await self.close_release.wait()
        self.closed.set()


async def test_stop_does_not_wait_for_noncooperative_sdk_close() -> None:
    envelope = core_native_response(
        protocol="responses", model="grok-test", text="Synthetic output"
    )
    body = NonCooperativeCloseBody([envelope.body])
    adapter = adapter_for_test(body, compressed=False)
    clock = ControlledClock()
    policy = ModelStreamTimeoutPolicy(
        connect_timeout_seconds=2,
        parsed_event_idle_timeout_seconds=50,
        absolute_attempt_timeout_seconds=100,
    )
    watchdog = watchdog_for_test(clock, policy)
    operation = asyncio.create_task(collect(adapter, watchdog, policy))
    await body.started.wait()
    operation.cancel(USER_STOP_CANCEL_MESSAGE)
    with pytest.raises(asyncio.CancelledError):
        await operation
    await body.close_requested.wait()
    assert not body.closed.is_set()
    assert watchdog.cleanup_registry.active_count > 0
    assert clock.time() == 0
    body.close_release.set()
    await body.closed.wait()
    assert await watchdog.cleanup_registry.drain(grace_seconds=5) == 0
    assert not adapter.active
