"""Pinned public Boto schema compatibility through the real main lowerer."""

import copy
import dataclasses
import datetime
import uuid
from typing import Protocol, runtime_checkable

import pytest
from botocore.model import StructureShape
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import (
    CachePoint,
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    SystemPromptPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.bedrock import BedrockModelSettings
from pydantic_ai.tools import ToolDefinition

from azents.core.enums import EventKind, LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelParameterCapabilities,
    ModelToolCallingCapabilities,
)
from azents.core.type_guards import is_string_object_dict
from azents.engine.events.pydantic_ai_adapter_test import context_for_test
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.pydantic_ai_types import (
    PydanticAIRequest,
    PydanticAIStreamEvent,
)
from azents.engine.events.types import (
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    NativeArtifact,
    OutputTextPart,
    UserMessagePayload,
    build_native_compat_key,
)
from azents.engine.provider_errors import map_model_provider_error
from azents.engine.providers.bedrock_lifecycle_test import (
    BedrockCall,
    bedrock_call,
    nominal_body,
)
from azents.engine.providers.observation_state import NativeObservationState
from azents.testing.provider_native_envelopes import aws_event_frame


@runtime_checkable
class ParameterValidationConfig(Protocol):
    """Narrow the public Config field omitted from the installed Boto stubs."""

    parameter_validation: bool


def cache_points(params: dict[str, object]) -> list[dict[str, object]]:
    blocks: list[object] = []
    system = params.get("system")
    if isinstance(system, list):
        blocks.extend(system)
    messages = params.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if is_string_object_dict(message):
                content = message.get("content")
                if isinstance(content, list):
                    blocks.extend(content)
    config = params.get("toolConfig")
    if is_string_object_dict(config):
        tools = config.get("tools")
        if isinstance(tools, list):
            blocks.extend(tools)
    points: list[dict[str, object]] = []
    for block in blocks:
        if is_string_object_dict(block):
            point = block.get("cachePoint")
            if is_string_object_dict(point):
                points.append(point)
    return points


async def collect_request(
    call: BedrockCall, request: PydanticAIRequest
) -> list[PydanticAIStreamEvent]:
    context = context_for_test()
    context = dataclasses.replace(context, provider="aws_bedrock", model=call.model)
    return [
        event
        async for event in call.adapter.stream(
            request,
            watchdog=call.watchdog,
            timeout_policy=call.policy,
            call_context=context,
        )
    ]


