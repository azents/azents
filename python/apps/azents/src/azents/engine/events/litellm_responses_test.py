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
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelCompatibilityCapabilities,
    ModelModalities,
    ModelModality,
    ModelReasoningEffort,
)
from azents.core.xai import XAI_API_BASE_URL
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
from azents.engine.events.protocols import (
    NativeEvent,
    NativeModelRequest,
    StreamProjection,
)
from azents.engine.events.system_reminders import (
    format_compaction_summary_reminder,
    format_goal_continuation_reminder,
    format_goal_resumed_reminder,
    format_goal_updated_reminder,
    format_interrupted_reminder,
    format_plain_system_reminder,
    format_system_reminder,
)
from azents.engine.events.types import (
    AgentMessagePayload,
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
    SkillLoadedPayload,
    SystemReminderPayload,
    UserMessagePayload,
    build_native_compat_key,
)
from azents.engine.model_stream import (
    ModelStreamCallContext,
    ModelStreamTimeoutPolicy,
    ModelStreamWatchdog,
)
from azents.engine.run.errors import ModelCallError
from azents.engine.run.types import BuiltinToolSpec
from azents.testing.model_stream import (
    make_test_model_stream_context,
    make_test_model_stream_watchdog,
)


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

    def test_skill_loaded_event_injects_skill_body_before_user_message(self) -> None:
        """Skill loaded events lower to model-visible Skill body injection."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.SKILL_LOADED,
                SkillLoadedPayload(
                    name="review",
                    skill_path="/workspace/agent/app/.claude/skills/review/SKILL.md",
                    body="# Review\nFollow this checklist.",
                    user_message="Review this PR",
                    content_hash="hash-1",
                    source_label="app",
                    relative_hint=".claude/skills/review",
                ),
            ),
            _event(
                EventKind.USER_MESSAGE,
                UserMessagePayload(content="Review this PR"),
            ),
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {
                "role": "user",
                "content": (
                    "Skill `review` has been loaded.\n"
                    "Read and follow the following Skill body.\n"
                    "The user's request is provided in the next user message.\n\n"
                    "Skill path: "
                    "`/workspace/agent/app/.claude/skills/review/SKILL.md`\n\n"
                    "<skill_body>\n"
                    "# Review\nFollow this checklist.\n"
                    "</skill_body>"
                ),
            },
            {"role": "user", "content": "Review this PR"},
        ]

    def test_lowers_agent_message_with_task_envelope(self) -> None:
        """agent_message events become explicit parent-to-child task envelopes."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.AGENT_MESSAGE,
                AgentMessagePayload(
                    message_kind="followup_task",
                    source_session_agent_id="source-agent",
                    source_path="/root",
                    target_session_agent_id="target-agent",
                    target_path="/root/child",
                    content="continue the investigation",
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input[-1] == {
            "role": "user",
            "content": (
                "Message Type: NEW_TASK\n"
                "Task name: /root/child\n"
                "Sender: /root\n"
                "Payload:\n"
                "continue the investigation"
            ),
        }

    def test_lowers_send_message_as_message_envelope(self) -> None:
        """send_message mailbox events render as non-task messages."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.AGENT_MESSAGE,
                AgentMessagePayload(
                    message_kind="send_message",
                    source_session_agent_id="source-agent",
                    source_path="/root",
                    target_session_agent_id="target-agent",
                    target_path="/root/child",
                    content="status note",
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input[-1] == {
            "role": "user",
            "content": (
                "Message Type: MESSAGE\n"
                "Task name: /root/child\n"
                "Sender: /root\n"
                "Payload:\n"
                "status note"
            ),
        }

    def test_openai_prompt_cache_key_uses_session_scope(self) -> None:
        """OpenAI prompt cache key is stable and scoped to the session."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
            provider_id=LLMProvider.OPENAI,
            prompt_cache_scope="session-1",
        )

        request = lowerer.lower([], model="gpt-5.1")

        key = request.kwargs.get("prompt_cache_key")
        assert isinstance(key, str)
        assert key.startswith("azs:")
        assert len(key) <= 64
        assert (
            key
            == LiteLLMResponsesLowerer(
                provider="openai",
                model="gpt-5.1",
                provider_id=LLMProvider.OPENAI,
                prompt_cache_scope="session-1",
            )
            .lower([], model="gpt-5.1")
            .kwargs["prompt_cache_key"]
        )
        assert (
            key
            != LiteLLMResponsesLowerer(
                provider="openai",
                model="gpt-5.1",
                provider_id=LLMProvider.OPENAI,
                prompt_cache_scope="session-2",
            )
            .lower([], model="gpt-5.1")
            .kwargs["prompt_cache_key"]
        )

    def test_openai_prompt_cache_key_respects_explicit_kwargs(self) -> None:
        """Explicit provider kwargs keep their default/overridden cache behavior."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
            provider_id=LLMProvider.OPENAI,
            kwargs={"prompt_cache_key": "custom-key"},
            prompt_cache_scope="session-1",
        )

        request = lowerer.lower([], model="gpt-5.1")

        assert request.kwargs["prompt_cache_key"] == "custom-key"

    def test_non_openai_does_not_force_prompt_cache_key(self) -> None:
        """Providers without request-level cache key support keep defaults."""
        lowerer = LiteLLMResponsesLowerer(
            provider="anthropic",
            model="claude-sonnet-4-5",
            provider_id=LLMProvider.ANTHROPIC,
            prompt_cache_scope="session-1",
        )

        request = lowerer.lower([], model="claude-sonnet-4-5")

        assert "prompt_cache_key" not in request.kwargs

    @pytest.mark.parametrize("provider_id", [LLMProvider.XAI, LLMProvider.XAI_OAUTH])
    def test_xai_sets_provider_and_endpoint_kwargs(
        self,
        provider_id: LLMProvider,
    ) -> None:
        """Both xAI credential modes use the xAI Responses transport."""
        lowerer = LiteLLMResponsesLowerer(
            provider=provider_id.value,
            model="grok-4.5",
            provider_id=provider_id,
            credential_kwargs={
                "api_key": "test-key",
                "base_url": XAI_API_BASE_URL,
            },
        )

        request = lowerer.lower([], model="xai/grok-4.5")

        assert request.kwargs["custom_llm_provider"] == "xai"
        assert request.kwargs["base_url"] == XAI_API_BASE_URL
        assert request.kwargs["api_base"] == XAI_API_BASE_URL

    @pytest.mark.parametrize("provider_id", [LLMProvider.XAI, LLMProvider.XAI_OAUTH])
    def test_xai_does_not_add_anthropic_cache_control(
        self,
        provider_id: LLMProvider,
    ) -> None:
        """xAI requests keep Anthropic cache-control hints disabled."""
        lowerer = LiteLLMResponsesLowerer(
            provider=provider_id.value,
            model="grok-4.5",
            provider_id=provider_id,
            model_developer=LLMModelDeveloper.XAI,
            tools=[
                {
                    "type": "function",
                    "name": "read",
                    "description": "Read a file",
                    "parameters": {"type": "object"},
                }
            ],
        )

        request = lowerer.lower(
            [
                _event(EventKind.USER_MESSAGE, UserMessagePayload(content="one")),
                _event(EventKind.USER_MESSAGE, UserMessagePayload(content="two")),
            ],
            model="xai/grok-4.5",
        )

        assert "cache_control" not in request.tools[-1]
        assert request.input[-2] == {"role": "user", "content": "one"}
        assert request.input[-1] == {"role": "user", "content": "two"}

    def test_chatgpt_oauth_requests_encrypted_reasoning_content(self) -> None:
        """ChatGPT OAuth requests encrypted reasoning for stateless replay."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1-codex",
            provider_id=LLMProvider.CHATGPT_OAUTH,
        )

        request = lowerer.lower([], model="gpt-5.1-codex")

        assert request.kwargs["include"] == ["reasoning.encrypted_content"]
        assert request.kwargs["store"] is False

    def test_chatgpt_oauth_responses_lite_uses_saved_capability_contract(
        self,
    ) -> None:
        """Lower Responses Lite entirely from the saved model capability snapshot."""
        capabilities = ModelCapabilities(
            modalities=ModelModalities(input=[ModelModality.IMAGE]),
            compatibility=ModelCompatibilityCapabilities(responses_lite=True),
        )
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.6-luna",
            provider_id=LLMProvider.CHATGPT_OAUTH,
            model_capabilities=capabilities,
            prompt_cache_scope="00000000-0000-0000-0000-000000000001",
            credential_kwargs={
                "extra_headers": {
                    "originator": "azents",
                    "ChatGPT-Account-Id": "account-id",
                }
            },
            reasoning_effort="high",
            tools=[
                {
                    "type": "function",
                    "name": "inspect_image",
                    "description": "Inspect an image",
                    "parameters": {"type": "object"},
                }
            ],
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

        request = lowerer.lower(
            transcript,
            model="gpt-5.6-luna",
            system_prompt="Be useful.",
        )

        assert request.tools == []
        assert request.input[:2] == [
            {
                "type": "additional_tools",
                "role": "developer",
                "tools": [
                    {
                        "type": "function",
                        "name": "inspect_image",
                        "description": "Inspect an image",
                        "parameters": {"type": "object"},
                    }
                ],
            },
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "Be useful."}],
            },
        ]
        assert request.input[2] == {
            "type": "function_call",
            "call_id": "call-1",
            "name": "inspect_image",
            "arguments": "{}",
        }
        assert request.input[3] == {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": [
                {
                    "type": "input_image",
                    "image_url": "data:image/png;base64,abc",
                }
            ],
        }
        assert request.kwargs["parallel_tool_calls"] is False
        assert request.kwargs["store"] is False
        assert request.kwargs["reasoning"] == {
            "effort": "high",
            "summary": "auto",
            "context": "all_turns",
        }
        assert request.kwargs["prompt_cache_key"] == (
            "00000000-0000-0000-0000-000000000001"
        )
        assert request.kwargs["extra_headers"] == {
            "originator": "azents",
            "ChatGPT-Account-Id": "account-id",
            "session-id": "00000000-0000-0000-0000-000000000001",
            "x-session-affinity": "00000000-0000-0000-0000-000000000001",
            "version": "0.144.0",
            "x-openai-internal-codex-responses-lite": "true",
        }

    def test_chatgpt_oauth_responses_lite_omits_empty_instructions(self) -> None:
        """Explicitly empty Lite instructions do not create a developer message."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.6-luna",
            provider_id=LLMProvider.CHATGPT_OAUTH,
            model_capabilities=ModelCapabilities(
                compatibility=ModelCompatibilityCapabilities(responses_lite=True)
            ),
            prompt_cache_scope="session-1",
        )

        request = lowerer.lower([], model="gpt-5.6-luna", system_prompt="")

        assert request.input == [
            {
                "type": "additional_tools",
                "role": "developer",
                "tools": [],
            }
        ]

    def test_chatgpt_oauth_standard_responses_ignores_lite_model_name(self) -> None:
        """A Lite-looking model name does not select the Lite transport."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.6-luna",
            provider_id=LLMProvider.CHATGPT_OAUTH,
            model_capabilities=ModelCapabilities(),
            prompt_cache_scope="session-1",
        )

        request = lowerer.lower([], model="gpt-5.6-luna", system_prompt="Be useful.")

        assert request.input == []
        assert request.tools == []
        assert request.kwargs["instructions"] == "Be useful."
        assert "parallel_tool_calls" not in request.kwargs
        assert "extra_headers" not in request.kwargs

    def test_chatgpt_oauth_preserves_existing_include_values(self) -> None:
        """Append encrypted reasoning include without dropping caller values."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1-codex",
            provider_id=LLMProvider.CHATGPT_OAUTH,
            kwargs={"include": ["file_search_call.results"]},
        )

        request = lowerer.lower([], model="gpt-5.1-codex")

        assert request.kwargs["include"] == [
            "file_search_call.results",
            "reasoning.encrypted_content",
        ]

    def test_anthropic_adds_cache_control_hints_to_prefix(self) -> None:
        """Claude targets receive cache_control hints on stable prefix blocks."""
        lowerer = LiteLLMResponsesLowerer(
            provider="anthropic",
            model="claude-sonnet-4-5",
            provider_id=LLMProvider.ANTHROPIC,
            tools=[
                {
                    "type": "function",
                    "name": "read",
                    "description": "Read a file",
                    "parameters": {"type": "object"},
                }
            ],
        )
        transcript = [
            _event(EventKind.USER_MESSAGE, UserMessagePayload(content="one")),
            _event(EventKind.USER_MESSAGE, UserMessagePayload(content="two")),
        ]

        request = lowerer.lower(transcript, model="claude-sonnet-4-5")

        assert request.tools[-1]["cache_control"] == {"type": "ephemeral"}
        assert request.input[0]["content"] == [
            {
                "type": "input_text",
                "text": "one",
                "cache_control": {"type": "ephemeral"},
            }
        ]
        assert request.input[1]["content"] == [
            {
                "type": "input_text",
                "text": "two",
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def test_anthropic_cache_control_preserves_existing_hints(self) -> None:
        """Do not overwrite explicit cache_control provided by callers/providers."""
        lowerer = LiteLLMResponsesLowerer(
            provider="anthropic",
            model="claude-sonnet-4-5",
            provider_id=LLMProvider.ANTHROPIC,
            tools=[
                {
                    "type": "function",
                    "name": "read",
                    "description": "Read a file",
                    "parameters": {"type": "object"},
                    "cache_control": {"type": "ephemeral", "ttl": "1h"},
                }
            ],
        )

        request = lowerer.lower(
            [_event(EventKind.USER_MESSAGE, UserMessagePayload(content="hello"))],
            model="claude-sonnet-4-5",
        )

        assert request.tools[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
        assert request.input[0]["content"] == [
            {
                "type": "input_text",
                "text": "hello",
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def test_anthropic_skips_tool_call_items_for_cache_control(self) -> None:
        """Tool call/result items are not cache_control breakpoints."""
        lowerer = LiteLLMResponsesLowerer(
            provider="anthropic",
            model="claude-sonnet-4-5",
            provider_id=LLMProvider.ANTHROPIC,
        )
        transcript = [
            _event(
                EventKind.CLIENT_TOOL_CALL,
                ClientToolCallPayload(
                    call_id="call-1",
                    name="read",
                    arguments="{}",
                    native_artifact=_artifact(
                        {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "read",
                            "arguments": "{}",
                        }
                    ),
                ),
            ),
            _event(
                EventKind.CLIENT_TOOL_RESULT,
                ClientToolResultPayload(
                    call_id="call-1",
                    name="read",
                    status="completed",
                    output=[OutputTextPart(text="ok")],
                ),
            ),
            _event(EventKind.USER_MESSAGE, UserMessagePayload(content="next")),
        ]

        request = lowerer.lower(transcript, model="claude-sonnet-4-5")

        assert "cache_control" not in request.input[0]
        assert "cache_control" not in request.input[1]
        assert request.input[2]["content"] == [
            {
                "type": "input_text",
                "text": "next",
                "cache_control": {"type": "ephemeral"},
            }
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

    def test_lowers_plain_system_reminder_with_hyphenated_envelope(self) -> None:
        """Lower a plain system reminder to the model-facing envelope."""
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
                "content": format_plain_system_reminder("Use <safe> mode & continue."),
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
                    metadata={"process_id": "proc_123", "status": "exited_unread"},
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

    def test_masks_native_provider_item_id_when_store_is_false(self) -> None:
        """Mask unstored provider response item ids consistently."""
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

        assert request.input == [{"type": "reasoning", "id": None, "summary": []}]
        assert request.kwargs["store"] is False

    def test_masks_native_item_id_but_keeps_call_id_when_store_is_false(
        self,
    ) -> None:
        """Preserve tool continuity while masking unstored provider item ids."""
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
                "id": None,
                "call_id": "call-1",
                "name": "read_text",
                "arguments": "{}",
            }
        ]
        assert request.kwargs["store"] is False

    def test_masks_all_response_item_ids_when_store_is_false(self) -> None:
        """Mask ids on native and canonical input items for unstored responses."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
            provider_id=LLMProvider.CHATGPT_OAUTH,
        )
        transcript = [
            _event(
                EventKind.USER_MESSAGE,
                UserMessagePayload(content="hello"),
            ),
            _event(
                EventKind.ASSISTANT_MESSAGE,
                AssistantMessagePayload(
                    content="done",
                    native_artifact=_artifact(
                        {
                            "type": "message",
                            "id": "msg-1",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "done",
                                }
                            ],
                        }
                    ),
                ),
            ),
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
            ),
            _event(
                EventKind.CLIENT_TOOL_RESULT,
                ClientToolResultPayload(
                    call_id="call-1",
                    name="read_text",
                    status="completed",
                    output="result",
                ),
            ),
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {"role": "user", "content": "hello"},
            {
                "type": "message",
                "id": None,
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "done",
                    }
                ],
            },
            {
                "type": "function_call",
                "id": None,
                "call_id": "call-1",
                "name": "read_text",
                "arguments": "{}",
            },
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "result",
            },
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

    @pytest.mark.parametrize(
        ("provider", "provider_id"),
        [
            ("xai", LLMProvider.XAI),
            ("xai_oauth", LLMProvider.XAI_OAUTH),
            ("xai", None),
        ],
    )
    def test_lowers_instructions_to_input_message_when_required(
        self,
        provider: str,
        provider_id: LLMProvider | None,
    ) -> None:
        """Use a system input message when top-level instructions are unsupported."""
        lowerer = LiteLLMResponsesLowerer(
            provider=provider,
            model="grok-4.20-0309-reasoning",
            provider_id=provider_id,
        )
        transcript = [
            _event(
                EventKind.USER_MESSAGE,
                UserMessagePayload(content="hello"),
            )
        ]

        request = lowerer.lower(
            transcript,
            model="xai/grok-4.20-0309-reasoning",
            system_prompt="Follow project rules.",
        )

        assert "instructions" not in request.kwargs
        assert request.input == [
            {"role": "system", "content": "Follow project rules."},
            {"role": "user", "content": "hello"},
        ]

    def test_uses_default_input_message_instructions_when_required(self) -> None:
        """Preserve default instructions for input-message instruction transport."""
        lowerer = LiteLLMResponsesLowerer(
            provider="xai_oauth",
            model="grok-4.20-0309-reasoning",
            provider_id=LLMProvider.XAI_OAUTH,
        )

        request = lowerer.lower([], model="xai/grok-4.20-0309-reasoning")

        assert "instructions" not in request.kwargs
        assert request.input == [
            {"role": "system", "content": "You are a helpful assistant."}
        ]

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

    def test_lowers_hosted_tools_in_deterministic_order(self) -> None:
        """Sort hosted tools by semantic name/config before provider request."""
        capabilities = ModelCapabilities()
        capabilities.built_in_tools.supported = ["web_search"]
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
            provider_id=LLMProvider.OPENAI,
            hosted_tools=[
                BuiltinToolSpec(
                    name="web_search", config={"search_context_size": "low"}
                ),
                BuiltinToolSpec(name="web_search", config={}),
            ],
            model_capabilities=capabilities,
        )

        request = lowerer.lower([], model="gpt-5.1")

        assert request.tools == [
            {"type": "web_search"},
            {"type": "web_search", "search_context_size": "low"},
        ]

    @pytest.mark.parametrize("provider_id", [LLMProvider.XAI, LLMProvider.XAI_OAUTH])
    def test_lowers_xai_web_search_hosted_tool(
        self,
        provider_id: LLMProvider,
    ) -> None:
        """Lower web search identically for both xAI credential modes."""
        capabilities = ModelCapabilities()
        capabilities.built_in_tools.supported = ["web_search"]
        lowerer = LiteLLMResponsesLowerer(
            provider=provider_id.value,
            model="grok-4.5",
            provider_id=provider_id,
            hosted_tools=[BuiltinToolSpec(name="web_search", config={})],
            model_capabilities=capabilities,
        )

        request = lowerer.lower([], model="xai/grok-4.5")

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


