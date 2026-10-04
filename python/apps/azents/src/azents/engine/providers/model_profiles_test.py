"""Encoding profiles honor saved facts without becoming catalog authority."""

import json
from typing import Literal, Never

import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel, JsonValue, TypeAdapter
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.native_tools import WebSearchTool
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.profiles.google import GoogleModelProfile
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities, ModelReasoningEffort
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_capability_projection import project_capabilities
from azents.core.model_catalog_source import (
    CatalogFact,
    CatalogSourceModel,
    decode_catalog_source,
)
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.providers.model_profiles import (
    RUNTIME_MODEL_PROFILE_RESOLVER_REVISION,
    resolve_runtime_model_profile,
    saved_bedrock_assembly_profile,
    vertex_model_family,
)
from azents.engine.run.types import BuiltinToolSpec
from azents.testing.provider_native_envelopes import core_native_response


def _source() -> CatalogSourceModel:
    return decode_catalog_source(
        json.dumps(
            {
                "gpt-5": {
                    "litellm_provider": "openai",
                    "mode": "responses",
                    "supports_reasoning": True,
                    "reasoning_effort_levels": ["none", "low", "high", "xhigh", "max"],
                    "supports_function_calling": True,
                }
            }
        ).encode()
    ).models[0]


@pytest.mark.parametrize("provider", [LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH])
def test_native_route_never_reads_a_pydantic_profile(
    provider: LLMProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject(*args: object, **kwargs: object) -> Never:
        raise AssertionError("Native OpenAI must not request Pydantic model knowledge")

    monkeypatch.setattr(OpenAIProvider, "model_profile", reject)
    resolution = resolve_runtime_model_profile(
        provider=provider,
        model="gpt-5",
        profile_model="unrelated-name",
        assembly_metadata=None,
        context_window=None,
        context_window_explicit=False,
        source_model=_source() if provider == LLMProvider.OPENAI else None,
    )
    assert resolution.model_kind == "native_openai_responses"
    assert resolution.profile == {}
    assert resolution.protocol == "responses"
    assert resolution.resolver_revision == RUNTIME_MODEL_PROFILE_RESOLVER_REVISION
    if provider == LLMProvider.OPENAI:
        assert (
            ModelReasoningEffort.XHIGH
            in resolution.normalized_capabilities.reasoning.effort_levels
        )
        assert (
            ModelReasoningEffort.MAX
            in resolution.normalized_capabilities.reasoning.effort_levels
        )


def test_native_historical_saved_capabilities_are_not_reinterpreted() -> None:
    historical = ModelCapabilities()
    before = historical.model_dump_json()
    resolution = resolve_runtime_model_profile(
        provider=LLMProvider.OPENAI,
        model="saved-opaque",
        profile_model=None,
        assembly_metadata=ModelAssemblyMetadata(
            model_developer=LLMModelDeveloper.OPENAI,
            model_family=None,
            capabilities=historical,
        ),
        context_window=100,
        context_window_explicit=True,
        source_model=_source(),
    )
    assert resolution.normalized_capabilities is historical
    assert historical.model_dump_json() == before
    assert historical.semantic_contract is None


def test_profile_defaults_are_not_used_as_missing_model_facts() -> None:
    resolution = resolve_runtime_model_profile(
        provider=LLMProvider.XAI,
        model="account-visible",
        profile_model=None,
        assembly_metadata=None,
        context_window=None,
        context_window_explicit=False,
        source_model=None,
    )
    assert resolution.profile["supports_tools"] is True
    assert resolution.profile["supports_thinking"] is True
    assert resolution.normalized_capabilities.tool_calling.supported is False
    assert resolution.normalized_capabilities.reasoning.effort_levels == []
    assert resolution.normalized_capabilities.semantic_contract is not None
    assert (
        resolution.normalized_capabilities.semantic_contract.function_calling.state
        == "unknown"
    )


def test_saved_v2_declarations_override_missing_google_profile_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        GoogleProvider,
        "model_profile",
        staticmethod(
            lambda model: GoogleModelProfile(
                supports_tools=False,
                supports_json_schema_output=False,
                supports_thinking=False,
                google_supports_strict_tool_definition=False,
            )
        ),
    )
    capabilities = project_capabilities(
        provider=LLMProvider.GOOGLE_GEMINI,
        exact_model="provider-visible-new-id",
        source_model=None,
        evidence=ProviderCapabilityEvidence(
            function_calling=CatalogFact(state="value", value=True),
            structured_response=CatalogFact(state="value", value=True),
            strict_function_schema=CatalogFact(state="value", value=True),
            reasoning=CatalogFact(state="value", value=True),
            reasoning_efforts=CatalogFact(
                state="value", value=(ModelReasoningEffort.HIGH,)
            ),
        ),
        model_developer=LLMModelDeveloper.GOOGLE,
    )
    resolution = resolve_runtime_model_profile(
        provider=LLMProvider.GOOGLE_GEMINI,
        model="provider-visible-new-id",
        profile_model=None,
        assembly_metadata=ModelAssemblyMetadata(
            model_developer=LLMModelDeveloper.GOOGLE,
            model_family=None,
            capabilities=capabilities,
        ),
        context_window=None,
        context_window_explicit=False,
        source_model=None,
    )
    assert resolution.profile["supports_tools"] is True
    assert resolution.profile["supports_json_schema_output"] is True
    assert resolution.profile["supports_thinking"] is True
    assert resolution.profile.get("google_supports_strict_tool_definition") is True
    assert resolution.normalized_capabilities is capabilities


