"""Public Google SDK wire translation after exact-context native incompatibility."""

import base64
import json

import httpx2
import pytest
from google.auth.credentials import Credentials
from google.auth.transport import Request
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.google_cloud import GoogleCloudProvider

from azents.core.enums import EventKind, LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.engine.events.model_messages import TransientModelMessage
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.pydantic_ai_output import PydanticAIOutputNormalizer
from azents.engine.events.pydantic_ai_types import (
    NativeModelObservation,
    PydanticAIStreamEvent,
)
from azents.engine.events.types import ClientToolResultPayload

_OPAQUE = base64.b64encode(b"synthetic-prior-encrypted-thought").decode()
_DOCUMENTED_SDK_MANUAL_SIGNATURE = base64.b64encode(
    b"skip_thought_signature_validator"
).decode()


class _FixtureCredentials(Credentials):
    """Synthetic local auth for a MockTransport; never call an auth endpoint."""

    def refresh(self, request: Request) -> None:
        del request
        self.token = "synthetic-not-live"


@pytest.mark.parametrize("vertex", [False, True])
@pytest.mark.parametrize("changed_revision", [False, True])
async def test_google_sdk_preserves_supported_tool_history_without_old_opaque_state(
    vertex: bool, changed_revision: bool
) -> None:
    provider_id = LLMProvider.GOOGLE_VERTEX_AI if vertex else LLMProvider.GOOGLE_GEMINI
    model_name = "gemini-3.1-pro-preview"
    instructions = "Same visible instruction prefix after clean regeneration."
    tool: dict[str, object] = {
        "type": "function",
        "name": "probe",
        "description": "Synthetic tool",
        "parameters": {"type": "object", "properties": {}},
    }
    lowerer = PydanticAILowerer(
        top_k=None,
        provider=provider_id.value,
        provider_id=provider_id,
        model=model_name,
        model_capabilities=ModelCapabilities(),
        tools=[tool],
        supported_execution_options=[],
        enabled_execution_options=[],
    )
    origin = lowerer.lower(
        [],
        model=model_name,
        system_prompt=instructions,
        native_replay_context="exact-original-revision",
    )
    normalizer = (
        PydanticAIOutputNormalizer(
            provider=provider_id.value,
            model=model_name,
            pricing=None,
            operation="sampling",
            integration=None,
        )
        .for_native_replay(origin.native_replay_schema_version())
        .start_transient()
    )
    sdk_provider = "google-vertex" if vertex else "google-gla"
    normalizer.process_event(
        PydanticAIStreamEvent(
            event=None,
            response=ModelResponse(
                parts=[
                    TextPart(
                        "Visible previous answer",
                        provider_name=sdk_provider,
                        provider_details={"thought_signature": _OPAQUE},
                    ),
                    ToolCallPart(
                        "probe",
                        args={},
                        tool_call_id="call-fixture",
                        provider_name=sdk_provider,
                        provider_details={"thought_signature": _OPAQUE},
                    ),
                ],
                model_name=model_name,
                provider_name=sdk_provider,
            ),
            observation=NativeModelObservation(
                protocol="google",
                event_type="fixture.completed",
                parsed_activity=True,
                terminal="success",
                end_turn=False,
                native_usage=None,
                reported_cost_usd=None,
                service_tier=None,
                native_items=(),
                annotations=(),
                error=None,
            ),
        )
    )
    completed = normalizer.complete()
    result = TransientModelMessage(
        kind=EventKind.CLIENT_TOOL_RESULT,
        payload=ClientToolResultPayload(
            call_id="call-fixture",
            name="probe",
            wire_dialect="json_function",
            status="completed",
            output="Visible result",
            metadata={},
        ),
    )
    request = lowerer.lower(
        [*completed.events, result],
        model=model_name,
        system_prompt=instructions,
        native_replay_context="exact-clean-revision"
        if changed_revision
        else "exact-original-revision",
    )
    bodies: list[dict[str, object]] = []

    def respond(raw_request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(raw_request.content))
        return httpx2.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": "Fixture response"}],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 1,
                    "candidatesTokenCount": 1,
                    "totalTokenCount": 2,
                },
                "modelVersion": model_name,
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
        provider = (
            GoogleCloudProvider(
                project="synthetic-project",
                location="global",
                credentials=_FixtureCredentials(),
                http_client=client,
            )
            if vertex
            else GoogleProvider(api_key="synthetic-not-live", http_client=client)
        )
        sdk = GoogleModel(model_name, provider=provider)
        try:
            await sdk.request(request.messages, request.settings, request.parameters)
        finally:
            await provider.client.aio.aclose()
    assert len(bodies) == 1
    wire = json.dumps(bodies[0])
    assert "Visible previous answer" in wire and "Visible result" in wire
    assert "functionCall" in wire and "functionResponse" in wire
    assert (_OPAQUE in wire) == (not changed_revision)
    assert (_DOCUMENTED_SDK_MANUAL_SIGNATURE in wire) == changed_revision
    assert "exact-original-revision" not in wire and "exact-clean-revision" not in wire
    assert "native_replay_context" not in wire
