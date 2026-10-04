"""Selected sampling controls survive the actual installed provider codecs."""

import dataclasses

import httpx2
import pytest
from google.oauth2.credentials import Credentials
from pydantic import JsonValue, TypeAdapter
from pydantic_ai.profiles import merge_profile
from pydantic_ai.profiles.anthropic import AnthropicModelProfile
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.bedrock import BedrockModelProfile, BedrockProvider

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.core.model_capability_contract import (
    CapabilitySupport,
    SupportPredicate,
    SupportState,
)
from azents.core.model_capability_projection import project_capabilities
from azents.engine.events.openai_responses import OpenAIResponsesLowerer
from azents.engine.events.pydantic_ai_adapter import PydanticAIModelAdapter
from azents.engine.events.pydantic_ai_adapter_test import (
    context_for_test,
    watchdog_for_test,
)
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.pydantic_ai_types import PydanticAIRequest
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.model_stream import ModelStreamTimeoutPolicy
from azents.engine.model_stream_test import ControlledClock
from azents.engine.provider_errors import SDK_PROVIDER_ERRORS, map_model_provider_error
from azents.engine.providers.bedrock_cache_compatibility_test import collect_request
from azents.engine.providers.bedrock_lifecycle_test import bedrock_call, nominal_body
from azents.engine.providers.model_factory import (
    ProviderModelFactory,
    ProviderTransports,
)
from azents.engine.providers.observation_state import InternalModelExecutionError
from azents.testing.provider_native_envelopes import (
    NativeFixtureProtocol,
    core_native_response,
)

_OBJECT = TypeAdapter(dict[str, JsonValue])


def _request(
    *,
    provider: LLMProvider,
    model: str,
    developer: LLMModelDeveloper,
    capabilities: ModelCapabilities,
    top_k: int | None,
    options: dict[str, object] | None,
) -> PydanticAIRequest:
    request = PydanticAILowerer(
        provider=provider.value,
        provider_id=provider,
        model=model,
        model_developer=developer,
        model_capabilities=capabilities,
        tools=None,
        supported_execution_options=[],
        enabled_execution_options=[],
        top_k=top_k,
        temperature=0.0,
        top_p=0.35,
        kwargs=options,
    ).lower(
        [],
        native_replay_context=None,
        model=model,
        system_prompt="Synthetic sampling contract",
    )
    return dataclasses.replace(
        request,
        assembly_metadata=ModelAssemblyMetadata(
            model_developer=developer,
            model_family=None,
            capabilities=capabilities,
        ),
    )


@pytest.mark.parametrize(
    ("provider", "model", "developer", "protocol"),
    [
        (
            LLMProvider.GOOGLE_GEMINI,
            "opaque-google",
            LLMModelDeveloper.GOOGLE,
            "google",
        ),
        (
            LLMProvider.GOOGLE_VERTEX_AI,
            "projects/synthetic-project/locations/us-central1/publishers/google/models/opaque-google",
            LLMModelDeveloper.GOOGLE,
            "google",
        ),
        (
            LLMProvider.ANTHROPIC,
            "opaque-anthropic",
            LLMModelDeveloper.ANTHROPIC,
            "anthropic",
        ),
        (
            LLMProvider.GOOGLE_VERTEX_AI,
            "projects/synthetic-project/locations/us-central1/publishers/anthropic/models/claude-test",
            LLMModelDeveloper.ANTHROPIC,
            "anthropic",
        ),
    ],
)
@pytest.mark.parametrize("top_k", [None, 37])
@pytest.mark.parametrize("historical", [False, True])
async def test_actual_factory_sdk_sends_all_selected_sampling_controls(
    provider: LLMProvider,
    model: str,
    developer: LLMModelDeveloper,
    protocol: NativeFixtureProtocol,
    top_k: int | None,
    historical: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        AnthropicProvider,
        "model_profile",
        staticmethod(
            lambda _: AnthropicModelProfile(anthropic_disallows_sampling_settings=True)
        ),
    )
    capabilities = (
        ModelCapabilities()
        if historical
        else project_capabilities(
            provider=provider,
            exact_model=model,
            source_model=None,
            evidence=None,
            model_developer=developer,
        )
    )
    before = capabilities.model_dump_json()
    request = _request(
        provider=provider,
        model=model,
        developer=developer,
        capabilities=capabilities,
        top_k=top_k,
        options=None,
    )
    wires: list[dict[str, JsonValue]] = []

    def respond(wire: httpx2.Request) -> httpx2.Response:
        wires.append(_OBJECT.validate_json(wire.content))
        envelope = core_native_response(
            protocol=protocol, model=model, text="Synthetic output"
        )
        return httpx2.Response(
            200,
            headers={"content-type": envelope.content_type},
            content=envelope.body,
        )

    adapter = PydanticAIModelAdapter(
        factory=ProviderModelFactory(
            provider=provider,
            credential_kwargs={
                "api_key": "synthetic-key",
                "vertex_project": "synthetic-project",
                "vertex_location": "us-central1",
                "vertex_credentials": "{}",
            },
            sdk_failure_mapper=map_model_provider_error,
            sdk_error_types=SDK_PROVIDER_ERRORS,
            transports=ProviderTransports(
                httpx2=httpx2.MockTransport(respond),
                google_credentials=Credentials(token="synthetic-token"),
            ),
        )
    )
    clock = ControlledClock()
    policy = ModelStreamTimeoutPolicy(
        connect_timeout_seconds=2,
        parsed_event_idle_timeout_seconds=50,
        absolute_attempt_timeout_seconds=100,
    )
    events = [
        event
        async for event in adapter.stream(
            request,
            watchdog=watchdog_for_test(clock, policy),
            timeout_policy=policy,
            call_context=dataclasses.replace(
                context_for_test(), provider=provider.value, model=model
            ),
        )
    ]
    assert any(event.response is not None for event in events)
    assert len(wires) == 1
    config = wires[0]["generationConfig"] if protocol == "google" else wires[0]
    assert isinstance(config, dict)
    assert config["temperature"] == 0.0
    assert config["topP" if protocol == "google" else "top_p"] == 0.35
    key = "topK" if protocol == "google" else "top_k"
    if top_k is None:
        assert key not in config or config[key] is None
    else:
        assert config[key] == top_k
    assert capabilities.model_dump_json() == before
    await adapter.close()


