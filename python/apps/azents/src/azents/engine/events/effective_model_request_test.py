"""Typed effective request intent agrees with official SDK body precedence."""

from collections.abc import Iterator, Mapping
from typing import Literal

import boto3
import httpx2
import pytest
from anthropic import AsyncAnthropic
from botocore.awsrequest import AWSPreparedRequest, AWSResponse
from botocore.compat import HTTPHeaders
from openai import AsyncOpenAI
from openai.types.shared_params.reasoning import Reasoning
from pydantic import TypeAdapter
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.bedrock import BedrockConverseModel, BedrockModelSettings
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.models.openai import (
    OpenAIChatModel,
    OpenAIChatModelSettings,
    OpenAIResponsesModel,
    OpenAIResponsesModelSettings,
)
from pydantic_ai.native_tools import ImageGenerationTool, WebSearchTool
from pydantic_ai.output import OutputObjectDefinition
from pydantic_ai.profiles.anthropic import AnthropicModelProfile
from pydantic_ai.profiles.google import GoogleModelProfile
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.bedrock import BedrockModelProfile, BedrockProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import ToolDefinition

from azents.engine.events.effective_model_request import (
    BudgetReasoning,
    ClearedReasoning,
    DisabledReasoning,
    EffectiveModelRequest,
    EffectiveRequestNormalizationError,
    EffortReasoning,
    OmittedReasoning,
    RequestDialect,
    normalize_effective_model_request,
    prepare_effective_model_parameters,
)

_BODY = TypeAdapter(dict[str, object])
_OUTPUT = TypeAdapter(OutputObjectDefinition)


def _normalize(
    dialect: RequestDialect,
    options: Mapping[str, object],
    *,
    parameters: ModelRequestParameters | None = None,
    tools: list[dict[str, object]] | None = None,
) -> EffectiveModelRequest:
    return normalize_effective_model_request(
        dialect=dialect, options=options, parameters=parameters, native_tools=tools
    )


@pytest.mark.parametrize(
    "dialect",
    [
        "native_responses",
        "openai_responses",
        "openai_chat",
        "anthropic",
        "google",
        "bedrock",
    ],
)
def test_absent_request_does_not_invent_reasoning_or_feature_facts(
    dialect: RequestDialect,
) -> None:
    request = _normalize(dialect, {})
    assert isinstance(request.reasoning, OmittedReasoning)
    assert request.reasoning_effort is None
    assert request.temperature is None
    assert request.max_output_tokens is None
    assert request.parallel_function_calls is None
    assert request.present_fields == frozenset()


@pytest.mark.parametrize(
    ("dialect", "options"),
    [
        ("native_responses", {"reasoning": {"effort": "high"}}),
        ("openai_responses", {"openai_reasoning_effort": "high"}),
        ("openai_chat", {"openai_reasoning_effort": "high"}),
        ("anthropic", {"anthropic_effort": "high"}),
        ("google", {"google_thinking_config": {"thinking_level": "HIGH"}}),
        (
            "bedrock",
            {
                "bedrock_additional_model_requests_fields": {
                    "output_config": {"effort": "high"}
                }
            },
        ),
    ],
)
def test_provider_encoded_efforts_are_not_clamped(
    dialect: RequestDialect,
    options: dict[str, object],
) -> None:
    request = _normalize(dialect, options)
    assert request.reasoning == EffortReasoning(level="high")
    assert request.reasoning_effort == "high"


@pytest.mark.parametrize("override", [None, {}, {"summary": "none"}])
def test_sdk_reasoning_whole_object_override_does_not_inherit_typed_effort(
    override: object,
) -> None:
    request = _normalize(
        "openai_responses",
        {
            "openai_reasoning_effort": "high",
            "openai_reasoning_summary": "auto",
            "extra_body": {"reasoning": override},
        },
    )
    assert isinstance(request.reasoning, ClearedReasoning)
    assert request.reasoning_effort is None
    assert not request.summary_requested
    assert "reasoning" in request.present_fields


