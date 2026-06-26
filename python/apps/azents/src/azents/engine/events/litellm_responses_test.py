"""LiteLLM Responses adapter tests."""

import asyncio
import datetime
import warnings
import xml.etree.ElementTree as ElementTree
from collections.abc import AsyncIterator

import pytest
from litellm.exceptions import (
    AuthenticationError,
    BadRequestError,
    ServiceUnavailableError,
)
from litellm.types.llms.openai import (
    ResponseAPIUsage,
    ResponseCompletedEvent,
    ResponsesAPIResponse,
)
from pydantic import ValidationError

from azents.core.enums import EventKind, LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities, ModelModalities, ModelModality
from azents.engine.events.file_parts import ModelFileLoweringContent
from azents.engine.events.litellm_responses import (
    LiteLLMEvent,
    LiteLLMResponsesLowerer,
    LiteLLMResponsesModelAdapter,
    LiteLLMResponsesOutputNormalizer,
    UnsupportedRequiredBuiltinToolError,
    coerce_litellm_completed_response_for_logging,
    guard_litellm_streaming_logging,
)
from azents.engine.events.protocols import NativeEvent, NativeModelRequest
from azents.engine.events.system_reminders import (
    format_compaction_summary_reminder,
    format_goal_continuation_reminder,
    format_goal_resumed_reminder,
    format_goal_updated_reminder,
    format_interrupted_reminder,
    format_system_reminder,
)
from azents.engine.events.types import (
    AssistantMessagePayload,
    Attachment,
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionSummaryPayload,
    Event,
    EventPayload,
    FileOutputPart,
    GoalBriefingPayload,
    InputTextPart,
    InterruptedPayload,
    NativeArtifact,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolResultPayload,
    ReasoningPayload,
    RunMarkerPayload,
    SystemReminderPayload,
    UserMessagePayload,
    build_native_compat_key,
)
from azents.engine.run.errors import ModelCallError
from azents.engine.run.types import BuiltinToolSpec


class _StaticModelFileResolver:
    """ModelFile resolver for tests."""

    def __init__(self, content: ModelFileLoweringContent | None) -> None:
        self._content = content

    def resolve(self, part: FileOutputPart) -> ModelFileLoweringContent | None:
        """Return fixed request-local content."""
        del part
        return self._content


def _artifact(item: dict[str, object]) -> NativeArtifact:
    """Create native artifact for tests."""
    return NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="litellm",
            native_format="responses",
            provider="openai",
            model="gpt-5.1",
            schema_version="1",
        ),
        adapter="litellm",
        native_format="responses",
        provider="openai",
        model="gpt-5.1",
        schema_version="1",
        item=item,
    )


def _event(kind: EventKind, payload: EventPayload) -> Event:
    """Create event for tests."""
    return Event(
        id="0" * 32,
        session_id="session-1",
        kind=kind,
        payload=payload,
        created_at=datetime.datetime.now(datetime.UTC),
    )


