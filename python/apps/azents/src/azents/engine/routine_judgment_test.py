"""Routine judgment through owned adapters and the official SDK wire boundary."""

import dataclasses
import datetime
import json

import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic import TypeAdapter

from azents.core.enums import EventKind, LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.core.model_capability_projection import compile_stored_choice
from azents.core.model_catalog_source import decode_catalog_source
from azents.core.model_provider_declarations import decode_stored_provider_evidence
from azents.core.openai_client_config import OpenAIResponsesClientConfig
from azents.core.routine_judgment_test import JUDGMENT_TIME, candidate
from azents.engine.events.openai_responses import (
    OpenAIResponsesClient,
    OpenAIResponsesRequest,
    OpenAISDKResponsesClient,
)
from azents.engine.events.types import Event, UserMessagePayload
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.model_factories import get_model_sdk_factories
from azents.engine.model_stream import ModelStreamCallContext
from azents.engine.providers.model_factory import (
    ProviderModelFactory,
    ProviderTransports,
)
from azents.engine.routine_judgment import (
    RoutineJudgmentModel,
    RoutineJudgmentRequest,
    call_routine_judgment,
    prepare_routine_judgment_request,
)
from azents.engine.run.errors import ModelCallError
from azents.testing.model_stream import make_test_model_stream_watchdog
from azents.testing.provider_native_envelopes import (
    NativeFixtureProtocol,
    core_native_response,
)

_BODY = TypeAdapter(dict[str, object])
_VALID = '{"decisions":[{"routine_id":"routine-a","act":true}]}'


def selection(provider: LLMProvider) -> RoutineJudgmentModel:
    """Use one saved ordinary selection without an alternate judgment setting."""
    return RoutineJudgmentModel(
        provider=provider,
        model="fixture",
        assembly=ModelAssemblyMetadata(
            model_developer=None,
            model_family=None,
            capabilities=ModelCapabilities(structured_response=True),
        ),
        temperature=None,
        max_output_tokens=None,
        top_p=None,
        top_k=None,
        stop=None,
        reasoning_effort=None,
        supported_execution_options=(),
        enabled_execution_options=(),
    )


def history() -> list[Event]:
    """Two independent messages must remain in the real provider request."""
    return [
        Event(
            id=str(index) * 32,
            session_id="judgment-session",
            kind=EventKind.USER_MESSAGE,
            payload=UserMessagePayload(sender_user_id=None, content=text),
            created_at=datetime.datetime(2026, 10, 18, tzinfo=datetime.UTC),
        )
        for index, text in enumerate(
            (
                "Watch official launch announcements.",
                "Only notify about confirmed news.",
            ),
            start=1,
        )
    ]


def context(model: RoutineJudgmentModel) -> ModelStreamCallContext:
    return ModelStreamCallContext(
        call_kind="routine_judgment",
        provider=model.provider.value,
        provider_integration_id="synthetic-integration",
        model=model.model,
        session_id="judgment-session",
        run_id=None,
        attempt_number=1,
        check_stop=None,
    )


def prepared(model: RoutineJudgmentModel) -> RoutineJudgmentRequest:
    return prepare_routine_judgment_request(
        selection=model,
        transcript=history(),
        system_prompt="Ordinary Session context, not a flattened helper prompt.",
        candidates=(candidate(),),
        current_time=JUDGMENT_TIME,
        session_id="judgment-session",
        native_replay_context="canonical-history",
        model_file_resolver=None,
    )