@pytest.mark.parametrize("dialect", ["openai_responses", "anthropic"])
def test_scalar_null_zero_empty_false_use_actual_shallow_overlay(
    dialect: Literal["openai_responses", "anthropic"],
) -> None:
    options: dict[str, object] = {
        "temperature": 0.8,
        "top_p": 0.9,
        "max_tokens": 500,
        "stop_sequences": ["END"],
        "parallel_tool_calls": True,
        "extra_body": {
            "temperature": 0,
            "top_p": None,
            "max_output_tokens"
            if dialect == "openai_responses"
            else "max_tokens": None,
            "stop" if dialect == "openai_responses" else "stop_sequences": [],
            "parallel_tool_calls": False,
        },
    }
    request = _normalize(dialect, options)
    assert request.temperature == 0
    assert request.top_p is None
    assert request.max_output_tokens is None
    assert request.stop_sequences == ()
    assert request.parallel_function_calls is False
    assert options["temperature"] == 0.8


@pytest.mark.parametrize(
    ("declaration", "kind", "effort"),
    [
        ({"thinkingLevel": "MINIMAL"}, "effort", "minimal"),
        ({"thinking_budget": 0}, "disabled", "none"),
        ({"thinkingBudget": 2048}, "budget", None),
        ({"thinking_budget": -1}, "adaptive", None),
        ({"include_thoughts": True}, "adaptive", None),
        (None, "cleared", None),
        ({}, "cleared", None),
    ],
)
def test_google_encoding_never_fabricates_effort_from_budget(
    declaration: object,
    kind: str,
    effort: str | None,
) -> None:
    request = _normalize("google", {"google_thinking_config": declaration})
    assert request.reasoning.kind == kind
    assert request.reasoning_effort == effort
    assert not isinstance(request.reasoning, OmittedReasoning)


@pytest.mark.parametrize("dialect", ["anthropic", "bedrock"])
@pytest.mark.parametrize(
    ("thinking", "kind"),
    [
        ({"type": "disabled"}, "disabled"),
        ({"type": "adaptive"}, "adaptive"),
        ({"type": "enabled", "budget_tokens": 4096}, "budget"),
    ],
)
def test_explicit_anthropic_thinking_forms_remain_distinct_from_omission(
    dialect: Literal["anthropic", "bedrock"],
    thinking: dict[str, object],
    kind: str,
) -> None:
    options = (
        {"anthropic_thinking": thinking}
        if dialect == "anthropic"
        else {"bedrock_additional_model_requests_fields": {"thinking": thinking}}
    )
    request = _normalize(dialect, options)
    assert request.reasoning.kind == kind
    assert request.reasoning_effort == ("none" if kind == "disabled" else None)


@pytest.mark.parametrize("unified", [True, False, "medium"])
def test_generic_thinking_without_encoded_provider_declaration_is_not_guessed(
    unified: bool | Literal["medium"],
) -> None:
    with pytest.raises(EffectiveRequestNormalizationError, match="provider-encoded"):
        _normalize("google", {"thinking": unified})
    request = _normalize(
        "google",
        {"thinking": unified, "google_thinking_config": {"thinking_budget": 2048}},
    )
    assert request.reasoning == BudgetReasoning(tokens=2048)


def test_sdk_synthetic_output_tools_count_as_actual_functions_and_strict() -> None:
    parameters = ModelRequestParameters(
        function_tools=[],
        output_tools=[
            ToolDefinition(
                name="final_answer",
                parameters_json_schema={"type": "object"},
                strict=True,
            )
        ],
        output_mode="tool",
    )
    request = _normalize("openai_responses", {}, parameters=parameters)
    assert request.function_tools
    assert request.strict_function_schema
    assert not request.structured_response


