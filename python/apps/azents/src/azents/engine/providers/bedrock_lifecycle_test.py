"""Offline contract tests through public Boto requests and AWS event parsing."""

import asyncio
import dataclasses
import json
import threading
from collections.abc import Iterator
from typing import Literal
from urllib.parse import unquote, urlsplit

import boto3
import pytest
from botocore.awsrequest import AWSPreparedRequest, AWSResponse
from botocore.client import BaseClient
from botocore.compat import HTTPHeaders
from botocore.config import Config
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.output import OutputObjectDefinition
from pydantic_ai.providers.bedrock import BedrockProvider
from pydantic_ai.settings import ModelSettings

from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelCapabilities, ModelToolCallingCapabilities
from azents.engine.events.pydantic_ai_adapter import PydanticAIModelAdapter
from azents.engine.events.pydantic_ai_adapter_test import context_for_test
from azents.engine.events.pydantic_ai_output import PydanticAIOutputNormalizer
from azents.engine.events.pydantic_ai_types import (
    PydanticAIRequest,
    PydanticAIStreamEvent,
)
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.model_stream import (
    ModelDispatchAdmissionError,
    ModelStreamTimeoutPolicy,
    ModelStreamTimeoutPolicyResolver,
    ModelStreamWatchdog,
)
from azents.engine.model_stream_test import ControlledClock, ObservableCleanupRegistry
from azents.engine.provider_errors import SDK_PROVIDER_ERRORS, map_model_provider_error
from azents.engine.providers.model_factory import (
    ProviderModelFactory,
    ProviderTransports,
)
from azents.engine.providers.observation_state import NativeObservationState
from azents.engine.run.errors import ModelStreamTimeoutError
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
)
from azents.engine.run.types import USER_STOP_CANCEL_MESSAGE
from azents.testing.provider_native_envelopes import (
    aws_event_frame,
    core_native_response,
)


class GatedAWSBody:
    """A public AWSResponse raw body with explicit cross-thread barriers."""

    def __init__(
        self, chunks: list[bytes], *, gate_body: bool, gate_close: bool
    ) -> None:
        self.loop = asyncio.get_running_loop()
        self.chunks = chunks
        self.started = asyncio.Event()
        self.closed = asyncio.Event()
        self.close_requested = asyncio.Event()
        self.release = threading.Event()
        self.close_release = threading.Event()
        self.iterations = 0
        if not gate_body:
            self.release.set()
        if not gate_close:
            self.close_release.set()

    def stream(
        self, amt: int | None = None, decode_content: bool = False
    ) -> Iterator[bytes]:
        self.iterations += 1
        self.loop.call_soon_threadsafe(self.started.set)
        self.release.wait()
        for chunk in self.chunks:
            if self.closed.is_set():
                return
            yield chunk

    def close(self) -> None:
        self.loop.call_soon_threadsafe(self.close_requested.set)
        self.close_release.wait()
        self.release.set()
        self.loop.call_soon_threadsafe(self.closed.set)


class BotoBoundary:
    """Return native HTTP bytes from the supported before-send event only."""

    def __init__(self, body: GatedAWSBody, *, gate_headers: bool) -> None:
        self.loop = asyncio.get_running_loop()
        self.body = body
        self.sent = asyncio.Event()
        self.returned = asyncio.Event()
        self.headers_release = threading.Event()
        self.paths: list[str] = []
        self.bodies: list[dict[str, object]] = []
        if not gate_headers:
            self.headers_release.set()
        self.client: BaseClient = boto3.client(
            "bedrock-runtime",
            region_name="us-east-1",
            aws_access_key_id="synthetic-sdk-key",
            aws_secret_access_key="synthetic-sdk-secret",
            config=Config(retries={"total_max_attempts": 1}),
        )
        self.client.meta.events.register(
            # The installed stubs constrain handlers to None, but the public
            # before-send event explicitly accepts a returned AWSResponse.
            "before-send.bedrock-runtime.ConverseStream",
            self.response,  # ty: ignore[invalid-argument-type]
        )

    def response(self, *, request: AWSPreparedRequest, **_: object) -> AWSResponse:
        self.paths.append(unquote(urlsplit(request.url).path))
        assert isinstance(request.body, str | bytes | bytearray)
        self.bodies.append(json.loads(request.body))
        self.loop.call_soon_threadsafe(self.sent.set)
        self.headers_release.wait()
        self.loop.call_soon_threadsafe(self.returned.set)
        headers = HTTPHeaders()
        headers["content-type"] = "application/vnd.amazon.eventstream"
        headers["x-amzn-requestid"] = "synthetic-bedrock-request"
        return AWSResponse(
            request.url,
            200,
            headers,
            self.body,
        )

    def release_all(self) -> None:
        self.headers_release.set()
        self.body.close_release.set()
        self.body.release.set()