@pytest.mark.parametrize(
    "model",
    [
        "anthropic.claude-3-haiku-20240307-v1:0",
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
        "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-3-haiku-20240307-v1:0",
    ],
)
async def test_real_main_lowerer_default_cache_ttl_survives_boto_validation(
    model: str,
) -> None:
    # Acquire history from the real SDK's native tool-call parser, never from a
    # canned ModelResponse or disabled Boto parameter validator.
    frames = [
        aws_event_frame("messageStart", {"role": "assistant"}),
        aws_event_frame(
            "contentBlockStart",
            {
                "contentBlockIndex": 0,
                "start": {
                    "toolUse": {
                        "toolUseId": "synthetic-client-tool",
                        "name": "fixture_tool",
                    }
                },
            },
        ),
        aws_event_frame(
            "contentBlockDelta",
            {"contentBlockIndex": 0, "delta": {"toolUse": {"input": "{}"}}},
        ),
        aws_event_frame("contentBlockStop", {"contentBlockIndex": 0}),
        aws_event_frame("messageStop", {"stopReason": "tool_use"}),
    ]
    first = bedrock_call(model=model, chunks=frames)
    history = await first.collect(
        ModelRequestParameters(
            function_tools=[
                ToolDefinition(
                    name="fixture_tool",
                    parameters_json_schema={"type": "object", "properties": {}},
                )
            ]
        )
    )
    assembled = [event.response for event in history if event.response is not None]
    assert len(assembled) == 1
    native_history: list[ModelMessage] = list(assembled)
    artifact = NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="pydantic_ai",
            native_format="model_messages",
            provider="aws_bedrock",
            model=model,
            schema_version="1",
        ),
        adapter="pydantic_ai",
        native_format="model_messages",
        provider="aws_bedrock",
        model=model,
        schema_version="1",
        item={
            "message": ModelMessagesTypeAdapter.dump_python(
                native_history, mode="json"
            )[0]
        },
    )
    now = datetime.datetime.now(datetime.UTC)
    transcript = [
        Event(
            id=uuid.uuid4().hex,
            session_id="synthetic-session",
            kind=EventKind.USER_MESSAGE,
            created_at=now,
            payload=UserMessagePayload(
                content="Synthetic initial input", sender_user_id=None
            ),
        ),
        Event(
            id=uuid.uuid4().hex,
            session_id="synthetic-session",
            kind=EventKind.CLIENT_TOOL_CALL,
            created_at=now,
            payload=ClientToolCallPayload(
                name="fixture_tool",
                call_id="synthetic-client-tool",
                arguments="{}",
                wire_dialect="json_function",
                native_artifact=artifact,
            ),
        ),
        Event(
            id=uuid.uuid4().hex,
            session_id="synthetic-session",
            kind=EventKind.CLIENT_TOOL_RESULT,
            created_at=now,
            payload=ClientToolResultPayload(
                name="fixture_tool",
                call_id="synthetic-client-tool",
                status="completed",
                wire_dialect="json_function",
                output=[OutputTextPart(text="Synthetic result")],
            ),
        ),
        Event(
            id=uuid.uuid4().hex,
            session_id="synthetic-session",
            kind=EventKind.USER_MESSAGE,
            created_at=now,
            payload=UserMessagePayload(
                content="Synthetic follow-up", sender_user_id=None
            ),
        ),
    ]
    request = PydanticAILowerer(
        provider="aws_bedrock",
        provider_id=LLMProvider.AWS_BEDROCK,
        model=model,
        model_developer=LLMModelDeveloper.ANTHROPIC,
        model_capabilities=ModelCapabilities(
            tool_calling=ModelToolCallingCapabilities(supported=True),
            parameters=ModelParameterCapabilities(
                temperature=True, max_output_tokens=True
            ),
        ),
        tools=[
            {
                "type": "function",
                "name": "fixture_tool",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        supported_execution_options=(),
        enabled_execution_options=(),
        temperature=0.2,
        max_output_tokens=64,
    ).lower(transcript, model=model, system_prompt="Synthetic instruction")
    logical_cache = [
        part
        for message in request.messages
        if isinstance(message, ModelRequest)
        for prompt in message.parts
        if isinstance(prompt, UserPromptPart) and not isinstance(prompt.content, str)
        for part in prompt.content
        if isinstance(part, CachePoint)
    ]
    assert len(logical_cache) == 2
    assert all(point.ttl == "5m" for point in logical_cache)
    call = bedrock_call(model=model, chunks=[nominal_body(model)])
    config = call.boundary.client.meta.config
    assert isinstance(config, ParameterValidationConfig)
    assert config.parameter_validation
    shape = call.boundary.client.meta.service_model.shape_for("CachePointBlock")
    assert isinstance(shape, StructureShape)
    assert set(shape.members) == {"type"}
    before: list[dict[str, object]] = []

    def snapshot(*, params: dict[str, object], **_: object) -> None:
        before.append(copy.deepcopy(params))

    call.boundary.client.meta.events.register_first(
        "before-parameter-build.bedrock-runtime.ConverseStream", snapshot
    )
    events = await collect_request(call, request)
    assert before
    assert sum(point.get("ttl") == "5m" for point in cache_points(before[0])) == 2
    wire = call.boundary.bodies[0]
    assert call.boundary.paths == [f"/model/{model}/converse-stream"]
    assert cache_points(wire) == [{"type": "default"}] * 4
    assert wire["inferenceConfig"] == {"maxTokens": 64, "temperature": 0.2}
    assert any(
        event.observation is not None and event.observation.terminal == "success"
        for event in events
    )
    assert all(point.ttl == "5m" for point in logical_cache)
    assert call.boundary.body.closed.is_set()


@pytest.mark.parametrize("position", ["message", "system", "tool"])
async def test_explicit_one_hour_cache_ttl_is_rejected_before_dispatch(
    position: str,
) -> None:
    model = "anthropic.claude-3-haiku-20240307-v1:0"
    call = bedrock_call(model=model, chunks=[nominal_body(model)])
    settings = BedrockModelSettings()
    content = (
        ["Synthetic input", CachePoint(ttl="1h")]
        if position == "message"
        else "Synthetic input"
    )
    if position == "system":
        settings["bedrock_cache_instructions"] = "1h"
    elif position == "tool":
        settings["bedrock_cache_tool_definitions"] = "1h"
    parameters = ModelRequestParameters(
        function_tools=[
            ToolDefinition(
                name="fixture_tool",
                parameters_json_schema={"type": "object", "properties": {}},
            )
        ]
    )
    state = NativeObservationState(
        protocol="bedrock",
        call_context=dataclasses.replace(
            context_for_test(), provider="aws_bedrock", model=model
        ),
        timeout_policy=call.policy,
        sdk_failure_mapper=map_model_provider_error,
    )
    binding = await call.adapter.factory.create(
        model=model, assembly_metadata=None, state=state
    )
    try:
        with pytest.raises(UserError, match="implicit five-minute cache TTL"):
            async with binding.model.request_stream(
                [
                    ModelRequest(
                        parts=[
                            SystemPromptPart("Synthetic instruction"),
                            UserPromptPart(content),
                        ]
                    )
                ],
                settings,
                parameters,
            ):
                pytest.fail("Unsupported one-hour TTL reached the response boundary")
        assert not call.boundary.paths
        assert state.dispatch_count == 0
    finally:
        await binding.close()


async def test_ttl_compatibility_does_not_rewrite_nested_tool_or_provider_json() -> (
    None
):
    model = "anthropic.claude-3-haiku-20240307-v1:0"
    marker = {"type": "default", "ttl": "1h"}
    call = bedrock_call(model=model, chunks=[nominal_body(model)])
    events = await call.collect(
        ModelRequestParameters(
            function_tools=[
                ToolDefinition(
                    name="fixture_tool",
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "cachePoint": {
                                "type": "object",
                                "properties": {
                                    "ttl": {"type": "string", "enum": ["1h"]}
                                },
                            }
                        },
                    },
                )
            ]
        ),
        messages=[
            ModelRequest(parts=[UserPromptPart(["Synthetic input", CachePoint()])])
        ],
        settings=BedrockModelSettings(
            bedrock_cache_tool_definitions=True,
            bedrock_additional_model_requests_fields={"cachePoint": marker},
        ),
    )
    wire = call.boundary.bodies[0]
    assert wire["additionalModelRequestFields"] == {"cachePoint": marker}
    tool_config = wire["toolConfig"]
    assert isinstance(tool_config, dict)
    schema = tool_config["tools"][0]["toolSpec"]["inputSchema"]["json"]
    assert schema["properties"]["cachePoint"]["properties"]["ttl"]["enum"] == ["1h"]
    assert cache_points(wire) == [{"type": "default"}] * 2
    assert any(
        event.observation is not None and event.observation.terminal == "success"
        for event in events
    )
