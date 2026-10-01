"""Public SDK wire dialects retain family-specific assembly without new caps."""

import base64

import pytest
from pydantic_ai.messages import (
    BinaryContent,
    CachePoint,
    ModelRequest,
    SystemPromptPart,
    ThinkingPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.bedrock import BedrockModelSettings
from pydantic_ai.providers.bedrock import BedrockProvider
from pydantic_ai.tools import ToolDefinition

from azents.core.agent import AgentModelSelection
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelModalities,
    ModelModality,
    ModelReasoningCapabilities,
    ModelReasoningEffort,
    ModelToolCallingCapabilities,
)
from azents.engine.events.pydantic_ai_adapter_test import context_for_test
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.provider_errors import map_model_provider_error
from azents.engine.providers.bedrock_cache_compatibility_test import (
    ParameterValidationConfig,
    cache_points,
)
from azents.engine.providers.bedrock_lifecycle_test import bedrock_call, nominal_body
from azents.engine.providers.model_profiles import bedrock_assembly_profile
from azents.engine.providers.observation_state import NativeObservationState
from azents.testing.provider_native_envelopes import aws_event_frame


def saved_metadata(
    model: str,
    *,
    developer: LLMModelDeveloper | None,
    family: str | None,
) -> ModelAssemblyMetadata:
    capabilities = ModelCapabilities(
        tool_calling=ModelToolCallingCapabilities(supported=True),
        reasoning=ModelReasoningCapabilities(
            supported=True, effort_levels=[ModelReasoningEffort.HIGH]
        ),
        modalities=ModelModalities(
            input=[ModelModality.TEXT, ModelModality.IMAGE, ModelModality.PDF]
        ),
    )
    if developer is None:
        return ModelAssemblyMetadata(
            model_developer=None,
            model_family=family,
            capabilities=capabilities,
        )
    return ModelAssemblyMetadata.from_selection(
        AgentModelSelection(
            llm_provider_integration_id="synthetic-integration",
            provider=LLMProvider.AWS_BEDROCK,
            model_identifier=model,
            model_display_name="Synthetic historical profile",
            model_developer=developer,
            model_family=family,
            normalized_capabilities=capabilities,
            model_snapshot={"source": "historical_saved_selection"},
        )
    )


@pytest.mark.parametrize(
    ("model", "forcing", "prompt_cache", "tool_cache"),
    [
        ("anthropic.claude-3-haiku-20240307-v1:0", True, True, True),
        ("amazon.nova-micro-v1:0", True, True, False),
        ("mistral.mistral-large-2402-v1:0", False, False, False),
        (
            "arn:aws:bedrock:us-east-1::foundation-model/"
            "anthropic.claude-3-haiku-20240307-v1:0",
            True,
            True,
            True,
        ),
        (
            "arn:aws:bedrock:us-east-1:123456789012:inference-profile/"
            "us.anthropic.claude-3-haiku-20240307-v1:0",
            True,
            True,
            True,
        ),
        (
            "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/"
            "anthropic.claude-3-haiku-20240307-v1:0",
            False,
            False,
            False,
        ),
    ],
)
async def test_real_boto_family_tool_choice_and_cache_wire(
    model: str,
    forcing: bool,
    prompt_cache: bool,
    tool_cache: bool,
) -> None:
    call = bedrock_call(model=model, chunks=[nominal_body(model)])
    await call.collect(
        ModelRequestParameters(
            function_tools=[
                ToolDefinition(
                    name="fixture_tool",
                    parameters_json_schema={"type": "object", "properties": {}},
                )
            ],
            allow_text_output=False,
        ),
        messages=[
            ModelRequest(
                parts=[
                    SystemPromptPart(content="Synthetic instruction"),
                    UserPromptPart(content="Synthetic input"),
                ]
            )
        ],
        settings=BedrockModelSettings(
            bedrock_cache_instructions=True,
            bedrock_cache_messages=True,
            bedrock_cache_tool_definitions=True,
        ),
    )
    assert call.boundary.paths == [f"/model/{model}/converse-stream"]
    wire = call.boundary.bodies[0]
    config = wire["toolConfig"]
    assert isinstance(config, dict)
    if forcing:
        assert config["toolChoice"] == {"any": {}}
    else:
        assert "toolChoice" not in config
    system = wire["system"]
    assert isinstance(system, list)
    assert any("cachePoint" in part for part in system) == prompt_cache
    messages = wire["messages"]
    assert isinstance(messages, list)
    assert any("cachePoint" in part for part in messages[-1]["content"]) == prompt_cache
    assert any("cachePoint" in part for part in config["tools"]) == tool_cache
    assert all(
        not tool.get("toolSpec", {}).get("name", "").startswith("pydantic")
        for tool in config["tools"]
    )
    assert call.boundary.body.closed.is_set()