@dataclasses.dataclass
class BedrockCall:
    boundary: BotoBoundary
    adapter: PydanticAIModelAdapter
    clock: ControlledClock
    watchdog: ModelStreamWatchdog
    registry: ObservableCleanupRegistry
    policy: ModelStreamTimeoutPolicy
    model: str

    async def collect(
        self,
        parameters: ModelRequestParameters,
        *,
        messages: list[ModelMessage] | None = None,
        settings: ModelSettings | None = None,
        assembly_metadata: ModelAssemblyMetadata | None = None,
    ) -> list[PydanticAIStreamEvent]:
        return [
            event
            async for event in self.adapter.stream(
                PydanticAIRequest(
                    native_replay_context=None,
                    provider="aws_bedrock",
                    model=self.model,
                    assembly_metadata=assembly_metadata,
                    messages=messages
                    if messages is not None
                    else [
                        ModelRequest(parts=[UserPromptPart(content="Synthetic input")])
                    ],
                    settings=settings if settings is not None else {},
                    parameters=parameters,
                ),
                watchdog=self.watchdog,
                timeout_policy=self.policy,
                call_context=dataclasses.replace(
                    context_for_test(), provider="aws_bedrock", model=self.model
                ),
            )
        ]


def bedrock_call(
    *,
    model: str,
    chunks: list[bytes],
    gate_headers: bool = False,
    gate_body: bool = False,
    gate_close: bool = False,
    connect: float = 2,
    idle: float = 5,
    absolute: float = 30,
) -> BedrockCall:
    body = GatedAWSBody(chunks, gate_body=gate_body, gate_close=gate_close)
    boundary = BotoBoundary(body, gate_headers=gate_headers)
    clock = ControlledClock()
    policy = ModelStreamTimeoutPolicy(
        connect_timeout_seconds=connect,
        parsed_event_idle_timeout_seconds=idle,
        absolute_attempt_timeout_seconds=absolute,
    )
    registry = ObservableCleanupRegistry(clock=clock)
    watchdog = ModelStreamWatchdog(
        resolver=ModelStreamTimeoutPolicyResolver(
            default=policy, provider_overrides=(), specific_overrides=()
        ),
        cleanup_registry=registry,
        close_grace_seconds=1,
        clock=clock,
    )
    adapter = PydanticAIModelAdapter(
        factory=ProviderModelFactory(
            provider=LLMProvider.AWS_BEDROCK,
            credential_kwargs={
                "aws_region_name": "us-east-1",
                "aws_access_key_id": "synthetic-sdk-key",
                "aws_secret_access_key": "synthetic-sdk-secret",
            },
            sdk_failure_mapper=map_model_provider_error,
            sdk_error_types=SDK_PROVIDER_ERRORS,
            transports=ProviderTransports(bedrock_client=boundary.client),
        )
    )
    return BedrockCall(boundary, adapter, clock, watchdog, registry, policy, model)


def nominal_body(model: str) -> bytes:
    return core_native_response(
        protocol="bedrock", model=model, text="Synthetic output"
    ).body


async def test_sdk_reports_non_converse_family_without_dispatch() -> None:
    call = bedrock_call(model="openai.gpt-4o", chunks=[])
    state = NativeObservationState(
        protocol="bedrock",
        call_context=dataclasses.replace(
            context_for_test(), provider="aws_bedrock", model=call.model
        ),
        timeout_policy=call.policy,
        sdk_failure_mapper=map_model_provider_error,
    )
    try:
        with pytest.raises(UserError, match="not served by the Bedrock Converse API"):
            await call.adapter.factory.create(
                model=call.model, assembly_metadata=None, state=state
            )
        assert not call.boundary.paths
    finally:
        for close in reversed(state.close_callbacks):
            await close()


