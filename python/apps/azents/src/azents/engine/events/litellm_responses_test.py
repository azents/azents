"""LiteLLM Responses adapter tests."""

import asyncio
import datetime
import logging
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
from openai import OpenAIError as OpenAIBaseError
from pydantic import ValidationError

from azents.core.enums import (
    AgentRunStatus,
    EventKind,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
    LLMModelDeveloper,
    LLMProvider,
)
from azents.core.llm_catalog import (
    ModelCapabilities,
    ModelModalities,
    ModelModality,
    ModelReasoningEffort,
)
from azents.core.openrouter import OPENROUTER_API_BASE_URL, OPENROUTER_APP_TITLE
from azents.core.xai import XAI_API_BASE_URL
from azents.engine.events.file_parts import ModelFileLoweringContent
from azents.engine.events.litellm_responses import (
    LiteLLMEvent,
    LiteLLMResponsesLowerer,
    LiteLLMResponsesModelAdapter,
    LiteLLMResponsesOutputNormalizer,
    coerce_litellm_completed_response_for_logging,
    guard_litellm_streaming_logging,
    map_litellm_provider_error,
)
from azents.engine.events.protocols import (
    ContentDeltaProjection,
    FunctionCallDeltaProjection,
    NativeEvent,
    NativeModelRequest,
    ProviderToolActivityProjection,
    ReasoningDeltaProjection,
)
from azents.engine.events.responses_continuation import ResponsesContinuationPlanner
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
    AttachmentOutputPart,
    ClientToolCallPayload,
    ClientToolResultPayload,
    CompactionSummaryPayload,
    Event,
    EventPayload,
    ExternalChannelMessagePayload,
    FileOutputPart,
    GoalBriefingPayload,
    InputTextPart,
    InterruptedPayload,
    NativeArtifact,
    OutputTextPart,
    ProviderToolCallPayload,
    ProviderToolReference,
    ProviderToolSemanticContent,
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
from azents.engine.run.builtin_tools import UnsupportedRequiredBuiltinToolError
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
    UnclassifiedModelProviderError,
)
from azents.engine.run.types import BuiltinToolSpec
from azents.testing.model_stream import (
    make_test_model_stream_context,
    make_test_model_stream_watchdog,
)

_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ"
    "/pLvAAAAAElFTkSuQmCC"
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