@pytest.mark.parametrize("override", [None, []])
def test_sdk_extra_body_tools_replaces_synthetic_and_regular_function_tools(
    override: object,
) -> None:
    parameters = ModelRequestParameters(
        function_tools=[ToolDefinition(name="function", strict=True)],
        output_tools=[ToolDefinition(name="final_answer", strict=True)],
    )
    request = _normalize(
        "openai_responses", {"extra_body": {"tools": override}}, parameters=parameters
    )
    assert not request.function_tools
    assert not request.strict_function_schema
    assert "tools" in request.present_fields


def test_native_response_schema_and_tool_strictness_are_independent() -> None:
    request = _normalize(
        "native_responses",
        {"text": {"format": {"type": "json_schema"}}},
        tools=[{"type": "web_search"}],
    )
    assert request.structured_response
    assert not request.function_tools
    assert not request.strict_function_schema


def test_sdk_native_output_object_is_not_a_synthetic_function() -> None:
    parameters = ModelRequestParameters(
        output_mode="native",
        output_object=_OUTPUT.validate_python({"json_schema": {"type": "object"}}),
    )
    request = _normalize(
        "anthropic", {"anthropic_effort": "high"}, parameters=parameters
    )
    assert request.structured_response
    assert not request.function_tools
    cleared = _normalize(
        "anthropic",
        {"anthropic_effort": "high", "extra_body": {"output_config": {}}},
        parameters=parameters,
    )
    assert not cleared.structured_response
    assert isinstance(cleared.reasoning, ClearedReasoning)


@pytest.mark.parametrize(
    "key", ["api_key", "api_base", "base_url", "vertex_credentials"]
)
def test_credentials_never_enter_effective_request(key: str) -> None:
    with pytest.raises(EffectiveRequestNormalizationError, match="credentials"):
        _normalize("openai_responses", {key: "private-value"})


@pytest.mark.parametrize("override", [None, {}, {"effort": "none"}])
async def test_official_openai_sdk_whole_reasoning_override_matches_normalized_intent(
    override: object,
) -> None:
    captured: list[dict[str, object]] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        captured.append(_BODY.validate_json(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "resp_fixture",
                "created_at": 1,
                "object": "response",
                "model": "fixture",
                "status": "completed",
                "output": [],
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
            },
        )

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
    client = AsyncOpenAI(api_key="synthetic-unused", http_client=http)
    reasoning: Reasoning = {"effort": "high", "summary": "auto"}
    try:
        await client.responses.create(
            model="fixture",
            input="fixture",
            reasoning=reasoning,
            extra_body={"reasoning": override},
        )
    finally:
        await client.close()
    assert len(captured) == 1
    assert captured[0]["reasoning"] == override
    expected = _normalize("native_responses", captured[0])
    actual = _normalize(
        "openai_responses",
        {
            "openai_reasoning_effort": "high",
            "openai_reasoning_summary": "auto",
            "extra_body": {"reasoning": override},
        },
    )
    assert actual.reasoning == expected.reasoning
    assert actual.reasoning_effort == expected.reasoning_effort
    assert actual.reasoning_summary == expected.reasoning_summary


@pytest.mark.parametrize("override", [None, {}, {"effort": "none"}])
async def test_actual_pydantic_openai_encoder_overlay_matches_effective_intent(
    override: object,
) -> None:
    captured: list[dict[str, object]] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        captured.append(_BODY.validate_json(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "resp_fixture",
                "created_at": 1,
                "object": "response",
                "model": "fixture",
                "status": "completed",
                "output": [],
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
            },
        )

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
    client = AsyncOpenAI(api_key="synthetic-unused", http_client=http)
    model = OpenAIResponsesModel(
        "fixture",
        provider=OpenAIProvider(openai_client=client),
        profile=OpenAIModelProfile(openai_supports_reasoning=True),
    )
    settings: OpenAIResponsesModelSettings = {
        "openai_reasoning_effort": "high",
        "openai_reasoning_summary": "auto",
        "extra_body": {"reasoning": override},
    }
    try:
        await model.request(
            [ModelRequest(parts=[UserPromptPart("fixture")])],
            settings,
            ModelRequestParameters(),
        )
    finally:
        await client.close()
    assert captured[0]["reasoning"] == override
    actual = _normalize("openai_responses", dict(settings))
    assert actual.reasoning == _normalize("native_responses", captured[0]).reasoning


