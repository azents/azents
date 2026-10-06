"""Captured model operations obey the foreground request and native SDK contracts."""

import dataclasses

import httpx2
import pytest
from pydantic import TypeAdapter
from pydantic_ai.messages import ModelMessagesTypeAdapter

from azents.core.agent import SelectableModelCandidate
from azents.core.enums import EventKind, LLMModelDeveloper, LLMProvider
from azents.core.openai_client_config import OpenAIResponsesClientConfig
from azents.engine.context.compaction import summarize_text_with_model
from azents.engine.events.model_messages import transient_model_message
from azents.engine.events.openai_responses import (
    OpenAIResponsesLowerer,
    OpenAIResponsesRequest,
)
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.pydantic_ai_types import PydanticAIRequest
from azents.engine.events.types import UserMessagePayload
from azents.engine.model_factories import get_model_sdk_factories
from azents.engine.provider_model_operation import bind_provider_model_operation
from azents.engine.providers.model_factory import (
    ProviderModelFactory,
    ProviderTransports,
)
from azents.engine.providers.model_profiles import protocol_for_provider
from azents.services.historical_memory.preparation import (
    generate_historical_memory_with_model,
)
from azents.services.historical_memory.preparation_test import _SummaryClient
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)
from azents.testing.model_stream import make_test_model_stream_watchdog
from azents.testing.provider_native_envelopes import core_native_response

_ROUTES = [
    (LLMProvider.OPENAI, "gpt-4o", LLMModelDeveloper.OPENAI),
    (LLMProvider.CHATGPT_OAUTH, "gpt-4o", LLMModelDeveloper.OPENAI),
    (LLMProvider.ANTHROPIC, "claude-sonnet-4-5", LLMModelDeveloper.ANTHROPIC),
    (LLMProvider.GOOGLE_GEMINI, "gemini-2.5-flash", LLMModelDeveloper.GOOGLE),
    (LLMProvider.GOOGLE_VERTEX_AI, "gemini-2.5-flash", LLMModelDeveloper.GOOGLE),
    (
        LLMProvider.AWS_BEDROCK,
        "anthropic.claude-sonnet-4-5",
        LLMModelDeveloper.ANTHROPIC,
    ),
    (
        LLMProvider.OPENROUTER,
        "anthropic/claude-sonnet-4.5",
        LLMModelDeveloper.ANTHROPIC,
    ),
    (LLMProvider.XAI, "grok-4", LLMModelDeveloper.XAI),
    (LLMProvider.XAI_OAUTH, "grok-4", LLMModelDeveloper.XAI),
]


@pytest.mark.parametrize("provider,model,developer", _ROUTES)
@pytest.mark.parametrize(
    "selected_tokens,model_limit", [(None, None), (20000, None), (20000, 8000)]
)
async def test_internal_text_request_matches_foreground_selected_settings(
    provider: LLMProvider,
    model: str,
    developer: LLMModelDeveloper,
    selected_tokens: int | None,
    model_limit: int | None,
) -> None:
    selection = make_test_model_selection(
        provider=provider, model_identifier=model, model_developer=developer
    )
    selection.normalized_capabilities.parameters.max_output_tokens = (
        selected_tokens is not None
    )
    selection.normalized_capabilities.context_window.max_output_tokens = model_limit
    settings = make_test_model_settings().model_copy(
        update={"max_output_tokens": selected_tokens}
    )
    client = _SummaryClient("Unused stream fixture")

    def native_factory(*, config: OpenAIResponsesClientConfig) -> _SummaryClient:
        return client

    operation = bind_provider_model_operation(
        selection=selection,
        settings=settings,
        credential_kwargs={"api_key": "synthetic-unused"},
        effective_input_tokens=128000,
        sdk_factories=dataclasses.replace(
            get_model_sdk_factories(), openai_responses=native_factory
        ),
        watchdog=make_test_model_stream_watchdog(),
        websocket_enabled=False,
        transport_state=None,
    )
    messages = [
        transient_model_message(
            EventKind.USER_MESSAGE,
            UserMessagePayload(sender_user_id=None, content="Source evidence"),
        )
    ]
    effective_tokens = (
        min(selected_tokens, model_limit)
        if selected_tokens is not None and model_limit is not None
        else selected_tokens
    )
    main_lowerer = (
        OpenAIResponsesLowerer
        if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}
        else PydanticAILowerer
    )
    expected = main_lowerer(
        provider=provider.value,
        provider_id=provider,
        model=model,
        tools=None,
        supported_execution_options=selection.supported_execution_options,
        enabled_execution_options=(),
        top_k=None,
        max_output_tokens=effective_tokens,
        model_developer=developer,
        model_capabilities=selection.normalized_capabilities,
    ).lower(
        messages,
        model=model,
        native_replay_context=None,
        system_prompt="Summarize the source",
    )
    try:
        prepared = operation.prepare(
            messages,
            None,
            system_prompt="Summarize the source",
            output_tokens=operation.max_output_tokens,
        )
        assert operation.max_output_tokens == effective_tokens
        if isinstance(prepared.request, OpenAIResponsesRequest):
            assert prepared.request == expected
        else:
            assert isinstance(expected, PydanticAIRequest)
            assert prepared.request.settings == expected.settings
            assert prepared.request.parameters == expected.parameters
            exclude = {"__all__": {"parts": {"__all__": {"timestamp"}}}}
            assert ModelMessagesTypeAdapter.dump_python(
                prepared.request.messages, mode="json", exclude=exclude
            ) == ModelMessagesTypeAdapter.dump_python(
                expected.messages, mode="json", exclude=exclude
            )
    finally:
        await operation.close()


