"""Final saved features own codec configuration and serialized request support."""

import dataclasses
from typing import Never

import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic import JsonValue, TypeAdapter
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.native_tools import ImageGenerationTool, WebSearchTool
from pydantic_ai.output import OutputObjectDefinition
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import ToolDefinition

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import (
    ModelBuiltInToolCapabilities,
    ModelCapabilities,
    ModelParameterCapabilities,
    ModelReasoningCapabilities,
    ModelReasoningEffort,
    ModelToolCallingCapabilities,
)
from azents.core.model_capability_contract import (
    ModelCapabilityFeature,
    ModelFeatureCondition,
    ModelRequestConstraints,
)
from azents.core.model_provider_protocol import vertex_model_family
from azents.engine.events.effective_model_request import (
    normalize_effective_model_request,
    prepare_effective_model_parameters,
)
from azents.engine.events.model_support_contract import validate_saved_model_request
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.providers.bedrock_cache_compatibility_test import collect_request
from azents.engine.providers.bedrock_lifecycle_test import bedrock_call, nominal_body
from azents.engine.providers.model_profiles import (
    RuntimeModelProfileResolution,
    bedrock_assembly_profile,
    resolve_runtime_model_profile,
    saved_bedrock_assembly_profile,
)
from azents.testing.provider_native_envelopes import core_native_response

_WIRE_OBJECT = TypeAdapter(dict[str, JsonValue])


def _caps(*, strict: bool = True) -> ModelCapabilities:
    return ModelCapabilities(
        tool_calling=ModelToolCallingCapabilities(
            supported=True, strict_json_schema=strict
        ),
        reasoning=ModelReasoningCapabilities(
            supported=True,
            effort_levels=[ModelReasoningEffort.NONE, ModelReasoningEffort.HIGH],
        ),
        parameters=ModelParameterCapabilities(temperature=True, top_p=True),
        structured_response=True,
        built_in_tools=ModelBuiltInToolCapabilities(supported=["web_search"]),
    )


def _resolve(
    provider: LLMProvider, model: str, caps: ModelCapabilities
) -> RuntimeModelProfileResolution:
    return resolve_runtime_model_profile(
        provider=provider,
        model=model,
        profile_model=model,
        assembly_metadata=ModelAssemblyMetadata(
            model_developer=LLMModelDeveloper.ANTHROPIC
            if provider == LLMProvider.ANTHROPIC
            else None,
            model_family=None,
            capabilities=caps,
        ),
        context_window=None,
        context_window_explicit=False,
        source_model=None,
    )


