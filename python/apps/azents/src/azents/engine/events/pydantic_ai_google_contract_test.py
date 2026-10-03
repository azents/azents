"""Authorized Google settings and native image contracts through official SDKs."""

import base64
import dataclasses
import hashlib
import json
from io import BytesIO

import httpx2
import pytest
from azcommon.types import JSONValue
from google.genai.types import HttpRetryOptions
from google.oauth2.credentials import Credentials
from PIL import Image
from pydantic import TypeAdapter
from pydantic_ai.messages import FilePart, ModelResponsePart, TextPart
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.google_cloud import GoogleCloudProvider

from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import (
    ModelBuiltInToolCapabilities,
    ModelCapabilities,
    ModelReasoningCapabilities,
    ModelReasoningEffort,
)
from azents.core.model_capability_evidence import ProviderCapabilityEvidence
from azents.core.model_capability_projection import project_capabilities
from azents.core.model_catalog_source import CatalogFact, decode_catalog_source
from azents.engine.events.protocols import NormalizedAdapterOutput
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.pydantic_ai_output import PydanticAIOutputNormalizer
from azents.engine.events.pydantic_ai_types import (
    PydanticAIRequest,
    PydanticAIStreamEvent,
)
from azents.engine.events.types import ProviderToolCallPayload
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.providers.model_profiles import resolve_runtime_model_profile
from azents.engine.providers.native_observation import observe_native_payload
from azents.engine.run.types import BuiltinToolSpec

_OBJECT = TypeAdapter(dict[str, JSONValue])


@dataclasses.dataclass(frozen=True)
class _Dispatch:
    wire: dict[str, JSONValue]
    parts: tuple[ModelResponsePart, ...]
    output: NormalizedAdapterOutput


def _request(
    *,
    provider: LLMProvider,
    model: str,
    effort: ModelReasoningEffort | None,
    image_config: dict[str, object] | None,
) -> PydanticAIRequest:
    capabilities = ModelCapabilities(
        reasoning=ModelReasoningCapabilities(
            supported=effort is not None,
            effort_levels=[effort] if effort is not None else [],
        ),
        built_in_tools=ModelBuiltInToolCapabilities(
            supported=["image_generation"] if image_config is not None else []
        ),
    )
    return PydanticAILowerer(
        top_k=None,
        provider=provider.value,
        provider_id=provider,
        model=model,
        tools=None,
        model_capabilities=capabilities,
        supported_execution_options=[],
        enabled_execution_options=[],
        model_developer=LLMModelDeveloper.GOOGLE,
        reasoning_effort=effort,
        hosted_tools=[BuiltinToolSpec(name="image_generation", config=image_config)]
        if image_config is not None
        else None,
    ).lower([], model=model, system_prompt="Synthetic SDK contract")