def test_saved_compatible_strict_schema_is_not_structured_response() -> None:
    capabilities = project_capabilities(
        provider=LLMProvider.OPENROUTER,
        exact_model="publisher/model",
        source_model=None,
        evidence=ProviderCapabilityEvidence(
            function_calling=CatalogFact(state="value", value=True),
            structured_response=CatalogFact(state="value", value=True),
            strict_function_schema=CatalogFact(state="value", value=False),
        ),
        model_developer=LLMModelDeveloper.OTHER,
    )
    resolution = resolve_runtime_model_profile(
        provider=LLMProvider.OPENROUTER,
        model="publisher/model",
        profile_model=None,
        assembly_metadata=ModelAssemblyMetadata(
            model_developer=LLMModelDeveloper.OTHER,
            model_family=None,
            capabilities=capabilities,
        ),
        context_window=None,
        context_window_explicit=False,
        source_model=None,
    )
    assert resolution.profile["supports_json_schema_output"] is True
    assert resolution.profile.get("openai_supports_strict_tool_definition") is False


def test_explicit_context_overrides_only_encoding_profile() -> None:
    resolution = resolve_runtime_model_profile(
        provider=LLMProvider.XAI,
        model="account-visible",
        profile_model=None,
        assembly_metadata=None,
        context_window=9000,
        context_window_explicit=True,
        source_model=None,
    )
    assert resolution.profile["context_window"] == 9000
    assert resolution.normalized_capabilities.context_window.max_input_tokens is None


def test_opaque_bedrock_retains_saved_encoding_dialect_only() -> None:
    profile = saved_bedrock_assembly_profile(
        "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/opaque",
        metadata=ModelAssemblyMetadata(
            model_developer=LLMModelDeveloper.ANTHROPIC,
            model_family=None,
            capabilities=ModelCapabilities(),
        ),
    )
    assert profile is not None
    assert profile["bedrock_thinking_variant"] == "anthropic"
    assert profile["bedrock_supports_prompt_caching"] is True


def test_vertex_route_classification_does_not_borrow_direct_model_facts() -> None:
    assert (
        vertex_model_family("projects/p/locations/l/publishers/anthropic/models/opaque")
        == "anthropic"
    )
    caps = project_capabilities(
        provider=LLMProvider.GOOGLE_VERTEX_AI,
        exact_model="projects/p/locations/l/publishers/anthropic/models/opaque",
        source_model=None,
        evidence=None,
        model_developer=LLMModelDeveloper.ANTHROPIC,
    )
    assert caps.tool_calling.supported is False
    assert caps.reasoning.effort_levels == []