@pytest.mark.parametrize("provider", [LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH])
def test_native_routes_do_not_infer_model_facts_from_pydantic(
    provider: LLMProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject(*args: object, **kwargs: object) -> Never:
        raise AssertionError("Native route must not inspect a Pydantic model profile")

    monkeypatch.setattr(OpenAIProvider, "model_profile", reject)
    caps = _caps()
    resolved = _resolve(provider, "exact-native", caps)
    assert resolved.profile == {}
    assert resolved.normalized_capabilities == caps


@pytest.mark.parametrize("strict", [True, False])
@pytest.mark.parametrize(
    "provider", [LLMProvider.XAI, LLMProvider.OPENROUTER, LLMProvider.KIMI_OAUTH]
)
def test_compatible_codec_flags_follow_saved_features(
    provider: LLMProvider, strict: bool
) -> None:
    profile = _resolve(provider, "publisher/exact", _caps(strict=strict)).profile
    assert profile.get("openai_supports_strict_tool_definition") is True
    assert _caps(strict=strict).tool_calling.strict_json_schema is strict
    assert profile.get("openai_responses_supports_json_schema_output") is True
    assert profile.get("supports_tools") is True
    assert profile.get("openai_supports_reasoning") is True
    assert profile.get("openai_supports_reasoning_effort_none") is True


def test_empty_final_feature_list_disables_codec_features() -> None:
    profile = _resolve(
        LLMProvider.OPENROUTER, "publisher/exact", ModelCapabilities()
    ).profile
    assert profile.get("supports_tools") is False
    assert profile.get("supports_thinking") is False
    assert profile.get("openai_supports_strict_tool_definition") is False
    assert profile.get("supported_native_tools") == frozenset()


def test_strict_anthropic_functions_do_not_enable_response_fact() -> None:
    caps = _caps()
    caps.structured_response = False
    resolved = _resolve(LLMProvider.ANTHROPIC, "claude-exact", caps)
    assert resolved.profile.get("supports_json_schema_output") is True
    assert caps.structured_response is False


def test_google_native_tools_are_saved_membership() -> None:
    caps = _caps()
    caps.built_in_tools.supported.append("image_generation")
    profile = _resolve(LLMProvider.GOOGLE_GEMINI, "gemini-exact", caps).profile
    assert profile.get("supported_native_tools") == frozenset(
        {WebSearchTool, ImageGenerationTool}
    )
    assert profile.get("google_supports_strict_tool_definition") is True


def test_bedrock_opaque_resource_needs_saved_family_authority() -> None:
    model = (
        "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/opaque"
    )
    assert bedrock_assembly_profile(model) is None
    assert saved_bedrock_assembly_profile(model, metadata=None) is None
    family = saved_bedrock_assembly_profile(
        model,
        metadata=ModelAssemblyMetadata(
            model_developer=LLMModelDeveloper.ANTHROPIC,
            model_family=None,
            capabilities=_caps(),
        ),
    )
    assert family is not None
    assert family.get("bedrock_thinking_variant") == "anthropic"
    resolved = _resolve(LLMProvider.AWS_BEDROCK, "anthropic.claude-exact", _caps())
    assert resolved.profile.get("bedrock_supports_strict_tool_definition") is True


@pytest.mark.parametrize("publisher", ["google", "anthropic"])
def test_vertex_publisher_identity_keeps_protocol(publisher: str) -> None:
    model = (
        f"projects/synthetic/locations/us-central1/publishers/{publisher}/models/exact"
    )
    assert vertex_model_family(model) == publisher


@pytest.mark.parametrize(
    "provider",
    [
        LLMProvider.XAI,
        LLMProvider.XAI_OAUTH,
        LLMProvider.OPENROUTER,
        LLMProvider.KIMI_OAUTH,
    ],
)
@pytest.mark.parametrize("conditional", [True, False])
@pytest.mark.parametrize("effort", ["none", "high"])
async def test_sampling_survives_real_compatible_sdk_serialization(
    provider: LLMProvider, conditional: bool, effort: str
) -> None:
    """Conditions own admission; stock codec cannot prune accepted request values."""
    model = "synthetic-exact"
    caps = _caps(strict=False)
    caps.built_in_tools.supported = []
    if conditional:
        caps.request_constraints = ModelRequestConstraints(
            feature_conditions=tuple(
                ModelFeatureCondition(
                    feature=feature, reasoning_efforts=("none",), function_tools=None
                )
                for feature in [
                    ModelCapabilityFeature.TEMPERATURE,
                    ModelCapabilityFeature.TOP_P,
                ]
            )
        )
    lowerer = PydanticAILowerer(
        top_k=None,
        provider=provider.value,
        provider_id=provider,
        model=model,
        tools=None,
        model_capabilities=caps,
        supported_execution_options=[],
        enabled_execution_options=[],
        reasoning_effort=effort,
        temperature=0.0,
        top_p=0.9,
    )
    if conditional and effort == "high":
        with pytest.raises(ValueError, match="conditions"):
            lowerer.lower([], model=model, native_replay_context=None)
        return
    request = lowerer.lower([], model=model, native_replay_context=None)
    bodies: list[dict[str, JsonValue]] = []

    def handle(message: httpx2.Request) -> httpx2.Response:
        bodies.append(_WIRE_OBJECT.validate_json(message.content))
        if provider == LLMProvider.KIMI_OAUTH:
            return httpx2.Response(
                200,
                json={
                    "id": "chatcmpl-synthetic",
                    "object": "chat.completion",
                    "created": 1,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "Synthetic"},
                        }
                    ],
                },
            )
        envelope = core_native_response(
            protocol="responses", model=model, text="Synthetic"
        )
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=envelope.body
        )

    sdk = AsyncOpenAI(
        api_key="synthetic-only",
        base_url="https://fixture.invalid/v1",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    )
    try:
        resolution = _resolve(provider, model, caps)
        sdk_provider = OpenAIProvider(openai_client=sdk)
        if provider == LLMProvider.KIMI_OAUTH:
            model_instance = OpenAIChatModel(
                model, provider=sdk_provider, profile=resolution.profile
            )
            await model_instance.request(
                request.messages, request.settings, request.parameters
            )
        else:
            model_instance = OpenAIResponsesModel(
                model, provider=sdk_provider, profile=resolution.profile
            )
            async with model_instance.request_stream(
                request.messages, request.settings, request.parameters
            ) as stream:
                async for _ in stream:
                    pass
        assert bodies[0]["temperature"] == 0.0
        assert bodies[0]["top_p"] == 0.9
        assert bodies[0]["reasoning"] == {"effort": effort}
        assert caps.reasoning.effort_levels == [
            ModelReasoningEffort.NONE,
            ModelReasoningEffort.HIGH,
        ]
    finally:
        await sdk.close()