def test_openai_endpoint_configuration_is_not_a_structured_request_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment client defaults cannot block a credential-free request intent."""
    monkeypatch.setenv("AZ_OPENAI_BASE_URL", "https://fixture.invalid/v1")
    request = prepared(selection(LLMProvider.OPENAI))
    assert isinstance(request, OpenAIResponsesRequest)
    assert request.tools == []
    text = request.options["text"]
    assert text is not None
    formatting = text["format"]
    assert isinstance(formatting, dict) and formatting["type"] == "json_schema"
    assert "base_url" not in request.options
    assert "api_base" not in request.options
    assert "api_key" not in request.options


@pytest.mark.parametrize(
    ("provider", "protocol", "model_name"),
    [
        (LLMProvider.OPENAI, "responses", "fixture"),
        (LLMProvider.CHATGPT_OAUTH, "responses", "gpt-6.1-terra"),
        (LLMProvider.CHATGPT_OAUTH, "responses", "new-account-model"),
        (LLMProvider.OPENROUTER, "responses", "fixture"),
        (LLMProvider.XAI, "responses", "fixture"),
        (LLMProvider.XAI_OAUTH, "responses", "fixture"),
        (LLMProvider.ANTHROPIC, "anthropic", "fixture"),
        (LLMProvider.GOOGLE_GEMINI, "google", "fixture"),
        (LLMProvider.KIMI_OAUTH, "chat_completions", "fixture"),
    ],
)
async def test_actual_sdk_wire_preserves_history_schema_usage_and_owned_cleanup(
    provider: LLMProvider, protocol: NativeFixtureProtocol, model_name: str
) -> None:
    captured: list[dict[str, object]] = []
    clients: list[httpx2.AsyncClient] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        captured.append(_BODY.validate_json(request.content))
        response = core_native_response(
            protocol=protocol, model=model_name, text=_VALID
        )
        return httpx2.Response(
            200, headers={"content-type": response.content_type}, content=response.body
        )

    defaults = get_model_sdk_factories()
    transport = httpx2.MockTransport(respond)

    def openai_factory(*, config: OpenAIResponsesClientConfig) -> OpenAIResponsesClient:
        client = httpx2.AsyncClient(transport=transport)
        clients.append(client)
        sdk = AsyncOpenAI(
            api_key=config.api_key,
            base_url="https://fixture.invalid/v1",
            default_headers=config.default_headers,
            max_retries=0,
            http_client=client,
        )
        return OpenAISDKResponsesClient(sdk, websocket_headers=config.default_headers)

    def provider_factory(
        *, provider: LLMProvider, credential_kwargs: dict[str, object]
    ) -> ProviderModelFactory:
        factory = defaults.provider_model(
            provider=provider, credential_kwargs=credential_kwargs
        )
        factory.transports = ProviderTransports(httpx2=transport)
        return factory

    model = dataclasses.replace(selection(provider), model=model_name)
    if provider is LLMProvider.CHATGPT_OAUTH:
        evidence = decode_stored_provider_evidence(
            provider=provider,
            provider_metadata={
                "input_modalities": ["text", "image"],
                "tool_mode": "code_mode_only",
            },
            capability_evidence=None,
        )
        compiled = compile_stored_choice(
            provider=provider,
            exact_model=model_name,
            source_model=decode_catalog_source(
                json.dumps(
                    {
                        f"chatgpt/{model_name}": {
                            "litellm_provider": "chatgpt",
                            "mode": "responses",
                            "supports_response_schema": True,
                        }
                    }
                ).encode()
            ).models[0],
            evidence=evidence,
            model_developer=LLMModelDeveloper.OPENAI,
        )
        model = dataclasses.replace(
            model,
            assembly=ModelAssemblyMetadata(
                model_developer=LLMModelDeveloper.OPENAI,
                model_family=None,
                capabilities=compiled.capabilities,
            ),
        )
    watchdog = make_test_model_stream_watchdog()
    request = prepare_routine_judgment_request(
        selection=model,
        transcript=history(),
        system_prompt="Ordinary Session context, not a flattened helper prompt.",
        candidates=(candidate(),),
        current_time=JUDGMENT_TIME,
        session_id="judgment-session",
        native_replay_context="canonical-history",
        model_file_resolver=None,
    )
    result = await call_routine_judgment(
        judgment_id="judgment-operation",
        candidates=(candidate(),),
        selection=model,
        request=request,
        sdk_factories=dataclasses.replace(
            defaults, openai_responses=openai_factory, provider_model=provider_factory
        ),
        credential_kwargs={
            "api_key": "synthetic-unused",
            "base_url": "https://fixture.invalid/v1",
        },
        pricing=None,
        watchdog=watchdog,
        timeout_policy=watchdog.resolve_policy(
            provider=provider.value, model=model_name, inference_profile=None
        ),
        call_context=context(model),
    )
    assert result.status == "completed"
    assert result.decision is not None and result.decision.decisions[0].act
    assert result.usage is not None and result.usage.total_tokens > 0
    assert len(captured) == 1
    if protocol == "responses":
        assert captured[0]["model"] == model_name
    wire = str(captured[0])
    assert "Watch official launch announcements." in wire
    assert "Only notify about confirmed news." in wire
    assert "Current time: 2026-10-19T09:58:00+00:00" in wire
    assert "requested interval has not elapsed, set act=false" in wire
    assert "routine_id" in wire and "boolean" in wire
    match protocol:
        case "responses":
            assert "json_schema" in str(captured[0]["text"])
        case "anthropic":
            assert "json_schema" in str(captured[0]["output_config"])
        case "google":
            assert "responseJsonSchema" in str(captured[0]["generationConfig"])
        case "chat_completions":
            assert "json_schema" in str(captured[0]["response_format"])
        case _:
            raise AssertionError(f"Unexpected protocol: {protocol}")
    assert not captured[0].get("tools")
    assert all(client.is_closed for client in clients)
    assert "run_id" not in result.model_dump()


@pytest.mark.parametrize(
    "text",
    [
        "not JSON",
        '{"decisions":[]}',
        '{"decisions":[{"routine_id":"foreign","act":true}]}',
    ],
)
async def test_invalid_completed_output_keeps_usage_and_is_not_no_action(
    text: str,
) -> None:
    clients: list[httpx2.AsyncClient] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        response = core_native_response(
            protocol="responses", model="fixture", text=text
        )
        return httpx2.Response(
            200, headers={"content-type": response.content_type}, content=response.body
        )

    def factory(*, config: OpenAIResponsesClientConfig) -> OpenAIResponsesClient:
        client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
        clients.append(client)
        return OpenAISDKResponsesClient(
            AsyncOpenAI(api_key="synthetic", http_client=client, max_retries=0),
            websocket_headers=None,
        )

    model = selection(LLMProvider.OPENAI)
    request = prepare_routine_judgment_request(
        selection=model,
        transcript=history(),
        system_prompt="Session context.",
        candidates=(candidate(),),
        current_time=JUDGMENT_TIME,
        session_id="judgment-session",
        native_replay_context=None,
        model_file_resolver=None,
    )
    watchdog = make_test_model_stream_watchdog()
    result = await call_routine_judgment(
        judgment_id="invalid-output",
        candidates=(candidate(),),
        selection=model,
        request=request,
        sdk_factories=dataclasses.replace(
            get_model_sdk_factories(), openai_responses=factory
        ),
        credential_kwargs={},
        pricing=None,
        watchdog=watchdog,
        timeout_policy=watchdog.resolve_policy(
            provider="openai", model="fixture", inference_profile=None
        ),
        call_context=context(model),
    )
    assert result.status == "failed"
    assert result.decision is None
    assert result.usage is not None
    assert result.error == "The model returned invalid Routine judgment output."
    assert all(client.is_closed for client in clients)


async def test_incomplete_native_stream_is_not_accepted_and_client_is_closed() -> None:
    clients: list[httpx2.AsyncClient] = []

    def factory(*, config: OpenAIResponsesClientConfig) -> OpenAIResponsesClient:
        def respond(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=(
                    b'data: {"type":"response.output_text.delta","sequence_number":0,'
                    b'"item_id":"m","output_index":0,"content_index":0,'
                    b'"delta":"partial"}\n\n'
                ),
            )

        client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
        clients.append(client)
        return OpenAISDKResponsesClient(
            AsyncOpenAI(api_key="synthetic", http_client=client, max_retries=0),
            websocket_headers=None,
        )

    model = selection(LLMProvider.OPENAI)
    request = prepare_routine_judgment_request(
        selection=model,
        transcript=history(),
        system_prompt="Session context.",
        candidates=(candidate(),),
        current_time=JUDGMENT_TIME,
        session_id="judgment-session",
        native_replay_context=None,
        model_file_resolver=None,
    )
    watchdog = make_test_model_stream_watchdog()
    with pytest.raises(ModelCallError):
        await call_routine_judgment(
            judgment_id="incomplete",
            candidates=(candidate(),),
            selection=model,
            request=request,
            sdk_factories=dataclasses.replace(
                get_model_sdk_factories(), openai_responses=factory
            ),
            credential_kwargs={},
            pricing=None,
            watchdog=watchdog,
            timeout_policy=watchdog.resolve_policy(
                provider="openai", model="fixture", inference_profile=None
            ),
            call_context=context(model),
        )
    assert all(client.is_closed for client in clients)