@pytest.mark.parametrize("outcome", ["ownership", "stop", "allowed"])
async def test_foreground_boto_dispatch_checks_common_owner_on_event_loop(
    outcome: str,
) -> None:
    """A synchronous official SDK must await the common foreground fence."""
    model = "anthropic.claude-3-haiku-20240307-v1:0"
    call = bedrock_call(model=model, chunks=[nominal_body(model)])
    loop = asyncio.get_running_loop()
    checks: list[str] = []

    async def check_stop() -> bool:
        assert asyncio.get_running_loop() is loop
        checks.append("checked")
        if outcome == "ownership":
            raise ModelDispatchAdmissionError("ownership")
        return outcome == "stop"

    async def collect() -> list[PydanticAIStreamEvent]:
        return [
            event
            async for event in call.adapter.stream(
                PydanticAIRequest(
                    native_replay_context=None,
                    provider="aws_bedrock",
                    model=model,
                    assembly_metadata=None,
                    messages=[
                        ModelRequest(parts=[UserPromptPart(content="Scoped input")])
                    ],
                    settings={},
                    parameters=ModelRequestParameters(),
                ),
                watchdog=call.watchdog,
                timeout_policy=call.policy,
                call_context=dataclasses.replace(
                    context_for_test(),
                    provider="aws_bedrock",
                    model=model,
                    check_stop=check_stop,
                ),
            )
        ]

    try:
        if outcome == "ownership":
            with pytest.raises(ModelDispatchAdmissionError) as failure:
                await collect()
            assert failure.value.reason == "ownership"
            assert call.boundary.paths == []
        elif outcome == "stop":
            with pytest.raises(asyncio.CancelledError):
                await collect()
            assert call.boundary.paths == []
        else:
            events = await collect()
            assert any(event.response is not None for event in events)
            assert len(call.boundary.paths) == 1
        assert checks
    finally:
        call.boundary.release_all()
        await call.adapter.close()


@pytest.mark.parametrize(
    "model",
    [
        "anthropic.claude-3-haiku-20240307-v1:0",
        "amazon.nova-micro-v1:0",
        "amazon.titan-text-express-v1",
        "ai21.jamba-1-5-mini-v1:0",
        "cohere.command-r-v1:0",
        "meta.llama3-8b-instruct-v1:0",
        "mistral.mistral-large-2402-v1:0",
        "us.anthropic.claude-3-haiku-20240307-v1:0",
        "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-3-haiku-20240307-v1:0",
    ],
)
async def test_converse_sdk_preserves_exact_model_id_and_native_terminal(
    model: str,
) -> None:
    call = bedrock_call(model=model, chunks=[nominal_body(model)])
    events = await call.collect(ModelRequestParameters())
    assert call.boundary.paths == [f"/model/{model}/converse-stream"]
    assert len(call.boundary.bodies) == 1
    observations = [
        event.observation for event in events if event.observation is not None
    ]
    assert [item.event_type for item in observations] == [
        "messageStart",
        "contentBlockDelta",
        "contentBlockStop",
        "messageStop",
        "metadata",
    ]
    assert observations[-2].terminal == "success"
    assert observations[-1].native_usage == {
        "inputTokens": 3,
        "outputTokens": 2,
        "totalTokens": 5,
    }
    finals = [event.response for event in events if event.response is not None]
    assert len(finals) == 1
    assert finals[0].model_name == model
    assert finals[0].usage.input_tokens == 3
    assert finals[0].usage.output_tokens == 2
    assert any(
        isinstance(part, TextPart) and part.content == "Synthetic output"
        for part in finals[0].parts
    )
    assert call.boundary.body.iterations == 1
    assert call.boundary.body.closed.is_set()
    assert not call.adapter.active