async def _dispatch(
    *,
    provider: LLMProvider,
    request: PydanticAIRequest,
    image: bytes | None,
    media_type: str | None,
    capabilities: ModelCapabilities | None,
) -> _Dispatch:
    parts: list[dict[str, object]] = [{"text": "Synthetic SDK output"}]
    if image is not None:
        assert media_type is not None
        parts.append(
            {
                "inlineData": {
                    "mimeType": media_type,
                    "data": base64.b64encode(image).decode(),
                }
            }
        )
    payload: dict[str, object] = {
        "candidates": [
            {
                "content": {"role": "model", "parts": parts},
                "finishReason": "STOP",
            }
        ],
        "modelVersion": request.model,
        "responseId": "synthetic-sdk-response",
        "usageMetadata": {
            "promptTokenCount": 3,
            "candidatesTokenCount": 2,
            "totalTokenCount": 5,
        },
    }
    wires: list[dict[str, JSONValue]] = []

    def respond(wire_request: httpx2.Request) -> httpx2.Response:
        assert wire_request.method == "POST"
        assert "streamGenerateContent" in wire_request.url.path
        wires.append(_OBJECT.validate_json(wire_request.content))
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: " + json.dumps(payload).encode() + b"\n\n",
        )

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
    google_provider = (
        GoogleCloudProvider(
            project="synthetic-project",
            location="us-central1",
            credentials=Credentials(token="synthetic-access-token"),
            http_client=client,
            retry_options=HttpRetryOptions(attempts=1),
        )
        if provider == LLMProvider.GOOGLE_VERTEX_AI
        else GoogleProvider(
            api_key="synthetic-api-key",
            http_client=client,
            retry_options=HttpRetryOptions(attempts=1),
        )
    )
    profile = (
        resolve_runtime_model_profile(
            provider=provider,
            model=request.model,
            profile_model=None,
            assembly_metadata=ModelAssemblyMetadata(
                model_developer=LLMModelDeveloper.GOOGLE,
                model_family=None,
                capabilities=capabilities,
            ),
            context_window=None,
            context_window_explicit=False,
            source_model=None,
        ).profile
        if capabilities is not None
        else None
    )
    model = GoogleModel(request.model, provider=google_provider, profile=profile)
    output = PydanticAIOutputNormalizer(
        provider=provider.value,
        model=request.model,
        pricing=None,
        operation="sampling",
        integration=None,
    ).start("synthetic-session")
    try:
        # The public SDK parses our native SSE and assembles the response.
        # No application ModelResponse or model-profile grant substitutes for it.
        async with model.request_stream(
            request.messages, request.settings, request.parameters
        ) as stream:
            async for event in stream:
                output.process_event(
                    PydanticAIStreamEvent(event=event, response=None, observation=None)
                )
            response = stream.get()
        output.process_event(
            PydanticAIStreamEvent(
                event=None,
                response=response,
                observation=observe_native_payload(protocol="google", payload=payload),
            )
        )
        assert len(wires) == 1
        return _Dispatch(
            wire=wires[0],
            parts=tuple(response.parts),
            output=output.complete(),
        )
    finally:
        await google_provider.client.aio.aclose()
        await client.aclose()


@pytest.mark.parametrize(
    "provider", [LLMProvider.GOOGLE_GEMINI, LLMProvider.GOOGLE_VERTEX_AI]
)
@pytest.mark.parametrize(
    "model",
    [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
        "gemini-3-flash-preview",
        "gemini-3-pro-preview",
        "gemini-3.1-pro-preview",
    ],
)
@pytest.mark.parametrize(
    "effort",
    [
        None,
        ModelReasoningEffort.NONE,
        ModelReasoningEffort.MINIMAL,
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
    ],
)
async def test_authorized_model_effort_reaches_official_sdk_wire(
    provider: LLMProvider, model: str, effort: ModelReasoningEffort | None
) -> None:
    # Preserve a real Vertex resource shape without rewriting request.model.
    selected_model = (
        f"projects/synthetic-project/locations/us-central1/publishers/google/models/{model}"
        if provider == LLMProvider.GOOGLE_VERTEX_AI
        else model
    )
    request = _request(
        provider=provider, model=selected_model, effort=effort, image_config=None
    )
    result = await _dispatch(
        provider=provider,
        request=request,
        image=None,
        media_type=None,
        capabilities=None,
    )
    assert request.model == selected_model
    config = result.wire["generationConfig"]
    assert isinstance(config, dict)
    if effort is None:
        assert "thinkingConfig" not in config
        return
    thinking = config["thinkingConfig"]
    assert isinstance(thinking, dict)
    assert thinking["include_thoughts"] is (effort != ModelReasoningEffort.NONE)
    if model.startswith("gemini-2.5"):
        minimal = {
            "gemini-2.5-flash": 1,
            "gemini-2.5-flash-lite": 512,
            "gemini-2.5-pro": 128,
        }
        expected = {
            ModelReasoningEffort.NONE: 0,
            ModelReasoningEffort.MINIMAL: minimal[model],
            ModelReasoningEffort.LOW: 1024,
            ModelReasoningEffort.MEDIUM: 2048,
            ModelReasoningEffort.HIGH: 4096,
        }
        assert thinking["thinking_budget"] == expected[effort]
        assert "thinking_level" not in thinking
    else:
        expected_level = {
            ModelReasoningEffort.NONE: "MINIMAL" if "flash" in model else "LOW",
            ModelReasoningEffort.MINIMAL: "MINIMAL" if "flash" in model else "LOW",
            ModelReasoningEffort.LOW: "LOW",
            ModelReasoningEffort.MEDIUM: "MEDIUM"
            if "flash" in model or model == "gemini-3.1-pro-preview"
            else "HIGH",
            ModelReasoningEffort.HIGH: "HIGH",
        }
        assert thinking["thinking_level"] == expected_level[effort]
        assert "thinking_budget" not in thinking


