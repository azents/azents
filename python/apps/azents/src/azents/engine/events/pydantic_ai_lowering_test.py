"""Canonical transcript authority and public model lowering contracts."""

import datetime
import json
import subprocess
import sys
from textwrap import dedent

import pytest
from azcommon.uuid import uuid7
from pydantic_ai.messages import (
    BinaryContent,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.native_tools import ImageGenerationTool

from azents.core.enums import AgentRunStatus, EventKind, LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import (
    ModelBuiltInToolCapabilities,
    ModelCapabilities,
    ModelModalities,
    ModelModality,
    ModelReasoningCapabilities,
    ModelReasoningEffort,
    ModelToolCallingCapabilities,
)
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.engine.events.file_parts import (
    ModelFileLoweringContent,
    RequestLocalModelFileResolver,
)
from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
from azents.engine.events.pydantic_ai_types import PydanticAIRequest
from azents.engine.events.types import (
    AgentMessagePayload,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionSummaryPayload,
    Event,
    EventPayload,
    FileOutputPart,
    InterruptedPayload,
    NativeArtifact,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolReference,
    ProviderToolSemanticContent,
    ReasoningPayload,
    SystemReminderPayload,
    UserMessagePayload,
    build_native_compat_key,
)
from azents.engine.run.types import BuiltinToolSpec


def _artifact(
    *,
    provider: str,
    model: str,
    message: ModelResponse | None,
    adapter: str = "pydantic_ai",
) -> NativeArtifact:
    native_format = "model_messages" if adapter == "pydantic_ai" else "responses"
    item = (
        {"message": ModelMessagesTypeAdapter.dump_python([message], mode="json")[0]}
        if message is not None
        else {"type": "message", "role": "assistant", "content": []}
    )
    return NativeArtifact(
        compat_key=build_native_compat_key(
            adapter=adapter,
            native_format=native_format,
            provider=provider,
            model=model,
            schema_version="1",
        ),
        adapter=adapter,
        native_format=native_format,
        provider=provider,
        model=model,
        schema_version="1",
        item=item,
    )


def _event(kind: EventKind, payload: EventPayload) -> Event:
    return Event(
        id=uuid7().hex,
        session_id="session-1",
        kind=kind,
        payload=payload,
        created_at=datetime.datetime.now(datetime.UTC),
    )


def _lowerer(
    *,
    provider: LLMProvider = LLMProvider.ANTHROPIC,
    model: str = "claude-selected",
    tools: list[dict[str, object]] | None = None,
    capabilities: ModelCapabilities | None = None,
    file_resolver: RequestLocalModelFileResolver | None = None,
    hosted_tools: list[BuiltinToolSpec] | None = None,
    enabled: list[ModelExecutionOptionId] | None = None,
    supported: list[ModelExecutionOptionId] | None = None,
    developer: LLMModelDeveloper | None = None,
    reasoning_effort: str | None = None,
) -> PydanticAILowerer:
    return PydanticAILowerer(
        top_k=None,
        provider=provider.value,
        provider_id=provider,
        model=model,
        tools=tools,
        model_capabilities=capabilities,
        supported_execution_options=supported or [],
        enabled_execution_options=enabled or [],
        model_file_resolver=file_resolver,
        hosted_tools=hosted_tools,
        model_developer=developer,
        reasoning_effort=reasoning_effort,
    )


def _text(request: PydanticAIRequest) -> str:
    return "\n".join(
        content
        for message in request.messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
        for content in (
            [part.content] if isinstance(part.content, str) else part.content
        )
        if isinstance(content, str)
    )


def test_old_native_artifact_uses_canonical_text_without_relabeling() -> None:
    old = _artifact(
        provider="anthropic", model="claude-selected", message=None, adapter="litellm"
    )
    event = _event(
        EventKind.ASSISTANT_MESSAGE,
        AssistantMessagePayload(content="canonical answer", native_artifact=old),
    )
    request = _lowerer().lower([event], model="claude-selected", system_prompt="policy")
    assert isinstance(request.messages[0], ModelRequest)
    assert isinstance(request.messages[0].parts[0], SystemPromptPart)
    assert request.messages[0].parts[0].content == "policy"
    assert isinstance(request.messages[1], ModelResponse)
    assert request.messages[1].parts == [TextPart("canonical answer")]
    assert old.adapter == "litellm"


def test_exact_native_thinking_replay_keeps_signature_opaque() -> None:
    message = ModelResponse(
        parts=[
            ThinkingPart(
                "visible summary",
                signature="opaque-signature",
                provider_name="anthropic",
            )
        ],
        provider_name="anthropic",
        model_name="claude-selected",
    )
    artifact = _artifact(provider="anthropic", model="claude-selected", message=message)
    event = _event(
        EventKind.REASONING,
        ReasoningPayload(
            text="visible summary", summary=None, native_artifact=artifact
        ),
    )
    request = _lowerer().lower([event], model="claude-selected")
    replayed = request.messages[1]
    assert isinstance(replayed, ModelResponse)
    assert isinstance(replayed.parts[0], ThinkingPart)
    assert replayed.parts[0].signature == "opaque-signature"
    assert "opaque-signature" not in _text(request)


@pytest.mark.parametrize(
    "provider,model", [("anthropic", "other-model"), ("xai", "claude-selected")]
)
def test_cross_model_or_provider_reasoning_is_not_visible_fallback(
    provider: str, model: str
) -> None:
    artifact = _artifact(
        provider=provider,
        model=model,
        message=ModelResponse(
            parts=[
                ThinkingPart(
                    "hidden-history", signature="signature", provider_name="anthropic"
                )
            ]
        ),
    )
    event = _event(
        EventKind.REASONING,
        ReasoningPayload(text="hidden-history", summary=None, native_artifact=artifact),
    )
    request = _lowerer().lower([event], model="claude-selected")
    assert len(request.messages) == 1
    assert (
        "hidden-history"
        not in ModelMessagesTypeAdapter.dump_json(request.messages).decode()
    )


def test_call_and_result_pair_preserve_ids_and_do_not_create_execution() -> None:
    old = _artifact(
        provider="anthropic", model="claude-selected", message=None, adapter="litellm"
    )
    call = _event(
        EventKind.CLIENT_TOOL_CALL,
        ClientToolCallPayload(
            call_id="call-1",
            name="lookup",
            arguments='{"x":1}',
            wire_dialect="json_function",
            native_artifact=old,
        ),
    )
    result = _event(
        EventKind.CLIENT_TOOL_RESULT,
        ClientToolResultPayload(
            call_id="call-1",
            name="lookup",
            wire_dialect="json_function",
            status="completed",
            output=[OutputTextPart(text="finished")],
        ),
    )
    request = _lowerer().lower([call, result], model="claude-selected")
    assert isinstance(request.messages[1], ModelResponse)
    assert isinstance(request.messages[1].parts[0], ToolCallPart)
    assert request.messages[1].parts[0].tool_call_id == "call-1"
    assert isinstance(request.messages[2], ModelRequest)
    assert isinstance(request.messages[2].parts[0], ToolReturnPart)
    assert request.messages[2].parts[0].tool_call_id == "call-1"
    assert request.messages[2].parts[0].content == "finished"


def test_orphan_and_mismatched_results_are_not_dispatched() -> None:
    orphan = _event(
        EventKind.CLIENT_TOOL_RESULT,
        ClientToolResultPayload(
            call_id="call-missing",
            wire_dialect="json_function",
            status="completed",
            output=[OutputTextPart(text="orphan")],
        ),
    )
    request = _lowerer().lower([orphan], model="claude-selected")
    assert len(request.messages) == 1


def test_historical_custom_dialect_is_bounded_non_executable() -> None:
    old = _artifact(
        provider="xai", model="grok-selected", message=None, adapter="litellm"
    )
    call = _event(
        EventKind.CLIENT_TOOL_CALL,
        ClientToolCallPayload(
            call_id="custom-1",
            name="apply_patch",
            arguments="secret-historical-command",
            wire_dialect="plaintext_custom",
            native_artifact=old,
        ),
    )
    result = _event(
        EventKind.CLIENT_TOOL_RESULT,
        ClientToolResultPayload(
            call_id="custom-1",
            name="apply_patch",
            wire_dialect="plaintext_custom",
            status="completed",
            output=[OutputTextPart(text="result" * 1000)],
        ),
    )
    request = _lowerer(provider=LLMProvider.XAI, model="grok-selected").lower(
        [call, result], model="grok-selected"
    )
    assert (
        "secret-historical-command"
        not in ModelMessagesTypeAdapter.dump_json(request.messages).decode()
    )
    assert "non-executable" in _text(request)
    assert len(_text(request)) < 3300
    assert not any(
        isinstance(part, ToolCallPart | ToolReturnPart)
        for message in request.messages
        for part in message.parts
    )


def test_replacement_route_cannot_enable_custom_from_library_metadata() -> None:
    lowerer = _lowerer(
        provider=LLMProvider.XAI,
        model="grok-selected",
        tools=[{"type": "custom", "name": "apply_patch", "format": {"type": "text"}}],
    )
    with pytest.raises(ValueError, match="does not support plaintext custom"):
        lowerer.lower([], model="grok-selected")


def test_native_tool_args_cannot_override_canonical_call() -> None:
    artifact = _artifact(
        provider="anthropic",
        model="claude-selected",
        message=ModelResponse(
            parts=[
                ToolCallPart(tool_name="lookup", tool_call_id="call-1", args={"x": 2})
            ]
        ),
    )
    event = _event(
        EventKind.CLIENT_TOOL_CALL,
        ClientToolCallPayload(
            call_id="call-1",
            name="lookup",
            arguments='{"x":1}',
            wire_dialect="json_function",
            native_artifact=artifact,
        ),
    )
    request = _lowerer().lower([event], model="claude-selected")
    assert isinstance(request.messages[1], ModelResponse)
    part = request.messages[1].parts[0]
    assert isinstance(part, ToolCallPart)
    assert isinstance(part.args, str)
    assert json.loads(part.args) == {"x": 1}


@pytest.mark.parametrize(
    "provider",
    [
        LLMProvider.ANTHROPIC,
        LLMProvider.GOOGLE_GEMINI,
        LLMProvider.AWS_BEDROCK,
        LLMProvider.GOOGLE_VERTEX_AI,
    ],
)
def test_historical_malformed_arguments_are_nonexecuting_on_object_only_sdk(
    provider: LLMProvider,
) -> None:
    artifact = _artifact(
        provider=provider.value, model="selected", message=None, adapter="litellm"
    )
    call = _event(
        EventKind.CLIENT_TOOL_CALL,
        ClientToolCallPayload(
            call_id="call-1",
            name="lookup",
            arguments='{"incomplete":' + "history-canary" * 1000,
            wire_dialect="json_function",
            native_artifact=artifact,
        ),
    )
    result = _event(
        EventKind.CLIENT_TOOL_RESULT,
        ClientToolResultPayload(
            call_id="call-1",
            name="lookup",
            wire_dialect="json_function",
            status="failed",
            output=[OutputTextPart(text="existing argument validation failure")],
        ),
    )
    request = _lowerer(provider=provider, model="selected").lower(
        [call, result], model="selected"
    )
    text = _text(request)
    assert "invalid JSON arguments; non-executable" in text
    assert "existing argument validation failure" in text
    assert len(text) < 3400
    assert not any(
        isinstance(part, ToolCallPart | ToolReturnPart)
        for message in request.messages
        for part in message.parts
    )


def test_provider_semantic_fallback_keeps_refs_and_excerpt() -> None:
    old = _artifact(
        provider="anthropic", model="claude-selected", message=None, adapter="litellm"
    )
    event = _event(
        EventKind.PROVIDER_TOOL_CALL,
        ProviderToolCallPayload(
            call_id="search-1",
            name="web_search",
            status="completed",
            semantic=ProviderToolSemanticContent(
                input='{"query":"example"}',
                output=[OutputTextPart(text="model-visible output")],
                references=[
                    ProviderToolReference(
                        kind="url",
                        uri="https://example.test/article",
                        title="Article",
                        excerpt="retained excerpt",
                        metadata={},
                    )
                ],
            ),
            native_artifact=old,
        ),
    )
    request = _lowerer().lower([event], model="claude-selected")
    serialized = ModelMessagesTypeAdapter.dump_json(request.messages).decode()
    for expected in [
        "model-visible output",
        "https://example.test/article",
        "retained excerpt",
        "example",
    ]:
        assert expected in serialized


@pytest.mark.parametrize(
    "kind,text",
    [
        (EventKind.COMPACTION_SUMMARY, "summary"),
        (EventKind.SYSTEM_REMINDER, "reminder"),
    ],
)
def test_reminder_and_compaction_are_input_not_assistant(
    kind: EventKind, text: str
) -> None:
    payload = (
        CompactionSummaryPayload(compaction_id="compaction-1", content=text)
        if kind == EventKind.COMPACTION_SUMMARY
        else SystemReminderPayload(text=text)
    )
    request = _lowerer().lower([_event(kind, payload)], model="claude-selected")
    assert isinstance(request.messages[1], ModelRequest)
    assert text in _text(request)


def test_stop_marker_has_ordinary_reminder() -> None:
    request = _lowerer().lower(
        [
            _event(
                EventKind.INTERRUPTED,
                InterruptedPayload(run_id="run-1", reason="user_requested"),
            )
        ],
        model="claude-selected",
    )
    assert "interrupt" in _text(request).lower()


def test_goal_continuation_uses_authoritative_reminder() -> None:
    payload = UserMessagePayload(
        sender_user_id=None,
        content="ignored-display-text",
        metadata={"goal_objective": "Finish the task"},
    )
    request = _lowerer().lower(
        [_event(EventKind.GOAL_CONTINUATION, payload)], model="claude-selected"
    )
    assert "Finish the task" in _text(request)
    assert "ignored-display-text" not in _text(request)


def test_goal_resume_preserves_fresh_blocked_audit_reminder() -> None:
    payload = UserMessagePayload(
        sender_user_id=None,
        content="ignored-display-text",
        metadata={
            "goal_control_action": "resume",
            "goal_objective": "Finish the task",
            "previous_goal_status": "blocked",
            "resume_hint": "The environment was changed",
        },
    )
    request = _lowerer().lower(
        [_event(EventKind.GOAL_UPDATED, payload)], model="claude-selected"
    )
    text = _text(request)
    assert "fresh blocked audit" in text
    assert "Finish the task" in text
    assert "The environment was changed" in text
    assert "ignored-display-text" not in text


def test_terminal_agent_result_keeps_message_kind_and_run_status() -> None:
    payload = AgentMessagePayload(
        message_kind="agent_result",
        source_session_agent_id="child-id",
        source_path="/root/child",
        target_session_agent_id="parent-id",
        target_path="/root",
        source_run_id="run-id",
        source_run_index=1,
        run_status=AgentRunStatus.FAILED,
        content="Terminal task result",
    )
    request = _lowerer().lower(
        [_event(EventKind.AGENT_MESSAGE, payload)], model="claude-selected"
    )
    text = _text(request)
    assert "Message Type: AGENT_RESULT" in text
    assert "Run status: failed" in text
    assert "Sender: /root/child" in text
    assert "Terminal task result" in text


def test_rich_file_uses_scoped_resolver_and_saved_capabilities() -> None:
    resolver = RequestLocalModelFileResolver()
    resolver.put(
        model_file_id="file-1",
        content=ModelFileLoweringContent(data_url="data:image/png;base64,aW1hZ2U="),
    )
    file = FileOutputPart(model_file_id="file-1", media_type="image/png", size=5)
    payload = UserMessagePayload(sender_user_id=None, content=[file])
    caps = ModelCapabilities(
        modalities=ModelModalities(
            input=[ModelModality.TEXT, ModelModality.IMAGE], output=[ModelModality.TEXT]
        )
    )
    request = _lowerer(capabilities=caps, file_resolver=resolver).lower(
        [_event(EventKind.USER_MESSAGE, payload)], model="claude-selected"
    )
    assert isinstance(request.messages[1], ModelRequest)
    user = request.messages[1].parts[0]
    assert isinstance(user, UserPromptPart)
    assert any(
        isinstance(part, BinaryContent) and part.data == b"image"
        for part in user.content
    )
    conservative = _lowerer(file_resolver=resolver).lower(
        [_event(EventKind.USER_MESSAGE, payload)], model="claude-selected"
    )
    assert (
        "does not support"
        in ModelMessagesTypeAdapter.dump_json(conservative.messages).decode()
    )


@pytest.mark.parametrize(
    "provider,limit",
    [
        (LLMProvider.XAI, 200),
        (LLMProvider.XAI_OAUTH, 200),
        (LLMProvider.GOOGLE_VERTEX_AI, 128),
    ],
)
def test_provider_declaration_budget_is_preserved(
    provider: LLMProvider, limit: int
) -> None:
    tools: list[dict[str, object]] = [
        {
            "type": "function",
            "name": f"tool_{i}",
            "parameters": {"type": "object", "properties": {}},
        }
        for i in range(limit + 1)
    ]
    lowerer = _lowerer(
        provider=provider,
        model="selected",
        tools=tools,
        developer=LLMModelDeveloper.GOOGLE,
    )
    with pytest.raises(ValueError, match="declaration limit"):
        lowerer.lower([], model="selected")


def test_unknown_saved_strict_parallel_support_is_conservative() -> None:
    request = _lowerer(
        tools=[
            {
                "type": "function",
                "name": "lookup",
                "parameters": {"type": "object", "properties": {}},
                "strict": True,
            }
        ]
    ).lower([], model="claude-selected")
    assert request.parameters.function_tools[0].strict is False
    assert request.settings["parallel_tool_calls"] is False


def test_library_tool_availability_does_not_authorize_hosted_search() -> None:
    lowerer = _lowerer(hosted_tools=[BuiltinToolSpec(name="web_search", config={})])
    with pytest.raises(ValueError, match="not authorized"):
        lowerer.lower([], model="claude-selected")


def test_authorized_hosted_search_uses_public_native_tool() -> None:
    caps = ModelCapabilities(
        built_in_tools=ModelBuiltInToolCapabilities(supported=["web_search"])
    )
    request = _lowerer(
        capabilities=caps,
        hosted_tools=[BuiltinToolSpec(name="web_search", config={"max_uses": 2})],
    ).lower([], model="claude-selected")
    assert len(request.parameters.native_tools) == 1
    assert request.parameters.native_tools[0].kind == "web_search"


@pytest.mark.parametrize(
    "provider", [LLMProvider.GOOGLE_GEMINI, LLMProvider.GOOGLE_VERTEX_AI]
)
def test_saved_authorized_google_image_uses_public_native_tool(
    provider: LLMProvider,
) -> None:
    caps = ModelCapabilities(
        built_in_tools=ModelBuiltInToolCapabilities(supported=["image_generation"])
    )
    request = _lowerer(
        provider=provider,
        model="gemini-3.1-flash-image-preview",
        developer=LLMModelDeveloper.GOOGLE,
        capabilities=caps,
        hosted_tools=[
            BuiltinToolSpec(
                name="image_generation", config={"size": "2K", "aspect_ratio": "16:9"}
            )
        ],
    ).lower([], model="gemini-3.1-flash-image-preview")
    tool = request.parameters.native_tools[0]
    assert isinstance(tool, ImageGenerationTool)
    assert tool.size == "2K"
    assert tool.aspect_ratio == "16:9"


def test_library_image_support_does_not_authorize_selected_hosted_image() -> None:
    lowerer = _lowerer(
        provider=LLMProvider.GOOGLE_GEMINI,
        model="gemini-3.1-flash-image-preview",
        hosted_tools=[BuiltinToolSpec(name="image_generation", config={})],
    )
    with pytest.raises(ValueError, match="not authorized"):
        lowerer.lower([], model="gemini-3.1-flash-image-preview")


@pytest.mark.parametrize(
    "provider", [LLMProvider.ANTHROPIC, LLMProvider.GOOGLE_VERTEX_AI]
)
def test_anthropic_route_does_not_claim_library_hosted_image_support(
    provider: LLMProvider,
) -> None:
    lowerer = _lowerer(
        provider=provider,
        developer=LLMModelDeveloper.ANTHROPIC,
        capabilities=ModelCapabilities(
            built_in_tools=ModelBuiltInToolCapabilities(supported=["image_generation"])
        ),
        hosted_tools=[BuiltinToolSpec(name="image_generation", config={})],
    )
    with pytest.raises(ValueError, match="does not support hosted image generation"):
        lowerer.lower([], model="claude-selected")


@pytest.mark.parametrize(
    "provider", [LLMProvider.GOOGLE_GEMINI, LLMProvider.GOOGLE_VERTEX_AI]
)
@pytest.mark.parametrize(
    "effort", [ModelReasoningEffort.XHIGH, ModelReasoningEffort.MAX]
)
def test_google_effort_without_legacy_mapping_fails_before_sdk_dispatch(
    provider: LLMProvider, effort: ModelReasoningEffort
) -> None:
    lowerer = _lowerer(
        provider=provider,
        model="gemini-3.1-pro-preview",
        capabilities=ModelCapabilities(
            reasoning=ModelReasoningCapabilities(supported=True, effort_levels=[effort])
        ),
        reasoning_effort=effort,
    )
    with pytest.raises(ValueError, match="no supported mapping"):
        lowerer.lower([], model="gemini-3.1-pro-preview")


def test_model_id_and_execution_intent_are_not_inferred_from_slashes() -> None:
    model = "projects/p/locations/r/publishers/anthropic/models/claude"
    request = _lowerer(
        provider=LLMProvider.GOOGLE_VERTEX_AI,
        model=model,
        developer=LLMModelDeveloper.ANTHROPIC,
    ).lower([], model=model)
    assert request.model == model
    assert request.provider == "google_vertex_ai"
    with pytest.raises(ValueError, match="differs"):
        _lowerer(model=model).lower([], model="claude")


def test_fast_and_reasoning_require_saved_authorization() -> None:
    lowerer = _lowerer(enabled=[ModelExecutionOptionId.FAST])
    with pytest.raises(ValueError, match="not supported by the model"):
        lowerer.lower([], model="claude-selected")
    lowerer = _lowerer(reasoning_effort="high")
    with pytest.raises(ValueError, match="Reasoning effort is not authorized"):
        lowerer.lower([], model="claude-selected")
    caps = ModelCapabilities(
        reasoning=ModelReasoningCapabilities(
            supported=True, effort_levels=[ModelReasoningEffort.HIGH]
        ),
        tool_calling=ModelToolCallingCapabilities(supported=True),
    )
    request = _lowerer(capabilities=caps, reasoning_effort="high").lower(
        [], model="claude-selected"
    )
    assert request.settings.get("anthropic_effort") == "high"


@pytest.mark.parametrize("helper_first", [False, True])
def test_bedrock_settings_and_structured_helper_import_in_fresh_process(
    helper_first: bool,
) -> None:
    script = dedent(
        """
        import json
        import sys
        if sys.argv[1] == "helper-first":
            from azents.engine.model_text import call_provider_text
        from azents.core.enums import LLMModelDeveloper, LLMProvider
        from azents.core.llm_catalog import (
            ModelCapabilities, ModelReasoningCapabilities, ModelReasoningEffort
        )
        from azents.engine.events.pydantic_ai_lowering import PydanticAILowerer
        from azents.engine.model_text import call_provider_text
        from azents.engine.events.pydantic_ai_types import PydanticAIRequest
        from pydantic import TypeAdapter
        from pydantic_ai.models import ModelRequestParameters
        from pydantic_ai.output import OutputObjectDefinition

        model = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
        profile = "arn:aws:bedrock:us-east-1:123456789012:inference-profile/fixture"
        lowerer = PydanticAILowerer(
        top_k=None,
            provider="aws_bedrock",
            provider_id=LLMProvider.AWS_BEDROCK,
            model=model,
            tools=None,
            model_capabilities=None,
            supported_execution_options=[],
            enabled_execution_options=[],
            model_developer=LLMModelDeveloper.ANTHROPIC,
            max_output_tokens=256,
            kwargs={
                "top_k": 42,
                "thinking": "high",
                "bedrock_cache_messages": "1h",
                "bedrock_inference_profile": profile,
                "bedrock_additional_model_requests_fields": {
                    "thinking": {"type": "enabled", "budget_tokens": 1024},
                    "output_config": {"existing_option": "preserved"},
                },
            },
        )
        request = lowerer.lower([], model=model)
        assert request.settings["max_tokens"] == 256
        assert request.settings["top_k"] == 42
        assert request.settings["thinking"] == "high"
        assert request.settings["bedrock_cache_instructions"] is True
        assert request.settings["bedrock_cache_tool_definitions"] is True
        assert request.settings["bedrock_cache_messages"] == "1h"
        assert request.settings["bedrock_inference_profile"] == profile
        assert request.settings["bedrock_additional_model_requests_fields"] == {
            "thinking": {"type": "enabled", "budget_tokens": 1024},
            "output_config": {"existing_option": "preserved"},
        }
        lowerer.model_capabilities = ModelCapabilities(
            reasoning=ModelReasoningCapabilities(
                supported=True, effort_levels=[ModelReasoningEffort.HIGH]
            )
        )
        lowerer.reasoning_effort = "high"
        effort_request = lowerer.lower([], model=model)
        assert effort_request.settings["bedrock_additional_model_requests_fields"] == {
            "thinking": {"type": "enabled", "budget_tokens": 1024},
            "output_config": {"existing_option": "preserved", "effort": "high"},
        }
        lowerer.reasoning_effort = None
        lowerer.model_developer = None
        ordinary = lowerer.lower([], model=model)
        assert ordinary.settings["top_k"] == 42
        assert ordinary.settings["bedrock_inference_profile"] == profile

        # The structured helper uses these same public runtime constructors.
        # No SDK request or provider client is created in this regression test.
        parameters = ModelRequestParameters(
            output_mode="native",
            output_object=TypeAdapter(OutputObjectDefinition).validate_python({
                "json_schema": {
                    "type": "object", "properties": {"answer": {"type": "string"}}
                },
                "name": "Answer", "description": None, "strict": True,
            }),
        )
        helper_request = PydanticAIRequest(
            provider=request.provider,
            model=request.model,
            messages=request.messages,
            settings=request.settings,
            parameters=parameters,
            assembly_metadata=None,
        )
        assert callable(call_provider_text)
        assert helper_request.parameters.output_mode == "native"
        assert helper_request.parameters.output_object.name == "Answer"
        assert helper_request.native_request_input_chars() > 0
        print(json.dumps({"fresh_bedrock_and_structured_helper": "passed"}))
        """
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            "helper-first" if helper_first else "main-first",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "fresh_bedrock_and_structured_helper": "passed"
    }