def test_unknown_function_facts_do_not_disable_the_existing_function_wire() -> None:
    caps = project_capabilities(
        provider=LLMProvider.XAI,
        exact_model="account-visible",
        source_model=None,
        evidence=None,
        model_developer=LLMModelDeveloper.XAI,
    )
    resolution = resolve_runtime_model_profile(
        provider=LLMProvider.XAI,
        model="account-visible",
        profile_model=None,
        assembly_metadata=ModelAssemblyMetadata(
            model_developer=LLMModelDeveloper.XAI,
            model_family=None,
            capabilities=caps,
        ),
        context_window=None,
        context_window_explicit=False,
        source_model=None,
    )
    assert caps.semantic_contract is not None
    assert caps.semantic_contract.function_calling.state == "unknown"
    assert resolution.profile["supports_tools"] is True


def test_anthropic_shared_encoder_gate_does_not_merge_model_facts() -> None:
    caps = project_capabilities(
        provider=LLMProvider.ANTHROPIC,
        exact_model="opaque",
        source_model=None,
        evidence=ProviderCapabilityEvidence(
            function_calling=CatalogFact(state="value", value=True),
            strict_function_schema=CatalogFact(state="value", value=True),
            structured_response=CatalogFact(state="value", value=False),
        ),
        model_developer=LLMModelDeveloper.ANTHROPIC,
    )
    resolution = resolve_runtime_model_profile(
        provider=LLMProvider.ANTHROPIC,
        model="opaque",
        profile_model=None,
        assembly_metadata=ModelAssemblyMetadata(
            model_developer=LLMModelDeveloper.ANTHROPIC,
            model_family=None,
            capabilities=caps,
        ),
        context_window=None,
        context_window_explicit=False,
        source_model=None,
    )
    # The stock Anthropic encoder uses this flag for strict tools too.
    assert resolution.profile["supports_json_schema_output"] is True
    assert caps.semantic_contract is not None
    assert caps.semantic_contract.structured_response.state == "unsupported"


type _CodecFeature = Literal["strict", "structured", "reasoning", "hosted"]
type _CodecState = Literal["conditional", "unknown", "unsupported"]
_WIRE_MODEL = "publisher/conditional"
_WIRE_OBJECT = TypeAdapter(dict[str, JsonValue])
_WIRE_TOOLS = TypeAdapter(list[dict[str, JsonValue]])
_FUNCTION_SCHEMA = {
    "type": "object",
    "properties": {"term": {"type": "string"}},
    "required": ["term"],
    "additionalProperties": False,
}


class _WireCompletedEnvelope(BaseModel):
    type: Literal["response.completed"]
    response: dict[str, JsonValue]


def _codec_snapshot(feature: _CodecFeature, state: _CodecState) -> ModelCapabilities:
    capabilities = project_capabilities(
        provider=LLMProvider.OPENROUTER,
        exact_model=_WIRE_MODEL,
        source_model=None,
        evidence=ProviderCapabilityEvidence(
            function_calling=CatalogFact(state="value", value=True),
            strict_function_schema=CatalogFact(state="value", value=True),
            structured_response=CatalogFact(state="value", value=True),
            reasoning=CatalogFact(state="value", value=True),
            reasoning_efforts=CatalogFact(
                state="value",
                value=(ModelReasoningEffort.NONE, ModelReasoningEffort.HIGH),
            ),
            reasoning_summaries=CatalogFact(state="value", value=False),
            web_search=CatalogFact(state="value", value=True),
        ),
        model_developer=LLMModelDeveloper.OTHER,
    )
    payload = capabilities.model_dump(mode="json")
    support = {
        "state": state,
        "origin": None if state == "unknown" else "explicit",
        "predicate": {
            "reasoning_efforts": ["none"],
            "function_tools": True,
        }
        if state == "conditional"
        else None,
    }
    contract = payload["semantic_contract"]
    match feature:
        case "strict":
            contract["strict_function_schema"] = support
            payload["tool_calling"]["strict_json_schema"] = (
                None if state == "unknown" else False
            )
        case "structured":
            contract["structured_response"] = support
        case "reasoning":
            contract["reasoning"]["support"] = support
            if state != "conditional":
                contract["reasoning"]["efforts"] = []
                contract["reasoning"]["completeness"] = (
                    "unknown" if state == "unknown" else "complete"
                )
            payload["reasoning"]["supported"] = False
            payload["reasoning"]["effort_levels"] = []
        case "hosted":
            contract["built_in_tools"][0]["support"] = support
            payload["built_in_tools"]["supported"] = []
    return ModelCapabilities.model_validate(payload)