@pytest.mark.parametrize(
    ("model", "native_replay"),
    [
        ("anthropic.claude-3-7-sonnet-20250219-v1:0", True),
        (
            "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-7-sonnet-20250219-v1:0",
            True,
        ),
        (
            "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            True,
        ),
        (
            "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/synthetic-opaque-profile",
            False,
        ),
    ],
)
async def test_real_boto_signed_thinking_replay_obeys_documented_family_authority(
    model: str,
    native_replay: bool,
) -> None:
    frames = [
        aws_event_frame("messageStart", {"role": "assistant"}),
        aws_event_frame(
            "contentBlockDelta",
            {
                "contentBlockIndex": 0,
                "delta": {"reasoningContent": {"text": "Synthetic visible reasoning"}},
            },
        ),
        aws_event_frame(
            "contentBlockDelta",
            {
                "contentBlockIndex": 0,
                "delta": {
                    "reasoningContent": {"signature": "synthetic-opaque-signature"}
                },
            },
        ),
        aws_event_frame("contentBlockStop", {"contentBlockIndex": 0}),
        aws_event_frame(
            "contentBlockDelta",
            {"contentBlockIndex": 1, "delta": {"text": "Synthetic output"}},
        ),
        aws_event_frame("contentBlockStop", {"contentBlockIndex": 1}),
        aws_event_frame("messageStop", {"stopReason": "end_turn"}),
    ]
    first = bedrock_call(model=model, chunks=frames)
    events = await first.collect(ModelRequestParameters())
    assembled = [event.response for event in events if event.response is not None]
    assert len(assembled) == 1
    # Replay the real SDK result, rather than constructing an application response.
    assert assembled[0].model_name == model
    assert any(
        isinstance(part, ThinkingPart)
        and part.signature == "synthetic-opaque-signature"
        for part in assembled[0].parts
    )
    second = bedrock_call(model=model, chunks=[nominal_body(model)])
    await second.collect(
        ModelRequestParameters(),
        messages=[
            ModelRequest(parts=[UserPromptPart(content="Synthetic input")]),
            assembled[0],
            ModelRequest(parts=[UserPromptPart(content="Synthetic follow-up")]),
        ],
    )
    messages = second.boundary.bodies[0]["messages"]
    assert isinstance(messages, list)
    content = messages[1]["content"]
    if native_replay:
        assert content[0] == {
            "reasoningContent": {
                "reasoningText": {
                    "text": "Synthetic visible reasoning",
                    "signature": "synthetic-opaque-signature",
                }
            }
        }
    else:
        # This is a recorded unsupported native-replay boundary, not proof of
        # parity: no saved family metadata reaches the opaque-profile factory.
        assert bedrock_assembly_profile(model) is None
        assert not any("reasoningContent" in part for part in content)
    assert not any(
        "text" in part and "synthetic-opaque-signature" in part["text"]
        for part in content
    )
    assert second.boundary.paths == [f"/model/{model}/converse-stream"]


@pytest.mark.parametrize(
    ("arn", "literal_model"),
    [
        (
            "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
            "anthropic.claude-3-haiku-20240307-v1:0",
        ),
        (
            "arn:aws:bedrock:us-east-1:123456789012:inference-profile/us.anthropic.claude-3-haiku-20240307-v1:0",
            "us.anthropic.claude-3-haiku-20240307-v1:0",
        ),
    ],
)
def test_documented_model_resource_uses_only_public_literal_profile(
    arn: str,
    literal_model: str,
) -> None:
    assert BedrockProvider.model_profile(arn) is None
    assert bedrock_assembly_profile(arn) == BedrockProvider.model_profile(literal_model)


