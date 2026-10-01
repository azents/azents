"""Native proof, canonical events, opaque data and billing integration tests."""

import base64
import json
from io import BytesIO

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo
from pydantic_ai.messages import (
    BinaryContent,
    FilePart,
    ModelResponse,
    ModelResponseStreamEvent,
    NativeToolCallPart,
    NativeToolReturnPart,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolCallPartDelta,
)
from pydantic_ai.usage import RequestUsage

from azents.core.enums import LLMProvider
from azents.core.model_pricing import GenAIModelPricing
from azents.engine.events.protocols import (
    ContentDeltaProjection,
    FunctionCallDeltaProjection,
    ProviderToolActivityProjection,
    ReasoningDeltaProjection,
)
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.pydantic_ai_output import PydanticAIOutputNormalizer
from azents.engine.events.pydantic_ai_types import (
    NativeErrorEvidence,
    NativeModelObservation,
    NativeModelProtocol,
    NativeTerminal,
    PydanticAIStreamEvent,
)
from azents.engine.events.types import (
    AssistantMessagePayload,
    ClientToolCallPayload,
    ProviderToolCallPayload,
    ReasoningPayload,
    UnknownAdapterOutputPayload,
)
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
)
from azents.testing.model_metadata import make_test_model_pricing


def _observation(
    *,
    protocol: NativeModelProtocol = "responses",
    terminal: NativeTerminal | None = None,
    end_turn: bool | None = None,
    usage: dict[str, object] | None = None,
    charge: float | None = None,
    tier: str | None = None,
    items: tuple[dict[str, object], ...] = (),
    annotations: tuple[dict[str, object], ...] = (),
    error: NativeErrorEvidence | None = None,
) -> NativeModelObservation:
    return NativeModelObservation(
        protocol=protocol,
        event_type="fixture.native",
        parsed_activity=True,
        terminal=terminal,
        end_turn=end_turn,
        native_usage=usage,
        reported_cost_usd=charge,
        service_tier=tier,
        native_items=items,
        annotations=annotations,
        error=error,
    )


def _event(
    *,
    response: ModelResponse | None = None,
    observation: NativeModelObservation | None = None,
    event: ModelResponseStreamEvent | None = None,
) -> PydanticAIStreamEvent:
    return PydanticAIStreamEvent(
        event=event, response=response, observation=observation
    )


def _normalizer(
    *,
    provider: str = "anthropic",
    model: str = "selected-model",
    pricing: GenAIModelPricing | None = None,
) -> PydanticAIOutputNormalizer:
    return PydanticAIOutputNormalizer(
        provider=provider,
        model=model,
        pricing=pricing,
        operation="sampling",
        integration=None,
    )


def _pricing() -> GenAIModelPricing:
    return make_test_model_pricing(
        provider=LLMProvider.ANTHROPIC,
        model_identifier="selected-model",
    )


def test_common_complete_or_content_eof_is_not_native_success() -> None:
    stream = _normalizer().start("session-1")
    stream.process_event(
        _event(event=PartStartEvent(index=0, part=TextPart("partial")))
    )
    stream.process_event(
        _event(response=ModelResponse(parts=[TextPart("partial")], state="complete"))
    )
    with pytest.raises(ModelProviderFailure, match="ended before completion") as raised:
        stream.complete()
    assert raised.value.category is ModelProviderFailureCategory.TRANSPORT


def test_stop_reason_pulse_without_terminal_is_not_success() -> None:
    stream = _normalizer().start("session-1")
    stream.process_event(
        _event(
            observation=_observation(
                protocol="anthropic", usage={"input_tokens": 2, "output_tokens": 1}
            )
        )
    )
    with pytest.raises(ModelProviderFailure, match="ended before completion"):
        stream.complete()


def test_native_success_and_exact_end_turn_control_followup_not_text() -> None:
    stream = _normalizer().start("session-1")
    stream.process_event(
        _event(
            response=ModelResponse(parts=[TextPart("done")]),
            observation=_observation(
                protocol="anthropic", terminal="success", end_turn=False
            ),
        )
    )
    result = stream.complete()
    assert result.needs_follow_up is True
    assert isinstance(result.events[0].payload, AssistantMessagePayload)
    assert result.events[0].payload.content == "done"


def test_end_turn_true_keeps_admitted_tool_call() -> None:
    stream = _normalizer().start("session-1")
    stream.process_event(
        _event(
            response=ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="lookup", tool_call_id="call-1", args={"key": "value"}
                    )
                ]
            ),
            observation=_observation(terminal="success", end_turn=True),
        )
    )
    result = stream.complete()
    assert result.needs_follow_up is False
    assert len(result.events) == 1
    assert isinstance(result.events[0].payload, ClientToolCallPayload)
    assert result.events[0].payload.call_id == "call-1"


