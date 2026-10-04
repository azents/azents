"""Text-operation fidelity, native completion and operation cleanup contracts."""

import dataclasses
from collections.abc import AsyncIterator

import httpx2
import pytest
from pydantic import TypeAdapter
from pydantic_ai.messages import ModelResponse, TextPart

import azents.engine.model_text as model_text
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelParameterCapabilities,
    ModelToolCallingCapabilities,
)
from azents.core.model_capability_contract import (
    ModelCapabilityFeature,
    ModelFeatureCondition,
    ModelRequestConstraints,
)
from azents.engine.events.model_support_contract import ModelRequestFeatureError
from azents.engine.events.pydantic_ai_types import (
    NativeModelObservation,
    PydanticAIRequest,
    PydanticAIStreamEvent,
)
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.model_factories import get_model_sdk_factories
from azents.engine.model_stream import (
    ModelStreamCallContext,
    ModelStreamTimeoutPolicy,
    ModelStreamWatchdog,
)
from azents.engine.model_text import call_provider_text
from azents.engine.providers.bedrock_lifecycle_test import bedrock_call
from azents.engine.providers.model_factory import (
    ProviderModelFactory,
    ProviderTransports,
)
from azents.engine.run.errors import ModelCallError
from azents.testing.model_stream import (
    make_test_model_stream_context,
    make_test_model_stream_watchdog,
)
from azents.testing.provider_native_envelopes import aws_event_frame


class _Adapter:
    """Typed single-consumed stream fixture with explicit native proof."""

    def __init__(self, *, factory: ProviderModelFactory, native_terminal: bool) -> None:
        self.factory = factory
        self.native_terminal = native_terminal
        self.requests: list[PydanticAIRequest] = []
        self.closed = False

    async def stream(
        self,
        request: PydanticAIRequest,
        *,
        watchdog: ModelStreamWatchdog,
        timeout_policy: ModelStreamTimeoutPolicy,
        call_context: ModelStreamCallContext,
    ) -> AsyncIterator[PydanticAIStreamEvent]:
        self.requests.append(request)
        yield PydanticAIStreamEvent(
            event=None,
            response=ModelResponse(
                parts=[TextPart("validated title")],
                model_name=request.model,
                provider_name=request.provider,
                finish_reason="stop",
            ),
            observation=(
                NativeModelObservation(
                    protocol="responses",
                    event_type="response.completed",
                    parsed_activity=True,
                    terminal="success",
                    end_turn=True,
                    native_usage=None,
                    reported_cost_usd=None,
                    service_tier=None,
                    native_items=(),
                    annotations=(),
                    error=None,
                )
                if self.native_terminal
                else None
            ),
        )

    async def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("native_terminal", [True, False])
async def test_text_operation_requires_native_terminal_and_always_closes(
    monkeypatch: pytest.MonkeyPatch, native_terminal: bool
) -> None:
    adapters: list[_Adapter] = []

    def create(*, factory: ProviderModelFactory) -> _Adapter:
        adapter = _Adapter(factory=factory, native_terminal=native_terminal)
        adapters.append(adapter)
        return adapter

    monkeypatch.setattr(model_text, "PydanticAIModelAdapter", create)
    watchdog = make_test_model_stream_watchdog()
    policy = watchdog.resolve_policy(
        provider="openrouter", model="publisher/model/exact", inference_profile=None
    )
    metadata = ModelAssemblyMetadata(
        model_developer=LLMModelDeveloper.ANTHROPIC,
        model_family="claude",
        capabilities=ModelCapabilities(
            parameters=ModelParameterCapabilities(max_output_tokens=True)
        ),
    )
    operation = call_provider_text(
        assembly_metadata=metadata,
        sdk_factories=get_model_sdk_factories(),
        provider=LLMProvider.OPENROUTER,
        model="publisher/model/exact",
        credential_kwargs={"api_key": "synthetic-key"},
        input_text="Summarize this request",
        instructions="Return only the title",
        max_output_tokens=80,
        watchdog=watchdog,
        timeout_policy=policy,
        call_context=make_test_model_stream_context(),
        text={"format": {"type": "text"}},
        extra_body=None,
    )
    if native_terminal:
        assert await operation == "validated title"
    else:
        with pytest.raises(ModelCallError):
            await operation
    assert len(adapters) == 1
    adapter = adapters[0]
    assert adapter.closed
    assert len(adapter.requests) == 1
    assert adapter.requests[0].model == "publisher/model/exact"
    assert adapter.requests[0].assembly_metadata is metadata
    assert adapter.requests[0].parameters.output_mode == "text"
    assert adapter.requests[0].settings["max_tokens"] == 80


