"""Native-clock, completion and hidden recovery contracts at public SDK seams."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
import pytest
from pydantic_ai import RunContext
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    PartStartEvent,
    TextPart,
)
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.settings import ModelSettings

from azents.core.enums import LLMProvider
from azents.engine.events.pydantic_ai_adapter import (
    PydanticAIModelAdapter,
    _parsed_native_activity,
)
from azents.engine.events.pydantic_ai_adapter_test import (
    GatedSDKBody,
    adapter_for_test,
    collect,
    context_for_test,
    request_for_test,
    watchdog_for_test,
)
from azents.engine.events.pydantic_ai_output import PydanticAIOutputNormalizer
from azents.engine.events.pydantic_ai_types import PydanticAIStreamEvent
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.model_stream import ModelStreamTimeoutPolicy
from azents.engine.model_stream_test import ControlledClock
from azents.engine.provider_errors import SDK_PROVIDER_ERRORS, map_model_provider_error
from azents.engine.providers.model_factory import (
    ProviderModelBinding,
    ProviderModelFactory,
    ProviderTransports,
)
from azents.engine.providers.native_observation import observe_native_payload
from azents.engine.providers.observation_state import NativeObservationState
from azents.engine.run.errors import ModelStreamTimeoutError
from azents.engine.run.provider_failure import ModelProviderFailure
from azents.testing.provider_native_envelopes import core_native_response


class SteppedSDKBody(GatedSDKBody):
    """Permit individual native frames through explicit state barriers."""

    def __init__(self, chunks: list[bytes]) -> None:
        super().__init__(chunks)
        self.requested: asyncio.Queue[int] = asyncio.Queue(maxsize=1)
        self.permits = [asyncio.Event() for _ in chunks]

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.iterations += 1
        self.started.set()
        for index, chunk in enumerate(self.chunks):
            await self.requested.put(index)
            await self.permits[index].wait()
            yield chunk


async def test_all_native_events_refresh_idle_without_common_deltas() -> None:
    envelope = core_native_response(
        protocol="responses", model="grok-test", text="Synthetic output"
    )
    frames = [frame + b"\n\n" for frame in envelope.body.split(b"\n\n") if frame]
    first = json.loads(frames[0].split(b"data: ", 1)[1])
    metadata = [
        b"data: "
        + json.dumps(
            {
                "type": "response.in_progress",
                "sequence_number": index,
                "response": first["response"],
            }
        ).encode()
        + b"\n\n"
        for index in range(1, 4)
    ]
    chunks = [frames[0], *metadata, *frames[1:]]
    body = SteppedSDKBody(chunks)
    adapter = adapter_for_test(body, compressed=False)
    clock = ControlledClock()
    policy = ModelStreamTimeoutPolicy(
        connect_timeout_seconds=2,
        parsed_event_idle_timeout_seconds=5,
        absolute_attempt_timeout_seconds=100,
    )
    watchdog = watchdog_for_test(clock, policy)
    native_received: asyncio.Queue[str] = asyncio.Queue()
    events: list[PydanticAIStreamEvent] = []

    async def consume() -> None:
        async for event in adapter.stream(
            request_for_test(),
            watchdog=watchdog,
            timeout_policy=policy,
            call_context=context_for_test(),
        ):
            events.append(event)
            if event.observation is not None:
                native_received.put_nowait(event.observation.event_type)

    operation = asyncio.create_task(consume())
    for index in range(len(chunks)):
        assert await body.requested.get() == index
        if index < 4:
            await clock.wait_until(lambda: clock.time() + 5 in clock.sleeper_deadlines)
            clock.advance(4)
        body.permits[index].set()
        if index < 4:
            await native_received.get()
    await operation
    assert clock.time() == 16
    assert (
        sum(
            event.observation is not None
            and event.observation.event_type == "response.in_progress"
            for event in events
        )
        == 3
    )
    assert body.iterations == 1
    assert body.closed.is_set()


async def test_common_parts_do_not_refresh_native_idle() -> None:
    clock = ControlledClock()
    policy = ModelStreamTimeoutPolicy(
        connect_timeout_seconds=2,
        parsed_event_idle_timeout_seconds=5,
        absolute_attempt_timeout_seconds=100,
    )
    watchdog = watchdog_for_test(clock, policy)
    closed = asyncio.Event()

    async def source() -> AsyncIterator[PydanticAIStreamEvent]:
        try:
            yield PydanticAIStreamEvent(
                event=None,
                response=None,
                observation=observe_native_payload(
                    "responses", {"type": "response.in_progress"}
                ),
            )
            await clock.sleep(4)
            yield PydanticAIStreamEvent(
                event=PartStartEvent(index=0, part=TextPart(content="Synthetic")),
                response=None,
                observation=None,
            )
            await clock.sleep(2)
        finally:
            closed.set()

    async def consume() -> None:
        async for _ in watchdog.watch_iterable(
            source(),
            policy=policy,
            context=context_for_test(),
            parsed_event_activity=_parsed_native_activity,
        ):
            pass

    operation = asyncio.create_task(consume())
    await clock.wait_until(lambda: 4 in clock.sleeper_deadlines)
    clock.advance(4)
    await clock.wait_until(lambda: 6 in clock.sleeper_deadlines)
    clock.advance(1)
    with pytest.raises(ModelStreamTimeoutError) as raised:
        await operation
    assert raised.value.failure_code == "model_stream_idle_timeout"
    assert closed.is_set()


@pytest.mark.parametrize("native_terminal", [False, True])
async def test_actual_sdk_eof_is_not_native_completion(native_terminal: bool) -> None:
    envelope = core_native_response(
        protocol="responses", model="grok-test", text="Synthetic output"
    )
    frames = [
        frame + b"\n\n"
        for frame in envelope.body.split(b"\n\n")
        if frame and (native_terminal or b'"type":"response.completed"' not in frame)
    ]
    body = GatedSDKBody(frames)
    body.release.set()
    adapter = adapter_for_test(body, compressed=False)
    clock = ControlledClock()
    policy = ModelStreamTimeoutPolicy(
        connect_timeout_seconds=2,
        parsed_event_idle_timeout_seconds=50,
        absolute_attempt_timeout_seconds=100,
    )
    events = await collect(adapter, watchdog_for_test(clock, policy), policy)
    output = PydanticAIOutputNormalizer(
        provider="xai",
        model="grok-test",
        pricing=None,
        operation="sampling",
        integration="synthetic-integration",
    ).start("synthetic-session")
    for event in events:
        output.process_event(event)
    if native_terminal:
        assert output.complete().events
    else:
        with pytest.raises(ModelProviderFailure) as raised:
            output.complete()
        assert raised.value.provider_code == "stream_ended_before_completion"
    assert body.closed.is_set()


class RecoverOnceModel(Model):
    """Exercise hidden recovery using only the real public SDK route."""

    def __init__(self, stock: Model) -> None:
        self.stock = stock
        super().__init__(profile=stock.profile)

    @property
    def model_name(self) -> str:
        return self.stock.model_name

    @property
    def system(self) -> str:
        return self.stock.system

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[object] | None = None,
    ) -> ModelResponse:
        return await self.stock.request(
            messages, model_settings, model_request_parameters
        )

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: RunContext[object] | None = None,
    ) -> AsyncIterator[StreamedResponse]:
        first = self.stock.request_stream(
            messages, model_settings, model_request_parameters, run_context
        )
        try:
            stream = await first.__aenter__()
        except ModelAPIError:
            async with self.stock.request_stream(
                messages, model_settings, model_request_parameters, run_context
            ) as stream:
                yield stream
            return
        try:
            yield stream
        finally:
            await first.__aexit__(None, None, None)


class RecoverOnceFactory(ProviderModelFactory):
    """Reuse official constructors while exposing recovery to the guard."""

    async def create(
        self,
        *,
        model: str,
        assembly_metadata: ModelAssemblyMetadata | None,
        state: NativeObservationState,
    ) -> ProviderModelBinding:
        binding = await super().create(
            model=model, assembly_metadata=assembly_metadata, state=state
        )
        return ProviderModelBinding(
            model=RecoverOnceModel(binding.model), close=binding.close
        )


async def test_sdk_recovery_wrap_retains_original_safe_failure() -> None:
    calls = 0

    def response(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(
            429,
            headers={"content-type": "application/json", "retry-after": "7"},
            stream=httpx2.ByteStream(
                json.dumps(
                    {
                        "error": {
                            "message": "Rate limit reached",
                            "code": "rate_limit_exceeded",
                            "type": "rate_limit_error",
                        }
                    }
                ).encode()
            ),
            request=request,
        )

    adapter = PydanticAIModelAdapter(
        factory=RecoverOnceFactory(
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
    clock = ControlledClock()
    policy = ModelStreamTimeoutPolicy(
        connect_timeout_seconds=2,
        parsed_event_idle_timeout_seconds=50,
        absolute_attempt_timeout_seconds=100,
    )
    with pytest.raises(ModelProviderFailure) as raised:
        await collect(adapter, watchdog_for_test(clock, policy), policy)
    assert calls == 1
    assert raised.value.status_code == 429
    assert raised.value.provider_message == "Rate limit reached"
    assert raised.value.retry_hint_seconds == 7
    assert not adapter.active