class TestLiteLLMResponsesLowerer:
    """LiteLLM Responses lowerer tests."""

    def test_drops_tool_result_without_matching_call(self) -> None:
        """Remove tool result without matching tool call from Responses input."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.USER_MESSAGE,
                UserMessagePayload(content="hello"),
            ),
            _event(
                EventKind.ASSISTANT_MESSAGE,
                AssistantMessagePayload(
                    content="hi",
                    native_artifact=_artifact({"type": "message"}),
                ),
            ),
            _event(
                EventKind.CLIENT_TOOL_RESULT,
                ClientToolResultPayload(
                    call_id="call-1",
                    name="read_text",
                    status="completed",
                    output=[OutputTextPart(text="file content")],
                ),
            ),
        ]

        request = lowerer.lower(transcript, model="gpt-5.1", system_prompt="Be useful.")

        assert request.kwargs["instructions"] == "Be useful."
        assert request.input == [
            {"role": "user", "content": "hello"},
            {"type": "message"},
        ]

    def test_skips_goal_briefing_for_model_input(self) -> None:
        """goal_briefing is UI-only durable event, so exclude it from model input."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.GOAL_BRIEFING,
                GoalBriefingPayload(
                    objective="Ship the feature",
                    created_at="2026-06-15T12:00:00+00:00",
                    completed_at="2026-06-15T12:05:00+00:00",
                    duration_seconds=300,
                ),
            ),
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == []

    def test_lowers_goal_updated_with_goal_snapshot(self) -> None:
        """goal_updated renders prompt from Goal snapshot without stored prompt."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.GOAL_UPDATED,
                UserMessagePayload(
                    content="",
                    metadata={"source": "goal", "goal_objective": "Updated goal"},
                ),
            ),
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {
                "role": "user",
                "content": format_goal_updated_reminder("Updated goal"),
            }
        ]

    def test_lowers_goal_resume_with_hint(self) -> None:
        """resume goal_updated renders resume-specific prompt and hint."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.GOAL_UPDATED,
                UserMessagePayload(
                    content="",
                    metadata={
                        "source": "goal",
                        "goal_control_action": "resume",
                        "previous_goal_status": "blocked",
                        "goal_objective": "Ship the feature",
                        "resume_hint": "CI credentials are restored.",
                    },
                ),
            ),
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {
                "role": "user",
                "content": format_goal_resumed_reminder(
                    goal_objective="Ship the feature",
                    previous_goal_status="blocked",
                    resume_hint="CI credentials are restored.",
                ),
            }
        ]

    def test_lowers_goal_continuation_without_stored_content(self) -> None:
        """goal_continuation renders prompt during lower phase without stored body."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.GOAL_CONTINUATION,
                UserMessagePayload(
                    content="",
                    metadata={"source": "goal", "goal_objective": "Ship the feature"},
                ),
            ),
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {
                "role": "user",
                "content": format_goal_continuation_reminder("Ship the feature"),
            }
        ]

    def test_lowers_interrupted_event_as_system_reminder(self) -> None:
        """Lower interrupted event to synthetic system reminder."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.INTERRUPTED,
                InterruptedPayload(run_id="run-1", reason="user_requested"),
            ),
            _event(EventKind.USER_MESSAGE, UserMessagePayload(content="next")),
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {
                "role": "user",
                "content": format_interrupted_reminder(),
            },
            {"role": "user", "content": "next"},
        ]

    def test_system_reminder_helpers_share_structured_xml_format(self) -> None:
        """Reminder helper uses only the same XML structure."""
        reminders = [
            (
                "goal_continuation",
                format_goal_continuation_reminder("Ship <fast>"),
                {"goal_objective": "Ship <fast>"},
            ),
            (
                "goal_updated",
                format_goal_updated_reminder("Updated & ready"),
                {"goal_objective": "Updated & ready"},
            ),
            (
                "goal_resumed",
                format_goal_resumed_reminder(
                    goal_objective="Ship <fast>",
                    previous_goal_status="blocked",
                    resume_hint="CI & creds restored",
                ),
                {
                    "goal_objective": "Ship <fast>",
                    "previous_goal_status": "blocked",
                    "resume_hint": "CI & creds restored",
                },
            ),
            (
                "compaction_summary",
                format_compaction_summary_reminder("## Summary\n- Keep going"),
                {"summary": "## Summary\n- Keep going"},
            ),
            (
                "interrupted",
                format_interrupted_reminder(),
                {"reason": "user_requested"},
            ),
            (
                "system_reminder",
                format_system_reminder(
                    reminder_type="system_reminder",
                    instruction="Use <safe> mode & continue.",
                    data=(),
                ),
                {},
            ),
        ]

        for reminder_type, rendered, expected_data in reminders:
            root = ElementTree.fromstring(rendered)
            children = list(root)
            assert root.tag == "system_reminder"
            assert root.attrib == {"type": reminder_type}
            assert [child.tag for child in children] == ["instruction", "data"]
            instruction, data = children
            assert instruction.text
            assert {
                item.attrib["name"]: item.text for item in data.findall("item")
            } == expected_data

    def test_lowers_system_reminder_with_shared_xml_envelope(self) -> None:
        """Lower system_reminder event to same XML envelope."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.SYSTEM_REMINDER,
                SystemReminderPayload(text="Use <safe> mode & continue."),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {
                "role": "user",
                "content": format_system_reminder(
                    reminder_type="system_reminder",
                    instruction="Use <safe> mode & continue.",
                    data=(),
                ),
            }
        ]

    def test_ignores_completed_run_marker(self) -> None:
        """Do not include completed run marker in model input."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.RUN_MARKER,
                RunMarkerPayload(run_id="run-1", status="completed"),
            ),
            _event(EventKind.USER_MESSAGE, UserMessagePayload(content="next")),
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [{"role": "user", "content": "next"}]

    def test_lowers_tool_result_with_matching_call(self) -> None:
        """Convert tool result with matching tool call to Responses input."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.CLIENT_TOOL_CALL,
                ClientToolCallPayload(
                    call_id="call-1",
                    name="read_text",
                    arguments="{}",
                    native_artifact=_artifact(
                        {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "read_text",
                            "arguments": "{}",
                        }
                    ),
                ),
            ),
            _event(
                EventKind.CLIENT_TOOL_RESULT,
                ClientToolResultPayload(
                    call_id="call-1",
                    name="read_text",
                    status="completed",
                    output=[OutputTextPart(text="file content")],
                ),
            ),
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {
                "type": "function_call",
                "call_id": "call-1",
                "name": "read_text",
                "arguments": "{}",
            },
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "file content",
            },
        ]

    def test_lowers_file_part_as_rich_image_when_capability_and_content_exist(
        self,
    ) -> None:
        """FilePart becomes rich input from capability and request-local content."""
        capabilities = ModelCapabilities(
            modalities=ModelModalities(input=[ModelModality.IMAGE])
        )
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
            model_capabilities=capabilities,
            model_file_resolver=_StaticModelFileResolver(
                ModelFileLoweringContent(data_url="data:image/png;base64,abc")
            ),
        )
        transcript = [
            _event(
                EventKind.CLIENT_TOOL_CALL,
                ClientToolCallPayload(
                    call_id="call-1",
                    name="inspect_image",
                    arguments="{}",
                    native_artifact=_artifact(
                        {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "inspect_image",
                            "arguments": "{}",
                        }
                    ),
                ),
            ),
            _event(
                EventKind.CLIENT_TOOL_RESULT,
                ClientToolResultPayload(
                    call_id="call-1",
                    name="inspect_image",
                    status="completed",
                    output=[
                        OutputTextPart(text="generated image"),
                        FileOutputPart(
                            model_file_id="model-file-1",
                            media_type="image/png",
                            name="plot.png",
                            size=123,
                            kind="image",
                        ),
                    ],
                ),
            ),
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input[-1] == {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": [
                {"type": "input_text", "text": "generated image"},
                {
                    "type": "input_image",
                    "detail": "auto",
                    "image_url": "data:image/png;base64,abc",
                },
            ],
        }

    def test_lowers_file_part_as_placeholder_when_unsupported(self) -> None:
        """Lower unsupported FilePart to bounded placeholder instead of silent omit."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="text-only")
        transcript = [
            _event(
                EventKind.CLIENT_TOOL_CALL,
                ClientToolCallPayload(
                    call_id="call-1",
                    name="inspect_image",
                    arguments="{}",
                    native_artifact=_artifact(
                        {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "inspect_image",
                            "arguments": "{}",
                        }
                    ),
                ),
            ),
            _event(
                EventKind.CLIENT_TOOL_RESULT,
                ClientToolResultPayload(
                    call_id="call-1",
                    name="inspect_image",
                    status="completed",
                    output=[
                        FileOutputPart(
                            model_file_id="model-file-1",
                            media_type="image/png",
                            name="plot.png",
                            size=123,
                            kind="image",
                        )
                    ],
                ),
            ),
        ]

        request = lowerer.lower(transcript, model="text-only")

        output = request.input[-1]["output"]
        assert isinstance(output, list)
        assert output == [
            {
                "type": "input_text",
                "text": (
                    "[file unavailable for rich input] plot.png "
                    "(image/png, 123 bytes). Reason: model does not support "
                    "this file input."
                ),
            }
        ]

    def test_lowers_file_part_as_placeholder_when_resolver_missing(self) -> None:
        """Leave placeholder when resolver content is absent even with capability."""
        capabilities = ModelCapabilities(
            modalities=ModelModalities(input=[ModelModality.IMAGE])
        )
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
            model_capabilities=capabilities,
        )
        transcript = [
            _event(
                EventKind.CLIENT_TOOL_CALL,
                ClientToolCallPayload(
                    call_id="call-1",
                    name="inspect_image",
                    arguments="{}",
                    native_artifact=_artifact(
                        {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "inspect_image",
                            "arguments": "{}",
                        }
                    ),
                ),
            ),
            _event(
                EventKind.CLIENT_TOOL_RESULT,
                ClientToolResultPayload(
                    call_id="call-1",
                    name="inspect_image",
                    status="completed",
                    output=[
                        FileOutputPart(
                            model_file_id="model-file-1",
                            media_type="image/png",
                            name="plot.png",
                            size=123,
                            kind="image",
                        )
                    ],
                ),
            ),
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        output = request.input[-1]["output"]
        assert isinstance(output, list)
        assert "file content is not available" in output[0]["text"]

    def test_lowers_compaction_summary_with_resume_prefix(self) -> None:
        """Inject compaction summary with user message prefix."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.COMPACTION_SUMMARY,
                CompactionSummaryPayload(
                    compaction_id="compaction-1",
                    content="## Next Steps\n- Continue upload UX work",
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {
                "role": "user",
                "content": format_compaction_summary_reminder(
                    "## Next Steps\n- Continue upload UX work"
                ),
            }
        ]

    def test_drops_reasoning_when_native_compat_does_not_match(self) -> None:
        """Do not pass reasoning in cross-model lowering."""
        lowerer = LiteLLMResponsesLowerer(provider="anthropic", model="claude")
        transcript = [
            _event(
                EventKind.REASONING,
                ReasoningPayload(
                    text="hidden",
                    summary="summary",
                    native_artifact=_artifact({"type": "reasoning"}),
                ),
            )
        ]

        request = lowerer.lower(transcript, model="claude")

        assert request.input == []

    def test_passes_through_same_native_artifact(self) -> None:
        """Use raw native item as-is when compat key is same."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.CLIENT_TOOL_CALL,
                ClientToolCallPayload(
                    call_id="call-1",
                    name="read_text",
                    arguments="{}",
                    native_artifact=_artifact({"type": "function_call", "id": "raw"}),
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [{"type": "function_call", "id": "raw"}]

    def test_passes_through_same_native_assistant_message_artifact(self) -> None:
        """Use assistant message native item as-is when compat key is same."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        raw_item: dict[str, object] = {
            "type": "message",
            "id": "msg-1",
            "role": "assistant",
            "status": "completed",
            "content": [
                {
                    "type": "output_text",
                    "text": "done",
                    "annotations": [],
                }
            ],
        }
        transcript = [
            _event(
                EventKind.ASSISTANT_MESSAGE,
                AssistantMessagePayload(
                    content="done",
                    native_artifact=_artifact(raw_item),
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [raw_item]

    def test_passes_through_same_native_provider_tool_call_artifact(self) -> None:
        """Use provider tool call native item as-is when compat key is same."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        raw_item: dict[str, object] = {
            "type": "web_search_call",
            "id": "ws-1",
            "status": "completed",
        }
        transcript = [
            _event(
                EventKind.PROVIDER_TOOL_CALL,
                ProviderToolCallPayload(
                    call_id="ws-1",
                    name="web_search",
                    arguments=None,
                    native_artifact=_artifact(raw_item),
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [raw_item]

    def test_passes_through_same_native_provider_tool_result_artifact(self) -> None:
        """Use provider tool result native item as-is when compat key is same."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        raw_item: dict[str, object] = {
            "type": "image_generation_call",
            "id": "img-1",
            "status": "completed",
        }
        transcript = [
            _event(
                EventKind.PROVIDER_TOOL_RESULT,
                ProviderToolResultPayload(
                    call_id="img-1",
                    name="image_generation",
                    status="completed",
                    output="Generated image",
                    native_artifact=_artifact(raw_item),
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [raw_item]

    def test_passes_through_same_native_reasoning_artifact(self) -> None:
        """Use reasoning native item as-is when compat key is same."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        raw_item: dict[str, object] = {
            "type": "reasoning",
            "id": "rs-1",
            "summary": [],
        }
        transcript = [
            _event(
                EventKind.REASONING,
                ReasoningPayload(
                    text=None,
                    summary="summary",
                    native_artifact=_artifact(raw_item),
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [raw_item]

    def test_drops_native_provider_item_id_when_store_is_false(self) -> None:
        """Do not replay unstored provider response item ids."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
            provider_id=LLMProvider.CHATGPT_OAUTH,
        )
        transcript = [
            _event(
                EventKind.REASONING,
                ReasoningPayload(
                    text=None,
                    summary="summary",
                    native_artifact=_artifact(
                        {"type": "reasoning", "id": "rs-1", "summary": []}
                    ),
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [{"type": "reasoning", "summary": []}]
        assert request.kwargs["store"] is False

    def test_drops_native_item_id_but_keeps_call_id_when_store_is_false(
        self,
    ) -> None:
        """Preserve tool continuity while avoiding unstored provider item ids."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
            provider_id=LLMProvider.CHATGPT_OAUTH,
        )
        transcript = [
            _event(
                EventKind.CLIENT_TOOL_CALL,
                ClientToolCallPayload(
                    call_id="call-1",
                    name="read_text",
                    arguments="{}",
                    native_artifact=_artifact(
                        {
                            "type": "function_call",
                            "id": "fc-1",
                            "call_id": "call-1",
                            "name": "read_text",
                            "arguments": "{}",
                        }
                    ),
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {
                "type": "function_call",
                "call_id": "call-1",
                "name": "read_text",
                "arguments": "{}",
            }
        ]
        assert request.kwargs["store"] is False

    def test_pass_through_preserves_null_native_fields(self) -> None:
        """Use native replay item as-is including null fields."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.CLIENT_TOOL_CALL,
                ClientToolCallPayload(
                    call_id="call-1",
                    name="read_text",
                    arguments="{}",
                    native_artifact=_artifact(
                        {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "read_text",
                            "arguments": "{}",
                            "namespace": None,
                        }
                    ),
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {
                "type": "function_call",
                "call_id": "call-1",
                "name": "read_text",
                "arguments": "{}",
                "namespace": None,
            }
        ]

    def test_uses_responses_top_level_instructions(self) -> None:
        """Responses lowerer lowers system prompt to top-level instructions."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
        )
        transcript = [
            _event(
                EventKind.USER_MESSAGE,
                UserMessagePayload(content="hello"),
            )
        ]

        request = lowerer.lower(
            transcript,
            model="gpt-5.1",
            system_prompt="Follow project rules.",
        )

        assert request.kwargs["instructions"] == "Follow project rules."
        assert request.input == [{"role": "user", "content": "hello"}]

    def test_sets_default_instructions_without_system_prompt(
        self,
    ) -> None:
        """Do not send empty instructions when Agent prompt is absent."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
        )

        request = lowerer.lower([], model="gpt-5.1")

        assert request.kwargs["instructions"] == "You are a helpful assistant."

    def test_does_not_expose_hosted_tool_without_agent_opt_in(self) -> None:
        """Do not send hosted tool without Agent opt-in even if capability exists."""
        capabilities = ModelCapabilities()
        capabilities.built_in_tools.supported = ["web_search"]
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
            provider_id=LLMProvider.OPENAI,
            model_capabilities=capabilities,
        )

        request = lowerer.lower([], model="gpt-5.1")

        assert request.tools == []

    def test_lowers_openai_web_search_hosted_tool(self) -> None:
        """Lower OpenAI web_search opt-in to Responses tool shape."""
        capabilities = ModelCapabilities()
        capabilities.built_in_tools.supported = ["web_search"]
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
            provider_id=LLMProvider.OPENAI,
            hosted_tools=[BuiltinToolSpec(name="web_search", config={})],
            model_capabilities=capabilities,
        )

        request = lowerer.lower([], model="gpt-5.1")

        assert request.tools == [{"type": "web_search"}]

    def test_lowers_google_web_search_hosted_tool(self) -> None:
        """Lower Google web_search opt-in to google_search tool shape."""
        capabilities = ModelCapabilities()
        capabilities.built_in_tools.supported = ["web_search"]
        lowerer = LiteLLMResponsesLowerer(
            provider="google_gemini",
            model="gemini/gemini-3-pro",
            provider_id=LLMProvider.GOOGLE_GEMINI,
            model_developer=LLMModelDeveloper.GOOGLE,
            hosted_tools=[BuiltinToolSpec(name="web_search", config={})],
            model_capabilities=capabilities,
        )

        request = lowerer.lower([], model="gemini/gemini-3-pro")

        assert request.tools == [{"google_search": {}}]

    def test_lowers_anthropic_web_search_hosted_tool(self) -> None:
        """Lower Anthropic web_search opt-in to Anthropic dated tool type."""
        capabilities = ModelCapabilities()
        capabilities.built_in_tools.supported = ["web_search"]
        lowerer = LiteLLMResponsesLowerer(
            provider="anthropic",
            model="claude-sonnet-4-5",
            provider_id=LLMProvider.ANTHROPIC,
            model_developer=LLMModelDeveloper.ANTHROPIC,
            hosted_tools=[BuiltinToolSpec(name="web_search", config={})],
            model_capabilities=capabilities,
        )

        request = lowerer.lower([], model="claude-sonnet-4-5")

        assert request.tools == [{"type": "web_search_20250305", "name": "web_search"}]

    def test_required_hosted_tool_without_capability_fails(self) -> None:
        """Fail before model call when Agent opt-in tool is absent from capability."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
            provider_id=LLMProvider.OPENAI,
            hosted_tools=[BuiltinToolSpec(name="web_search", config={})],
            model_capabilities=ModelCapabilities(),
        )

        with pytest.raises(UnsupportedRequiredBuiltinToolError):
            lowerer.lower([], model="gpt-5.1")

    def test_lowers_user_message_file_part_as_placeholder_without_resolver(
        self,
    ) -> None:
        """Lower user FilePart to bounded placeholder when resolver is absent."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.USER_MESSAGE,
                UserMessagePayload(
                    content=[
                        InputTextPart(text="inspect upload"),
                        FileOutputPart(
                            model_file_id="model-file-upload-1",
                            media_type="text/plain",
                            name="notes.txt",
                            size=11,
                            kind="text",
                            metadata={"source": "user_upload"},
                        ),
                    ]
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "inspect upload"},
                    {
                        "type": "input_text",
                        "text": (
                            "[file unavailable for rich input] notes.txt "
                            "(text/plain, 11 bytes). Reason: model does not support "
                            "this file input."
                        ),
                    },
                ],
            }
        ]

    def test_lowers_user_message_attachments_as_context_part(self) -> None:
        """Lower attachment to model context without polluting transcript."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.USER_MESSAGE,
                UserMessagePayload(
                    content="inspect upload",
                    attachments=[
                        Attachment(
                            attachment_id="attachment-1",
                            uri="exchange://exchange/workspace/files/file-1/original",
                            name="notes.txt",
                            media_type="text/plain",
                            size=12,
                            created_at=datetime.datetime.now(datetime.UTC),
                            preview_summary="preview text",
                        )
                    ],
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "inspect upload"},
                    {
                        "type": "input_text",
                        "text": (
                            "[Attachments]\n"
                            "- notes.txt (text/plain, "
                            "exchange://exchange/workspace/files/file-1/original)\n"
                            "```\npreview text\n```"
                        ),
                    },
                ],
            }
        ]

    def test_degrades_cross_model_provider_tool_transcript(self) -> None:
        """Lower cross-model provider tool transcript to text."""
        lowerer = LiteLLMResponsesLowerer(provider="anthropic", model="claude")
        transcript = [
            _event(
                EventKind.PROVIDER_TOOL_CALL,
                ProviderToolCallPayload(
                    call_id="ws-1",
                    name="web_search",
                    arguments='{"query":"docs"}',
                    native_artifact=_artifact({"type": "web_search_call"}),
                ),
            ),
            _event(
                EventKind.PROVIDER_TOOL_RESULT,
                ProviderToolResultPayload(
                    call_id="img-1",
                    name="image_generation",
                    status="completed",
                    output=[
                        OutputTextPart(text="generated image"),
                    ],
                    native_artifact=_artifact({"type": "image_generation_call"}),
                ),
            ),
        ]

        request = lowerer.lower(transcript, model="claude")

        assert request.input == [
            {
                "role": "assistant",
                "content": '[provider tool call] web_search({"query":"docs"})',
            },
            {
                "role": "assistant",
                "content": (
                    "[provider tool result] image_generation: completed\n"
                    "generated image"
                ),
            },
        ]


class TestLiteLLMResponsesModelAdapter:
    """LiteLLM Responses model adapter tests."""

    async def test_stream_wraps_response_items_as_litellm_events(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Wrap LiteLLM stream item as LiteLLM native event."""

        class ResponseItem:
            def model_dump(self) -> dict[str, object]:
                """Return test payload."""
                return {"type": "response.completed"}

        async def response_iter() -> AsyncIterator[object]:
            yield ResponseItem()

        async def streaming_call(**kwargs: object) -> object:
            del kwargs
            return response_iter()

        monkeypatch.setattr(
            "azents.engine.events.litellm_responses.aresponses",
            streaming_call,
        )
        adapter = LiteLLMResponsesModelAdapter()

        events = [
            event
            async for event in adapter.stream(
                NativeModelRequest(model="gpt-5.1-codex", input=[]),
            )
        ]

        assert events == [
            LiteLLMEvent(
                type="ResponseItem",
                item={"type": "response.completed"},
            )
        ]

    async def test_litellm_bad_request_stays_internal(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Treat provider 400 as malformed request and propagate as internal error."""

        async def fail_call(**kwargs: object) -> object:
            del kwargs
            raise BadRequestError(
                message='{"detail":"Instructions are required"}',
                model="gpt-5.1-codex",
                llm_provider="openai",
            )

        monkeypatch.setattr(
            "azents.engine.events.litellm_responses.aresponses",
            fail_call,
        )
        adapter = LiteLLMResponsesModelAdapter()

        with pytest.raises(BadRequestError, match="Instructions are required"):
            _ = [
                event
                async for event in adapter.stream(
                    NativeModelRequest(model="gpt-5.1-codex", input=[]),
                )
            ]

    async def test_auth_error_is_user_visible(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Provider auth failure requires user action, so convert to user-visible."""

        async def fail_call(**kwargs: object) -> object:
            del kwargs
            raise AuthenticationError(
                message="Missing scopes",
                model="gpt-5.1-codex",
                llm_provider="openai",
            )

        monkeypatch.setattr(
            "azents.engine.events.litellm_responses.aresponses",
            fail_call,
        )
        adapter = LiteLLMResponsesModelAdapter()

        with pytest.raises(ModelCallError, match="Model call failed \\(401\\)"):
            _ = [
                event
                async for event in adapter.stream(
                    NativeModelRequest(model="gpt-5.1-codex", input=[]),
                )
            ]

    async def test_provider_server_error_is_user_visible_after_retries(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Convert final provider 5xx failure to user-visible."""

        async def fail_call(**kwargs: object) -> object:
            del kwargs
            raise ServiceUnavailableError(
                message="provider unavailable",
                model="gpt-5.1-codex",
                llm_provider="openai",
            )

        monkeypatch.setattr(
            "azents.engine.events.litellm_responses.aresponses",
            fail_call,
        )
        adapter = LiteLLMResponsesModelAdapter()

        with pytest.raises(ModelCallError, match="Model call failed \\(503\\)"):
            _ = [
                event
                async for event in adapter.stream(
                    NativeModelRequest(model="gpt-5.1-codex", input=[]),
                )
            ]

    async def test_request_validation_error_stays_internal(self) -> None:
        """Propagate adapter request validation failure as internal error."""
        adapter = LiteLLMResponsesModelAdapter()

        with pytest.raises(ValidationError):
            _ = [
                event
                async for event in adapter.stream(
                    NativeModelRequest(
                        model="gpt-5.1-codex",
                        input=[],
                        tools=[
                            {
                                "type": "function",
                                "name": "echo",
                                "parameters": {"type": "object"},
                            }
                        ],
                    ),
                )
            ]

    async def test_provider_hosted_tool_shape_bypasses_openai_tool_validation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pass provider-hosted tool shape to LiteLLM raw as-is."""
        captured: dict[str, object] = {}

        async def response_iter() -> AsyncIterator[object]:
            if False:
                yield object()

        async def streaming_call(**kwargs: object) -> object:
            captured.update(kwargs)
            return response_iter()

        monkeypatch.setattr(
            "azents.engine.events.litellm_responses.aresponses",
            streaming_call,
        )
        adapter = LiteLLMResponsesModelAdapter()

        _ = [
            event
            async for event in adapter.stream(
                NativeModelRequest(
                    model="gemini/gemini-3-pro",
                    input=[],
                    tools=[
                        {
                            "google_search": {},
                        }
                    ],
                    kwargs={"web_search_options": {"search_context_size": "low"}},
                )
            )
        ]

        assert captured["tools"] == [{"google_search": {}}]
        assert captured["web_search_options"] == {"search_context_size": "low"}

    async def test_stream_cancellation_closes_async_response(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Streaming cancellation calls response aclose hook best-effort."""

        class CancellableResponse:
            def __init__(self) -> None:
                self.closed = False

            def __aiter__(self) -> "CancellableResponse":
                return self

            async def __anext__(self) -> object:
                raise asyncio.CancelledError

            async def aclose(self) -> None:
                """Record whether close was called."""
                self.closed = True

        response = CancellableResponse()

        async def streaming_call(**kwargs: object) -> object:
            del kwargs
            return response

        monkeypatch.setattr(
            "azents.engine.events.litellm_responses.aresponses",
            streaming_call,
        )
        adapter = LiteLLMResponsesModelAdapter()

        with pytest.raises(asyncio.CancelledError):
            _ = [
                event
                async for event in adapter.stream(
                    NativeModelRequest(model="gpt-5.1-codex", input=[]),
                )
            ]

        assert response.closed

    async def test_stream_coerces_model_constructed_completed_event_before_dump(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Avoid Pydantic warnings from LiteLLM fallback response events."""

        class ResponseIterator:
            def __init__(self, event: object) -> None:
                self._event = event
                self._done = False

            def __aiter__(self) -> "ResponseIterator":
                return self

            async def __anext__(self) -> object:
                if self._done:
                    raise StopAsyncIteration
                self._done = True
                return self._event

        event = ResponseCompletedEvent.model_construct(
            type="response.completed",
            response={
                "id": "resp-1",
                "created_at": 1,
                "output": [],
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 5,
                    "total_tokens": 8,
                },
            },
        )

        async def streaming_call(**kwargs: object) -> object:
            del kwargs
            return ResponseIterator(event)

        monkeypatch.setattr(
            "azents.engine.events.litellm_responses.aresponses",
            streaming_call,
        )
        adapter = LiteLLMResponsesModelAdapter()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            events = [
                native_event
                async for native_event in adapter.stream(
                    NativeModelRequest(model="gpt-5.1-codex", input=[]),
                )
            ]

        assert len(events) == 1
        response_payload = events[0].item["response"]
        assert isinstance(response_payload, dict)
        usage_payload = response_payload["usage"]
        assert isinstance(usage_payload, dict)
        assert usage_payload["total_tokens"] == 8
        assert not [
            warning
            for warning in caught
            if "Pydantic serializer" in str(warning.message)
        ]

    def test_coerces_model_constructed_response_event_for_litellm_logging(
        self,
    ) -> None:
        """Restore response dict of LiteLLM model_construct fallback event."""
        event = ResponseCompletedEvent.model_construct(
            type="response.completed",
            response={
                "id": "resp-1",
                "created_at": 1,
                "output": [],
                "usage": {
                    "input_tokens": 3,
                    "output_tokens": 5,
                    "total_tokens": 8,
                },
            },
        )

        coerce_litellm_completed_response_for_logging(event)

        assert isinstance(event.response, ResponsesAPIResponse)
        assert isinstance(event.response.usage, ResponseAPIUsage)
        assert event.response.usage.total_tokens == 8

    def test_streaming_logging_guard_ignores_iterator_without_logging_obj(
        self,
    ) -> None:
        """Skip guard when LiteLLM iterator implementation lacks logging_obj."""

        class IteratorWithoutLoggingObj:
            def __aiter__(self) -> "IteratorWithoutLoggingObj":
                return self

            async def __anext__(self) -> object:
                raise StopAsyncIteration

        guard_litellm_streaming_logging(IteratorWithoutLoggingObj())


class TestLiteLLMResponsesOutputNormalizer:
    """LiteLLM Responses normalizer tests."""

    def test_normalizes_completed_output_items(self) -> None:
        """Convert completed response output item to event."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )
        native_events = [
            NativeEvent(
                type="ResponseCompletedEvent",
                item={
                    "response": {
                        "usage": {
                            "input_tokens": 12,
                            "output_tokens": 7,
                            "total_tokens": 19,
                            "input_tokens_details": {"cached_tokens": 3},
                            "output_tokens_details": {"reasoning_tokens": 2},
                        },
                        "output": [
                            {
                                "type": "message",
                                "content": [{"type": "output_text", "text": "hello"}],
                            },
                            {
                                "type": "reasoning",
                                "summary": [{"text": "summary"}],
                            },
                            {
                                "type": "function_call",
                                "call_id": "call-1",
                                "name": "read_text",
                                "arguments": "{}",
                            },
                            {
                                "type": "web_search_call",
                                "id": "ws-1",
                            },
                            {
                                "type": "image_generation_call",
                                "id": "img-1",
                                "result": "aW1hZ2U=",
                            },
                            {"type": "custom_output", "value": 1},
                        ],
                    }
                },
            )
        ]

        output = normalizer.normalize("session-1", native_events)

        assert [event.kind for event in output.events] == [
            EventKind.ASSISTANT_MESSAGE,
            EventKind.REASONING,
            EventKind.CLIENT_TOOL_CALL,
            EventKind.PROVIDER_TOOL_CALL,
            EventKind.PROVIDER_TOOL_RESULT,
            EventKind.UNKNOWN_ADAPTER_OUTPUT,
        ]
        reasoning = output.events[1].payload
        assert isinstance(reasoning, ReasoningPayload)
        assert reasoning.text is None
        assert reasoning.summary == "summary"
        provider_tool_result = output.events[4].payload
        assert isinstance(provider_tool_result, ProviderToolResultPayload)
        assert provider_tool_result.output == [
            OutputTextPart(
                text=(
                    "Generated image is available as an attachment "
                    "(id: inline:696d616765)."
                )
            )
        ]
        assert provider_tool_result.attachments[0].attachment_id == "inline:696d616765"
        assert "result" not in provider_tool_result.native_artifact.item
        assert output.usage is not None
        assert output.usage.model_dump(mode="json", exclude_none=True) == {
            "prompt_tokens": 12,
            "completion_tokens": 7,
            "total_tokens": 19,
            "raw": {
                "input_tokens": 12,
                "output_tokens": 7,
                "total_tokens": 19,
                "input_tokens_details": {"cached_tokens": 3},
                "output_tokens_details": {"reasoning_tokens": 2},
            },
            "cached_tokens": 3,
            "reasoning_tokens": 2,
        }

    def test_normalizes_chat_usage_shape(self) -> None:
        """Keep LiteLLM chat-style usage details as event usage too."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )

        output = normalizer.normalize(
            "session-1",
            [
                NativeEvent(
                    type="ResponseCompletedEvent",
                    item={
                        "response": {
                            "usage": {
                                "prompt_tokens": 20,
                                "completion_tokens": 4,
                                "total_tokens": 24,
                                "prompt_tokens_details": {"cached_tokens": 8},
                                "completion_tokens_details": {"reasoning_tokens": 2},
                            },
                            "output": [],
                        }
                    },
                )
            ],
        )

        assert output.events == []
        assert output.usage is not None
        assert output.usage.model_dump(mode="json", exclude_none=True) == {
            "prompt_tokens": 20,
            "completion_tokens": 4,
            "total_tokens": 24,
            "raw": {
                "prompt_tokens": 20,
                "completion_tokens": 4,
                "total_tokens": 24,
                "prompt_tokens_details": {"cached_tokens": 8},
                "completion_tokens_details": {"reasoning_tokens": 2},
            },
            "cached_tokens": 8,
            "reasoning_tokens": 2,
        }

    def test_preserves_cache_creation_tokens_from_raw_usage(self) -> None:
        """Cache write token counts are retained for post-hoc cost normalization."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="anthropic",
            model="claude-sonnet-4.5",
        )

        output = normalizer.normalize(
            "session-1",
            [
                NativeEvent(
                    type="ResponseCompletedEvent",
                    item={
                        "response": {
                            "usage": {
                                "input_tokens": 100,
                                "output_tokens": 10,
                                "total_tokens": 110,
                                "cache_creation_input_tokens": 80,
                            },
                            "output": [],
                        }
                    },
                )
            ],
        )

        assert output.usage is not None
        assert output.usage.model_dump(mode="json", exclude_none=True) == {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "total_tokens": 110,
            "raw": {
                "input_tokens": 100,
                "output_tokens": 10,
                "total_tokens": 110,
                "cache_creation_input_tokens": 80,
            },
            "cache_creation_tokens": 80,
        }

    def test_normalizes_cache_creation_and_cost_usage(self) -> None:
        """Cache write/cost fields are preserved as event usage with raw."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )

        output = normalizer.normalize(
            "session-1",
            [
                NativeEvent(
                    type="ResponseCompletedEvent",
                    item={
                        "response": {
                            "usage": {
                                "input_tokens": 20,
                                "output_tokens": 4,
                                "total_tokens": 24,
                                "input_tokens_details": {"cache_creation_tokens": 12},
                                "cost": 0.001,
                            },
                            "output": [],
                        }
                    },
                )
            ],
        )

        assert output.usage is not None
        assert output.usage.cache_creation_tokens == 12
        assert output.usage.cost_usd == 0.001
        assert output.usage.raw == {
            "input_tokens": 20,
            "output_tokens": 4,
            "total_tokens": 24,
            "input_tokens_details": {"cache_creation_tokens": 12},
            "cost": 0.001,
        }

    def test_normalizes_output_item_done_when_completed_response_has_no_output(
        self,
    ) -> None:
        """Convert completed item from ChatGPT OAuth stream to durable message."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )

        output = normalizer.normalize(
            "session-1",
            [
                NativeEvent(
                    type="OutputTextDeltaEvent",
                    item={"delta": "hel"},
                ),
                NativeEvent(
                    type="OutputItemDoneEvent",
                    item={
                        "item": {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "hello",
                                }
                            ],
                        }
                    },
                ),
                NativeEvent(
                    type="ResponseCompletedEvent",
                    item={"response": {"status": "completed"}},
                ),
            ],
        )

        assert [event.kind for event in output.events] == [EventKind.ASSISTANT_MESSAGE]
        payload = output.events[0].payload
        assert isinstance(payload, AssistantMessagePayload)
        assert payload.content == "hello"
        assert output.projections[0].delta == "hel"

    @pytest.mark.parametrize(
        "event_type",
        ["OutputItemDoneEvent", "ResponseOutputItemDoneEvent"],
    )
    def test_normalizes_tool_call_from_output_item_done(self, event_type: str) -> None:
        """Leave completed function_call from ChatGPT OAuth stream as durable."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )

        output = normalizer.normalize(
            "session-1",
            [
                NativeEvent(
                    type=event_type,
                    item={
                        "item": {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "read_text",
                            "arguments": '{"path": "/tmp/example"}',
                        }
                    },
                ),
                NativeEvent(
                    type="ResponseCompletedEvent",
                    item={"response": {"status": "completed"}},
                ),
            ],
        )

        assert [event.kind for event in output.events] == [EventKind.CLIENT_TOOL_CALL]
        payload = output.events[0].payload
        assert isinstance(payload, ClientToolCallPayload)
        assert payload.call_id == "call-1"
        assert payload.name == "read_text"
        assert payload.arguments == '{"path": "/tmp/example"}'

    def test_prefers_completed_response_output_over_output_item_done(self) -> None:
        """Do not duplicate output_item.done when completed response output exists."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )

        output = normalizer.normalize(
            "session-1",
            [
                NativeEvent(
                    type="OutputItemDoneEvent",
                    item={
                        "item": {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "item done",
                                }
                            ],
                        }
                    },
                ),
                NativeEvent(
                    type="ResponseCompletedEvent",
                    item={
                        "response": {
                            "output": [
                                {
                                    "type": "message",
                                    "content": [
                                        {
                                            "type": "output_text",
                                            "text": "response output",
                                        }
                                    ],
                                }
                            ]
                        }
                    },
                ),
            ],
        )

        assert len(output.events) == 1
        payload = output.events[0].payload
        assert isinstance(payload, AssistantMessagePayload)
        assert payload.content == "response output"

    def test_normalizes_reasoning_text_and_summary_separately(self) -> None:
        """Do not mix reasoning content and summary in event payload."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )

        output = normalizer.normalize(
            "session-1",
            [
                NativeEvent(
                    type="ResponseCompletedEvent",
                    item={
                        "response": {
                            "output": [
                                {
                                    "type": "reasoning",
                                    "content": [{"text": "private chain"}],
                                    "summary": [{"text": "audit summary"}],
                                }
                            ]
                        }
                    },
                )
            ],
        )

        reasoning = output.events[0].payload
        assert isinstance(reasoning, ReasoningPayload)
        assert reasoning.text == "private chain"
        assert reasoning.summary == "audit summary"

    @pytest.mark.parametrize(
        ("item_added_type", "delta_type"),
        [
            ("OutputItemAddedEvent", "FunctionCallArgumentsDeltaEvent"),
            (
                "ResponseOutputItemAddedEvent",
                "ResponseFunctionCallArgumentsDeltaEvent",
            ),
        ],
    )
    def test_projects_function_call_delta_with_ref(
        self,
        item_added_type: str,
        delta_type: str,
    ) -> None:
        """Repair call_id/name on function call arguments delta."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )
        output = normalizer.normalize(
            "session-1",
            [
                NativeEvent(
                    type=item_added_type,
                    item={
                        "output_index": 2,
                        "item": {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "read_text",
                        },
                    },
                ),
                NativeEvent(
                    type=delta_type,
                    item={"output_index": 2, "delta": '{"path"'},
                ),
            ],
        )

        assert output.projections[1].call_id == "call-1"
        assert output.projections[1].name == "read_text"
        assert output.projections[1].delta == '{"path"'

    def test_response_prefixed_text_delta_projects_content(self) -> None:
        """Convert text delta containing OpenAI SDK class name to projection too."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )

        output = normalizer.normalize(
            "session-1",
            [
                NativeEvent(
                    type="ResponseTextDeltaEvent",
                    item={"delta": "hello"},
                )
            ],
        )

        assert len(output.projections) == 1
        assert output.projections[0].type == "content_delta"
        assert output.projections[0].delta == "hello"