def test_absent_end_turn_has_existing_client_call_fallback() -> None:
    stream = _normalizer().start("session-1")
    stream.process_event(
        _event(
            response=ModelResponse(
                parts=[ToolCallPart(tool_name="lookup", tool_call_id="call-1", args={})]
            ),
            observation=_observation(terminal="success"),
        )
    )
    assert stream.complete().needs_follow_up is True


@pytest.mark.parametrize("args", [None, '{"incomplete":', "[1,2]"])
def test_incomplete_or_malformed_calls_have_nonexecuting_diagnostic(
    args: str | None,
) -> None:
    stream = _normalizer().start("session-1")
    stream.process_event(
        _event(
            response=ModelResponse(
                parts=[
                    ToolCallPart(tool_name="lookup", tool_call_id="call-1", args=args)
                ]
            ),
            observation=_observation(terminal="success"),
        )
    )
    result = stream.complete()
    assert not any(
        isinstance(event.payload, ClientToolCallPayload) for event in result.events
    )
    assert any(
        isinstance(event.payload, UnknownAdapterOutputPayload)
        for event in result.events
    )
    assert result.needs_follow_up is False


def test_success_does_not_override_an_explicit_native_failure() -> None:
    stream = _normalizer().start("session-1")
    evidence = NativeErrorEvidence(
        message="Too many requests",
        code="rate_limit_exceeded",
        error_type="rate_limit_error",
        parameter=None,
        status_code=429,
    )
    stream.process_event(
        _event(
            response=ModelResponse(parts=[TextPart("provisional")]),
            observation=_observation(terminal="failed", error=evidence),
        )
    )
    stream.process_event(_event(observation=_observation(terminal="success")))
    with pytest.raises(ModelProviderFailure) as raised:
        stream.complete()
    assert raised.value.status_code == 429
    assert raised.value.provider_code == "rate_limit_exceeded"


def test_partial_stop_preserves_text_without_tool_execution_claim() -> None:
    stream = _normalizer().start("session-1")
    stream.process_event(_event(event=PartStartEvent(index=0, part=TextPart("prefix"))))
    stream.process_event(
        _event(event=PartDeltaEvent(index=0, delta=TextPartDelta(" tail")))
    )
    result = stream.interrupt()
    assert result.needs_follow_up is False
    assert isinstance(result.events[0].payload, AssistantMessagePayload)
    assert result.events[0].payload.content == "prefix tail"


def test_opaque_signatures_never_become_visible_reasoning_delta() -> None:
    stream = _normalizer().start("session-1")
    initial = ThinkingPart(
        "",
        id="redacted_thinking",
        signature="opaque-signature",
        provider_name="anthropic",
    )
    stream.process_event(_event(event=PartStartEvent(index=0, part=initial)))
    pulse = stream.process_event(
        _event(
            event=PartDeltaEvent(
                index=0,
                delta=ThinkingPartDelta(
                    signature_delta="opaque-new", provider_name="anthropic"
                ),
            )
        )
    )
    assert not any(
        isinstance(projection, ReasoningDeltaProjection)
        for projection in pulse.projections
    )
    final = ThinkingPart(
        "", id="redacted_thinking", signature="opaque-new", provider_name="anthropic"
    )
    stream.process_event(
        _event(
            response=ModelResponse(parts=[final], provider_name="anthropic"),
            observation=_observation(protocol="anthropic", terminal="success"),
        )
    )
    result = stream.complete()
    payload = result.events[0].payload
    assert isinstance(payload, ReasoningPayload)
    assert payload.text is None
    assert "opaque-new" in json.dumps(payload.native_artifact.item)
    lowerer = PydanticAILowerer(
        provider="anthropic",
        provider_id=LLMProvider.ANTHROPIC,
        model="selected-model",
        tools=None,
        model_capabilities=None,
        supported_execution_options=[],
        enabled_execution_options=[],
    )
    request = lowerer.lower(result.events, model="selected-model")
    replayed = request.messages[1]
    assert isinstance(replayed, ModelResponse)
    assert isinstance(replayed.parts[0], ThinkingPart)
    assert replayed.parts[0].signature == "opaque-new"