def _codec_profile(capabilities: ModelCapabilities) -> ModelProfile:
    return resolve_runtime_model_profile(
        provider=LLMProvider.OPENROUTER,
        model=_WIRE_MODEL,
        profile_model=None,
        assembly_metadata=ModelAssemblyMetadata(
            model_developer=LLMModelDeveloper.OTHER,
            model_family=None,
            capabilities=capabilities,
        ),
        context_window=None,
        context_window_explicit=False,
        source_model=None,
    ).profile


@pytest.mark.parametrize("feature", ["strict", "structured", "reasoning", "hosted"])
@pytest.mark.parametrize("state", ["conditional", "unknown", "unsupported"])
def test_codec_flags_do_not_reapply_conservative_capability_views(
    feature: _CodecFeature,
    state: _CodecState,
) -> None:
    caps = _codec_snapshot(feature, state)
    before = caps.model_dump_json()
    profile = _codec_profile(caps)
    permitted = state != "unsupported"
    match feature:
        case "strict":
            assert profile.get("openai_supports_strict_tool_definition") is permitted
        case "structured":
            assert profile["supports_json_schema_output"] is permitted
            assert (
                profile.get("openai_responses_supports_json_schema_output") is permitted
            )
        case "reasoning":
            assert profile["supports_thinking"] is permitted
            assert profile.get("openai_supports_reasoning") is permitted
            assert profile.get("openai_supports_reasoning_effort_none") is (
                state == "conditional"
            )
        case "hosted":
            # Unknown hosted capabilities still do not grant tool authorization.
            assert (WebSearchTool in profile["supported_native_tools"]) is (
                state == "conditional"
            )
    assert caps.model_dump_json() == before