@pytest.mark.parametrize(
    "arn",
    [
        "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/anthropic.claude-3-haiku-20240307-v1:0",
        "arn:aws:bedrock:us-east-1:123456789012:inference-profile/synthetic-opaque-profile",
        "arn:aws:bedrock:us-east-1:123456789012:custom-model/anthropic.claude-3-haiku-20240307-v1:0",
        "arn:aws:iam:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
        "arn:aws:bedrock:us-east-1:123456789012:foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
        "arn:aws:bedrock:us-east-1::inference-profile/us.anthropic.claude-3-haiku-20240307-v1:0",
        "arn:aws:bedrock:us-east-1::foundation-model/prefix/anthropic.claude-3-haiku-20240307-v1:0",
    ],
)
def test_opaque_or_non_model_resource_does_not_authorize_family(arn: str) -> None:
    assert bedrock_assembly_profile(arn) is None


@pytest.mark.parametrize(
    ("model", "colocated"),
    [
        ("anthropic.claude-3-haiku-20240307-v1:0", True),
        ("mistral.mistral-large-2402-v1:0", False),
    ],
)
async def test_real_boto_family_tool_return_image_layout(
    model: str, colocated: bool
) -> None:
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
    parameters = ModelRequestParameters(
        function_tools=[
            ToolDefinition(
                name="fixture_tool",
                parameters_json_schema={"type": "object", "properties": {}},
            )
        ]
    )
    first = bedrock_call(model=model, chunks=frames)
    events = await first.collect(parameters)
    assembled = [event.response for event in events if event.response is not None]
    assert len(assembled) == 1
    second = bedrock_call(model=model, chunks=[nominal_body(model)])
    await second.collect(
        parameters,
        messages=[
            ModelRequest(parts=[UserPromptPart(content="Synthetic input")]),
            assembled[0],
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="fixture_tool",
                        content="Synthetic result",
                        tool_call_id="synthetic-client-tool",
                    ),
                    UserPromptPart(
                        content=[
                            BinaryContent(
                                data=b"synthetic-image-bytes", media_type="image/png"
                            )
                        ]
                    ),
                ]
            ),
        ],
    )
    messages = second.boundary.bodies[0]["messages"]
    assert isinstance(messages, list)
    result_turns = [
        turn
        for turn in messages
        if any("toolResult" in part for part in turn["content"])
    ]
    assert len(result_turns) == 1
    assert any("image" in part for part in result_turns[0]["content"]) == colocated
    if not colocated:
        assert len(result_turns[0]["content"]) == 1
        assert any("image" in part for part in messages[-1]["content"])
    assert second.boundary.paths == [f"/model/{model}/converse-stream"]