@pytest.mark.parametrize("override", [None, {}, {"effort": "low"}])
async def test_actual_anthropic_output_config_overlay_matches_effective_effort(
    override: object,
) -> None:
    captured: list[dict[str, object]] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        captured.append(_BODY.validate_json(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "msg_fixture",
                "type": "message",
                "role": "assistant",
                "model": "fixture",
                "content": [{"type": "text", "text": "fixture"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    client = AsyncAnthropic(
        api_key="synthetic-unused",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    )
    model = AnthropicModel(
        "fixture",
        provider=AnthropicProvider(anthropic_client=client),
        profile=AnthropicModelProfile(
            anthropic_supports_effort=True, anthropic_disallows_sampling_settings=False
        ),
    )
    settings: AnthropicModelSettings = {
        "max_tokens": 16,
        "anthropic_effort": "high",
        "extra_body": {"output_config": override},
    }
    try:
        await model.request(
            [ModelRequest(parts=[UserPromptPart("fixture")])],
            settings,
            ModelRequestParameters(),
        )
    finally:
        await client.close()
    assert captured[0]["output_config"] == override
    actual = _normalize("anthropic", dict(settings))
    assert actual.reasoning_effort == ("low" if override == {"effort": "low"} else None)
    assert actual.reasoning.kind == (
        "effort" if override == {"effort": "low"} else "cleared"
    )


@pytest.mark.parametrize("budget", [-1, 0, 2048])
async def test_actual_google_sdk_budget_preserves_kind_without_fake_effort(
    budget: int,
) -> None:
    captured: list[dict[str, object]] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        captured.append(_BODY.validate_json(request.content))
        return httpx2.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "fixture"}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 1,
                    "candidatesTokenCount": 1,
                    "totalTokenCount": 2,
                },
                "modelVersion": "fixture",
            },
        )

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
    model = GoogleModel(
        "fixture",
        provider=GoogleProvider(api_key="synthetic-unused", http_client=http),
        profile=GoogleModelProfile(supports_thinking=True),
    )
    settings: GoogleModelSettings = {
        "google_thinking_config": {"thinking_budget": budget}
    }
    try:
        await model.request(
            [ModelRequest(parts=[UserPromptPart("fixture")])],
            settings,
            ModelRequestParameters(),
        )
    finally:
        await http.aclose()
    config = _BODY.validate_python(captured[0]["generationConfig"])
    thinking = _BODY.validate_python(config["thinkingConfig"])
    encoded = _normalize("google", {"google_thinking_config": thinking})
    assert encoded.reasoning == _normalize("google", dict(settings)).reasoning
    actual = _normalize("google", dict(settings))
    assert (
        actual.reasoning.kind == {-1: "adaptive", 0: "disabled", 2048: "budget"}[budget]
    )
    assert actual.reasoning_effort == ("none" if budget == 0 else None)


def test_coexisting_anthropic_effort_and_disabled_thinking_are_preserved() -> None:
    request = _normalize(
        "anthropic",
        {
            "anthropic_effort": "high",
            "anthropic_thinking": {"type": "disabled"},
        },
    )
    assert request.reasoning == EffortReasoning(level="high")
    assert request.encoded_thinking == DisabledReasoning()


def test_final_encoded_tools_replace_instead_of_union_with_authored_parameters() -> (
    None
):
    parameters = ModelRequestParameters(
        function_tools=[ToolDefinition(name="authored", strict=True)]
    )
    request = _normalize(
        "openai_responses",
        {},
        parameters=parameters,
        tools=[{"type": "function", "name": "physical", "strict": False}],
    )
    assert request.function_tools
    assert not request.strict_function_schema