@pytest.mark.parametrize(
    ("model", "developer", "expected"),
    [
        (
            "anthropic.claude-3-haiku-20240307-v1:0",
            LLMModelDeveloper.ANTHROPIC,
            {"top_k": 37},
        ),
        (
            "amazon.nova-micro-v1:0",
            LLMModelDeveloper.OTHER,
            {"inferenceConfig": {"topK": 37}},
        ),
        (
            "arn:aws:bedrock:us-east-1:123456789012:application-inference-profile/opaque",
            LLMModelDeveloper.ANTHROPIC,
            {"top_k": 37},
        ),
    ],
)
@pytest.mark.parametrize("historical", [False, True])
@pytest.mark.parametrize("raw_override", [False, True])
async def test_actual_bedrock_wrapper_sends_family_top_k_and_sampling(
    model: str,
    developer: LLMModelDeveloper,
    expected: dict[str, object],
    historical: bool,
    raw_override: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = BedrockProvider.model_profile
    monkeypatch.setattr(
        BedrockProvider,
        "model_profile",
        staticmethod(
            lambda value: merge_profile(
                original(value),
                AnthropicModelProfile(anthropic_disallows_sampling_settings=True),
                BedrockModelProfile(bedrock_disallows_sampling_settings=True),
            )
        ),
    )
    additional: dict[str, object] = {"marker": "retained"}
    if raw_override:
        expected = (
            {"top_k": 41} if "top_k" in expected else {"inferenceConfig": {"topK": 41}}
        )
        additional.update(expected)
    request = _request(
        provider=LLMProvider.AWS_BEDROCK,
        model=model,
        developer=developer,
        capabilities=ModelCapabilities()
        if historical
        else project_capabilities(
            provider=LLMProvider.AWS_BEDROCK,
            exact_model=model,
            source_model=None,
            evidence=None,
            model_developer=developer,
        ),
        top_k=37,
        options={"bedrock_additional_model_requests_fields": additional},
    )
    call = bedrock_call(model=model, chunks=[nominal_body(model)])
    events = await collect_request(call, request)
    assert any(event.response is not None for event in events)
    wire = call.boundary.bodies[0]
    assert wire["additionalModelRequestFields"] == {"marker": "retained", **expected}
    config = wire["inferenceConfig"]
    assert isinstance(config, dict)
    assert config["temperature"] == 0.0
    assert config["topP"] == 0.35


async def test_bedrock_without_top_k_mapping_fails_before_http() -> None:
    model = "meta.llama3-8b-instruct-v1:0"
    request = _request(
        provider=LLMProvider.AWS_BEDROCK,
        model=model,
        developer=LLMModelDeveloper.META,
        capabilities=ModelCapabilities(),
        top_k=37,
        options=None,
    )
    call = bedrock_call(model=model, chunks=[])
    with pytest.raises(InternalModelExecutionError) as error:
        await collect_request(call, request)
    assert error.value.origin_type == "ValueError"
    assert not call.boundary.paths


@pytest.mark.parametrize("provider", [LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH])
def test_native_selected_top_k_is_explicitly_unrepresentable(
    provider: LLMProvider,
) -> None:
    lowerer = OpenAIResponsesLowerer(
        provider=provider.value,
        provider_id=provider,
        model="opaque-native",
        supported_execution_options=[],
        enabled_execution_options=[],
        top_k=37,
    )
    with pytest.raises(ValueError, match="top-k has no mapping"):
        lowerer.lower([], native_replay_context=None, model="opaque-native")


@pytest.mark.parametrize(
    "provider",
    [
        LLMProvider.XAI,
        LLMProvider.XAI_OAUTH,
        LLMProvider.OPENROUTER,
        LLMProvider.KIMI_OAUTH,
    ],
)
def test_compatible_codec_cannot_silently_drop_canonical_top_k(
    provider: LLMProvider,
) -> None:
    with pytest.raises(ValueError, match="top-k has no mapping"):
        _request(
            provider=provider,
            model="opaque-compatible",
            developer=LLMModelDeveloper.OTHER,
            capabilities=ModelCapabilities(),
            top_k=37,
            options=None,
        )


@pytest.mark.parametrize(
    ("state", "requires_functions"),
    [
        ("supported", False),
        ("conditional", False),
        ("conditional", True),
        ("unsupported", False),
    ],
)
def test_selected_top_k_keeps_saved_support_predicates(
    state: SupportState, requires_functions: bool
) -> None:
    capabilities = project_capabilities(
        provider=LLMProvider.GOOGLE_GEMINI,
        exact_model="opaque-google",
        source_model=None,
        evidence=None,
        model_developer=LLMModelDeveloper.GOOGLE,
    )
    contract = capabilities.semantic_contract
    assert contract is not None
    support = (
        CapabilitySupport(
            state="conditional",
            origin="explicit",
            predicate=SupportPredicate(
                reasoning_efforts=None, function_tools=requires_functions
            ),
        )
        if state == "conditional"
        else CapabilitySupport(state=state, origin="explicit", predicate=None)
    )
    capabilities.semantic_contract = contract.model_copy(
        update={"parameters": contract.parameters.model_copy(update={"top_k": support})}
    )
    if state == "unsupported" or state == "conditional" and requires_functions:
        with pytest.raises(ValueError, match="top-k"):
            _request(
                provider=LLMProvider.GOOGLE_GEMINI,
                model="opaque-google",
                developer=LLMModelDeveloper.GOOGLE,
                capabilities=capabilities,
                top_k=37,
                options=None,
            )
    else:
        request = _request(
            provider=LLMProvider.GOOGLE_GEMINI,
            model="opaque-google",
            developer=LLMModelDeveloper.GOOGLE,
            capabilities=capabilities,
            top_k=37,
            options=None,
        )
        assert request.settings["top_k"] == 37


async def test_actual_chat_codec_rejects_top_k_after_historical_developer_hint() -> (
    None
):
    request = _request(
        provider=LLMProvider.KIMI_OAUTH,
        model="opaque-kimi",
        developer=LLMModelDeveloper.ANTHROPIC,
        capabilities=ModelCapabilities(),
        top_k=37,
        options=None,
    )
    assert request.settings["top_k"] == 37
    attempts: list[httpx2.Request] = []

    def poison(wire: httpx2.Request) -> httpx2.Response:
        attempts.append(wire)
        pytest.fail("An unrepresentable canonical top-k reached HTTP.")

    adapter = PydanticAIModelAdapter(
        factory=ProviderModelFactory(
            provider=LLMProvider.KIMI_OAUTH,
            credential_kwargs={"api_key": "synthetic-key"},
            sdk_failure_mapper=map_model_provider_error,
            sdk_error_types=SDK_PROVIDER_ERRORS,
            transports=ProviderTransports(httpx2=httpx2.MockTransport(poison)),
        )
    )
    clock = ControlledClock()
    policy = ModelStreamTimeoutPolicy(
        connect_timeout_seconds=2,
        parsed_event_idle_timeout_seconds=50,
        absolute_attempt_timeout_seconds=100,
    )
    with pytest.raises(InternalModelExecutionError) as error:
        _ = [
            event
            async for event in adapter.stream(
                request,
                watchdog=watchdog_for_test(clock, policy),
                timeout_policy=policy,
                call_context=dataclasses.replace(
                    context_for_test(), provider="kimi_oauth", model=request.model
                ),
            )
        ]
    assert error.value.origin_type == "ValueError"
    assert not attempts
    assert not adapter.active
    await adapter.close()