async def test_structured_title_keeps_schema_and_openrouter_routing_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapters: list[_Adapter] = []

    def create(*, factory: ProviderModelFactory) -> _Adapter:
        adapter = _Adapter(factory=factory, native_terminal=True)
        adapters.append(adapter)
        return adapter

    monkeypatch.setattr(model_text, "PydanticAIModelAdapter", create)
    watchdog = make_test_model_stream_watchdog()
    policy = watchdog.resolve_policy(
        provider="openrouter", model="publisher/model/exact", inference_profile=None
    )
    await call_provider_text(
        assembly_metadata=None,
        sdk_factories=get_model_sdk_factories(),
        provider=LLMProvider.OPENROUTER,
        model="publisher/model/exact",
        credential_kwargs={"api_key": "synthetic-key"},
        input_text="Create a title",
        instructions="Return the requested JSON object",
        max_output_tokens=80,
        watchdog=watchdog,
        timeout_policy=policy,
        call_context=make_test_model_stream_context(),
        text={
            "format": {
                "type": "json_schema",
                "name": "session_title",
                "schema": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                    "additionalProperties": False,
                },
                "strict": True,
            }
        },
        extra_body={"provider": {"require_parameters": True}},
    )
    request = adapters[0].requests[0]
    assert request.parameters.output_mode == "native"
    assert request.parameters.output_object is not None
    assert request.parameters.output_object.name == "session_title"
    assert request.parameters.output_object.strict is True
    assert request.settings["extra_body"] == {"provider": {"require_parameters": True}}
    assert adapters[0].closed


@pytest.mark.parametrize("supported", [False, True])
async def test_saved_native_response_support_is_checked_before_helper_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    supported: bool,
) -> None:
    adapters: list[_Adapter] = []

    def create(*, factory: ProviderModelFactory) -> _Adapter:
        adapter = _Adapter(factory=factory, native_terminal=True)
        adapters.append(adapter)
        return adapter

    monkeypatch.setattr(model_text, "PydanticAIModelAdapter", create)
    capabilities = ModelCapabilities(
        structured_response=supported,
        parameters=ModelParameterCapabilities(max_output_tokens=True),
    )
    metadata = ModelAssemblyMetadata(
        model_developer=LLMModelDeveloper.ANTHROPIC,
        model_family=None,
        capabilities=capabilities,
    )
    watchdog = make_test_model_stream_watchdog()
    operation = call_provider_text(
        sdk_factories=get_model_sdk_factories(),
        provider=LLMProvider.OPENROUTER,
        model="publisher/model/exact",
        credential_kwargs={"api_key": "synthetic-unused"},
        assembly_metadata=metadata,
        input_text="fixture",
        instructions="fixture",
        max_output_tokens=80,
        watchdog=watchdog,
        timeout_policy=watchdog.resolve_policy(
            provider="openrouter",
            model="publisher/model/exact",
            inference_profile=None,
        ),
        call_context=make_test_model_stream_context(),
        text={
            "format": {
                "type": "json_schema",
                "name": "answer",
                "schema": {"type": "object", "properties": {}},
                "strict": True,
            }
        },
        extra_body=None,
    )
    if not supported:
        with pytest.raises(ModelRequestFeatureError) as raised:
            await operation
        assert raised.value.feature is ModelCapabilityFeature.STRUCTURED_RESPONSE
        assert adapters == []
    else:
        assert await operation == "validated title"
        assert len(adapters) == 1
        assert adapters[0].requests[0].parameters.output_mode == "native"
        assert adapters[0].closed