def test_bedrock_nova_additional_topk_scope_does_not_replace_converse_controls() -> (
    None
):
    request = _normalize(
        "bedrock",
        {
            "temperature": 0.2,
            "top_p": 0.7,
            "max_tokens": 100,
            "stop_sequences": ["END"],
            "top_k": 10,
            "bedrock_additional_model_requests_fields": {
                "inferenceConfig": {
                    "topK": 42,
                    "temperature": 0.9,
                    "topP": 0.1,
                    "maxTokens": 999,
                    "stopSequences": ["NOVA"],
                },
            },
        },
    )
    assert request.top_k == 42
    assert request.temperature == 0.2
    assert request.top_p == 0.7
    assert request.max_output_tokens == 100
    assert request.stop_sequences == ("END",)


class _BedrockResponseBody:
    """Actual Boto JSON parser body; no provider transport is contacted."""

    def stream(self) -> Iterator[bytes]:
        yield (
            b'{"output":{"message":{"role":"assistant","content":'
            b'[{"text":"fixture"}]}},"stopReason":"end_turn","usage":'
            b'{"inputTokens":1,"outputTokens":1,"totalTokens":2},'
            b'"metrics":{"latencyMs":1}}'
        )


@pytest.mark.parametrize(
    "additional",
    [
        {"output_config": {"effort": "high"}},
        {"thinking": {"type": "disabled"}},
        {"thinking": {"type": "adaptive"}},
        {"thinking": {"type": "enabled", "budget_tokens": 2048}},
    ],
)
async def test_official_boto_converse_wire_retains_encoded_thinking_and_effort(
    additional: dict[str, object],
) -> None:
    bodies: list[dict[str, object]] = []
    client = boto3.client(
        "bedrock-runtime",
        region_name="us-east-1",
        aws_access_key_id="synthetic",
        aws_secret_access_key="synthetic",
        endpoint_url="https://fixture.invalid",
    )

    def respond(request: AWSPreparedRequest, **kwargs: object) -> AWSResponse:
        del kwargs
        body = request.body
        assert isinstance(body, str | bytes)
        bodies.append(_BODY.validate_json(body))
        headers = HTTPHeaders()
        headers["content-type"] = "application/json"
        return AWSResponse(
            request.url,
            200,
            headers,
            _BedrockResponseBody(),
        )

    client.meta.events.register("before-send.bedrock-runtime.Converse", respond)
    model = BedrockConverseModel(
        "fixture",
        provider=BedrockProvider(bedrock_client=client),
        profile=BedrockModelProfile(bedrock_thinking_variant="anthropic"),
    )
    settings: BedrockModelSettings = {
        "max_tokens": 16,
        "temperature": 0.2,
        "bedrock_additional_model_requests_fields": additional,
    }
    try:
        await model.request(
            [ModelRequest(parts=[UserPromptPart("fixture")])],
            settings,
            ModelRequestParameters(),
        )
    finally:
        client.close()
    assert len(bodies) == 1
    assert bodies[0]["additionalModelRequestFields"] == additional
    physical = _normalize(
        "bedrock",
        {
            "bedrock_additional_model_requests_fields": bodies[0][
                "additionalModelRequestFields"
            ]
        },
    )
    selected = _normalize("bedrock", dict(settings))
    assert selected.reasoning == physical.reasoning
    assert selected.encoded_thinking == physical.encoded_thinking


