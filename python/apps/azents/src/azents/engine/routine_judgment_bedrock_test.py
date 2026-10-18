"""Routine judgment at the public Boto Structured-output boundary."""

import dataclasses

from pydantic import TypeAdapter

from azents.core.enums import LLMProvider
from azents.core.llm_catalog import ModelCapabilities, ModelToolCallingCapabilities
from azents.core.routine_judgment_test import candidate
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.model_factories import get_model_sdk_factories
from azents.engine.providers.bedrock_lifecycle_test import bedrock_call
from azents.engine.providers.model_factory import ProviderModelFactory
from azents.engine.routine_judgment import (
    call_routine_judgment,
    prepare_routine_judgment_request,
)
from azents.engine.routine_judgment_test import context, history, selection
from azents.testing.provider_native_envelopes import aws_event_frame

_BODY = TypeAdapter(dict[str, object])


async def test_bedrock_judgment_uses_only_the_structured_output_tool() -> None:
    model_name = "anthropic.claude-3-haiku-20240307-v1:0"
    frames = [
        aws_event_frame("messageStart", {"role": "assistant"}),
        aws_event_frame(
            "contentBlockStart",
            {
                "contentBlockIndex": 0,
                "start": {
                    "toolUse": {
                        "toolUseId": "synthetic-output",
                        "name": "json_tool_call",
                    }
                },
            },
        ),
        aws_event_frame(
            "contentBlockDelta",
            {
                "contentBlockIndex": 0,
                "delta": {
                    "toolUse": {
                        "input": '{"decisions":[{"routine_id":"routine-a","act":true}]}'
                    }
                },
            },
        ),
        aws_event_frame("contentBlockStop", {"contentBlockIndex": 0}),
        aws_event_frame("messageStop", {"stopReason": "tool_use"}),
        aws_event_frame(
            "metadata",
            {
                "usage": {"inputTokens": 3, "outputTokens": 2, "totalTokens": 5},
                "metrics": {"latencyMs": 1},
            },
        ),
    ]
    boundary = bedrock_call(model=model_name, chunks=frames)
    model = dataclasses.replace(
        selection(LLMProvider.AWS_BEDROCK),
        model=model_name,
        assembly=ModelAssemblyMetadata(
            model_developer=None,
            model_family=None,
            capabilities=ModelCapabilities(
                structured_response=False,
                tool_calling=ModelToolCallingCapabilities(supported=True),
            ),
        ),
    )
    request = prepare_routine_judgment_request(
        selection=model,
        transcript=history(),
        system_prompt="Session context.",
        candidates=(candidate(),),
        session_id="judgment-session",
        native_replay_context=None,
        model_file_resolver=None,
    )

    def factory(
        *, provider: LLMProvider, credential_kwargs: dict[str, object]
    ) -> ProviderModelFactory:
        assert provider is LLMProvider.AWS_BEDROCK
        return boundary.adapter.factory

    try:
        result = await call_routine_judgment(
            judgment_id="bedrock-output",
            candidates=(candidate(),),
            selection=model,
            request=request,
            sdk_factories=dataclasses.replace(
                get_model_sdk_factories(), provider_model=factory
            ),
            credential_kwargs={},
            pricing=None,
            watchdog=boundary.watchdog,
            timeout_policy=boundary.policy,
            call_context=context(model),
        )
        assert result.status == "completed"
        assert result.decision is not None and result.decision.decisions[0].act
        assert result.usage is not None and result.usage.total_tokens == 5
        assert len(boundary.boundary.bodies) == 1
        body = boundary.boundary.bodies[0]
        config = _BODY.validate_python(body["toolConfig"])
        tools = TypeAdapter(list[dict[str, object]]).validate_python(config["tools"])
        assert len(tools) == 1
        tool = _BODY.validate_python(tools[0]["toolSpec"])
        assert tool["name"] == "json_tool_call"
        assert "routine_id" in str(tool["inputSchema"])
        assert "Watch official launch announcements." in str(body["messages"])
        assert boundary.boundary.body.closed.is_set()
    finally:
        boundary.boundary.release_all()
        await boundary.adapter.close()
        boundary.boundary.client.close()