def test_live_common_deltas_and_final_tool_assembly_are_separate() -> None:
    stream = _normalizer().start("session-1")
    first = stream.process_event(
        _event(event=PartStartEvent(index=0, part=TextPart("a")))
    )
    second = stream.process_event(
        _event(event=PartDeltaEvent(index=0, delta=TextPartDelta("b")))
    )
    stream.process_event(
        _event(
            event=PartStartEvent(
                index=1,
                part=ToolCallPart(tool_name="lookup", tool_call_id="call-1", args=None),
            )
        )
    )
    delta = stream.process_event(
        _event(
            event=PartDeltaEvent(index=1, delta=ToolCallPartDelta(args_delta='{"x":1}'))
        )
    )
    final = ToolCallPart(tool_name="lookup", tool_call_id="call-1", args='{"x":1}')
    stream.process_event(_event(event=PartEndEvent(index=1, part=final)))
    stream.process_event(
        _event(
            response=ModelResponse(parts=[TextPart("ab"), final]),
            observation=_observation(terminal="success"),
        )
    )
    assert first.projections == [ContentDeltaProjection(delta="a", content_index=0)]
    assert second.projections == [ContentDeltaProjection(delta="b", content_index=0)]
    assert any(
        isinstance(projection, FunctionCallDeltaProjection)
        for projection in delta.projections
    )
    result = stream.complete()
    assert len(result.events) == 2
    assert isinstance(result.events[1].payload, ClientToolCallPayload)
    assert result.events[1].payload.arguments == '{"x":1}'


def test_native_hosted_item_is_not_duplicated_by_common_parts() -> None:
    call = NativeToolCallPart(
        tool_name="web_search", tool_call_id="search-1", args={"query": "example"}
    )
    returned = NativeToolReturnPart(
        tool_name="web_search",
        tool_call_id="search-1",
        content=[{"url": "https://example.test/a", "title": "A"}],
    )
    native: dict[str, object] = {
        "type": "web_search_call",
        "id": "search-1",
        "status": "completed",
        "action": {
            "type": "search",
            "query": "example",
            "sources": [{"url": "https://example.test/a", "title": "A"}],
        },
    }
    stream = _normalizer(provider="xai").start("session-1")
    activity = stream.process_event(_event(observation=_observation(items=(native,))))
    stream.process_event(
        _event(
            response=ModelResponse(parts=[call, returned]),
            observation=_observation(terminal="success", items=(native,)),
        )
    )
    result = stream.complete()
    hosted = [
        event.payload
        for event in result.events
        if isinstance(event.payload, ProviderToolCallPayload)
    ]
    assert len(hosted) == 1
    assert hosted[0].call_id == "search-1"
    assert any(
        reference.uri == "https://example.test/a"
        for reference in hosted[0].semantic.references
    )
    assert any(
        isinstance(projection, ProviderToolActivityProjection)
        for projection in activity.projections
    )
    assert hosted[0].native_artifact.adapter == "pydantic_ai"


def test_annotation_supplement_is_retained_without_new_citation_event() -> None:
    annotation: dict[str, object] = {
        "type": "citation_delta",
        "url": "https://example.test/source",
        "title": "Source",
    }
    stream = _normalizer().start("session-1")
    stream.process_event(
        _event(
            response=ModelResponse(parts=[TextPart("answer")]),
            observation=_observation(
                protocol="anthropic", terminal="success", annotations=(annotation,)
            ),
        )
    )
    result = stream.complete()
    assert len(result.events) == 1
    payload = result.events[0].payload
    assert isinstance(payload, AssistantMessagePayload)
    assert payload.native_artifact.item["annotations"] == [annotation]


def test_native_final_usage_cache_partition_and_snapshot_are_fixed() -> None:
    normalizer = _normalizer(pricing=_pricing())
    stream = normalizer.start("session-1")
    normalizer.pricing = None
    first = stream.process_event(
        _event(
            observation=_observation(
                protocol="anthropic",
                usage={
                    "input_tokens": 5,
                    "output_tokens": 1,
                    "cache_read_input_tokens": 2,
                    "cache_creation_input_tokens": 3,
                },
            )
        )
    )
    assert first.usage is not None
    assert first.usage.prompt_tokens == 10
    assert first.usage.completion_tokens == 1
    late = stream.process_event(
        _event(
            response=ModelResponse(
                parts=[TextPart("done")],
                usage=RequestUsage(
                    input_tokens=10,
                    output_tokens=5,
                    cache_read_tokens=2,
                    cache_write_tokens=3,
                ),
            ),
            observation=_observation(
                protocol="anthropic", terminal="success", usage={"output_tokens": 5}
            ),
        )
    )
    assert late.usage is not None
    result = stream.complete()
    assert result.usage is not None
    assert result.usage.total_tokens == 15
    assert result.usage.cached_tokens == 2
    assert result.usage.cache_creation_tokens == 3
    assert result.usage.cost_usd == pytest.approx(1.97)
    assert result.usage.cost_provenance is not None
    assert result.usage.cost_provenance.source_snapshot_id == "source-snapshot-1"