@pytest.mark.parametrize(
    ("declaration", "expected"),
    [
        ({"type": "web_search"}, ("web_search",)),
        ({"type": "openrouter:web_search"}, ("web_search",)),
        ({"type": "web_search_20250305", "name": "web_search"}, ("web_search",)),
        ({"type": "web_search_20260209", "name": "web_search"}, ("web_search",)),
        ({"googleSearch": {}}, ("web_search",)),
        ({"type": "image_generation"}, ("image_generation",)),
        ({"type": "function", "name": "web_search"}, ()),
        ({"type": "function", "name": "image_generation"}, ()),
    ],
)
def test_only_existing_native_builtin_aliases_create_builtin_request_membership(
    declaration: dict[str, object],
    expected: tuple[str, ...],
) -> None:
    request = _normalize("native_responses", {}, tools=[declaration])
    assert request.builtin_tools == expected


@pytest.mark.parametrize(
    "kind", ["x_search", "code_interpreter", "computer", "file_search"]
)
def test_unimplemented_native_tools_are_not_mapped_to_other_capabilities(
    kind: str,
) -> None:
    with pytest.raises(
        EffectiveRequestNormalizationError, match="unimplemented native"
    ):
        _normalize("native_responses", {}, tools=[{"type": kind}])


def test_sdk_native_objects_and_raw_openai_native_tools_are_in_actual_request() -> None:
    parameters = ModelRequestParameters(
        native_tools=[WebSearchTool(), ImageGenerationTool()]
    )
    request = _normalize("google", {}, parameters=parameters)
    assert request.builtin_tools == ("web_search", "image_generation")
    assert not request.function_tools
    request = _normalize(
        "openai_responses",
        {"openai_native_tools": [{"type": "web_search"}]},
    )
    assert request.builtin_tools == ("web_search",)


@pytest.mark.parametrize("override", [None, []])
def test_body_tools_clear_removes_native_and_synthetic_function_declarations(
    override: object,
) -> None:
    parameters = ModelRequestParameters(
        function_tools=[ToolDefinition(name="ordinary")],
        output_tools=[ToolDefinition(name="output", strict=True)],
        native_tools=[WebSearchTool()],
    )
    request = _normalize(
        "openai_responses",
        {
            "openai_native_tools": [{"type": "image_generation"}],
            "extra_body": {"tools": override},
        },
        parameters=parameters,
    )
    assert request.builtin_tools == ()
    assert not request.function_tools
    assert not request.strict_function_schema


def test_body_tools_replacement_is_the_only_actual_authority_not_native_union() -> None:
    request = _normalize(
        "openai_responses",
        {
            "openai_native_tools": [{"type": "web_search"}],
            "extra_body": {
                "tools": [{"type": "function", "name": "web_search", "strict": False}]
            },
        },
    )
    assert request.function_tools
    assert request.builtin_tools == ()


@pytest.mark.parametrize("override", [None, [], [{"type": "web_search"}]])
async def test_actual_sdk_body_tools_override_matches_function_and_builtin_intent(
    override: object,
) -> None:
    captured: list[dict[str, object]] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        captured.append(_BODY.validate_json(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "resp_fixture",
                "created_at": 1,
                "object": "response",
                "model": "fixture",
                "status": "completed",
                "output": [],
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
            },
        )

    client = AsyncOpenAI(
        api_key="synthetic-unused",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    )
    model = OpenAIResponsesModel(
        "fixture",
        provider=OpenAIProvider(openai_client=client),
        profile=OpenAIModelProfile(supports_tools=True),
    )
    settings: OpenAIResponsesModelSettings = {"extra_body": {"tools": override}}
    parameters = ModelRequestParameters(
        function_tools=[
            ToolDefinition(
                name="ordinary",
                parameters_json_schema={"type": "object", "properties": {}},
            )
        ],
        output_tools=[
            ToolDefinition(
                name="synthetic_output",
                parameters_json_schema={"type": "object", "properties": {}},
                strict=True,
            )
        ],
    )
    try:
        await model.request(
            [ModelRequest(parts=[UserPromptPart("fixture")])], settings, parameters
        )
    finally:
        await client.close()
    assert captured[0]["tools"] == override
    selected = _normalize("openai_responses", dict(settings), parameters=parameters)
    physical = _normalize("native_responses", captured[0])
    assert selected.function_tools == physical.function_tools
    assert selected.strict_function_schema == physical.strict_function_schema
    assert selected.builtin_tools == physical.builtin_tools


