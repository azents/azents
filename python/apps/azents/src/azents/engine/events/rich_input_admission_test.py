"""Rich inputs preserve unknown support through both model-message routes."""

import base64
import json
from typing import Literal

import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic_ai.messages import BinaryContent, ModelRequest, ToolReturnPart
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from azents.core.enums import EventKind, LLMProvider
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelModality,
    ModelReasoningEffort,
)
from azents.core.model_capability_contract import CapabilitySupport, SupportPredicate
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_capability_projection import project_capabilities
from azents.core.model_catalog_source import CatalogFact
from azents.engine.events.file_parts import (
    FilePartLoweringCapabilities,
    ModelFileLoweringContent,
    RequestLocalModelFileResolver,
)
from azents.engine.events.model_support_contract import ModelSupportContext
from azents.engine.events.openai_responses import (
    OpenAIResponsesLowerer,
    OpenAIResponsesRequest,
)
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.pydantic_ai_lowering_test import _artifact, _event
from azents.engine.events.pydantic_ai_types import PydanticAIRequest
from azents.engine.events.types import (
    ClientToolCallPayload,
    ClientToolResultPayload,
    FileOutputPart,
    OutputTextPart,
    UserMessagePayload,
)

_Adapter = Literal["pydantic_ai", "responses"]
_State = Literal["unknown", "supported", "unsupported", "conditional"]


def _capabilities(provider: LLMProvider, state: _State) -> ModelCapabilities:
    if state in {"unknown", "conditional"}:
        modalities = CatalogFact[tuple[str, ...]](state="absent", value=None)
    else:
        modalities = CatalogFact[tuple[str, ...]](
            state="value",
            value=("text", "image", "pdf") if state == "supported" else ("text",),
        )
    result = project_capabilities(
        provider=provider,
        exact_model="probe-model",
        source_model=None,
        evidence=ProviderCapabilityEvidence(
            input_modalities=modalities,
            reasoning=CatalogFact(state="value", value=True),
            reasoning_efforts=CatalogFact(
                state="value",
                value=(ModelReasoningEffort.LOW, ModelReasoningEffort.HIGH),
            ),
        ),
        model_developer=None,
    )
    if state == "conditional":
        data = result.model_dump(mode="json")
        contract = result.semantic_contract
        assert contract is not None
        conditioned = contract.model_copy(
            update={
                "input_modalities": tuple(
                    item.model_copy(
                        update={
                            "support": CapabilitySupport(
                                state="conditional",
                                origin="explicit",
                                predicate=SupportPredicate(
                                    reasoning_efforts=("high",), function_tools=None
                                ),
                            )
                        }
                    )
                    if item.modality == "image"
                    else item
                    for item in contract.input_modalities
                )
            }
        )
        data["semantic_contract"] = conditioned.model_dump(mode="json")
        result = ModelCapabilities.model_validate(data)
    return result


def _request(
    adapter: _Adapter,
    provider: LLMProvider,
    state: _State,
    *,
    media_type: str,
    effort: str | None,
    options: dict[str, object] | None,
) -> PydanticAIRequest | OpenAIResponsesRequest:
    resolver = RequestLocalModelFileResolver()
    resolver.put(
        model_file_id="probe-file",
        content=ModelFileLoweringContent(data_url=f"data:{media_type};base64,aW1hZ2U="),
    )
    part = FileOutputPart(
        model_file_id="probe-file",
        media_type=media_type,
        size=5,
        kind="image" if media_type.startswith("image/") else "document",
        name="probe.jpg" if media_type.startswith("image/") else "probe.pdf",
    )
    transcript = [
        _event(
            EventKind.USER_MESSAGE,
            UserMessagePayload(sender_user_id=None, content="Read the tool image."),
        ),
        _event(
            EventKind.CLIENT_TOOL_CALL,
            ClientToolCallPayload(
                call_id="probe-call",
                name="read_image",
                wire_dialect="json_function",
                arguments='{"path":"/tmp/probe.jpg"}',
                native_artifact=_artifact(
                    provider="old-route", model="old-model", message=None
                ),
            ),
        ),
        _event(
            EventKind.CLIENT_TOOL_RESULT,
            ClientToolResultPayload(
                call_id="probe-call",
                name="read_image",
                wire_dialect="json_function",
                status="completed",
                output=[OutputTextPart(text="Image loaded."), part],
            ),
        ),
    ]
    cls = PydanticAILowerer if adapter == "pydantic_ai" else OpenAIResponsesLowerer
    lowerer = cls(
        provider=provider.value,
        provider_id=provider,
        model="probe-model",
        tools=None,
        kwargs=options,
        reasoning_effort=effort,
        model_capabilities=_capabilities(provider, state),
        model_file_resolver=resolver,
        supported_execution_options=[],
        enabled_execution_options=[],
        top_k=None,
    )
    return lowerer.lower(transcript, model="probe-model")