def test_google_thought_tokens_are_not_double_counted() -> None:
    stream = _normalizer(provider="google_gemini").start("session-1")
    stream.process_event(
        _event(
            response=ModelResponse(
                parts=[TextPart("answer")],
                usage=RequestUsage(
                    input_tokens=10, output_tokens=7, details={"reasoning_tokens": 2}
                ),
            ),
            observation=_observation(
                protocol="google",
                terminal="success",
                usage={
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 5,
                    "thoughtsTokenCount": 2,
                    "cachedContentTokenCount": 3,
                },
            ),
        )
    )
    usage = stream.complete().usage
    assert usage is not None
    assert usage.prompt_tokens == 10
    assert usage.completion_tokens == 7
    assert usage.reasoning_tokens == 2
    assert usage.total_tokens == 17


def test_reported_charge_is_not_the_model_library_estimate() -> None:
    stream = _normalizer(provider="openrouter", model="publisher/model").start(
        "session-1"
    )
    stream.process_event(
        _event(
            response=ModelResponse(
                parts=[TextPart("answer")],
                usage=RequestUsage(input_tokens=10, output_tokens=5),
                provider_details={"cost": 999},
            ),
            observation=_observation(
                terminal="success",
                charge=0.25,
                usage={"input_tokens": 10, "output_tokens": 5},
            ),
        )
    )
    usage = stream.complete().usage
    assert usage is not None
    assert usage.cost_usd == 0.25
    assert usage.cost_provenance is not None
    assert usage.cost_provenance.method == "provider_reported"


def test_duplicate_terminal_does_not_duplicate_output_or_usage() -> None:
    stream = _normalizer().start("session-1")
    completed = _event(
        response=ModelResponse(
            parts=[TextPart("answer")],
            usage=RequestUsage(input_tokens=10, output_tokens=5),
        ),
        observation=_observation(terminal="success"),
    )
    stream.process_event(completed)
    stream.process_event(completed)
    result = stream.complete()
    assert len(result.events) == 1
    assert result.usage is not None
    assert result.usage.total_tokens == 15


def test_file_output_bytes_are_transient_not_native_base64() -> None:
    stream = _normalizer(provider="google_gemini").start("session-1")
    body = b"generated-image-canary"
    stream.process_event(
        _event(
            response=ModelResponse(
                parts=[FilePart(BinaryContent(data=body, media_type="image/png"))]
            ),
            observation=_observation(protocol="google", terminal="success"),
        )
    )
    result = stream.complete()
    assert len(result.pending_provider_files) == 1
    assert result.pending_provider_files[0].body == body
    assert "generated-image-canary" not in json.dumps(
        [event.model_dump(mode="json") for event in result.events]
    )
    assert isinstance(result.events[0].payload, ProviderToolCallPayload)
    assert result.events[0].payload.name == "image_generation"


@pytest.mark.parametrize("args", ['{"incomplete":', "[1,2]", "null", ""])
@pytest.mark.parametrize("closure", ["part_end", "native_item"])
def test_closed_malformed_call_keeps_raw_args_for_existing_validator(
    args: str, closure: str
) -> None:
    part = ToolCallPart(tool_name="lookup", tool_call_id="call-1", args=args)
    stream = _normalizer().start("session-1")
    native: dict[str, object] = {
        "type": "function_call",
        "call_id": "call-1",
        "name": "lookup",
        "arguments": args,
        "status": "completed",
    }
    if closure == "part_end":
        stream.process_event(_event(event=PartEndEvent(index=0, part=part)))
    stream.process_event(
        _event(
            response=ModelResponse(parts=[part]),
            observation=_observation(
                terminal="success", items=(native,) if closure == "native_item" else ()
            ),
        )
    )
    result = stream.complete()
    payload = result.events[0].payload
    assert isinstance(payload, ClientToolCallPayload)
    assert payload.arguments == args
    assert result.needs_follow_up is True