@pytest.mark.parametrize("override", [None, "low"])
async def test_actual_openai_chat_scalar_effort_override_matches_encoded_intent(
    override: Literal["low"] | None,
) -> None:
    captured: list[dict[str, object]] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        captured.append(_BODY.validate_json(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "chat_fixture",
                "object": "chat.completion",
                "created": 1,
                "model": "fixture",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "fixture"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        )

    client = AsyncOpenAI(
        api_key="synthetic-unused",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    )
    model = OpenAIChatModel(
        "fixture",
        provider=OpenAIProvider(openai_client=client),
        profile=OpenAIModelProfile(openai_supports_reasoning=True),
    )
    settings: OpenAIChatModelSettings = {
        "openai_reasoning_effort": "high",
        "extra_body": {"reasoning_effort": override},
    }
    try:
        await model.request(
            [ModelRequest(parts=[UserPromptPart("fixture")])],
            settings,
            ModelRequestParameters(),
        )
    finally:
        await client.close()
    assert captured[0]["reasoning_effort"] == override
    request = _normalize("openai_chat", dict(settings))
    assert request.reasoning_effort == override
    assert request.reasoning.kind == ("effort" if override is not None else "cleared")


@pytest.mark.parametrize("config", [None, {}])
def test_google_empty_specific_config_cannot_hide_unresolved_generic_translation(
    config: object,
) -> None:
    with pytest.raises(EffectiveRequestNormalizationError, match="provider-encoded"):
        _normalize("google", {"thinking": False, "google_thinking_config": config})


def test_anthropic_scalar_effort_does_not_prove_generic_thinking_mode_encoding() -> (
    None
):
    with pytest.raises(EffectiveRequestNormalizationError, match="provider-encoded"):
        _normalize("anthropic", {"thinking": True, "anthropic_effort": "high"})


def test_generated_summary_without_effort_keeps_default_eligible_omission() -> None:
    request = _normalize("openai_responses", {"openai_reasoning_summary": "auto"})
    assert isinstance(request.reasoning, OmittedReasoning)
    assert request.summary_requested


async def test_official_sdk_scalar_overlay_preserves_null_false_zero_and_empty() -> (
    None
):
    captured: list[dict[str, object]] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        captured.append(_BODY.validate_json(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "resp_fixture",
                "created_at": 1,
                "object": "response",
                "model": "fixture",
                "status": "completed",
                "output": [],
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
            },
        )

    client = AsyncOpenAI(
        api_key="synthetic-unused",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    )
    overlay: dict[str, object] = {
        "temperature": 0,
        "top_p": None,
        "max_output_tokens": None,
        "parallel_tool_calls": False,
        "stop": [],
    }
    try:
        await client.responses.create(
            model="fixture",
            input="fixture",
            temperature=0.8,
            top_p=0.9,
            max_output_tokens=500,
            parallel_tool_calls=True,
            extra_body=overlay,
        )
    finally:
        await client.close()
    actual = _normalize(
        "openai_responses",
        {
            "temperature": 0.8,
            "top_p": 0.9,
            "max_tokens": 500,
            "parallel_tool_calls": True,
            "extra_body": overlay,
        },
    )
    physical = _normalize("native_responses", captured[0])
    assert actual.temperature == physical.temperature == 0
    assert actual.top_p is physical.top_p is None
    assert actual.max_output_tokens is physical.max_output_tokens is None
    assert actual.parallel_function_calls is physical.parallel_function_calls is False
    assert actual.stop_sequences == physical.stop_sequences == ()
    assert overlay == {
        "temperature": 0,
        "top_p": None,
        "max_output_tokens": None,
        "parallel_tool_calls": False,
        "stop": [],
    }


@pytest.mark.parametrize("override", [None, {}, {"format": {"type": "text"}}])
async def test_actual_sdk_schema_container_replacement_can_clear_output_schema(
    override: object,
) -> None:
    captured: list[dict[str, object]] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        captured.append(_BODY.validate_json(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "resp_fixture",
                "created_at": 1,
                "object": "response",
                "model": "fixture",
                "status": "completed",
                "output": [],
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
            },
        )

    client = AsyncOpenAI(
        api_key="synthetic-unused",
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)),
    )
    model = OpenAIResponsesModel(
        "fixture",
        provider=OpenAIProvider(openai_client=client),
        profile=OpenAIModelProfile(
            supports_json_schema_output=True,
            openai_responses_supports_json_schema_output=True,
        ),
    )
    parameters = ModelRequestParameters(
        output_mode="native",
        output_object=_OUTPUT.validate_python(
            {
                "json_schema": {"type": "object", "properties": {}},
                "name": "answer",
            }
        ),
    )
    settings: OpenAIResponsesModelSettings = {"extra_body": {"text": override}}
    try:
        await model.request(
            [ModelRequest(parts=[UserPromptPart("fixture")])],
            settings,
            parameters,
        )
    finally:
        await client.close()
    assert captured[0]["text"] == override
    actual = _normalize("openai_responses", dict(settings), parameters=parameters)
    physical = _normalize("native_responses", captured[0])
    assert actual.structured_response is physical.structured_response is False