async def test_helper_raw_builtin_and_condition_bypass_are_rejected_before_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_adapter(*, factory: ProviderModelFactory) -> _Adapter:
        del factory
        raise AssertionError("Rejected effective request must not acquire an adapter")

    monkeypatch.setattr(model_text, "PydanticAIModelAdapter", fail_adapter)
    capabilities = ModelCapabilities(
        parameters=ModelParameterCapabilities(max_output_tokens=True, temperature=True),
        request_constraints=ModelRequestConstraints(
            feature_conditions=(
                ModelFeatureCondition(
                    feature=ModelCapabilityFeature.TEMPERATURE,
                    reasoning_efforts=None,
                    function_tools=True,
                ),
            )
        ),
    )
    watchdog = make_test_model_stream_watchdog()
    metadata = ModelAssemblyMetadata(
        model_developer=None,
        model_family=None,
        capabilities=capabilities,
    )
    cases: list[tuple[dict[str, object], ModelCapabilityFeature]] = [
        ({"temperature": 0}, ModelCapabilityFeature.TEMPERATURE),
        ({"tools": [{"type": "web_search"}]}, ModelCapabilityFeature.WEB_SEARCH),
    ]
    for body, feature in cases:
        with pytest.raises(ModelRequestFeatureError) as raised:
            await call_provider_text(
                sdk_factories=get_model_sdk_factories(),
                provider=LLMProvider.OPENROUTER,
                model="publisher/model/exact",
                credential_kwargs={"api_key": "synthetic-unused"},
                assembly_metadata=metadata,
                input_text="fixture",
                instructions="fixture",
                max_output_tokens=80,
                watchdog=watchdog,
                timeout_policy=watchdog.resolve_policy(
                    provider="openrouter",
                    model="publisher/model/exact",
                    inference_profile=None,
                ),
                call_context=make_test_model_stream_context(),
                text=None,
                extra_body=body,
            )
        assert raised.value.feature is feature


async def test_actual_text_helper_retains_native_schema_through_mock_sdk_wire() -> None:
    captured: list[dict[str, object]] = []
    body_adapter = TypeAdapter(dict[str, object])

    def respond(request: httpx2.Request) -> httpx2.Response:
        captured.append(body_adapter.validate_json(request.content))
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                b'data: {"type":"response.output_text.delta","sequence_number":0,'
                b'"item_id":"msg_fixture","output_index":0,"content_index":0,'
                b'"delta":"fixture"}\n\n'
                b'data: {"type":"response.completed","sequence_number":1,"response":'
                b'{"id":"resp_fixture","object":"response","created_at":1,"model":"fixture",'
                b'"status":"completed","parallel_tool_calls":true,"tool_choice":"auto",'
                b'"tools":[],"output":[{"id":"msg_fixture","type":"message","role":"assistant",'
                b'"status":"completed","content":[{"type":"output_text","text":"fixture",'
                b'"annotations":[]}]}],"usage":{"input_tokens":1,"output_tokens":1,'
                b'"total_tokens":2,"input_tokens_details":{"cached_tokens":0},'
                b'"output_tokens_details":{"reasoning_tokens":0}}}}\n\n'
                b"data: [DONE]\n\n"
            ),
        )

    defaults = get_model_sdk_factories()
    transport = httpx2.MockTransport(respond)

    def factory(
        *,
        provider: LLMProvider,
        credential_kwargs: dict[str, object],
    ) -> ProviderModelFactory:
        result = defaults.provider_model(
            provider=provider,
            credential_kwargs=credential_kwargs,
        )
        result.transports = ProviderTransports(httpx2=transport)
        return result

    sdk_factories = dataclasses.replace(defaults, provider_model=factory)
    capabilities = ModelCapabilities(
        structured_response=True,
        parameters=ModelParameterCapabilities(max_output_tokens=True),
    )
    watchdog = make_test_model_stream_watchdog()
    result = await call_provider_text(
        sdk_factories=sdk_factories,
        provider=LLMProvider.OPENROUTER,
        model="fixture",
        credential_kwargs={
            "api_key": "synthetic-unused",
            "base_url": "https://fixture.invalid/v1",
        },
        assembly_metadata=ModelAssemblyMetadata(
            model_developer=None,
            model_family=None,
            capabilities=capabilities,
        ),
        input_text="fixture",
        instructions="fixture",
        max_output_tokens=80,
        watchdog=watchdog,
        timeout_policy=watchdog.resolve_policy(
            provider="openrouter",
            model="fixture",
            inference_profile=None,
        ),
        call_context=make_test_model_stream_context(),
        text={
            "format": {
                "type": "json_schema",
                "name": "answer",
                "schema": {"type": "object", "properties": {}},
                "strict": True,
            }
        },
        extra_body=None,
    )
    assert result == "fixture"
    assert len(captured) == 1
    text = body_adapter.validate_python(captured[0]["text"])
    format = body_adapter.validate_python(text["format"])
    assert format["type"] == "json_schema"
    assert format["name"] == "answer"
    assert format["strict"] is True