@pytest.mark.parametrize("function_strict", [True, False])
@pytest.mark.parametrize("response_structured", [True, False])
@pytest.mark.parametrize("declared_strict", [None, False, True])
async def test_shared_sdk_encoding_flag_never_unions_function_authorization(
    function_strict: bool, response_structured: bool, declared_strict: bool | None
) -> None:
    """Native-schema encoding permission does not authorize strict function requests."""
    caps = _caps(strict=function_strict)
    caps.structured_response = response_structured
    caps.built_in_tools.supported = []
    tool: dict[str, object] = {
        "type": "function",
        "name": "probe",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    }
    if declared_strict is not None:
        tool["strict"] = declared_strict
    lowerer = PydanticAILowerer(
        provider="openrouter",
        provider_id=LLMProvider.OPENROUTER,
        model="fixture",
        tools=[tool],
        top_k=None,
        model_capabilities=caps,
        supported_execution_options=[],
        enabled_execution_options=[],
    )
    if declared_strict is True and not function_strict:
        with pytest.raises(ValueError, match="strict_function_schema"):
            lowerer.lower([], model="fixture", native_replay_context=None)
        return
    request = lowerer.lower([], model="fixture", native_replay_context=None)
    assert request.parameters.function_tools[0].strict is (declared_strict is True)
    bodies: list[dict[str, JsonValue]] = []

    def handle(message: httpx2.Request) -> httpx2.Response:
        bodies.append(_WIRE_OBJECT.validate_json(message.content))
        envelope = core_native_response(
            protocol="responses", model="fixture", text="Synthetic"
        )
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=envelope.body
        )

    sdk = AsyncOpenAI(
        api_key="synthetic",
        base_url="https://fixture.invalid/v1",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    )
    try:
        profile = _resolve(LLMProvider.OPENROUTER, "fixture", caps).profile
        model = OpenAIResponsesModel(
            "fixture", provider=OpenAIProvider(openai_client=sdk), profile=profile
        )
        async with model.request_stream(
            request.messages, request.settings, request.parameters
        ) as stream:
            async for _ in stream:
                pass
        declarations = TypeAdapter(list[dict[str, JsonValue]]).validate_python(
            bodies[0]["tools"]
        )
        assert declarations[0]["strict"] is (declared_strict is True)
        assert caps.structured_response is response_structured
        assert caps.tool_calling.strict_json_schema is function_strict
    finally:
        await sdk.close()


@pytest.mark.parametrize("strict", [None, False, True])
@pytest.mark.parametrize("function_strict", [True, False])
async def test_synthetic_output_tool_strict_defaults_reach_compatible_wire(
    strict: bool | None, function_strict: bool
) -> None:
    """Synthetic function outputs receive explicit defaults before admission and SDK."""
    caps = _caps(strict=function_strict)
    caps.built_in_tools.supported = []
    parameters = prepare_effective_model_parameters(
        ModelRequestParameters(
            output_mode="tool",
            allow_text_output=False,
            output_tools=[
                ToolDefinition(
                    name="synthetic_output",
                    strict=strict,
                    parameters_json_schema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                )
            ],
        )
    )
    assert parameters.output_tools[0].strict is (strict is True)
    effective = normalize_effective_model_request(
        dialect="openai_responses", options={}, parameters=parameters, native_tools=None
    )
    if strict is True and not function_strict:
        with pytest.raises(ValueError, match="strict_function_schema"):
            validate_saved_model_request(caps, request=effective)
        return
    validate_saved_model_request(caps, request=effective)
    base = PydanticAILowerer(
        provider="openrouter",
        provider_id=LLMProvider.OPENROUTER,
        model="fixture",
        tools=None,
        top_k=None,
        model_capabilities=caps,
        supported_execution_options=[],
        enabled_execution_options=[],
    ).lower([], model="fixture", native_replay_context=None)
    request = dataclasses.replace(base, parameters=parameters)
    bodies: list[dict[str, JsonValue]] = []

    def handle(message: httpx2.Request) -> httpx2.Response:
        bodies.append(_WIRE_OBJECT.validate_json(message.content))
        envelope = core_native_response(
            protocol="responses", model="fixture", text="Synthetic"
        )
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=envelope.body
        )

    sdk = AsyncOpenAI(
        api_key="synthetic",
        base_url="https://fixture.invalid/v1",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    )
    try:
        model = OpenAIResponsesModel(
            "fixture",
            provider=OpenAIProvider(openai_client=sdk),
            profile=_resolve(LLMProvider.OPENROUTER, "fixture", caps).profile,
        )
        async with model.request_stream(
            request.messages, request.settings, request.parameters
        ) as stream:
            async for _ in stream:
                pass
        tools = TypeAdapter(list[dict[str, JsonValue]]).validate_python(
            bodies[0]["tools"]
        )
        assert tools[0]["strict"] is (strict is True)
        assert parameters.output_tools[0].strict is (strict is True)
    finally:
        await sdk.close()


