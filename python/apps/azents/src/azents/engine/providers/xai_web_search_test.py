"""Real SDK request-wire regression tests for xAI native search compatibility."""

import dataclasses
import json

import httpx2
import pytest
from pydantic_ai.messages import NativeToolCallPart
from pydantic_ai.native_tools import WebSearchTool

from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelBuiltInToolCapabilities, ModelCapabilities
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_capability_projection import project_capabilities
from azents.core.model_catalog_source import CatalogFact
from azents.engine.events.pydantic_ai_adapter import PydanticAIModelAdapter
from azents.engine.events.pydantic_ai_adapter_test import (
    context_for_test,
    watchdog_for_test,
)
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.model_stream import ModelStreamTimeoutPolicy
from azents.engine.model_stream_test import ControlledClock
from azents.engine.provider_errors import SDK_PROVIDER_ERRORS, map_model_provider_error
from azents.engine.providers.model_factory import (
    ProviderModelFactory,
    ProviderTransports,
)
from azents.engine.providers.xai_web_search import xai_web_search_declaration
from azents.engine.run.types import BuiltinToolSpec
from azents.testing.provider_native_envelopes import core_native_response


@pytest.mark.parametrize(
    "provider", [LLMProvider.XAI, LLMProvider.XAI_OAUTH, LLMProvider.OPENROUTER]
)
@pytest.mark.parametrize("semantic", [False, True])
async def test_search_wire_preserves_function_tools_and_other_settings(
    provider: LLMProvider, semantic: bool
) -> None:
    bodies: list[dict[str, object]] = []
    envelope = core_native_response(
        protocol="responses", model="grok-test", text="Synthetic output"
    )
    frames = [
        json.loads(frame.split(b"data: ", 1)[1])
        for frame in envelope.body.split(b"\n\n")
        if frame
    ]
    search_item = {
        "id": "synthetic-search",
        "type": "web_search_call",
        "status": "completed",
        "action": {"type": "search", "query": "synthetic query"},
    }
    frames[-1]["response"]["output"].append(search_item)
    frames[1:1] = [
        {
            "type": "response.output_item.added",
            "output_index": 1,
            "item": {**search_item, "status": "in_progress"},
        },
        {
            "type": "response.web_search_call.completed",
            "output_index": 1,
            "item_id": search_item["id"],
        },
        {
            "type": "response.output_item.done",
            "output_index": 1,
            "item": search_item,
        },
    ]
    wire = b"".join(
        b"data: " + json.dumps({**frame, "sequence_number": index}).encode() + b"\n\n"
        for index, frame in enumerate(frames)
    )

    def respond(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return httpx2.Response(
            200,
            headers={"content-type": envelope.content_type},
            content=wire,
            request=request,
        )

    capabilities = (
        project_capabilities(
            provider=provider,
            exact_model="grok-test",
            source_model=None,
            model_developer=None,
            evidence=ProviderCapabilityEvidence(
                web_search=CatalogFact(state="value", value=True)
            ),
        )
        if semantic
        else ModelCapabilities(
            built_in_tools=ModelBuiltInToolCapabilities(supported=["web_search"])
        )
    )
    lowerer = PydanticAILowerer(
        top_k=None,
        provider=provider.value,
        provider_id=provider,
        model="grok-test",
        tools=[
            {
                "type": "function",
                "name": name,
                "description": "Synthetic function",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                "strict": False,
            }
            for name in ("first_function", "second_function")
        ],
        model_capabilities=capabilities,
        hosted_tools=[
            BuiltinToolSpec(
                name="web_search",
                config={
                    "search_context_size": "high",
                    "allowed_domains": ["example.com"],
                    "blocked_domains": ["blocked.example"],
                    "user_location": {"country": "KR"},
                    "external_web_access": False,
                },
            )
        ],
        supported_execution_options=[],
        enabled_execution_options=[],
        max_output_tokens=32,
        temperature=0.2 if semantic else None,
        top_p=0.7 if semantic else None,
        kwargs={"extra_body": {"metadata": {"source": "synthetic"}}},
    )
    logical = dataclasses.replace(
        lowerer.lower([], model="grok-test"),
        assembly_metadata=ModelAssemblyMetadata(
            model_developer=None, model_family=None, capabilities=capabilities
        ),
    )
    adapter = PydanticAIModelAdapter(
        factory=ProviderModelFactory(
            provider=provider,
            credential_kwargs={
                "api_key": "synthetic-sdk-key",
                "base_url": "https://synthetic.invalid/v1",
            },
            sdk_failure_mapper=map_model_provider_error,
            sdk_error_types=SDK_PROVIDER_ERRORS,
            transports=ProviderTransports(httpx2=httpx2.MockTransport(respond)),
        )
    )
    policy = ModelStreamTimeoutPolicy(
        connect_timeout_seconds=15,
        parsed_event_idle_timeout_seconds=300,
        absolute_attempt_timeout_seconds=1800,
    )
    watchdog = watchdog_for_test(ControlledClock(), policy)
    events = [
        event
        async for event in adapter.stream(
            logical,
            watchdog=watchdog,
            timeout_policy=policy,
            call_context=context_for_test(),
        )
    ]
    assert events
    assert any(
        isinstance(part, NativeToolCallPart) and part.tool_name == "web_search"
        for event in events
        if event.response is not None
        for part in event.response.parts
    )
    assert len(bodies) == 1
    tools = bodies[0]["tools"]
    assert isinstance(tools, list)
    search, first, second = tools
    expected_search = {
        "type": "web_search",
        "user_location": {"type": "approximate", "country": "KR"},
        "filters": {
            "allowed_domains": ["example.com"],
            "blocked_domains": ["blocked.example"],
        },
        "external_web_access": False,
    }
    if provider is LLMProvider.OPENROUTER:
        expected_search["search_context_size"] = "high"
    assert search == expected_search
    assert [first["name"], second["name"]] == ["first_function", "second_function"]
    assert first["parameters"]["required"] == ["query"]
    assert first["strict"] is False
    assert bodies[0]["max_output_tokens"] == 32
    assert bodies[0]["metadata"] == {"source": "synthetic"}
    if semantic:
        assert bodies[0]["temperature"] == 0.2
        assert bodies[0]["top_p"] == 0.7
    assert len(logical.parameters.function_tools) == 2


def test_search_declaration_does_not_mutate_public_tool_options() -> None:
    tool = WebSearchTool(search_context_size="high", allowed_domains=["example.com"])
    first = xai_web_search_declaration(tool)
    second = xai_web_search_declaration(tool)
    assert (
        first
        == second
        == {
            "type": "web_search",
            "filters": {"allowed_domains": ["example.com"]},
        }
    )
    assert tool.search_context_size == "high"
    assert tool.allowed_domains == ["example.com"]