@pytest.mark.parametrize(
    ("feature", "state", "effort", "allowed"),
    [
        ("strict", "conditional", "none", True),
        ("strict", "conditional", "high", False),
        ("strict", "unknown", "none", True),
        ("strict", "unsupported", "none", False),
        ("reasoning", "conditional", "none", True),
        ("reasoning", "conditional", "high", False),
        ("hosted", "conditional", "none", True),
        ("hosted", "conditional", "high", False),
    ],
)
async def test_saved_conditions_reach_real_sdk_wire_without_codec_clamping(
    feature: _CodecFeature,
    state: _CodecState,
    effort: str,
    allowed: bool,
) -> None:
    """Met conditions preserve exact intent; failed ones never reach HTTP."""
    caps = _codec_snapshot(feature, state)
    lowerer = PydanticAILowerer(
        top_k=None,
        provider=LLMProvider.OPENROUTER.value,
        provider_id=LLMProvider.OPENROUTER,
        model=_WIRE_MODEL,
        tools=[
            {
                "type": "function",
                "name": "lookup",
                "description": "Synthetic lookup",
                "strict": True,
                "parameters": _FUNCTION_SCHEMA,
            }
        ],
        model_capabilities=caps,
        supported_execution_options=[],
        enabled_execution_options=[],
        reasoning_effort=effort,
        hosted_tools=(
            [BuiltinToolSpec(name="web_search", config={})]
            if feature == "hosted"
            else []
        ),
    )
    fixture = core_native_response(
        protocol="responses", model=_WIRE_MODEL, text="Synthetic codec response"
    )
    frame = next(
        item for item in fixture.body.split(b"\n\n") if b'"response.completed"' in item
    )
    reply = _WireCompletedEnvelope.model_validate_json(
        frame.split(b"data: ", 1)[1]
    ).response
    captured: list[dict[str, JsonValue]] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        captured.append(_WIRE_OBJECT.validate_json(request.content))
        return httpx2.Response(200, request=request, json=reply)

    sdk = AsyncOpenAI(
        api_key="synthetic-codec-key",
        base_url="https://provider.invalid/v1",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    )
    try:
        model = OpenAIResponsesModel(
            _WIRE_MODEL,
            provider=OpenAIProvider(openai_client=sdk),
            profile=_codec_profile(caps),
        )
        if not allowed:
            with pytest.raises(ValueError):
                request = lowerer.lower(
                    [],
                    native_replay_context=None,
                    model=_WIRE_MODEL,
                    system_prompt="Synthetic condition test",
                )
                await model.request(
                    request.messages, request.settings, request.parameters
                )
            assert captured == []
            return
        request = lowerer.lower(
            [],
            native_replay_context=None,
            model=_WIRE_MODEL,
            system_prompt="Synthetic condition test",
        )
        assert request.parameters.function_tools[0].strict is True
        await model.request(request.messages, request.settings, request.parameters)
        assert len(captured) == 1
        wire = captured[0]
        tools = _WIRE_TOOLS.validate_python(wire["tools"])
        function = next(tool for tool in tools if tool.get("name") == "lookup")
        assert function["strict"] is True
        assert function["parameters"] == _FUNCTION_SCHEMA
        assert wire["reasoning"] == {"effort": effort}
        if feature == "hosted":
            assert any(
                tool.get("type") in {"web_search", "web_search_preview"}
                for tool in tools
            )
    finally:
        await sdk.close()


def test_sampling_bridge_keeps_existing_typed_settings_normalization() -> None:
    caps = _codec_snapshot("strict", "unknown")
    request = PydanticAILowerer(
        top_k=None,
        provider=LLMProvider.OPENROUTER.value,
        provider_id=LLMProvider.OPENROUTER,
        model=_WIRE_MODEL,
        tools=[],
        model_capabilities=caps,
        supported_execution_options=[],
        enabled_execution_options=[],
        kwargs={"temperature": "0.2", "top_p": "0.9"},
    ).lower([], native_replay_context=None, model=_WIRE_MODEL)
    assert request.settings is not None
    body = _WIRE_OBJECT.validate_python(request.settings["extra_body"])
    assert body["temperature"] == 0.2
    assert body["top_p"] == 0.9