class _TestLiteLLMResponsesModelAdapter(LiteLLMResponsesModelAdapter):
    """Bind standard watchdog inputs for adapter behavior tests."""

    async def stream(
        self,
        request: NativeModelRequest,
        *,
        watchdog: ModelStreamWatchdog | None = None,
        timeout_policy: ModelStreamTimeoutPolicy | None = None,
        call_context: ModelStreamCallContext | None = None,
    ) -> AsyncIterator[LiteLLMEvent]:
        """Run the production adapter with the standard test policy."""
        effective_watchdog = watchdog or make_test_model_stream_watchdog()
        effective_policy = timeout_policy or effective_watchdog.resolve_policy(
            provider="test",
            model=request.model,
            inference_profile=None,
        )
        async for event in super().stream(
            request,
            watchdog=effective_watchdog,
            timeout_policy=effective_policy,
            call_context=call_context or make_test_model_stream_context(),
        ):
            yield event


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
        adapter = _TestLiteLLMResponsesModelAdapter()

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

    async def test_stream_preserves_responses_lite_extensions(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pass Responses Lite reasoning and header extensions through LiteLLM."""
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
        adapter = _TestLiteLLMResponsesModelAdapter()

        _ = [
            event
            async for event in adapter.stream(
                NativeModelRequest(
                    model="gpt-5.6-luna",
                    input=[],
                    kwargs={
                        "reasoning": {
                            "effort": "high",
                            "summary": "auto",
                            "context": "all_turns",
                        },
                        "parallel_tool_calls": False,
                        "extra_headers": {
                            "x-openai-internal-codex-responses-lite": "true"
                        },
                    },
                )
            )
        ]

        assert captured["reasoning"] == {
            "effort": "high",
            "summary": "auto",
            "context": "all_turns",
        }
        assert captured["parallel_tool_calls"] is False
        assert captured["extra_headers"] == {
            "x-openai-internal-codex-responses-lite": "true"
        }
        assert captured["stream"] is True

    async def test_stream_accepts_max_reasoning_effort(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pass the catalog's maximum reasoning effort through the SDK boundary."""
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
        adapter = _TestLiteLLMResponsesModelAdapter()

        _ = [
            event
            async for event in adapter.stream(
                NativeModelRequest(
                    model="gpt-5.6-sol",
                    input=[],
                    kwargs={
                        "reasoning": {
                            "effort": ModelReasoningEffort.MAX,
                            "summary": "auto",
                        }
                    },
                )
            )
        ]

        assert captured["reasoning"] == {
            "effort": ModelReasoningEffort.MAX,
            "summary": "auto",
        }

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
        adapter = _TestLiteLLMResponsesModelAdapter()

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
        adapter = _TestLiteLLMResponsesModelAdapter()

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
        adapter = _TestLiteLLMResponsesModelAdapter()

        with pytest.raises(ModelCallError, match="Model call failed \\(503\\)"):
            _ = [
                event
                async for event in adapter.stream(
                    NativeModelRequest(model="gpt-5.1-codex", input=[]),
                )
            ]

    async def test_request_validation_error_stays_internal(self) -> None:
        """Propagate adapter request validation failure as internal error."""
        adapter = _TestLiteLLMResponsesModelAdapter()

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
        adapter = _TestLiteLLMResponsesModelAdapter()

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
        adapter = _TestLiteLLMResponsesModelAdapter()

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
        adapter = _TestLiteLLMResponsesModelAdapter()

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

    def test_processes_live_deltas_before_stream_completion(self) -> None:
        """Return text and reasoning projections one native event at a time."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )
        output_stream = normalizer.start("session-1")

        text = output_stream.process_event(
            NativeEvent(type="OutputTextDeltaEvent", item={"delta": "hello"})
        )
        reasoning = output_stream.process_event(
            NativeEvent(
                type="ReasoningSummaryTextDeltaEvent",
                item={"delta": "thinking"},
            )
        )

        assert text.events == []
        assert text.projections == [
            StreamProjection(type="content_delta", delta="hello")
        ]
        assert reasoning.events == []
        assert reasoning.projections == [
            StreamProjection(type="reasoning_delta", delta="thinking")
        ]

    def test_interrupt_preserves_received_partial_assistant_text(self) -> None:
        """Create one incomplete assistant event from received text deltas."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )
        output_stream = normalizer.start("session-1")
        output_stream.process_event(
            NativeEvent(type="OutputTextDeltaEvent", item={"delta": "hel"})
        )
        output_stream.process_event(
            NativeEvent(type="ResponseTextDeltaEvent", item={"delta": "lo"})
        )

        interrupted = output_stream.interrupt()

        assert interrupted.needs_follow_up is False
        assert len(interrupted.events) == 1
        payload = interrupted.events[0].payload
        assert isinstance(payload, AssistantMessagePayload)
        assert payload.content == "hello"
        assert payload.native_artifact.item == {
            "type": "message",
            "status": "incomplete",
            "content": [{"type": "output_text", "text": "hello"}],
        }
        assert payload.native_artifact.schema_version == "1-partial"

        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        request = lowerer.lower(interrupted.events, model="gpt-5.1")

        assert request.input == [{"role": "assistant", "content": "hello"}]

    def test_withholds_tool_call_until_stream_completion(self) -> None:
        """Do not expose a completed tool call as durable output mid-stream."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )
        output_stream = normalizer.start("session-1")

        incremental = output_stream.process_event(
            NativeEvent(
                type="OutputItemDoneEvent",
                item={
                    "item": {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "read_text",
                        "arguments": '{"path": "/tmp/example"}',
                    }
                },
            )
        )

        assert incremental.events == []
        output_stream.process_event(
            NativeEvent(
                type="ResponseCompletedEvent",
                item={"response": {"output": []}},
            )
        )
        completed = output_stream.complete()
        assert [event.kind for event in completed.events] == [
            EventKind.CLIENT_TOOL_CALL
        ]

    def test_rejects_completed_output_item_without_terminal_event(self) -> None:
        """Do not treat output-item completion as response completion."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )
        output_stream = normalizer.start("session-1")
        output_stream.process_event(
            NativeEvent(
                type="OutputItemDoneEvent",
                item={
                    "item": {
                        "type": "reasoning",
                        "summary": [{"text": "unfinished"}],
                    }
                },
            )
        )

        with pytest.raises(
            ModelCallError,
            match="stream ended before completion",
        ):
            output_stream.complete()

    def test_rejects_empty_stream_without_terminal_event(self) -> None:
        """Reject EOF when no native response terminal event was observed."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )
        output_stream = normalizer.start("session-1")

        with pytest.raises(
            ModelCallError,
            match="stream ended before completion",
        ):
            output_stream.complete()

    @pytest.mark.parametrize(
        ("event_type", "item", "message"),
        [
            (
                "ResponseIncompleteEvent",
                {"response": {"incomplete_details": {"reason": "max_output_tokens"}}},
                "Model response was incomplete: max_output_tokens",
            ),
            (
                "ResponseFailedEvent",
                {
                    "response": {
                        "error": {
                            "message": "Provider rejected the response",
                            "code": "provider_failed",
                        }
                    }
                },
                (
                    "Model response failed: Provider rejected the response; "
                    "code: provider_failed"
                ),
            ),
            (
                "ResponseErrorEvent",
                {
                    "message": "Provider stream failed",
                    "code": "stream_failed",
                },
                "Model call failed: Provider stream failed; code: stream_failed",
            ),
        ],
    )
    def test_rejects_unsuccessful_terminal_event(
        self,
        event_type: str,
        item: dict[str, object],
        message: str,
    ) -> None:
        """Convert native unsuccessful terminal outcomes to model errors."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )
        output_stream = normalizer.start("session-1")
        output_stream.process_event(
            NativeEvent(
                type="OutputItemDoneEvent",
                item={
                    "item": {
                        "type": "reasoning",
                        "summary": [{"text": "unfinished"}],
                    }
                },
            )
        )
        output_stream.process_event(NativeEvent(type=event_type, item=item))

        with pytest.raises(ModelCallError, match=message):
            output_stream.complete()

    def test_interrupt_does_not_mask_unsuccessful_terminal_event(self) -> None:
        """Keep provider failure authoritative over later cancellation."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )
        output_stream = normalizer.start("session-1")
        output_stream.process_event(
            NativeEvent(
                type="ResponseIncompleteEvent",
                item={
                    "response": {"incomplete_details": {"reason": "max_output_tokens"}}
                },
            )
        )

        with pytest.raises(ModelCallError, match="max_output_tokens"):
            output_stream.interrupt()

    def test_bounds_unsuccessful_terminal_details(self) -> None:
        """Keep provider terminal details bounded and scalar-only."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
        )
        output_stream = normalizer.start("session-1")
        output_stream.process_event(
            NativeEvent(
                type="ResponseErrorEvent",
                item={
                    "message": "x" * 600,
                    "code": {"raw": "not user safe"},
                },
            )
        )

        with pytest.raises(ModelCallError) as raised:
            output_stream.complete()

        assert str(raised.value) == f"Model call failed: {'x' * 512}"

    def test_accepts_explicitly_completed_reasoning_only_response(self) -> None:
        """Keep explicit completed reasoning-only output in current scope."""
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
                                    "summary": [{"text": "completed reasoning"}],
                                }
                            ]
                        }
                    },
                )
            ],
        )

        assert [event.kind for event in output.events] == [EventKind.REASONING]

    @pytest.mark.parametrize(
        ("end_turn", "expected_follow_up"),
        [
            (False, True),
            (True, False),
            (None, False),
            ("false", False),
            (0, False),
        ],
    )
    def test_maps_optional_end_turn_to_follow_up(
        self,
        end_turn: object,
        expected_follow_up: bool,
    ) -> None:
        """Continue only when a completed response explicitly sets end_turn false."""
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
                            "end_turn": end_turn,
                            "output": [
                                {
                                    "type": "message",
                                    "content": [
                                        {"type": "output_text", "text": "continue"}
                                    ],
                                }
                            ],
                        }
                    },
                )
            ],
        )

        assert output.needs_follow_up is expected_follow_up

    def test_missing_end_turn_does_not_request_follow_up(self) -> None:
        """Keep existing completion behavior when the provider omits end_turn."""
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
                                    "type": "message",
                                    "content": [
                                        {"type": "output_text", "text": "done"}
                                    ],
                                }
                            ]
                        }
                    },
                )
            ],
        )

        assert output.needs_follow_up is False

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

    def test_normalizes_hidden_params_cost_usage(self) -> None:
        """LiteLLM hidden params are preserved for cache hit analysis."""
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
                            },
                            "_hidden_params": {
                                "response_cost": 0.002,
                                "cache_hit": True,
                                "model_id": "gpt-5.1",
                            },
                            "output": [],
                        }
                    },
                )
            ],
        )

        assert output.usage is not None
        assert output.usage.cost_usd == 0.002
        assert output.usage.raw_hidden_params == {
            "response_cost": 0.002,
            "cache_hit": True,
            "model_id": "gpt-5.1",
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
                NativeEvent(
                    type="ResponseCompletedEvent",
                    item={"response": {"output": []}},
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
                ),
                NativeEvent(
                    type="ResponseCompletedEvent",
                    item={"response": {"output": []}},
                ),
            ],
        )

        assert len(output.projections) == 1
        assert output.projections[0].type == "content_delta"
        assert output.projections[0].delta == "hello"