@pytest.mark.parametrize(
    ("developer", "family", "forcing", "prompt_cache", "tool_cache"),
    [
        (LLMModelDeveloper.ANTHROPIC, "anthropic.claude", True, True, True),
        (LLMModelDeveloper.ANTHROPIC, None, True, True, True),
        (LLMModelDeveloper.OTHER, "amazon.nova", True, True, False),
        (LLMModelDeveloper.OTHER, "nova", True, True, False),
        (LLMModelDeveloper.MISTRAL, "mistral.mistral", False, False, False),
        (LLMModelDeveloper.META, "meta.llama3", False, False, False),
        (LLMModelDeveloper.OTHER, None, False, False, False),
        (LLMModelDeveloper.OTHER, "nova-2", False, False, False),
        (LLMModelDeveloper.OTHER, "unknown-nova-like", False, False, False),
        (None, "nova", False, False, False),
    ],
)
async def test_opaque_saved_family_cache_and_forcing_use_only_captured_authority(
    developer: LLMModelDeveloper | None,
    family: str | None,
    forcing: bool,
    prompt_cache: bool,
    tool_cache: bool,
) -> None:
    model = (
        "arn:aws:bedrock:us-east-1:123456789012:"
        "application-inference-profile/synthetic-opaque-profile"
    )
    metadata = saved_metadata(model, developer=developer, family=family)
    captured_caps = metadata.capabilities.model_dump()
    call = bedrock_call(model=model, chunks=[nominal_body(model)])
    config = call.boundary.client.meta.config
    assert isinstance(config, ParameterValidationConfig)
    assert config.parameter_validation
    events = await call.collect(
        ModelRequestParameters(
            function_tools=[
                ToolDefinition(
                    name="fixture_tool",
                    parameters_json_schema={"type": "object", "properties": {}},
                )
            ],
            allow_text_output=False,
        ),
        messages=[
            ModelRequest(
                parts=[
                    SystemPromptPart("Synthetic instruction"),
                    UserPromptPart(["Synthetic input", CachePoint()]),
                ]
            )
        ],
        settings=BedrockModelSettings(
            bedrock_cache_instructions=True,
            bedrock_cache_messages=True,
            bedrock_cache_tool_definitions=True,
        ),
        assembly_metadata=metadata,
    )
    assert call.boundary.paths == [f"/model/{model}/converse-stream"]
    wire = call.boundary.bodies[0]
    tools = wire["toolConfig"]
    assert isinstance(tools, dict)
    if forcing:
        assert tools["toolChoice"] == {"any": {}}
    else:
        assert "toolChoice" not in tools
    assert len(cache_points(wire)) == (2 if prompt_cache else 0) + (
        1 if tool_cache else 0
    )
    assert all(point == {"type": "default"} for point in cache_points(wire))
    additional = wire.get("additionalModelRequestFields", {})
    assert isinstance(additional, dict)
    assert "thinking" not in additional
    assert "output_config" not in additional
    assert not any("systemTool" in tool for tool in tools["tools"])
    assert metadata.capabilities.model_dump() == captured_caps
    assert any(
        event.observation is not None and event.observation.terminal == "success"
        for event in events
    )


@pytest.mark.parametrize(
    "kind",
    [
        "application-inference-profile",
        "inference-profile",
        "provisioned-model",
        "custom-model-deployment",
        "custom-model",
    ],
)
async def test_opaque_anthropic_saved_metadata_preserves_signed_and_redacted_replay(
    kind: str,
) -> None:
    model = f"arn:aws:bedrock:us-east-1:123456789012:{kind}/synthetic-opaque-profile"
    metadata = saved_metadata(
        model, developer=LLMModelDeveloper.ANTHROPIC, family="claude-sonnet-4.6"
    )
    redacted = b"synthetic-opaque-redaction"
    encoded_redacted = base64.b64encode(redacted).decode()
    frames = [
        aws_event_frame("messageStart", {"role": "assistant"}),
        aws_event_frame(
            "contentBlockDelta",
            {
                "contentBlockIndex": 0,
                "delta": {"reasoningContent": {"text": "Synthetic visible reasoning"}},
            },
        ),
        aws_event_frame(
            "contentBlockDelta",
            {
                "contentBlockIndex": 0,
                "delta": {
                    "reasoningContent": {"signature": "synthetic-opaque-signature"}
                },
            },
        ),
        aws_event_frame("contentBlockStop", {"contentBlockIndex": 0}),
        aws_event_frame(
            "contentBlockDelta",
            {
                "contentBlockIndex": 1,
                "delta": {"reasoningContent": {"redactedContent": encoded_redacted}},
            },
        ),
        aws_event_frame("contentBlockStop", {"contentBlockIndex": 1}),
        aws_event_frame(
            "contentBlockDelta",
            {
                "contentBlockIndex": 2,
                "delta": {"text": "Synthetic output"},
            },
        ),
        aws_event_frame("contentBlockStop", {"contentBlockIndex": 2}),
        aws_event_frame("messageStop", {"stopReason": "end_turn"}),
    ]
    first = bedrock_call(model=model, chunks=frames)
    first_config = first.boundary.client.meta.config
    assert isinstance(first_config, ParameterValidationConfig)
    assert first_config.parameter_validation
    events = await first.collect(ModelRequestParameters(), assembly_metadata=metadata)
    assembled = [event.response for event in events if event.response is not None]
    assert len(assembled) == 1
    assert assembled[0].model_name == model
    redacted_parts = [
        part
        for part in assembled[0].parts
        if isinstance(part, ThinkingPart) and part.id == "redacted_content"
    ]
    assert len(redacted_parts) == 1
    assert redacted_parts[0].signature == redacted.decode()
    assert not redacted_parts[0].content
    # Replay the actual public SDK result under the same exact saved ARN.
    second = bedrock_call(model=model, chunks=[nominal_body(model)])
    await second.collect(
        ModelRequestParameters(),
        messages=[
            ModelRequest(parts=[UserPromptPart("Synthetic input")]),
            assembled[0],
            ModelRequest(parts=[UserPromptPart(["Synthetic follow-up", CachePoint()])]),
        ],
        settings=BedrockModelSettings(bedrock_cache_messages=True),
        assembly_metadata=metadata,
    )
    wire = second.boundary.bodies[0]
    assert second.boundary.paths == [f"/model/{model}/converse-stream"]
    messages = wire["messages"]
    assert isinstance(messages, list)
    content = messages[1]["content"]
    assert content[0] == {
        "reasoningContent": {
            "reasoningText": {
                "text": "Synthetic visible reasoning",
                "signature": "synthetic-opaque-signature",
            }
        }
    }
    assert content[1] == {"reasoningContent": {"redactedContent": encoded_redacted}}
    assert not any(
        "text" in block
        and (
            "synthetic-opaque-signature" in block["text"]
            or "synthetic-opaque-redaction" in block["text"]
        )
        for block in content
    )
    assert cache_points(wire) == [{"type": "default"}]
    assert "toolConfig" not in first.boundary.bodies[0]
    additional = wire.get("additionalModelRequestFields", {})
    assert isinstance(additional, dict)
    assert "thinking" not in additional
    assert "output_config" not in additional