@pytest.mark.parametrize("function_strict", [True, False])
async def test_synthetic_bedrock_output_none_is_explicit_false_on_boto_wire(
    function_strict: bool,
) -> None:

    model = "anthropic.claude-sonnet-4-5-20250929-v1:0"
    caps = _caps(strict=function_strict)
    caps.structured_response = False
    caps.built_in_tools.supported = []
    parameters = prepare_effective_model_parameters(
        ModelRequestParameters(
            output_mode="tool",
            allow_text_output=False,
            output_tools=[
                ToolDefinition(
                    name="synthetic_output",
                    strict=None,
                    parameters_json_schema={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                )
            ],
        )
    )
    effective = normalize_effective_model_request(
        dialect="bedrock", options={}, parameters=parameters, native_tools=None
    )
    validate_saved_model_request(caps, request=effective)
    base = PydanticAILowerer(
        provider="aws_bedrock",
        provider_id=LLMProvider.AWS_BEDROCK,
        model=model,
        model_developer=LLMModelDeveloper.ANTHROPIC,
        tools=None,
        top_k=None,
        model_capabilities=caps,
        supported_execution_options=[],
        enabled_execution_options=[],
    ).lower([], model=model, native_replay_context=None)
    request = dataclasses.replace(
        base,
        parameters=parameters,
        assembly_metadata=ModelAssemblyMetadata(
            model_developer=LLMModelDeveloper.ANTHROPIC,
            model_family=None,
            capabilities=caps,
        ),
    )
    call = bedrock_call(model=model, chunks=[nominal_body(model)])
    await collect_request(call, request)
    tool_config = _WIRE_OBJECT.validate_python(call.boundary.bodies[0]["toolConfig"])
    wire_tools = TypeAdapter(list[dict[str, JsonValue]]).validate_python(
        tool_config["tools"]
    )
    tool_spec = _WIRE_OBJECT.validate_python(wire_tools[0]["toolSpec"])
    assert "strict" not in tool_spec
    assert parameters.output_tools[0].strict is False
    assert effective.structured_response is False


@pytest.mark.parametrize("chat", [True, False])
@pytest.mark.parametrize("function_strict", [True, False])
@pytest.mark.parametrize("response_strict", [True, False])
async def test_native_response_schema_strict_is_independent_on_sdk_wire(
    chat: bool, function_strict: bool, response_strict: bool
) -> None:
    caps = _caps(strict=function_strict)
    caps.built_in_tools.supported = []
    provider = LLMProvider.KIMI_OAUTH if chat else LLMProvider.OPENROUTER
    parameters = ModelRequestParameters(
        output_mode="native",
        output_object=TypeAdapter(OutputObjectDefinition).validate_python(
            {
                "name": "response",
                "strict": response_strict,
                "json_schema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            }
        ),
    )
    effective = normalize_effective_model_request(
        dialect="openai_chat" if chat else "openai_responses",
        options={},
        parameters=parameters,
        native_tools=None,
    )
    validate_saved_model_request(caps, request=effective)
    assert effective.strict_function_schema is False
    bodies: list[dict[str, JsonValue]] = []

    def handle(message: httpx2.Request) -> httpx2.Response:
        bodies.append(_WIRE_OBJECT.validate_json(message.content))
        if chat:
            return httpx2.Response(
                200,
                json={
                    "id": "chatcmpl-synthetic",
                    "created": 1,
                    "object": "chat.completion",
                    "model": "fixture",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "{}"},
                        }
                    ],
                },
            )
        envelope = core_native_response(
            protocol="responses", model="fixture", text="{}"
        )
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, content=envelope.body
        )

    sdk = AsyncOpenAI(
        api_key="synthetic",
        base_url="https://fixture.invalid/v1",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    )
    try:
        sdk_provider = OpenAIProvider(openai_client=sdk)
        profile = _resolve(provider, "fixture", caps).profile
        if chat:
            model = OpenAIChatModel("fixture", provider=sdk_provider, profile=profile)
            await model.request(
                [ModelRequest(parts=[UserPromptPart("Synthetic")])], {}, parameters
            )
            response_format = _WIRE_OBJECT.validate_python(bodies[0]["response_format"])
            format = _WIRE_OBJECT.validate_python(response_format["json_schema"])
        else:
            model = OpenAIResponsesModel(
                "fixture", provider=sdk_provider, profile=profile
            )
            async with model.request_stream(
                [ModelRequest(parts=[UserPromptPart("Synthetic")])], {}, parameters
            ) as stream:
                async for _ in stream:
                    pass
            text = _WIRE_OBJECT.validate_python(bodies[0]["text"])
            format = _WIRE_OBJECT.validate_python(text["format"])
        assert format["strict"] is response_strict
        assert caps.tool_calling.strict_json_schema is function_strict
    finally:
        await sdk.close()