@pytest.mark.parametrize(
    "provider,model,developer",
    [
        (LLMProvider.ANTHROPIC, "claude-sonnet-4-5", LLMModelDeveloper.ANTHROPIC),
        (LLMProvider.GOOGLE_GEMINI, "gemini-2.5-flash", LLMModelDeveloper.GOOGLE),
        (
            LLMProvider.OPENROUTER,
            "anthropic/claude-sonnet-4.5",
            LLMModelDeveloper.ANTHROPIC,
        ),
        (LLMProvider.XAI, "grok-4", LLMModelDeveloper.XAI),
    ],
)
@pytest.mark.parametrize("operation", ["preparation", "compaction"])
async def test_text_task_consumes_official_sdk_native_summary(
    provider: LLMProvider,
    model: str,
    developer: LLMModelDeveloper,
    operation: str,
) -> None:
    captured: list[dict[str, object]] = []
    urls: list[str] = []
    body_adapter = TypeAdapter(dict[str, object])
    envelope = core_native_response(
        protocol=protocol_for_provider(provider=provider, model=model),
        model=model,
        text='{"summary":"Observed native source evidence"}'
        if operation == "preparation"
        else "Observed native source evidence",
    )

    def respond(request: httpx2.Request) -> httpx2.Response:
        captured.append(body_adapter.validate_json(request.content))
        urls.append(str(request.url))
        return httpx2.Response(
            200, headers={"content-type": envelope.content_type}, content=envelope.body
        )

    defaults = get_model_sdk_factories()
    transport = httpx2.MockTransport(respond)

    def factory(
        *, provider: LLMProvider, credential_kwargs: dict[str, object]
    ) -> ProviderModelFactory:
        result = defaults.provider_model(
            provider=provider, credential_kwargs=credential_kwargs
        )
        result.transports = ProviderTransports(httpx2=transport)
        return result

    selection = make_test_model_selection(
        provider=provider, model_identifier=model, model_developer=developer
    )
    settings = make_test_model_settings()
    factories = dataclasses.replace(defaults, provider_model=factory)
    credentials: dict[str, object] = {
        "api_key": "synthetic-unused",
        "base_url": "https://synthetic.invalid/v1",
    }
    if operation == "preparation":
        result = await generate_historical_memory_with_model(
            selection=selection,
            settings=settings,
            credential_kwargs=credentials,
            effective_input_tokens=128000,
            sdk_factories=factories,
            watchdog=make_test_model_stream_watchdog(),
            websocket_enabled=False,
            source_text="Observed source evidence",
            source_session_id="s" * 32,
        )
    else:
        result = await summarize_text_with_model(
            candidate=SelectableModelCandidate(
                model_selection=selection, settings=settings
            ),
            credential_kwargs=credentials,
            effective_input_tokens=128000,
            sdk_factories=factories,
            watchdog=make_test_model_stream_watchdog(),
            websocket_enabled=False,
            transport_state=None,
            system_prompt="Create a checkpoint",
            user_prompt="Prefix",
            conversation_text="Source",
            session_id="s" * 32,
        )
    assert result == "Observed native source evidence"
    assert len(captured) == 1
    if provider is LLMProvider.GOOGLE_GEMINI:
        assert model in urls[0]
    else:
        assert captured[0]["model"] == model