def _openai_artifact(item: dict[str, object]) -> NativeArtifact:
    """Create official SDK native artifact for cross-adapter tests."""
    return NativeArtifact(
        compat_key=build_native_compat_key(
            adapter="openai",
            native_format="responses",
            provider="openai",
            model="gpt-5.1",
            schema_version="1",
        ),
        adapter="openai",
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


def _external_payload(
    *,
    message_id: str,
    revision_id: str,
    batch_id: str,
    body: str | None,
) -> ExternalChannelMessagePayload:
    """Create one deterministic external message payload."""
    return ExternalChannelMessagePayload(
        provider=ExternalChannelProvider.SLACK,
        provider_tenant_id="tenant-1",
        resource_id="resource-1",
        resource_label="#incident / thread",
        resource_type=ExternalChannelResourceType.THREAD,
        binding_id="binding-1",
        invocation_batch_id=batch_id,
        external_message_id=message_id,
        revision_id=revision_id,
        revision_kind=(
            ExternalChannelMessageRevisionKind.DELETE
            if body is None
            else ExternalChannelMessageRevisionKind.ORIGINAL
        ),
        projection_root_id=f"external-channel:binding-1:{message_id}",
        provider_message_key=f"slack:tenant-1:C1:{message_id}",
        provider_position=f"000000000000000000{message_id}.000001",
        principal_id="principal-1",
        provider_user_id="U1",
        sender_display_name="Alice",
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        authorization="authorized_invocation",
        lifecycle=(
            ExternalChannelMessageLifecycle.DELETED
            if body is None
            else ExternalChannelMessageLifecycle.CURRENT
        ),
        body=body,
        attachment_metadata={},
        provider_created_at=datetime.datetime(2026, 7, 22, 12, 0, tzinfo=datetime.UTC),
        provider_updated_at=None,
        original_url=None,
        truncated_context_message_count=0,
        truncated_context_size=0,
        correction_of_revision_id=None,
    )


def _response_stream_event(
    event_type: str,
    item: dict[str, object],
) -> object:
    """Create a model-dumpable event with the requested native class name."""

    class TestResponseEvent:
        def model_dump(self) -> dict[str, object]:
            """Return the fixed native event payload."""
            return item

    TestResponseEvent.__name__ = event_type
    return TestResponseEvent()


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
                    wire_dialect="json_function",
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

    def test_lowers_agent_result_as_terminal_envelope(self) -> None:
        """Terminal mailbox events render status without internal IDs."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        transcript = [
            _event(
                EventKind.AGENT_MESSAGE,
                AgentMessagePayload(
                    message_kind="agent_result",
                    source_session_agent_id="source-agent",
                    source_path="/root/reviewer",
                    target_session_agent_id="target-agent",
                    target_path="/root",
                    source_run_id="1" * 32,
                    source_run_index=2,
                    run_status=AgentRunStatus.COMPLETED,
                    source_terminal_result_event_id="2" * 32,
                    content="No blocking issues.",
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input[-1] == {
            "role": "user",
            "content": (
                "Message Type: AGENT_RESULT\n"
                "Task name: /root\n"
                "Sender: /root/reviewer\n"
                "Run status: completed\n"
                "Payload:\n"
                "No blocking issues."
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

    def test_openrouter_sets_provider_endpoint_and_attribution_kwargs(self) -> None:
        """OpenRouter stays on LiteLLM Responses with fixed credential kwargs."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openrouter",
            model="anthropic/claude-sonnet-4.6",
            provider_id=LLMProvider.OPENROUTER,
            credential_kwargs={
                "api_key": "test-key",
                "base_url": OPENROUTER_API_BASE_URL,
                "extra_headers": {
                    "X-OpenRouter-Title": OPENROUTER_APP_TITLE,
                },
            },
        )

        request = lowerer.lower(
            [],
            model="openrouter/anthropic/claude-sonnet-4.6",
        )

        assert request.kwargs["custom_llm_provider"] == "openrouter"
        assert request.kwargs["base_url"] == OPENROUTER_API_BASE_URL
        assert request.kwargs["api_base"] == OPENROUTER_API_BASE_URL
        assert request.kwargs["extra_headers"] == {
            "X-OpenRouter-Title": OPENROUTER_APP_TITLE,
        }

    def test_openrouter_claude_does_not_add_anthropic_cache_control(self) -> None:
        """OpenRouter wire semantics override the selected model developer."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openrouter",
            model="anthropic/claude-sonnet-4.6",
            provider_id=LLMProvider.OPENROUTER,
            model_developer=LLMModelDeveloper.ANTHROPIC,
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
            [_event(EventKind.USER_MESSAGE, UserMessagePayload(content="hello"))],
            model="openrouter/anthropic/claude-sonnet-4.6",
        )

        assert "cache_control" not in request.tools[-1]
        assert request.input == [{"role": "user", "content": "hello"}]

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

    def test_chatgpt_oauth_uses_standard_responses_request(self) -> None:
        """ChatGPT requests retain top-level tools and instructions."""
        tool: dict[str, object] = {
            "type": "function",
            "name": "lookup",
            "description": "Look up a value",
            "parameters": {"type": "object"},
        }
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.6-luna",
            provider_id=LLMProvider.CHATGPT_OAUTH,
            prompt_cache_scope="session-1",
            tools=[tool],
        )

        request = lowerer.lower([], model="gpt-5.6-luna", system_prompt="Be useful.")

        assert request.input == []
        assert request.tools == [tool]
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
                    wire_dialect="json_function",
                ),
            ),
            _event(
                EventKind.CLIENT_TOOL_RESULT,
                ClientToolResultPayload(
                    call_id="call-1",
                    name="read",
                    status="completed",
                    output=[OutputTextPart(text="ok")],
                    wire_dialect="json_function",
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

    def test_custom_tool_call_drops_cross_dialect_output(self) -> None:
        """Do not pair a custom call with a JSON-function result sharing its ID."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
            tools=[
                {
                    "type": "custom",
                    "name": "apply_patch",
                    "description": "Apply a patch.",
                    "format": {"type": "text"},
                }
            ],
        )
        transcript = [
            _event(
                EventKind.CLIENT_TOOL_CALL,
                ClientToolCallPayload(
                    call_id="call-custom",
                    name="apply_patch",
                    arguments="opaque-custom-input",
                    wire_dialect="plaintext_custom",
                    native_artifact=_artifact(
                        {
                            "type": "custom_tool_call",
                            "call_id": "call-custom",
                            "name": "apply_patch",
                            "input": "opaque-custom-input",
                        }
                    ),
                ),
            ),
            _event(
                EventKind.CLIENT_TOOL_RESULT,
                ClientToolResultPayload(
                    call_id="call-custom",
                    name="apply_patch",
                    wire_dialect="json_function",
                    status="completed",
                    output="completed",
                ),
            ),
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {
                "type": "custom_tool_call",
                "call_id": "call-custom",
                "name": "apply_patch",
                "input": "opaque-custom-input",
            }
        ]

    def test_completed_custom_history_is_non_executable_on_later_route(self) -> None:
        """Project a completed custom pair without emitting custom wire items."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
            tools=[
                {
                    "type": "function",
                    "name": "apply_patch",
                    "description": "Apply a patch.",
                    "parameters": {"type": "object"},
                }
            ],
        )
        transcript = [
            _event(
                EventKind.CLIENT_TOOL_CALL,
                ClientToolCallPayload(
                    call_id="call-custom",
                    name="apply_patch",
                    arguments="opaque-custom-input",
                    wire_dialect="plaintext_custom",
                    native_artifact=_artifact(
                        {
                            "type": "custom_tool_call",
                            "call_id": "call-custom",
                            "name": "apply_patch",
                            "input": "opaque-custom-input",
                        }
                    ),
                ),
            ),
            _event(
                EventKind.CLIENT_TOOL_RESULT,
                ClientToolResultPayload(
                    call_id="call-custom",
                    name="apply_patch",
                    wire_dialect="plaintext_custom",
                    status="completed",
                    output="completed",
                ),
            ),
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {
                "role": "assistant",
                "content": (
                    "[Historical custom tool call: apply_patch. "
                    "Input omitted; non-executable history.]"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "[Historical custom tool result: apply_patch. "
                    "Non-executable history.]\ncompleted"
                ),
            },
        ]
        assert all(item.get("type") != "custom_tool_call" for item in request.input)
        assert all("opaque-custom-input" not in str(item) for item in request.input)

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
                    wire_dialect="json_function",
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
                    wire_dialect="json_function",
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
                    wire_dialect="json_function",
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
                    wire_dialect="json_function",
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

    @pytest.mark.parametrize(
        "provider_id",
        [None, LLMProvider.CHATGPT_OAUTH],
        ids=["stored", "chatgpt-store-false"],
    )
    def test_rehydrates_compatible_image_generation_result(
        self,
        provider_id: LLMProvider | None,
    ) -> None:
        """Restore a valid generated-image item in same-native request memory."""
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
            provider_id=provider_id,
            model_file_resolver=_StaticModelFileResolver(
                ModelFileLoweringContent(
                    data_url="data:image/jpeg;base64,cmVoeWRyYXRlZA=="
                )
            ),
        )
        transcript = [
            _event(
                EventKind.PROVIDER_TOOL_CALL,
                ProviderToolCallPayload(
                    call_id="image-call-1",
                    name="image_generation",
                    status="completed",
                    semantic=ProviderToolSemanticContent(
                        input=None,
                        output=[
                            FileOutputPart(
                                model_file_id="model-file-1",
                                media_type="image/jpeg",
                                name="generated.jpg",
                                size=123,
                                kind="image",
                            ),
                            AttachmentOutputPart(
                                attachment_id="attachment-1",
                                uri="exchange://generated-image",
                                name="generated.jpg",
                                media_type="image/jpeg",
                                size=123,
                            ),
                        ],
                        references=[],
                    ),
                    native_artifact=_artifact(
                        {
                            "type": "image_generation_call",
                            "id": "image-call-1",
                            "status": "completed",
                            "action": "generate",
                            "revised_prompt": "output-only prompt",
                            "provider_extension": "output-only value",
                        }
                    ),
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        expected_item: dict[str, object] = {
            "type": "image_generation_call",
            "status": "completed",
            "result": "cmVoeWRyYXRlZA==",
        }
        if provider_id != LLMProvider.CHATGPT_OAUTH:
            expected_item["id"] = "image-call-1"
        assert request.input == [
            expected_item,
            {
                "role": "assistant",
                "content": (
                    "[Provider tool call: image_generation completed]\n"
                    "Output:\n"
                    "Attachment: generated.jpg (image/jpeg, 123 bytes)\n"
                    "URI: exchange://generated-image"
                ),
            },
        ]
        assert request.kwargs.get("store") is (
            False if provider_id == LLMProvider.CHATGPT_OAUTH else None
        )

    def test_cross_adapter_image_generation_uses_rich_file_fallback(self) -> None:
        """Lower incompatible generated output with rich image and URI context."""
        capabilities = ModelCapabilities(
            modalities=ModelModalities(input=[ModelModality.IMAGE])
        )
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
            model_capabilities=capabilities,
            model_file_resolver=_StaticModelFileResolver(
                ModelFileLoweringContent(
                    data_url="data:image/jpeg;base64,cmVoeWRyYXRlZA=="
                )
            ),
        )
        transcript = [
            _event(
                EventKind.PROVIDER_TOOL_CALL,
                ProviderToolCallPayload(
                    call_id="image-call-1",
                    name="image_generation",
                    status="completed",
                    semantic=ProviderToolSemanticContent(
                        input=None,
                        output=[
                            FileOutputPart(
                                model_file_id="model-file-1",
                                media_type="image/jpeg",
                                name="generated.jpg",
                                size=123,
                                kind="image",
                            ),
                            AttachmentOutputPart(
                                attachment_id="attachment-1",
                                uri="exchange://generated-image",
                                name="generated.jpg",
                                media_type="image/jpeg",
                                size=123,
                            ),
                        ],
                        references=[],
                    ),
                    native_artifact=_openai_artifact(
                        {
                            "type": "image_generation_call",
                            "id": "image-call-1",
                            "status": "completed",
                        }
                    ),
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "[Provider tool call: image_generation completed]\n"
                            "Output:\n"
                            "Attachment: generated.jpg (image/jpeg, 123 bytes)\n"
                            "URI: exchange://generated-image"
                        ),
                    },
                    {
                        "type": "input_image",
                        "detail": "auto",
                        "image_url": ("data:image/jpeg;base64,cmVoeWRyYXRlZA=="),
                    },
                ],
            }
        ]

    def test_cross_adapter_image_generation_uses_explicit_placeholder(self) -> None:
        """Describe generated images explicitly for models without image input."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="text-only")
        transcript = [
            _event(
                EventKind.PROVIDER_TOOL_CALL,
                ProviderToolCallPayload(
                    call_id="image-call-1",
                    name="image_generation",
                    status="completed",
                    semantic=ProviderToolSemanticContent(
                        input=None,
                        output=[
                            FileOutputPart(
                                model_file_id="model-file-1",
                                media_type="image/jpeg",
                                name="generated.jpg",
                                size=123,
                                kind="image",
                            )
                        ],
                        references=[],
                    ),
                    native_artifact=_openai_artifact(
                        {
                            "type": "image_generation_call",
                            "id": "image-call-1",
                            "status": "completed",
                        }
                    ),
                ),
            )
        ]

        request = lowerer.lower(transcript, model="text-only")

        assert request.input[0]["content"] == [
            {
                "type": "input_text",
                "text": "[Provider tool call: image_generation completed]",
            },
            {
                "type": "input_text",
                "text": (
                    "[file unavailable for rich input] generated.jpg "
                    "(image/jpeg, 123 bytes). Reason: model does not support "
                    "this file input."
                ),
            },
        ]

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
                    wire_dialect="json_function",
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
                    wire_dialect="json_function",
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
                    wire_dialect="json_function",
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
                    wire_dialect="json_function",
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
                    wire_dialect="json_function",
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
                    status="completed",
                    semantic=ProviderToolSemanticContent(
                        input=None,
                        output=[],
                        references=[],
                    ),
                    native_artifact=_artifact(raw_item),
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [raw_item]

    def test_rebuilds_same_native_image_generation_result_artifact(self) -> None:
        """Rebuild provider image output as a valid Responses input item."""
        lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
        raw_item: dict[str, object] = {
            "type": "image_generation_call",
            "id": "img-1",
            "status": "completed",
            "action": "generate",
            "provider_extension": "output-only value",
        }
        transcript = [
            _event(
                EventKind.PROVIDER_TOOL_CALL,
                ProviderToolCallPayload(
                    call_id="img-1",
                    name="image_generation",
                    status="completed",
                    semantic=ProviderToolSemanticContent(
                        input=None,
                        output="Generated image",
                        references=[],
                    ),
                    native_artifact=_artifact(raw_item),
                ),
            )
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {
                "type": "image_generation_call",
                "id": "img-1",
                "status": "completed",
                "result": None,
            }
        ]

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

    def test_omits_native_provider_item_id_when_store_is_false(self) -> None:
        """Omit unstored provider response item ids consistently."""
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

    def test_omits_native_item_id_but_keeps_call_id_when_store_is_false(
        self,
    ) -> None:
        """Preserve tool continuity while omitting unstored provider item ids."""
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
                    wire_dialect="json_function",
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

    def test_omits_all_response_item_ids_when_store_is_false(self) -> None:
        """Omit ids on native and canonical input items for unstored responses."""
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
                    wire_dialect="json_function",
                ),
            ),
            _event(
                EventKind.CLIENT_TOOL_RESULT,
                ClientToolResultPayload(
                    call_id="call-1",
                    name="read_text",
                    status="completed",
                    output="result",
                    wire_dialect="json_function",
                ),
            ),
        ]

        request = lowerer.lower(transcript, model="gpt-5.1")

        assert request.input == [
            {"role": "user", "content": "hello"},
            {
                "type": "message",
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
                    wire_dialect="json_function",
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

    @pytest.mark.parametrize(
        "provider_id",
        [LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH],
    )
    def test_lowers_openai_compatible_web_search_hosted_tool(
        self,
        provider_id: LLMProvider,
    ) -> None:
        """Lower hosted web search into the standard Responses tools field."""
        capabilities = ModelCapabilities()
        capabilities.built_in_tools.supported = ["web_search"]
        lowerer = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.6-luna",
            provider_id=provider_id,
            hosted_tools=[BuiltinToolSpec(name="web_search", config={})],
            model_capabilities=capabilities,
        )

        request = lowerer.lower([], model="gpt-5.6-luna")

        assert request.tools == [{"type": "web_search"}]

    @pytest.mark.parametrize(
        "provider_id",
        [LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH],
    )
    def test_lowers_openai_compatible_image_generation_hosted_tool(
        self,
        provider_id: LLMProvider,
    ) -> None:
        """Lower hosted image generation into the Responses tools field."""
        capabilities = ModelCapabilities()
        capabilities.built_in_tools.supported = ["image_generation"]
        lowerer = LiteLLMResponsesLowerer(
            provider=provider_id.value,
            model="gpt-5.6-luna",
            provider_id=provider_id,
            hosted_tools=[
                BuiltinToolSpec(
                    name="image_generation",
                    config={"quality": "high", "size": "1024x1024"},
                )
            ],
            model_capabilities=capabilities,
        )

        request = lowerer.lower([], model="gpt-5.6-luna")

        assert request.tools == [
            {
                "type": "image_generation",
                "quality": "high",
                "size": "1024x1024",
            }
        ]

    def test_lowers_explicit_litellm_image_generation_capability(self) -> None:
        """Pass the semantic Responses tool to a known LiteLLM target."""
        capabilities = ModelCapabilities()
        capabilities.built_in_tools.supported = ["image_generation"]
        lowerer = LiteLLMResponsesLowerer(
            provider="anthropic",
            model="future-image-model",
            provider_id=LLMProvider.ANTHROPIC,
            hosted_tools=[BuiltinToolSpec(name="image_generation", config={})],
            model_capabilities=capabilities,
        )

        request = lowerer.lower([], model="future-image-model")

        assert request.tools == [{"type": "image_generation"}]

    def test_image_generation_on_unknown_litellm_target_fails(self) -> None:
        """Fail instead of silently omitting an unsupported target."""
        capabilities = ModelCapabilities()
        capabilities.built_in_tools.supported = ["image_generation"]
        lowerer = LiteLLMResponsesLowerer(
            provider="unknown",
            model="future-image-model",
            hosted_tools=[BuiltinToolSpec(name="image_generation", config={})],
            model_capabilities=capabilities,
        )

        with pytest.raises(UnsupportedRequiredBuiltinToolError):
            lowerer.lower([], model="future-image-model")

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

    def test_lowers_openrouter_web_search_hosted_tool(self) -> None:
        """Lower OpenRouter web search to the current server-tool namespace."""
        capabilities = ModelCapabilities()
        capabilities.built_in_tools.supported = ["web_search"]
        lowerer = LiteLLMResponsesLowerer(
            provider="openrouter",
            model="anthropic/claude-sonnet-4.6",
            provider_id=LLMProvider.OPENROUTER,
            model_developer=LLMModelDeveloper.ANTHROPIC,
            hosted_tools=[BuiltinToolSpec(name="web_search", config={})],
            model_capabilities=capabilities,
        )

        request = lowerer.lower(
            [],
            model="openrouter/anthropic/claude-sonnet-4.6",
        )

        assert request.tools == [{"type": "openrouter:web_search"}]

    def test_openrouter_image_generation_hosted_tool_fails(self) -> None:
        """Keep unverified OpenRouter image generation disabled."""
        capabilities = ModelCapabilities()
        capabilities.built_in_tools.supported = ["image_generation"]
        lowerer = LiteLLMResponsesLowerer(
            provider="openrouter",
            model="openai/gpt-5-image",
            provider_id=LLMProvider.OPENROUTER,
            hosted_tools=[BuiltinToolSpec(name="image_generation", config={})],
            model_capabilities=capabilities,
        )

        with pytest.raises(UnsupportedRequiredBuiltinToolError):
            lowerer.lower([], model="openrouter/openai/gpt-5-image")

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
                    status=None,
                    semantic=ProviderToolSemanticContent(
                        input='{"query":"docs"}',
                        output=[OutputTextPart(text="search complete")],
                        references=[
                            ProviderToolReference(
                                kind="url",
                                uri="https://example.com/docs",
                                title="Docs",
                                excerpt=None,
                                metadata={},
                            )
                        ],
                    ),
                    native_artifact=_artifact({"type": "web_search_call"}),
                ),
            ),
            _event(
                EventKind.PROVIDER_TOOL_CALL,
                ProviderToolCallPayload(
                    call_id="img-1",
                    name="image_generation",
                    status="completed",
                    semantic=ProviderToolSemanticContent(
                        input="generate a diagram",
                        output=[
                            OutputTextPart(text="generated image"),
                        ],
                        references=[
                            ProviderToolReference(
                                kind="file",
                                uri=None,
                                title="diagram.png",
                                excerpt="Generated diagram",
                                metadata={"file_id": "file-1"},
                            )
                        ],
                    ),
                    native_artifact=_artifact({"type": "image_generation_call"}),
                ),
            ),
        ]

        request = lowerer.lower(transcript, model="claude")

        assert request.input == [
            {
                "role": "assistant",
                "content": (
                    "[Provider tool call: web_search]\n"
                    "Input:\n"
                    '{"query":"docs"}\n'
                    "Output:\n"
                    "search complete\n"
                    "References:\n"
                    "- url: https://example.com/docs\n"
                    "  Title: Docs"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "[Provider tool call: image_generation completed]\n"
                    "Input:\n"
                    "generate a diagram\n"
                    "Output:\n"
                    "generated image\n"
                    "References:\n"
                    "- file: diagram.png\n"
                    "  Excerpt:\n"
                    "    Generated diagram\n"
                    '  Metadata: {"file_id":"file-1"}'
                ),
            },
        ]