def test_explicit_incomplete_native_call_is_not_admitted_after_success() -> None:
    native: dict[str, object] = {
        "type": "function_call",
        "call_id": "call-1",
        "status": "incomplete",
        "arguments": '{"x":1}',
    }
    stream = _normalizer().start("session-1")
    stream.process_event(
        _event(
            response=ModelResponse(
                parts=[ToolCallPart(tool_name="lookup", tool_call_id="call-1", args={})]
            ),
            observation=_observation(terminal="success", items=(native,)),
        )
    )
    result = stream.complete()
    assert isinstance(result.events[0].payload, UnknownAdapterOutputPayload)
    assert result.needs_follow_up is False


def test_incomplete_call_diagnostic_is_bounded_without_raw_argument_payload() -> None:
    args = '{"payload":"' + "incomplete-raw-canary" * 10000
    native: dict[str, object] = {
        "type": "function_call",
        "call_id": "call-1",
        "status": "incomplete",
        "arguments": args,
    }
    stream = _normalizer().start("session-1")
    stream.process_event(
        _event(
            response=ModelResponse(
                parts=[
                    ToolCallPart(tool_name="lookup", tool_call_id="call-1", args=args)
                ]
            ),
            observation=_observation(terminal="success", items=(native,)),
        )
    )
    result = stream.complete()
    payload = result.events[0].payload
    assert isinstance(payload, UnknownAdapterOutputPayload)
    serialized = json.dumps(payload.model_dump(mode="json"))
    assert len(serialized) < 1500
    assert "incomplete-raw-canary" not in serialized
    assert payload.reason == "incomplete_client_tool_call"


def test_native_image_bytes_materialize_only_through_transient_pending_file() -> None:
    buffer = BytesIO()
    metadata = PngInfo()
    metadata.add_text("canary", "native-generated-image-canary")
    Image.new("RGB", (1, 1), color=(255, 0, 0)).save(
        buffer, format="PNG", pnginfo=metadata
    )
    body = buffer.getvalue()
    encoded = base64.b64encode(body).decode()
    native: dict[str, object] = {
        "type": "image_generation_call",
        "id": "image-1",
        "status": "completed",
        "result": encoded,
        "partial_image_b64": encoded,
        "output_format": "png",
    }
    stream = _normalizer(provider="openrouter").start("session-1")
    stream.process_event(
        _event(observation=_observation(terminal="success", items=(native,)))
    )
    result = stream.complete()
    assert len(result.pending_provider_files) == 1
    assert result.pending_provider_files[0].body == body
    serialized = json.dumps([event.model_dump(mode="json") for event in result.events])
    assert encoded not in serialized
    assert "native-generated-image-canary" not in serialized
    payload = result.events[0].payload
    assert isinstance(payload, ProviderToolCallPayload)
    supplement = payload.native_artifact.item["supplement"]
    assert isinstance(supplement, dict)
    item = supplement["native_item"]
    assert isinstance(item, dict)
    assert item["id"] == "image-1"
    assert "result" not in item
    assert "partial_image_b64" not in item


def test_native_source_base64_is_excluded_from_supplement() -> None:
    body = b"transient-native-source-canary"
    encoded = base64.b64encode(body).decode()
    native: dict[str, object] = {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": encoded},
    }
    stream = _normalizer().start("session-1")
    stream.process_event(
        _event(
            response=ModelResponse(parts=[TextPart("answer")]),
            observation=_observation(terminal="success", items=(native,)),
        )
    )
    result = stream.complete()
    serialized = json.dumps([event.model_dump(mode="json") for event in result.events])
    assert encoded not in serialized
    assert "transient-native-source-canary" not in serialized


def test_common_hosted_output_excludes_opaque_content_from_visible_semantics() -> None:
    stream = _normalizer().start("session-1")
    stream.process_event(
        _event(
            response=ModelResponse(
                parts=[
                    NativeToolReturnPart(
                        tool_name="web_search",
                        tool_call_id="search-1",
                        content={
                            "text": "Visible search result",
                            "signature": "opaque-signature-canary",
                            "encrypted_content": "opaque-encrypted-canary",
                            "results": [
                                {
                                    "url": "https://example.test/result",
                                    "title": "Result",
                                }
                            ],
                        },
                    )
                ]
            ),
            observation=_observation(terminal="success"),
        )
    )
    result = stream.complete()
    payload = result.events[0].payload
    assert isinstance(payload, ProviderToolCallPayload)
    visible = json.dumps(payload.semantic.model_dump(mode="json"))
    assert "Visible search result" in visible
    assert "opaque-signature-canary" not in visible
    assert "opaque-encrypted-canary" not in visible
    assert payload.semantic.references[0].uri == "https://example.test/result"
    artifact = json.dumps(payload.native_artifact.item)
    assert "opaque-signature-canary" in artifact
    assert "opaque-encrypted-canary" in artifact