def _rich_count(request: PydanticAIRequest | OpenAIResponsesRequest) -> int:
    if isinstance(request, PydanticAIRequest):
        return sum(
            len(part.files)
            for message in request.messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        )
    return sum(
        1
        for item in request.input
        if item.get("type") == "function_call_output"
        and isinstance(output := item.get("output"), list)
        for part in output
        if isinstance(part, dict) and part.get("type") in {"input_image", "input_file"}
    )


@pytest.mark.parametrize(
    "adapter,provider",
    [
        ("responses", LLMProvider.OPENAI),
        ("responses", LLMProvider.CHATGPT_OAUTH),
        ("pydantic_ai", LLMProvider.XAI),
        ("pydantic_ai", LLMProvider.XAI_OAUTH),
        ("pydantic_ai", LLMProvider.ANTHROPIC),
        ("pydantic_ai", LLMProvider.GOOGLE_GEMINI),
        ("pydantic_ai", LLMProvider.GOOGLE_VERTEX_AI),
        ("pydantic_ai", LLMProvider.AWS_BEDROCK),
        ("pydantic_ai", LLMProvider.KIMI_OAUTH),
        ("pydantic_ai", LLMProvider.OPENROUTER),
    ],
)
@pytest.mark.parametrize("state", ["unknown", "supported", "unsupported"])
@pytest.mark.parametrize("media_type", ["image/jpeg", "application/pdf"])
def test_tool_rich_input_unknown_is_not_an_explicit_denial(
    adapter: _Adapter,
    provider: LLMProvider,
    state: _State,
    media_type: str,
) -> None:
    request = _request(
        adapter,
        provider,
        state,
        media_type=media_type,
        effort=None,
        options=None,
    )
    assert _rich_count(request) == (0 if state == "unsupported" else 1)
    if state == "unknown":
        caps = _capabilities(provider, state)
        assert caps.modalities.input == [ModelModality.TEXT]
        assert caps.semantic_contract is not None
        assert (
            next(
                item.support.state
                for item in caps.semantic_contract.input_modalities
                if item.modality == "image"
            )
            == "unknown"
        )


@pytest.mark.parametrize("adapter", ["pydantic_ai", "responses"])
@pytest.mark.parametrize("wire_effort", ["low", "high"])
def test_conditional_image_uses_effective_wire_context(
    adapter: _Adapter, wire_effort: str
) -> None:
    request = _request(
        adapter,
        LLMProvider.XAI_OAUTH if adapter == "pydantic_ai" else LLMProvider.OPENAI,
        "conditional",
        media_type="image/jpeg",
        effort=None,
        options=(
            {"extra_body": {"reasoning": {"effort": wire_effort}}}
            if adapter == "pydantic_ai"
            else {"reasoning": {"effort": wire_effort}}
        ),
    )
    assert _rich_count(request) == (1 if wire_effort == "high" else 0)


def test_legacy_and_unimplemented_media_remain_conservative() -> None:
    context = ModelSupportContext(reasoning_effort=None, function_tools=None)
    assert not FilePartLoweringCapabilities.from_model_capabilities(
        ModelCapabilities(), context=context
    ).supports_image_input
    assert not FilePartLoweringCapabilities.from_model_capabilities(
        None, context=context
    ).supports_pdf_input
    caps = _capabilities(LLMProvider.XAI_OAUTH, "unknown")
    assert caps.semantic_contract is not None
    assert {
        item.modality: item.support.state
        for item in caps.semantic_contract.input_modalities
        if item.modality in {"audio", "video"}
    } == {"audio": "unsupported", "video": "unsupported"}