def test_unrequested_strict_defaults_preserve_explicit_values_and_native_output() -> (
    None
):
    output = _OUTPUT.validate_python(
        {"json_schema": {"type": "object", "properties": {}}, "strict": True}
    )
    parameters = ModelRequestParameters(
        function_tools=[
            ToolDefinition(name="unspecified"),
            ToolDefinition(name="explicit_true", strict=True),
            ToolDefinition(name="explicit_false", strict=False),
        ],
        output_tools=[ToolDefinition(name="synthetic_output", kind="output")],
        output_object=output,
    )
    prepared = prepare_effective_model_parameters(parameters)
    assert [tool.strict for tool in prepared.function_tools] == [False, True, False]
    assert prepared.output_tools[0].strict is False
    assert prepared.output_object is output
    assert prepared.output_object.strict is True
    assert parameters.function_tools[0].strict is None
    assert parameters.output_tools[0].strict is None
    assert prepare_effective_model_parameters(prepared) == prepared


async def test_google_sdk_default_function_strictness_is_not_validated() -> None:
    captured: list[dict[str, object]] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        captured.append(_BODY.validate_json(request.content))
        return httpx2.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "fixture"}]},
                        "finishReason": "STOP",
                    }
                ],
                "modelVersion": "fixture",
            },
        )

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
    model = GoogleModel(
        "fixture",
        provider=GoogleProvider(api_key="synthetic-unused", http_client=http),
        profile=GoogleModelProfile(),
    )
    parameters = prepare_effective_model_parameters(
        ModelRequestParameters(
            function_tools=[
                ToolDefinition(
                    name="ordinary",
                    parameters_json_schema={"type": "object", "properties": {}},
                )
            ]
        )
    )
    selected = _normalize("google", {}, parameters=parameters)
    assert selected.function_tools
    assert not selected.strict_function_schema
    try:
        await model.request(
            [ModelRequest(parts=[UserPromptPart("fixture")])], {}, parameters
        )
    finally:
        await http.aclose()
    tool_config = _BODY.validate_python(captured[0].get("toolConfig", {}))
    calling_config = _BODY.validate_python(tool_config.get("functionCallingConfig", {}))
    assert calling_config.get("mode") != "VALIDATED"
    assert captured[0]["tools"]


def test_unrepresentable_ultra_is_not_guessed_as_max() -> None:
    with pytest.raises(EffectiveRequestNormalizationError, match="encoding"):
        _normalize("native_responses", {"reasoning": {"effort": "ultra"}})