@pytest.mark.parametrize(
    "model",
    [
        "anthropic.claude-3-haiku-20240307-v1:0",
        "arn:aws:bedrock:us-east-1:123456789012:inference-profile/synthetic-json-title",
    ],
)
async def test_installed_converse_schema_and_json_output_tool_extraction(
    model: str,
) -> None:
    text = '{"title":"Synthetic title"}'
    frames = [
        aws_event_frame("messageStart", {"role": "assistant"}),
        aws_event_frame(
            "contentBlockStart",
            {
                "contentBlockIndex": 0,
                "start": {
                    "toolUse": {
                        "toolUseId": "synthetic-output",
                        "name": "json_tool_call",
                    }
                },
            },
        ),
        aws_event_frame(
            "contentBlockDelta",
            {"contentBlockIndex": 0, "delta": {"toolUse": {"input": text}}},
        ),
        aws_event_frame("contentBlockStop", {"contentBlockIndex": 0}),
        aws_event_frame("messageStop", {"stopReason": "tool_use"}),
        aws_event_frame(
            "metadata",
            {
                "usage": {"inputTokens": 3, "outputTokens": 2, "totalTokens": 5},
                "metrics": {"latencyMs": 1},
            },
        ),
    ]
    call = bedrock_call(model=model, chunks=frames)
    shape = call.boundary.client.meta.service_model.operation_model(
        "ConverseStream"
    ).input_shape
    assert shape is not None
    assert "toolConfig" in shape.members
    assert "outputConfig" not in shape.members
    events = await call.collect(
        ModelRequestParameters(
            output_mode="native",
            output_object=OutputObjectDefinition(
                json_schema={
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                },
            ),
        ),
        assembly_metadata=ModelAssemblyMetadata(
            model_developer=None,
            model_family=None,
            capabilities=ModelCapabilities(
                tool_calling=ModelToolCallingCapabilities(supported=True)
            ),
        ),
    )
    assert call.boundary.paths == [f"/model/{model}/converse-stream"]
    payload = call.boundary.bodies[0]
    assert "outputConfig" not in payload
    config = payload["toolConfig"]
    assert isinstance(config, dict)
    if model.startswith("anthropic."):
        assert config["toolChoice"] == {"any": {}}
    else:
        # The public SDK cannot resolve an arbitrary inference-profile ARN to a
        # publisher. Exact routing is preserved without inventing tool forcing.
        assert BedrockProvider.model_profile(model) is None
        assert "toolChoice" not in config
    assert config["tools"][0]["toolSpec"]["name"] == "json_tool_call"
    finals = [event.response for event in events if event.response is not None]
    assert len(finals) == 1
    assert finals[0].model_name == model
    assert [part.content for part in finals[0].parts if isinstance(part, TextPart)] == [
        text
    ]
    assert not any(isinstance(part, ToolCallPart) for part in finals[0].parts)
    assert call.boundary.body.closed.is_set()


@pytest.mark.parametrize(
    "stop_reason", [None, "end_turn", "max_tokens", "guardrail_intervened"]
)
async def test_boto_parsed_content_stop_is_not_native_completion(
    stop_reason: str | None,
) -> None:
    model = "amazon.nova-micro-v1:0"
    frames = [
        aws_event_frame("messageStart", {"role": "assistant"}),
        aws_event_frame(
            "contentBlockDelta",
            {"contentBlockIndex": 0, "delta": {"text": "Synthetic output"}},
        ),
        aws_event_frame("contentBlockStop", {"contentBlockIndex": 0}),
    ]
    if stop_reason is not None:
        frames.append(aws_event_frame("messageStop", {"stopReason": stop_reason}))
    call = bedrock_call(model=model, chunks=frames)
    events = await call.collect(ModelRequestParameters())
    output = PydanticAIOutputNormalizer(
        provider="aws_bedrock",
        model=model,
        pricing=None,
        operation="sampling",
        integration="synthetic-integration",
    ).start("synthetic-session")
    for event in events:
        output.process_event(event)
    if stop_reason == "end_turn":
        assert output.complete().events
        finals = [event.response for event in events if event.response is not None]
        assert finals[0].finish_reason == "stop"
    else:
        with pytest.raises(ModelProviderFailure) as raised:
            output.complete()
        if stop_reason == "max_tokens":
            assert raised.value.provider_code == "max_output_tokens"
            assert raised.value.provider_message == (
                "The model response reached its output token limit."
            )
        elif stop_reason == "guardrail_intervened":
            assert raised.value.provider_code == stop_reason
    assert call.boundary.body.closed.is_set()