@pytest.mark.parametrize(
    "provider", [LLMProvider.GOOGLE_GEMINI, LLMProvider.GOOGLE_VERTEX_AI]
)
async def test_saved_image_tool_real_sdk_inline_data_becomes_transient_file(
    provider: LLMProvider,
) -> None:
    buffer = BytesIO()
    Image.new("RGB", (1, 1), color=(255, 0, 0)).save(buffer, format="PNG")
    image = buffer.getvalue()
    model = "gemini-3.1-flash-image-preview"
    request = _request(
        provider=provider,
        model=model,
        effort=None,
        image_config={"size": "2K", "aspect_ratio": "16:9"},
    )
    result = await _dispatch(
        provider=provider,
        request=request,
        image=image,
        media_type="image/png",
        capabilities=None,
    )
    config = result.wire["generationConfig"]
    assert isinstance(config, dict)
    assert config["responseModalities"] == ["TEXT", "IMAGE"]
    assert config["imageConfig"] == {"imageSize": "2K", "aspectRatio": "16:9"}
    assert any(isinstance(part, TextPart) for part in result.parts)
    file_parts = [part for part in result.parts if isinstance(part, FilePart)]
    assert len(file_parts) == 1
    assert file_parts[0].content.data == image
    assert file_parts[0].content.media_type == "image/png"
    pending = result.output.pending_provider_files
    assert len(pending) == 1
    assert pending[0].body == image
    assert pending[0].sha256 == hashlib.sha256(image).hexdigest()
    hosted = [
        event.payload
        for event in result.output.events
        if isinstance(event.payload, ProviderToolCallPayload)
    ]
    assert len(hosted) == 1
    assert hosted[0].name == "image_generation"
    assert hosted[0].call_id == pending[0].call_id
    assert hosted[0].status == "completed"
    assert hosted[0].semantic.output == []
    assert result.output.usage is not None
    assert result.output.usage.total_tokens == 5
    serialized = json.dumps(
        [event.model_dump(mode="json") for event in result.output.events]
    )
    assert base64.b64encode(image).decode() not in serialized


@pytest.mark.parametrize(
    "provider", [LLMProvider.GOOGLE_GEMINI, LLMProvider.GOOGLE_VERTEX_AI]
)
async def test_exact_source_image_support_reaches_google_sdk_without_name_profile(
    provider: LLMProvider,
) -> None:
    model = "account-visible-visual"
    namespace = "gemini" if provider == LLMProvider.GOOGLE_GEMINI else "vertex_ai"
    source = decode_catalog_source(
        json.dumps(
            {
                f"{namespace}/{model}": {
                    "litellm_provider": namespace,
                    "mode": "chat",
                    "supported_output_modalities": ["text", "image"],
                }
            }
        ).encode()
    ).models[0]
    caps = project_capabilities(
        provider=provider,
        exact_model=model,
        source_model=source,
        evidence=None,
        model_developer=LLMModelDeveloper.GOOGLE,
    )
    caps = ModelCapabilities.model_validate_json(caps.model_dump_json())
    assert "image_generation" in caps.built_in_tools.supported
    request = PydanticAILowerer(
        top_k=None,
        provider=provider.value,
        provider_id=provider,
        model=model,
        model_developer=LLMModelDeveloper.GOOGLE,
        tools=None,
        model_capabilities=caps,
        supported_execution_options=[],
        enabled_execution_options=[],
        hosted_tools=[BuiltinToolSpec(name="image_generation", config={"size": "2K"})],
    ).lower([], model=model, system_prompt="Exact source image test")
    buffer = BytesIO()
    Image.new("RGB", (1, 1), color=(0, 0, 255)).save(buffer, format="PNG")
    result = await _dispatch(
        provider=provider,
        request=request,
        image=buffer.getvalue(),
        media_type="image/png",
        capabilities=caps,
    )
    config = _OBJECT.validate_python(result.wire["generationConfig"])
    assert config["responseModalities"] == ["TEXT", "IMAGE"]
    assert config["imageConfig"] == {"imageSize": "2K"}
    assert any(isinstance(part, FilePart) for part in result.parts)
    assert len(result.output.pending_provider_files) == 1