@pytest.mark.parametrize(
    ("developer", "family", "colocated", "json_result"),
    [
        (LLMModelDeveloper.ANTHROPIC, "anthropic.claude", True, False),
        (LLMModelDeveloper.MISTRAL, "mistral.mistral", False, True),
        (LLMModelDeveloper.META, "meta.llama3", False, False),
    ],
)
async def test_opaque_saved_family_retains_tool_result_and_media_layout(
    developer: LLMModelDeveloper,
    family: str,
    colocated: bool,
    json_result: bool,
) -> None:
    model = (
        "arn:aws:bedrock:us-east-1:123456789012:"
        "application-inference-profile/synthetic-opaque-profile"
    )
    metadata = saved_metadata(model, developer=developer, family=family)
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
                    },
                },
            },
        ),
        aws_event_frame(
            "contentBlockDelta",
            {
                "contentBlockIndex": 0,
                "delta": {
                    "toolUse": {"input": "{}"},
                },
            },
        ),
        aws_event_frame("contentBlockStop", {"contentBlockIndex": 0}),
        aws_event_frame("messageStop", {"stopReason": "tool_use"}),
    ]
    parameters = ModelRequestParameters(
        function_tools=[
            ToolDefinition(
                name="fixture_tool",
                parameters_json_schema={
                    "type": "object",
                    "properties": {},
                },
            ),
        ]
    )
    first = bedrock_call(model=model, chunks=frames)
    history = await first.collect(parameters, assembly_metadata=metadata)
    assembled = [event.response for event in history if event.response is not None]
    assert len(assembled) == 1
    second = bedrock_call(model=model, chunks=[nominal_body(model)])
    await second.collect(
        parameters,
        messages=[
            ModelRequest(parts=[UserPromptPart("Synthetic input")]),
            assembled[0],
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="fixture_tool",
                        tool_call_id="synthetic-client-tool",
                        content={"value": "Synthetic result"},
                    ),
                    UserPromptPart(
                        [
                            BinaryContent(
                                data=b"synthetic-image-bytes", media_type="image/png"
                            )
                        ]
                    ),
                ]
            ),
        ],
        assembly_metadata=metadata,
    )
    wire = second.boundary.bodies[0]
    assert second.boundary.paths == [f"/model/{model}/converse-stream"]
    messages = wire["messages"]
    assert isinstance(messages, list)
    results = [
        turn
        for turn in messages
        if any("toolResult" in part for part in turn["content"])
    ]
    assert len(results) == 1
    assert any("image" in part for part in results[0]["content"]) == colocated
    block = results[0]["content"][0]["toolResult"]["content"][0]
    assert ("json" in block) == json_result
    if not colocated:
        assert len(results[0]["content"]) == 1
        assert any("image" in part for part in messages[-1]["content"])