async def _sdk_wire(request: PydanticAIRequest) -> dict[str, object]:
    captured: list[dict[str, object]] = []

    async def handle(native: httpx2.Request) -> httpx2.Response:
        captured.append(json.loads(native.content))
        return httpx2.Response(
            200,
            json={
                "id": "resp-probe",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "probe-model",
                "output": [
                    {
                        "type": "message",
                        "id": "message-probe",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": "ok", "annotations": []}
                        ],
                    }
                ],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handle)) as http:
        async with AsyncOpenAI(
            api_key="synthetic-not-a-secret",
            base_url="https://wire-probe.invalid/v1",
            http_client=http,
            max_retries=0,
        ) as sdk:
            model = OpenAIResponsesModel(
                "probe-model", provider=OpenAIProvider(openai_client=sdk)
            )
            await model.request(request.messages, request.settings, request.parameters)
    assert len(captured) == 1
    return captured[0]


@pytest.mark.parametrize("state", ["unknown", "supported", "unsupported"])
async def test_tool_image_reaches_public_responses_sdk_wire(state: _State) -> None:
    request = _request(
        "pydantic_ai",
        LLMProvider.XAI_OAUTH,
        state,
        media_type="image/jpeg",
        effort=None,
        options=None,
    )
    assert isinstance(request, PydanticAIRequest)
    wire = json.dumps(await _sdk_wire(request))
    assert ('"type": "input_image"' in wire) is (state != "unsupported")
    if state != "unsupported":
        encoded = base64.b64encode(b"image").decode()
        assert f"data:image/jpeg;base64,{encoded}" in wire
        part = next(
            part
            for message in request.messages
            if isinstance(message, ModelRequest)
            for part in message.parts
            if isinstance(part, ToolReturnPart)
        )
        assert len(part.files) == 1
        assert isinstance(part.files[0], BinaryContent)
        assert part.files[0].data == b"image"
    else:
        assert "model does not support this file input" in wire


@pytest.mark.parametrize("wire_effort", ["low", "high"])
@pytest.mark.parametrize("channel", ["typed", "extra_body", "native_dropped"])
async def test_conditional_image_matches_actual_sdk_reasoning(
    wire_effort: str, channel: str
) -> None:
    options: dict[str, object]
    if channel == "typed":
        options = {"openai_reasoning_effort": wire_effort}
    elif channel == "extra_body":
        options = {"extra_body": {"reasoning": {"effort": wire_effort}}}
    else:
        options = {"reasoning": {"effort": wire_effort}}
    request = _request(
        "pydantic_ai",
        LLMProvider.XAI_OAUTH,
        "conditional",
        media_type="image/jpeg",
        effort=None,
        options=options,
    )
    assert isinstance(request, PydanticAIRequest)
    wire = await _sdk_wire(request)
    sent_effort = (
        reasoning.get("effort")
        if isinstance(reasoning := wire.get("reasoning"), dict)
        else None
    )
    assert sent_effort == (None if channel == "native_dropped" else wire_effort)
    allowed = sent_effort == "high"
    assert _rich_count(request) == int(allowed)
    assert ('"type": "input_image"' in json.dumps(wire)) is allowed


@pytest.mark.parametrize("override", [None, {}, {"summary": "none"}])
async def test_sdk_body_reasoning_override_does_not_grant_unsent_effort(
    override: dict[str, object] | None,
) -> None:
    request = _request(
        "pydantic_ai",
        LLMProvider.XAI_OAUTH,
        "conditional",
        media_type="image/jpeg",
        effort=None,
        options={
            "openai_reasoning_effort": "high",
            "extra_body": {"reasoning": override},
        },
    )
    assert isinstance(request, PydanticAIRequest)
    wire = await _sdk_wire(request)
    assert wire.get("reasoning") == override
    assert _rich_count(request) == 0
    assert '"type": "input_image"' not in json.dumps(wire)