class _TestLiteLLMResponsesModelAdapter(LiteLLMResponsesModelAdapter):
    """Bind standard watchdog inputs for adapter behavior tests."""

    def __init__(
        self,
        continuation_planner: ResponsesContinuationPlanner | None = None,
    ) -> None:
        super().__init__(continuation_planner)

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

    async def test_stream_forwards_openrouter_server_tool_and_headers(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Preserve OpenRouter-only Responses fields across LiteLLM validation."""
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
                    model="openrouter/anthropic/claude-sonnet-4.6",
                    input=[],
                    tools=[{"type": "openrouter:web_search"}],
                    kwargs={
                        "custom_llm_provider": "openrouter",
                        "api_key": "openrouter-test-key",
                        "base_url": OPENROUTER_API_BASE_URL,
                        "api_base": OPENROUTER_API_BASE_URL,
                        "extra_headers": {
                            "X-OpenRouter-Title": OPENROUTER_APP_TITLE,
                        },
                    },
                )
            )
        ]

        assert captured["tools"] == [{"type": "openrouter:web_search"}]
        assert captured["custom_llm_provider"] == "openrouter"
        assert captured["base_url"] == OPENROUTER_API_BASE_URL
        assert captured["api_base"] == OPENROUTER_API_BASE_URL
        assert captured["extra_headers"] == {
            "X-OpenRouter-Title": OPENROUTER_APP_TITLE,
        }

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

    async def test_stream_continues_with_previous_response_and_delta_input(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Send only new tool output after an exact completed response boundary."""
        caplog.set_level(
            logging.INFO,
            logger="azents.engine.events.litellm_responses",
        )
        calls: list[dict[str, object]] = []
        function_call = {
            "type": "function_call",
            "id": "fc-1",
            "call_id": "call-1",
            "name": "read",
            "arguments": "{}",
        }

        async def streaming_call(**kwargs: object) -> object:
            calls.append(kwargs)
            response_id = f"resp-{len(calls)}"

            async def response_iter() -> AsyncIterator[object]:
                if len(calls) == 1:
                    yield _response_stream_event(
                        "ResponseOutputItemDoneEvent",
                        {"item": function_call},
                    )
                yield _response_stream_event(
                    "ResponseCompletedEvent",
                    {"response": {"id": response_id, "output": []}},
                )

            return response_iter()

        monkeypatch.setattr(
            "azents.engine.events.litellm_responses.aresponses",
            streaming_call,
        )
        adapter = _TestLiteLLMResponsesModelAdapter(ResponsesContinuationPlanner())
        first = NativeModelRequest(
            model="gpt-5.1",
            input=[{"role": "user", "content": "read"}],
            kwargs={"store": True},
        )
        tool_output = {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": "contents",
        }
        second = first.model_copy(
            update={"input": [*first.input, function_call, tool_output]}
        )

        _ = [event async for event in adapter.stream(first)]
        _ = [event async for event in adapter.stream(second)]

        assert calls[0]["input"] == first.input
        assert calls[0]["previous_response_id"] is None
        assert calls[1]["input"] == [tool_output]
        assert calls[1]["previous_response_id"] == "resp-1"
        assert [
            record.__dict__["previous_response_id_supplied"]
            for record in caplog.records
            if record.message == "Dispatching OpenAI Responses request"
        ] == [False, True]

    async def test_stream_does_not_continue_without_successful_terminal_response(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Do not commit state when a stream ends without response.completed."""
        calls: list[dict[str, object]] = []

        async def streaming_call(**kwargs: object) -> object:
            calls.append(kwargs)

            async def response_iter() -> AsyncIterator[object]:
                if False:
                    yield object()

            return response_iter()

        monkeypatch.setattr(
            "azents.engine.events.litellm_responses.aresponses",
            streaming_call,
        )
        adapter = _TestLiteLLMResponsesModelAdapter(ResponsesContinuationPlanner())
        first = NativeModelRequest(
            model="gpt-5.1",
            input=[{"role": "user", "content": "first"}],
        )
        second = NativeModelRequest(
            model="gpt-5.1",
            input=[*first.input, {"role": "user", "content": "second"}],
        )

        _ = [event async for event in adapter.stream(first)]
        _ = [event async for event in adapter.stream(second)]

        assert calls[1]["input"] == second.input
        assert calls[1]["previous_response_id"] is None

    async def test_failed_continuation_discards_the_prior_boundary(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Use full input after an incremental stream reaches a failed terminal."""
        calls: list[dict[str, object]] = []
        function_call = {
            "type": "function_call",
            "id": "fc-1",
            "call_id": "call-1",
            "name": "read",
            "arguments": "{}",
        }

        async def streaming_call(**kwargs: object) -> object:
            calls.append(kwargs)

            async def response_iter() -> AsyncIterator[object]:
                if len(calls) == 1:
                    yield _response_stream_event(
                        "ResponseCompletedEvent",
                        {"response": {"id": "resp-1", "output": [function_call]}},
                    )
                elif len(calls) == 2:
                    yield _response_stream_event(
                        "ResponseIncompleteEvent",
                        {"response": {"id": "resp-2", "output": []}},
                    )

            return response_iter()

        monkeypatch.setattr(
            "azents.engine.events.litellm_responses.aresponses",
            streaming_call,
        )
        adapter = _TestLiteLLMResponsesModelAdapter(ResponsesContinuationPlanner())
        first = NativeModelRequest(
            model="gpt-5.1",
            input=[{"role": "user", "content": "read"}],
            kwargs={"store": True},
        )
        tool_output = {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": "contents",
        }
        second = first.model_copy(
            update={"input": [*first.input, function_call, tool_output]}
        )
        third = second.model_copy(
            update={"input": [*second.input, {"role": "user", "content": "retry"}]}
        )

        _ = [event async for event in adapter.stream(first)]
        _ = [event async for event in adapter.stream(second)]
        _ = [event async for event in adapter.stream(third)]

        assert calls[1]["previous_response_id"] == "resp-1"
        assert calls[2]["previous_response_id"] is None
        assert calls[2]["input"] == third.input

    async def test_missing_previous_response_retries_full_request_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Recover a rejected stored response by disabling and retrying full input."""
        caplog.set_level(
            logging.INFO,
            logger="azents.engine.events.litellm_responses",
        )
        calls: list[dict[str, object]] = []
        function_call = {
            "type": "function_call",
            "id": "fc-1",
            "call_id": "call-1",
            "name": "read",
            "arguments": "{}",
        }

        async def streaming_call(**kwargs: object) -> object:
            calls.append(kwargs)
            if kwargs.get("previous_response_id") == "resp-1":
                raise BadRequestError(
                    message="Previous response was not found",
                    model="gpt-5.1",
                    llm_provider="openai",
                    body={
                        "error": {
                            "code": "previous_response_not_found",
                            "message": "Previous response was not found",
                        }
                    },
                )

            async def response_iter() -> AsyncIterator[object]:
                yield _response_stream_event(
                    "ResponseCompletedEvent",
                    {
                        "response": {
                            "id": f"resp-{len(calls)}",
                            "output": [function_call] if len(calls) == 1 else [],
                        }
                    },
                )

            return response_iter()

        monkeypatch.setattr(
            "azents.engine.events.litellm_responses.aresponses",
            streaming_call,
        )
        adapter = _TestLiteLLMResponsesModelAdapter(ResponsesContinuationPlanner())
        first = NativeModelRequest(
            model="gpt-5.1",
            input=[{"role": "user", "content": "read"}],
            kwargs={"store": True},
        )
        tool_output = {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": "contents",
        }
        second = first.model_copy(
            update={"input": [*first.input, function_call, tool_output]}
        )

        _ = [event async for event in adapter.stream(first)]
        _ = [event async for event in adapter.stream(second)]

        assert len(calls) == 3
        assert calls[1]["input"] == [tool_output]
        assert calls[1]["previous_response_id"] == "resp-1"
        assert calls[2]["input"] == second.input
        assert calls[2]["previous_response_id"] is None
        assert [
            record.__dict__["previous_response_id_supplied"]
            for record in caplog.records
            if record.message == "Dispatching OpenAI Responses request"
        ] == [False, True, False]

    async def test_litellm_bad_request_is_provider_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Normalize a provider-attributed 400 into the common contract."""

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

        with pytest.raises(
            ModelProviderFailure,
            match="Instructions are required",
        ) as raised:
            _ = [
                event
                async for event in adapter.stream(
                    NativeModelRequest(model="gpt-5.1-codex", input=[]),
                    call_context=ModelStreamCallContext(
                        call_kind="sampling",
                        provider="openai",
                        provider_integration_id="integration-001",
                        model="gpt-5.1-codex",
                        session_id="session-1",
                        run_id="run-1",
                        attempt_number=1,
                        check_stop=None,
                    ),
                )
            ]

        assert raised.value.category is ModelProviderFailureCategory.INVALID_REQUEST
        assert raised.value.status_code == 400
        assert raised.value.integration == "integration-001"

    async def test_unclassified_sdk_error_is_safely_normalized(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Preserve safe provider diagnostics without raw SDK serialization."""
        original = OpenAIBaseError("synthetic unclassified SDK failure")

        async def fail_call(**kwargs: object) -> object:
            del kwargs
            raise original

        monkeypatch.setattr(
            "azents.engine.events.litellm_responses.aresponses",
            fail_call,
        )
        adapter = _TestLiteLLMResponsesModelAdapter()

        with pytest.raises(UnclassifiedModelProviderError) as raised:
            _ = [
                event
                async for event in adapter.stream(
                    NativeModelRequest(model="gpt-5.1-codex", input=[]),
                )
            ]

        assert raised.value.provider_message == "synthetic unclassified SDK failure"
        assert raised.value.provider_error_type == "OpenAIError"
        assert raised.value.fingerprint

    def test_direct_litellm_error_body_ignores_sdk_serialization(self) -> None:
        """Direct typed body fields win over LiteLLM's serialized message."""
        failure = map_litellm_provider_error(
            BadRequestError(
                message=(
                    "Error code: 400 - {'error': {'message': 'Request rejected'}}"
                ),
                model="gpt-5.1-codex",
                llm_provider="openai",
                body={
                    "message": "Request rejected",
                    "type": "invalid_request_error",
                    "code": "invalid_request",
                },
            ),
            call_context=ModelStreamCallContext(
                call_kind="sampling",
                provider="openai",
                provider_integration_id="integration-001",
                model="gpt-5.1-codex",
                session_id="session-1",
                run_id="run-1",
                attempt_number=1,
                check_stop=None,
            ),
        )

        assert failure is not None
        assert failure.provider_message == "Request rejected"
        assert failure.provider_code == "invalid_request"
        assert failure.provider_error_type == "invalid_request_error"
        assert "Error code" not in failure.user_message

    def test_serialized_litellm_error_extracts_only_typed_provider_fields(
        self,
    ) -> None:
        """Recover bounded diagnostics when LiteLLM omits its typed body."""
        failure = map_litellm_provider_error(
            BadRequestError(
                message=(
                    "Error code: 400 - {'error': {'message': "
                    "'Request rejected api_key=sk-abcdefghijk', "
                    "'type': 'invalid_request_error', "
                    "'code': 'invalid_request'}}"
                ),
                model="openrouter/google/gemini-3.5-flash",
                llm_provider="openrouter",
            ),
            call_context=ModelStreamCallContext(
                call_kind="sampling",
                provider="openrouter",
                provider_integration_id="integration-001",
                model="openrouter/google/gemini-3.5-flash",
                session_id="session-1",
                run_id="run-1",
                attempt_number=1,
                check_stop=None,
            ),
        )

        assert failure is not None
        assert failure.provider_message == "Request rejected api_key=[REDACTED]"
        assert failure.provider_code == "invalid_request"
        assert failure.provider_error_type == "invalid_request_error"

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

        with pytest.raises(
            ModelProviderFailure,
            match="Model provider error: Missing scopes",
        ) as raised:
            _ = [
                event
                async for event in adapter.stream(
                    NativeModelRequest(model="gpt-5.1-codex", input=[]),
                )
            ]

        assert raised.value.category is ModelProviderFailureCategory.AUTHENTICATION
        assert raised.value.status_code == 401

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

        with pytest.raises(
            ModelProviderFailure,
            match="Model provider error: provider unavailable",
        ) as raised:
            _ = [
                event
                async for event in adapter.stream(
                    NativeModelRequest(model="gpt-5.1-codex", input=[]),
                )
            ]

        assert (
            raised.value.category is ModelProviderFailureCategory.PROVIDER_UNAVAILABLE
        )
        assert raised.value.status_code == 503

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
            operation="sampling",
            integration=None,
        )
        output_stream = normalizer.start("session-1")

        text = output_stream.process_event(
            NativeEvent(type="OutputTextDeltaEvent", item={"delta": "hello"})
        )
        reasoning = output_stream.process_event(
            NativeEvent(
                type="ReasoningSummaryTextDeltaEvent",
                item={
                    "delta": "thinking",
                    "item_id": "rs_1",
                    "output_index": 2,
                    "summary_index": 1,
                },
            )
        )

        assert text.events == []
        assert text.projections == [ContentDeltaProjection(delta="hello")]
        assert reasoning.events == []
        assert reasoning.projections == [
            ReasoningDeltaProjection(
                delta="thinking",
                item_id="rs_1",
                output_index=2,
                summary_index=1,
            )
        ]

    def test_projects_provider_tool_lifecycle(self) -> None:
        """Translate LiteLLM hosted-tool stages to canonical snapshots."""
        output_stream = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
            operation="sampling",
            integration=None,
        ).start("session-1")

        running = output_stream.process_event(
            NativeEvent(
                type="ResponseWebSearchCallSearchingEvent",
                item={"item_id": "search-1", "output_index": 0},
            )
        )
        completed = output_stream.process_event(
            NativeEvent(
                type="ResponseWebSearchCallCompletedEvent",
                item={"item_id": "search-1", "output_index": 0},
            )
        )
        duplicate = output_stream.process_event(
            NativeEvent(
                type="ResponseWebSearchCallCompletedEvent",
                item={"item_id": "search-1", "output_index": 0},
            )
        )

        assert running.projections == [
            ProviderToolActivityProjection(
                call_id="search-1",
                name="web_search",
                status="running",
                arguments=None,
            )
        ]
        assert completed.projections == [
            ProviderToolActivityProjection(
                call_id="search-1",
                name="web_search",
                status="completed",
                arguments=None,
            )
        ]
        assert duplicate.projections == []

    def test_projects_generic_provider_tool_output_items(self) -> None:
        """Treat generic output-item completion as a hosted-tool terminal state."""
        output_stream = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
            operation="sampling",
            integration=None,
        ).start("session-1")

        running = output_stream.process_event(
            NativeEvent(
                type="ResponseOutputItemAddedEvent",
                item={
                    "item": {
                        "type": "web_search_call",
                        "id": "search-1",
                        "status": "in_progress",
                    }
                },
            )
        )
        completed = output_stream.process_event(
            NativeEvent(
                type="ResponseOutputItemDoneEvent",
                item={
                    "item": {
                        "type": "web_search_call",
                        "id": "search-1",
                        "status": "in_progress",
                    }
                },
            )
        )
        incomplete = output_stream.process_event(
            NativeEvent(
                type="ResponseOutputItemDoneEvent",
                item={
                    "item": {
                        "type": "file_search_call",
                        "id": "search-2",
                        "status": "incomplete",
                    }
                },
            )
        )

        assert running.projections == [
            ProviderToolActivityProjection(
                call_id="search-1",
                name="web_search",
                status="running",
                arguments=None,
            )
        ]
        assert completed.projections == [
            ProviderToolActivityProjection(
                call_id="search-1",
                name="web_search",
                status="completed",
                arguments=None,
            )
        ]
        assert incomplete.projections == [
            ProviderToolActivityProjection(
                call_id="search-2",
                name="file_search",
                status="failed",
                arguments=None,
            )
        ]

    def test_interrupt_preserves_received_partial_assistant_text(self) -> None:
        """Create one incomplete assistant event from received text deltas."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
            operation="sampling",
            integration=None,
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
            operation="sampling",
            integration=None,
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
            operation="sampling",
            integration=None,
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
            ModelProviderFailure,
            match="stream ended before completion",
        ) as raised:
            output_stream.complete()

        assert raised.value.category is ModelProviderFailureCategory.TRANSPORT
        assert raised.value.provider_code == "stream_ended_before_completion"

    def test_rejects_empty_stream_without_terminal_event(self) -> None:
        """Reject EOF when no native response terminal event was observed."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
            operation="sampling",
            integration=None,
        )
        output_stream = normalizer.start("session-1")

        with pytest.raises(
            ModelProviderFailure,
            match="stream ended before completion",
        ) as raised:
            output_stream.complete()

        assert raised.value.category is ModelProviderFailureCategory.TRANSPORT
        assert raised.value.provider_code == "stream_ended_before_completion"

    @pytest.mark.parametrize(
        ("event_type", "item", "message", "category", "provider_code"),
        [
            (
                "ResponseIncompleteEvent",
                {"response": {"incomplete_details": {"reason": "max_output_tokens"}}},
                (
                    "Model provider error: The model response reached its output "
                    "token limit."
                ),
                ModelProviderFailureCategory.INVALID_REQUEST,
                "max_output_tokens",
            ),
        ],
    )
    def test_rejects_unsuccessful_terminal_event(
        self,
        event_type: str,
        item: dict[str, object],
        message: str,
        category: ModelProviderFailureCategory,
        provider_code: str,
    ) -> None:
        """Convert native unsuccessful terminal outcomes to model errors."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
            operation="sampling",
            integration=None,
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

        with pytest.raises(ModelProviderFailure, match=message) as raised:
            output_stream.complete()

        assert raised.value.category is category
        assert raised.value.provider_code == provider_code

    @pytest.mark.parametrize(
        ("event_type", "item", "expected_detail"),
        [
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
                    "provider_code=provider_failed, "
                    "provider_error_type=response_failed, "
                    "provider_message=Provider rejected the response"
                ),
            ),
            (
                "ResponseErrorEvent",
                {
                    "message": "Provider stream failed",
                    "code": "stream_failed",
                },
                (
                    "provider_code=stream_failed, "
                    "provider_error_type=response_error, "
                    "provider_message=Provider stream failed"
                ),
            ),
            (
                "ResponseErrorEvent",
                {},
                "provider_error_type=response_error",
            ),
        ],
    )
    def test_unclassified_terminal_event_is_internal(
        self,
        event_type: str,
        item: dict[str, object],
        expected_detail: str,
    ) -> None:
        """Unclassified terminal events bypass provider-failure recovery."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
            operation="sampling",
            integration=None,
        )
        output_stream = normalizer.start("session-1")

        with pytest.raises(UnclassifiedModelProviderError, match=expected_detail):
            output_stream.process_event(NativeEvent(type=event_type, item=item))

    def test_interrupt_does_not_mask_unsuccessful_terminal_event(self) -> None:
        """Keep provider failure authoritative over later cancellation."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
            operation="sampling",
            integration=None,
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

        with pytest.raises(
            ModelProviderFailure,
            match="The model response reached its output token limit",
        ) as raised:
            output_stream.interrupt()

        assert raised.value.category is ModelProviderFailureCategory.INVALID_REQUEST
        assert raised.value.provider_code == "max_output_tokens"

    def test_bounds_unclassified_terminal_details(self) -> None:
        """Keep internal provider diagnostics bounded and scalar-only."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
            operation="sampling",
            integration=None,
        )
        output_stream = normalizer.start("session-1")

        with pytest.raises(UnclassifiedModelProviderError) as raised:
            output_stream.process_event(
                NativeEvent(
                    type="ResponseErrorEvent",
                    item={
                        "message": "x" * 1200,
                        "code": {"raw": "not user safe"},
                    },
                )
            )

        assert raised.value.provider_message == "x" * 1000
        assert raised.value.provider_code is None
        assert str(raised.value).endswith("provider_message=" + ("x" * 1000))

    def test_accepts_explicitly_completed_reasoning_only_response(self) -> None:
        """Keep explicit completed reasoning-only output in current scope."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
            operation="sampling",
            integration=None,
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
            operation="sampling",
            integration=None,
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
            operation="sampling",
            integration=None,
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
            operation="sampling",
            integration=None,
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
                                "type": "custom_tool_call",
                                "call_id": "call-custom",
                                "name": "apply_patch",
                                "input": "opaque-custom-input",
                            },
                            {
                                "type": "web_search_call",
                                "id": "ws-1",
                            },
                            {
                                "type": "image_generation_call",
                                "id": "img-1",
                                "result": _PNG_BASE64,
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
            EventKind.CLIENT_TOOL_CALL,
            EventKind.PROVIDER_TOOL_CALL,
            EventKind.PROVIDER_TOOL_CALL,
            EventKind.UNKNOWN_ADAPTER_OUTPUT,
        ]
        reasoning = output.events[1].payload
        assert isinstance(reasoning, ReasoningPayload)
        assert reasoning.text is None
        assert reasoning.summary == "summary"
        custom_call = output.events[3].payload
        assert isinstance(custom_call, ClientToolCallPayload)
        assert custom_call.arguments == "opaque-custom-input"
        assert custom_call.wire_dialect == "plaintext_custom"
        provider_tool_call = output.events[5].payload
        assert isinstance(provider_tool_call, ProviderToolCallPayload)
        assert provider_tool_call.output == []
        assert "result" not in provider_tool_call.native_artifact.item
        assert len(output.pending_provider_files) == 1
        pending = output.pending_provider_files[0]
        assert pending.call_id == "img-1"
        assert pending.media_type == "image/png"
        assert pending.body.startswith(b"\x89PNG")
        assert "body" not in output.model_dump(mode="json")
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
            operation="sampling",
            integration=None,
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
            operation="sampling",
            integration=None,
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
            operation="sampling",
            integration=None,
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
            operation="sampling",
            integration=None,
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
            operation="sampling",
            integration=None,
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
        projection = output.projections[0]
        assert isinstance(projection, ContentDeltaProjection)
        assert projection.delta == "hel"

    @pytest.mark.parametrize(
        "event_type",
        ["OutputItemDoneEvent", "ResponseOutputItemDoneEvent"],
    )
    def test_normalizes_tool_call_from_output_item_done(self, event_type: str) -> None:
        """Leave completed function_call from ChatGPT OAuth stream as durable."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
            operation="sampling",
            integration=None,
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
            operation="sampling",
            integration=None,
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
            operation="sampling",
            integration=None,
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
                                    "id": "rs_1",
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
        assert reasoning.native_artifact.item["output_index"] == 0

        request = LiteLLMResponsesLowerer(
            provider="openai",
            model="gpt-5.1",
        ).lower(output.events, model="gpt-5.1")
        assert request.input == [
            {
                "type": "reasoning",
                "id": "rs_1",
                "content": [{"text": "private chain"}],
                "summary": [{"text": "audit summary"}],
            }
        ]

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
            operation="sampling",
            integration=None,
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

        projection = output.projections[1]
        assert isinstance(projection, FunctionCallDeltaProjection)
        assert projection.call_id == "call-1"
        assert projection.name == "read_text"
        assert projection.delta == '{"path"'

    def test_response_prefixed_text_delta_projects_content(self) -> None:
        """Convert text delta containing OpenAI SDK class name to projection too."""
        normalizer = LiteLLMResponsesOutputNormalizer(
            provider="openai",
            model="gpt-5.1",
            operation="sampling",
            integration=None,
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


def test_litellm_lowerer_groups_contiguous_external_batch() -> None:
    """Lower one contiguous invocation batch into one explicit user turn."""
    lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
    transcript = [
        _event(
            EventKind.EXTERNAL_CHANNEL_MESSAGE,
            _external_payload(
                message_id="1", revision_id="r1", batch_id="batch-1", body="first"
            ),
        ),
        _event(
            EventKind.EXTERNAL_CHANNEL_MESSAGE,
            _external_payload(
                message_id="2", revision_id="r2", batch_id="batch-1", body="second"
            ),
        ),
    ]

    request = lowerer.lower(transcript, model="gpt-5.1")
    content = request.input[-1]["content"]
    assert isinstance(content, str)
    assert content.startswith("Message Type: EXTERNAL_CHANNEL_TURN")
    assert content.index("Body: first") < content.index("Body: second")


def test_litellm_lowerer_keeps_noncontiguous_batch_segments_in_order(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Report a reused batch ID without reordering transcript segments."""
    lowerer = LiteLLMResponsesLowerer(provider="openai", model="gpt-5.1")
    transcript = [
        _event(
            EventKind.EXTERNAL_CHANNEL_MESSAGE,
            _external_payload(
                message_id="1", revision_id="r1", batch_id="batch-1", body="first"
            ),
        ),
        _event(EventKind.USER_MESSAGE, UserMessagePayload(content="middle")),
        _event(
            EventKind.EXTERNAL_CHANNEL_MESSAGE,
            _external_payload(
                message_id="2", revision_id="r2", batch_id="batch-1", body="later"
            ),
        ),
    ]

    with caplog.at_level(logging.WARNING):
        request = lowerer.lower(transcript, model="gpt-5.1")

    contents = [item["content"] for item in request.input if item.get("role") == "user"]
    assert any(
        isinstance(content, str) and "Body: first" in content for content in contents
    )
    assert any(isinstance(content, str) and content == "middle" for content in contents)
    assert any(
        isinstance(content, str) and "Body: later" in content for content in contents
    )
    assert "not contiguous" in caplog.text