@pytest.mark.parametrize("outcome", ["stop", "connect", "absolute"])
async def test_late_boto_worker_response_is_closed_after_caller_left(
    outcome: Literal["stop", "connect", "absolute"],
) -> None:
    model = "amazon.nova-micro-v1:0"
    call = bedrock_call(
        model=model,
        chunks=[nominal_body(model)],
        gate_headers=True,
        absolute=1 if outcome == "absolute" else 30,
        connect=10 if outcome == "absolute" else 2,
    )
    operation = asyncio.create_task(call.collect(ModelRequestParameters()))
    try:
        await call.boundary.sent.wait()
        if outcome == "stop":
            operation.cancel(USER_STOP_CANCEL_MESSAGE)
            with pytest.raises(asyncio.CancelledError):
                await operation
        else:
            deadline = 1 if outcome == "absolute" else 2
            await call.clock.wait_until(
                lambda: deadline in call.clock.sleeper_deadlines
            )
            call.clock.advance(deadline)
            # Timeout cleanup and the adapter finalizer each own one bounded grace.
            for _ in range(2):
                await call.clock.wait_until(
                    lambda: call.clock.time() + 1 in call.clock.sleeper_deadlines
                )
                call.clock.advance(1)
            with pytest.raises(ModelStreamTimeoutError) as raised:
                await operation
            assert raised.value.failure_code == (
                "model_attempt_timeout"
                if outcome == "absolute"
                else "model_connect_timeout"
            )
        assert not call.boundary.returned.is_set()
        assert call.registry.active_count > 0
        assert not call.adapter.active
        call.boundary.headers_release.set()
        await call.boundary.returned.wait()
        await call.boundary.body.closed.wait()
        await call.registry.settled.wait()
        assert call.registry.active_count == 0
        assert len(call.boundary.paths) == 1
    finally:
        call.boundary.release_all()


@pytest.mark.parametrize("outcome", ["stop", "idle", "absolute"])
async def test_acquired_boto_stream_blocked_close_has_bounded_caller_lifetime(
    outcome: Literal["stop", "idle", "absolute"],
) -> None:
    model = "amazon.nova-micro-v1:0"
    call = bedrock_call(
        model=model,
        chunks=[nominal_body(model)],
        gate_body=True,
        gate_close=True,
        absolute=3 if outcome == "absolute" else 30,
    )
    operation = asyncio.create_task(call.collect(ModelRequestParameters()))
    try:
        await call.boundary.body.started.wait()
        if outcome == "stop":
            operation.cancel(USER_STOP_CANCEL_MESSAGE)
            with pytest.raises(asyncio.CancelledError):
                await operation
            assert call.clock.time() == 0
        else:
            deadline = 3 if outcome == "absolute" else 5
            await call.clock.wait_until(
                lambda: deadline in call.clock.sleeper_deadlines
            )
            call.clock.advance(deadline)
            for _ in range(2):
                await call.clock.wait_until(
                    lambda: call.clock.time() + 1 in call.clock.sleeper_deadlines
                )
                call.clock.advance(1)
            with pytest.raises(ModelStreamTimeoutError) as raised:
                await operation
            assert raised.value.failure_code == (
                "model_attempt_timeout"
                if outcome == "absolute"
                else "model_stream_idle_timeout"
            )
        await call.boundary.body.close_requested.wait()
        assert not call.boundary.body.closed.is_set()
        assert call.registry.active_count > 0
        call.boundary.body.close_release.set()
        await call.boundary.body.closed.wait()
        await call.registry.settled.wait()
        assert call.registry.active_count == 0
        assert not call.adapter.active
        assert len(call.boundary.paths) == 1
    finally:
        call.boundary.release_all()