@pytest.mark.parametrize(
    "provider",
    [
        LLMProvider.XAI,
        LLMProvider.XAI_OAUTH,
        LLMProvider.OPENROUTER,
        LLMProvider.KIMI_OAUTH,
    ],
)
@pytest.mark.parametrize(
    ("state", "effort", "default_none", "override", "allowed"),
    [
        ("supported", "high", False, False, True),
        ("supported", "high", False, True, True),
        ("supported", None, False, False, True),
        ("conditional", "none", False, False, True),
        ("conditional", "high", False, False, False),
        ("conditional", None, True, False, True),
        ("conditional", None, False, False, False),
        ("unsupported", "high", False, True, False),
    ],
)
async def test_saved_sampling_survives_compatible_sdk_reasoning_filter(
    provider: LLMProvider,
    state: Literal["supported", "conditional", "unsupported"],
    effort: str | None,
    default_none: bool,
    override: bool,
    allowed: bool,
) -> None:
    """The codec sends authorized sampling with reasoning, including explicit zero."""
    model_id = "exact-sampling"
    source = decode_catalog_source(
        json.dumps(
            {
                f"{provider.value}/{model_id}": {
                    "litellm_provider": provider.value,
                    "mode": "chat",
                    "supports_reasoning": True,
                    "reasoning_effort_levels": ["none", "high"],
                    "supports_sampling_params": True,
                }
            }
        ).encode()
    ).models[0]
    caps = project_capabilities(
        provider=provider,
        exact_model=model_id,
        source_model=source,
        evidence=ProviderCapabilityEvidence(
            default_reasoning_effort=CatalogFact(
                state="value" if default_none else "absent",
                value=ModelReasoningEffort.NONE if default_none else None,
            )
        ),
        model_developer=None,
    )
    payload = caps.model_dump(mode="json")
    for key in ("temperature", "top_p"):
        payload["semantic_contract"]["parameters"][key] = {
            "state": state,
            "origin": "explicit",
            "predicate": {"reasoning_efforts": ["none"], "function_tools": None}
            if state == "conditional"
            else None,
        }
        payload["parameters"][key] = state == "supported"
    caps = ModelCapabilities.model_validate(payload)
    saved = caps.model_dump_json()
    bodies: list[dict[str, JsonValue]] = []
    chat = provider == LLMProvider.KIMI_OAUTH

    def handle(request: httpx2.Request) -> httpx2.Response:
        bodies.append(_WIRE_OBJECT.validate_json(request.content))
        if chat:
            reply = {
                "id": "chatcmpl_sampling",
                "object": "chat.completion",
                "created": 1,
                "model": model_id,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        else:
            fixture = core_native_response(
                protocol="responses", model=model_id, text="ok"
            )
            frame = next(
                item
                for item in fixture.body.split(b"\n\n")
                if b'"response.completed"' in item
            )
            reply = _WireCompletedEnvelope.model_validate_json(
                frame.split(b"data: ", 1)[1]
            ).response
        return httpx2.Response(200, request=request, json=reply)

    sdk = AsyncOpenAI(
        api_key="synthetic-sampling-key",
        base_url="https://provider.invalid/v1",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    )
    profile = resolve_runtime_model_profile(
        provider=provider,
        model=model_id,
        profile_model=None,
        assembly_metadata=ModelAssemblyMetadata(
            model_developer=None, model_family=None, capabilities=caps
        ),
        context_window=None,
        context_window_explicit=False,
        source_model=None,
    ).profile
    assert profile.get("openai_supports_reasoning") is True
    lowerer = PydanticAILowerer(
        top_k=None,
        provider=provider.value,
        provider_id=provider,
        model=model_id,
        tools=[],
        model_capabilities=caps,
        supported_execution_options=[],
        enabled_execution_options=[],
        reasoning_effort=effort,
        temperature=0.2,
        top_p=0.9,
        kwargs={
            "extra_body": {
                "vendor_extension": "kept",
                **({"temperature": 0.0} if override else {}),
            }
        },
    )
    try:
        if not allowed:
            with pytest.raises(ValueError):
                lowerer.lower(
                    [],
                    native_replay_context=None,
                    model=model_id,
                    system_prompt="Sampling test",
                )
            assert bodies == []
            return
        request = lowerer.lower(
            [],
            native_replay_context=None,
            model=model_id,
            system_prompt="Sampling test",
        )
        assert request.settings is not None
        assert "temperature" not in request.settings
        assert "top_p" not in request.settings
        public_model = (
            OpenAIChatModel(
                model_id, provider=OpenAIProvider(openai_client=sdk), profile=profile
            )
            if chat
            else OpenAIResponsesModel(
                model_id, provider=OpenAIProvider(openai_client=sdk), profile=profile
            )
        )
        await public_model.request(
            request.messages, request.settings, request.parameters
        )
        assert len(bodies) == 1
        assert bodies[0]["temperature"] == (0.0 if override else 0.2)
        assert bodies[0]["top_p"] == 0.9
        assert bodies[0]["vendor_extension"] == "kept"
        if effort is not None:
            assert (
                _WIRE_OBJECT.validate_python(bodies[0]["reasoning"])["effort"] == effort
            )
        assert caps.model_dump_json() == saved
    finally:
        await sdk.close()
