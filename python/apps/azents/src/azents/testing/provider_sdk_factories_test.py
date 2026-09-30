"""Public SDK native fixture contracts, not API/worker E2E evidence."""

import json

import pytest
from botocore.eventstream import EventStreamBuffer
from pydantic import BaseModel, ConfigDict

from azents.core.enums import LLMProvider
from azents.engine.model_stream import ModelStreamCallContext
from azents.engine.model_text import call_provider_text
from azents.testing.model_stream import make_test_model_stream_watchdog
from azents.testing.provider_native_envelopes import core_native_response
from azents.testing.provider_sdk_factories import (
    FIXTURE_CREDENTIAL_PREFIX,
    fixture_model_sdk_factories,
)


class _NativeEventView(BaseModel):
    """Decode the public SDK response view instead of its inaccurate field stub."""

    model_config = ConfigDict(extra="ignore")
    headers: dict[str, str]
    body: bytes


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        (LLMProvider.ANTHROPIC, "claude-sonnet-4-6"),
        (LLMProvider.GOOGLE_GEMINI, "gemini-2.5-flash"),
        (LLMProvider.XAI, "grok-4"),
        (LLMProvider.XAI_OAUTH, "grok-4"),
        (LLMProvider.OPENROUTER, "anthropic/claude-sonnet-4.6"),
        (LLMProvider.KIMI_OAUTH, "kimi-for-coding"),
    ],
)
async def test_core_fixture_uses_real_sdk_assembly_and_native_success_proof(
    provider: LLMProvider, model: str
) -> None:
    """No canned application output bypasses SDK/parser/native admission."""
    watchdog = make_test_model_stream_watchdog()
    policy = watchdog.resolve_policy(
        provider=provider.value, model=model, inference_profile=None
    )
    context = ModelStreamCallContext(
        call_kind="session_title",
        provider=provider.value,
        provider_integration_id="synthetic",
        model=model,
        session_id="synthetic-session",
        run_id=None,
        attempt_number=1,
        check_stop=None,
    )
    result = await call_provider_text(
        assembly_metadata=None,
        sdk_factories=fixture_model_sdk_factories(),
        provider=provider,
        model=model,
        credential_kwargs={
            "api_key": FIXTURE_CREDENTIAL_PREFIX + provider.value,
            "base_url": "https://native-fixture.invalid/v1",
            "extra_headers": {"X-Msh-Device-Id": "synthetic-device"},
        },
        input_text="Create a title from this request: core",
        instructions="Return the title",
        max_output_tokens=80,
        watchdog=watchdog,
        timeout_policy=policy,
        call_context=context,
        text=None,
        extra_body=None,
    )
    assert json.loads(result) == {"title": "Provider cutover core"}


def test_aws_fixture_has_public_binary_event_stream_framing_and_terminal() -> None:
    """Botocore validates both CRCs and parses genuine native frame headers."""
    fixture = core_native_response(
        protocol="bedrock", model="anthropic.claude-sonnet", text="core fixture"
    )
    parser = EventStreamBuffer()
    parser.add_data(fixture.body)
    events = [
        _NativeEventView.model_validate(event.to_response_dict()) for event in parser
    ]
    assert [event.headers[":event-type"] for event in events] == [
        "messageStart",
        "contentBlockDelta",
        "contentBlockStop",
        "messageStop",
        "metadata",
    ]
    assert json.loads(events[-2].body) == {"stopReason": "end_turn"}
    assert json.loads(events[-1].body)["usage"]["totalTokens"] == 5