@pytest.mark.parametrize("function_supported", [True, False])
async def test_bedrock_helper_gates_actual_output_tool_and_restores_json_text(
    function_supported: bool,
) -> None:
    model = "anthropic.claude-3-haiku-20240307-v1:0"
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
    boundary = bedrock_call(model=model, chunks=frames)
    defaults = get_model_sdk_factories()

    def factory(
        *, provider: LLMProvider, credential_kwargs: dict[str, object]
    ) -> ProviderModelFactory:
        assert provider is LLMProvider.AWS_BEDROCK
        assert credential_kwargs == {}
        return boundary.adapter.factory

    operation = call_provider_text(
        sdk_factories=dataclasses.replace(defaults, provider_model=factory),
        provider=LLMProvider.AWS_BEDROCK,
        model=model,
        credential_kwargs={},
        assembly_metadata=ModelAssemblyMetadata(
            model_developer=None,
            model_family=None,
            capabilities=ModelCapabilities(
                # The actual request is a synthetic output function, not native
                # schema output. These inverse flags expose authority mix-ups.
                structured_response=not function_supported,
                tool_calling=ModelToolCallingCapabilities(
                    supported=function_supported, strict_json_schema=False
                ),
                parameters=ModelParameterCapabilities(max_output_tokens=True),
            ),
        ),
        input_text="Create a title",
        instructions="Return JSON",
        max_output_tokens=80,
        watchdog=boundary.watchdog,
        timeout_policy=boundary.policy,
        call_context=dataclasses.replace(
            make_test_model_stream_context(), provider="aws_bedrock", model=model
        ),
        text={
            "format": {
                "type": "json_schema",
                "name": "answer",
                "schema": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                    "required": ["title"],
                },
                "strict": True,
            }
        },
        extra_body=None,
    )
    try:
        if not function_supported:
            with pytest.raises(ModelRequestFeatureError) as raised:
                await operation
            assert raised.value.feature is ModelCapabilityFeature.FUNCTION_CALLING
            assert boundary.boundary.paths == []
        else:
            assert await operation == text
            assert boundary.boundary.paths == [f"/model/{model}/converse-stream"]
            payload = boundary.boundary.bodies[0]
            config = TypeAdapter(dict[str, object]).validate_python(
                payload["toolConfig"]
            )
            tools = TypeAdapter(list[dict[str, object]]).validate_python(
                config["tools"]
            )
            tool = TypeAdapter(dict[str, object]).validate_python(tools[0]["toolSpec"])
            assert tool["name"] == "json_tool_call"
            assert tool.get("strict") is not True
            assert "outputConfig" not in payload
            assert boundary.boundary.body.closed.is_set()
    finally:
        boundary.boundary.release_all()
        await boundary.adapter.close()
        boundary.boundary.client.close()
