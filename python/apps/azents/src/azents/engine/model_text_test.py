"""Text-operation fidelity, native completion and operation cleanup contracts."""

from collections.abc import AsyncIterator

import pytest
from pydantic_ai.messages import ModelResponse, TextPart

import azents.engine.model_text as model_text
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities
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
from azents.engine.providers.model_factory import ProviderModelFactory
from azents.engine.run.errors import ModelCallError
from azents.testing.model_stream import (
    make_test_model_stream_context,
    make_test_model_stream_watchdog,
)


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
        capabilities=ModelCapabilities(),
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