async def test_known_literal_profile_has_priority_over_saved_opaque_family_traits() -> (
    None
):
    model = "mistral.mistral-large-2402-v1:0"
    metadata = saved_metadata(
        model, developer=LLMModelDeveloper.ANTHROPIC, family="anthropic.claude"
    )
    call = bedrock_call(model=model, chunks=[nominal_body(model)])
    await call.collect(
        ModelRequestParameters(
            function_tools=[
                ToolDefinition(
                    name="fixture_tool",
                    parameters_json_schema={"type": "object", "properties": {}},
                ),
            ],
            allow_text_output=False,
        ),
        settings=BedrockModelSettings(bedrock_cache_messages=True),
        assembly_metadata=metadata,
    )
    wire = call.boundary.bodies[0]
    config = wire["toolConfig"]
    assert isinstance(config, dict)
    assert "toolChoice" not in config
    assert not cache_points(wire)
    assert call.boundary.paths == [f"/model/{model}/converse-stream"]


async def test_opaque_metadata_does_not_grant_version_specific_sdk_features() -> None:
    model = (
        "arn:aws:bedrock:us-east-1:123456789012:"
        "application-inference-profile/synthetic-opaque-profile"
    )
    metadata = saved_metadata(
        model, developer=LLMModelDeveloper.ANTHROPIC, family="claude-sonnet-4.6"
    )
    call = bedrock_call(model=model, chunks=[])
    state = NativeObservationState(
        protocol="bedrock",
        call_context=context_for_test(),
        timeout_policy=call.policy,
        sdk_failure_mapper=map_model_provider_error,
    )
    binding = await call.adapter.factory.create(
        model=model, assembly_metadata=metadata, state=state
    )
    try:
        profile = binding.model.profile
        assert profile.get("bedrock_send_back_thinking_parts") is True
        assert not profile.get("bedrock_supports_adaptive_thinking", False)
        assert not profile.get("bedrock_supports_effort", False)
        assert not profile.get("thinking_enabled_by_default", False)
        assert not profile.get("thinking_always_enabled", False)
        assert not profile.get("bedrock_supports_strict_tool_definition", False)
        assert not profile.get("supported_native_tools")
        assert not call.boundary.paths
    finally:
        await binding.close()


@pytest.mark.parametrize(
    "kind",
    [
        "application-inference-profile",
        "inference-profile",
        "provisioned-model",
        "custom-model-deployment",
        "custom-model",
    ],
)
async def test_opaque_resource_kind_alone_does_not_grant_family(kind: str) -> None:
    model = f"arn:aws:bedrock:us-east-1:123456789012:{kind}/synthetic-opaque-profile"
    call = bedrock_call(model=model, chunks=[nominal_body(model)])
    events = await call.collect(
        ModelRequestParameters(
            function_tools=[
                ToolDefinition(
                    name="fixture_tool",
                    parameters_json_schema={"type": "object", "properties": {}},
                )
            ],
            allow_text_output=False,
        ),
        messages=[
            ModelRequest(
                parts=[
                    SystemPromptPart("Synthetic instruction"),
                    UserPromptPart(["Synthetic input", CachePoint()]),
                ]
            )
        ],
        settings=BedrockModelSettings(
            bedrock_cache_instructions=True,
            bedrock_cache_messages=True,
            bedrock_cache_tool_definitions=True,
        ),
        assembly_metadata=None,
    )
    wire = call.boundary.bodies[0]
    tools = wire["toolConfig"]
    assert isinstance(tools, dict)
    assert "toolChoice" not in tools
    assert not cache_points(wire)
    assert call.boundary.paths == [f"/model/{model}/converse-stream"]
    assert any(
        event.observation is not None and event.observation.terminal == "success"
        for event in events
    )