@pytest.mark.parametrize(
    "provider", [LLMProvider.GOOGLE_GEMINI, LLMProvider.GOOGLE_VERTEX_AI]
)
@pytest.mark.parametrize("hosted", [False, None])
async def test_saved_google_image_denial_is_not_reenabled_by_codec_defaults(
    provider: LLMProvider,
    hosted: bool | None,
) -> None:
    model = "gemini-3.1-flash-image-preview"
    namespace = "gemini" if provider == LLMProvider.GOOGLE_GEMINI else "vertex_ai"
    source = decode_catalog_source(
        json.dumps(
            {
                f"{namespace}/{model}": {
                    "litellm_provider": namespace,
                    "mode": "chat",
                    "supported_output_modalities": ["text", "image"],
                }
            }
        ).encode()
    ).models[0]
    caps = project_capabilities(
        provider=provider,
        exact_model=model,
        source_model=source,
        evidence=ProviderCapabilityEvidence(
            hosted_image_generation=CatalogFact(
                state="null" if hosted is None else "value",
                value=hosted,
            )
        ),
        model_developer=LLMModelDeveloper.GOOGLE,
    )
    assert "image_generation" not in caps.built_in_tools.supported
    lowerer = PydanticAILowerer(
        top_k=None,
        provider=provider.value,
        provider_id=provider,
        model=model,
        tools=None,
        model_developer=LLMModelDeveloper.GOOGLE,
        model_capabilities=caps,
        supported_execution_options=[],
        enabled_execution_options=[],
        hosted_tools=[BuiltinToolSpec(name="image_generation", config={})],
    )
    with pytest.raises(ValueError):
        lowerer.lower([], model=model)
    lowerer = PydanticAILowerer(
        top_k=None,
        provider=provider.value,
        provider_id=provider,
        model=model,
        tools=None,
        model_developer=LLMModelDeveloper.GOOGLE,
        model_capabilities=caps,
        supported_execution_options=[],
        enabled_execution_options=[],
        hosted_tools=None,
    )
    result = await _dispatch(
        provider=provider,
        request=lowerer.lower([], model=model),
        image=None,
        media_type=None,
        capabilities=caps,
    )
    config = _OBJECT.validate_python(result.wire["generationConfig"])
    assert config.get("responseModalities") in (None, ["TEXT"])


@pytest.mark.parametrize(
    "provider", [LLMProvider.GOOGLE_GEMINI, LLMProvider.GOOGLE_VERTEX_AI]
)
@pytest.mark.parametrize(
    "effort",
    [
        ModelReasoningEffort.MINIMAL,
        ModelReasoningEffort.LOW,
        ModelReasoningEffort.MEDIUM,
        ModelReasoningEffort.HIGH,
    ],
)
async def test_explicit_source_effort_survives_sparse_google_codec_on_wire(
    provider: LLMProvider,
    effort: ModelReasoningEffort,
) -> None:
    model = "gemini-3-flash-preview"
    namespace = "gemini" if provider == LLMProvider.GOOGLE_GEMINI else "vertex_ai"
    source = decode_catalog_source(
        json.dumps(
            {
                f"{namespace}/{model}": {
                    "litellm_provider": namespace,
                    "mode": "chat",
                    "supports_reasoning": True,
                    "reasoning_effort_levels": ["minimal", "low", "medium", "high"],
                }
            }
        ).encode()
    ).models[0]
    caps = project_capabilities(
        provider=provider,
        exact_model=model,
        source_model=source,
        evidence=None,
        model_developer=LLMModelDeveloper.GOOGLE,
    )
    caps = ModelCapabilities.model_validate_json(caps.model_dump_json())
    assert effort in caps.reasoning.effort_levels
    request = PydanticAILowerer(
        top_k=None,
        provider=provider.value,
        provider_id=provider,
        model=model,
        tools=None,
        model_developer=LLMModelDeveloper.GOOGLE,
        model_capabilities=caps,
        supported_execution_options=[],
        enabled_execution_options=[],
        reasoning_effort=effort,
        hosted_tools=None,
    ).lower([], model=model, system_prompt="Exact source scalar test")
    result = await _dispatch(
        provider=provider,
        request=request,
        image=None,
        media_type=None,
        capabilities=caps,
    )
    config = _OBJECT.validate_python(result.wire["generationConfig"])
    thinking = _OBJECT.validate_python(config["thinkingConfig"])
    assert thinking["thinking_level"] == effort.value.upper()
    assert "thinking_budget" not in thinking
