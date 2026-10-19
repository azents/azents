"""Full custom history and final Structured-request capability regressions."""

import dataclasses
import datetime

import pytest

from azents.core.enums import EventKind, LLMProvider
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelModalities,
    ModelModality,
    ModelParameterCapabilities,
    ModelToolCallingCapabilities,
)
from azents.core.model_capability_contract import (
    ModelCapabilityFeature,
    ModelFeatureCondition,
    ModelRequestConstraints,
)
from azents.core.routine_judgment_test import JUDGMENT_TIME, candidate
from azents.engine.events.native_replay import native_replay_schema_version
from azents.engine.events.openai_responses import (
    OpenAIResponsesLowerer,
    OpenAIResponsesRequest,
)
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.routine_judgment_test import _schema
from azents.engine.events.types import (
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    NativeArtifact,
    build_native_compat_key,
)
from azents.engine.model_assembly import ModelAssemblyMetadata
from azents.engine.routine_judgment import prepare_routine_judgment_request
from azents.engine.routine_judgment_test import selection


@pytest.mark.parametrize("provider", [LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH])
@pytest.mark.parametrize("compatible", [False, True])
def test_judgment_retains_ordinary_custom_history_without_tool_authority(
    provider: LLMProvider, compatible: bool
) -> None:
    schema = native_replay_schema_version(
        "Session context." if compatible else "Older Session instructions.",
        native_replay_context=None,
    )
    model = dataclasses.replace(
        selection(provider),
        assembly=ModelAssemblyMetadata(
            model_developer=None,
            model_family=None,
            capabilities=ModelCapabilities(
                structured_response=True,
                tool_calling=ModelToolCallingCapabilities(supported=True),
            ),
        ),
    )
    artifact = NativeArtifact(
        compat_key=build_native_compat_key(
            adapter=OpenAIResponsesLowerer.adapter,
            native_format=OpenAIResponsesLowerer.native_format,
            provider=provider.value,
            model=model.model,
            schema_version=schema,
        ),
        adapter=OpenAIResponsesLowerer.adapter,
        native_format=OpenAIResponsesLowerer.native_format,
        provider=provider.value,
        model=model.model,
        schema_version=schema,
        item={
            "type": "custom_tool_call",
            "call_id": "historical-call",
            "name": "apply_patch",
            "input": "IMPORTANT PATCH CONTENT",
        },
    )
    long_result = "Full result: " + ("retained content " * 1000) + "TAIL EVIDENCE"
    now = datetime.datetime.now(datetime.UTC)
    transcript = [
        Event(
            id="1" * 32,
            session_id="judgment-session",
            kind=EventKind.CLIENT_TOOL_CALL,
            payload=ClientToolCallPayload(
                call_id="historical-call",
                name="apply_patch",
                arguments="IMPORTANT PATCH CONTENT",
                wire_dialect="plaintext_custom",
                native_artifact=artifact,
            ),
            created_at=now,
        ),
        Event(
            id="2" * 32,
            session_id="judgment-session",
            kind=EventKind.CLIENT_TOOL_RESULT,
            payload=ClientToolResultPayload(
                call_id="historical-call",
                name="apply_patch",
                wire_dialect="plaintext_custom",
                status="completed",
                output=long_result,
            ),
            created_at=now,
        ),
    ]
    ordinary = OpenAIResponsesLowerer(
        provider=provider.value,
        provider_id=provider,
        model=model.model,
        tools=[{"type": "custom", "name": "apply_patch", "description": "Patch"}],
        top_k=None,
        model_capabilities=model.assembly.capabilities,
        historical_plaintext_custom_supported=True,
        supported_execution_options=(),
        enabled_execution_options=(),
    ).lower(
        transcript,
        model=model.model,
        system_prompt="Session context.",
        native_replay_context=None,
    )
    judgment = prepare_routine_judgment_request(
        selection=model,
        transcript=transcript,
        system_prompt="Session context.",
        candidates=(candidate(),),
        current_time=JUDGMENT_TIME,
        session_id="judgment-session",
        native_replay_context=None,
        model_file_resolver=None,
    )
    assert isinstance(judgment, OpenAIResponsesRequest)
    assert judgment.tools == []
    assert judgment.input[: len(ordinary.input)] == ordinary.input
    assert "IMPORTANT PATCH CONTENT" in str(judgment.input)
    assert long_result in str(judgment.input)


@pytest.mark.parametrize("temperature_allowed", [False, True])
def test_bedrock_structured_input_support_uses_actual_output_tool_context(
    temperature_allowed: bool,
) -> None:
    caps = ModelCapabilities(
        structured_response=False,
        tool_calling=ModelToolCallingCapabilities(supported=True),
        parameters=ModelParameterCapabilities(temperature=True),
        modalities=ModelModalities(input=[ModelModality.IMAGE]),
        request_constraints=ModelRequestConstraints(
            feature_conditions=(
                ModelFeatureCondition(
                    feature=ModelCapabilityFeature.TEMPERATURE,
                    function_tools=temperature_allowed,
                    reasoning_efforts=None,
                ),
                ModelFeatureCondition(
                    feature=ModelCapabilityFeature.INPUT_IMAGE,
                    function_tools=True,
                    reasoning_efforts=None,
                ),
            )
        ),
    )
    lowerer = PydanticAILowerer(
        provider="aws_bedrock",
        provider_id=LLMProvider.AWS_BEDROCK,
        model="anthropic.claude-3-haiku-20240307-v1:0",
        tools=None,
        top_k=None,
        temperature=0.2,
        model_capabilities=caps,
        supported_execution_options=(),
        enabled_execution_options=(),
    )
    if temperature_allowed:
        request = lowerer.lower_structured(
            [],
            model=lowerer.model,
            system_prompt="Session context.",
            native_replay_context=None,
            output=_schema(),
        )
        assert request.parameters.output_mode == "native"
        assert lowerer.file_capabilities.supports_image_input
    else:
        with pytest.raises(ValueError, match="temperature.*conditions"):
            lowerer.lower_structured(
                [],
                model=lowerer.model,
                system_prompt="Session context.",
                native_replay_context=None,
                output=_schema(),
            )
