"""Context compaction tests."""

from collections.abc import AsyncIterator

import pytest
from litellm.exceptions import ContextWindowExceededError
from pytest import MonkeyPatch

from azents.core.enums import LLMProvider
from azents.engine.context.compaction import (
    SUMMARY_SYSTEM_PROMPT,
    SUMMARY_USER_TEMPLATE,
    CompactionSummaryBudget,
    compute_summary_budget,
    enforce_summary_char_budget,
    summarize_text_with_model,
)
from azents.engine.run.errors import CompactionFailedError


class _ResponsesOutputText:
    """LiteLLM Responses response for tests."""

    output_text = "summary"


class _ResponsesStreamEvent:
    """Streaming Responses event for tests."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def model_dump(self, *, mode: str = "python") -> dict[str, object]:
        """Return payload in the same shape as a Pydantic event."""
        del mode
        return self._payload


class TestSummaryBudget:
    def test_computes_small_context_budget_with_min_clamp(self) -> None:
        """Small context window applies lower-bound clamp."""
        budget = compute_summary_budget(32_000)

        assert budget == CompactionSummaryBudget(
            target_chars=12_000,
            limit_chars=16_000,
            truncate_chars=18_000,
            max_output_tokens=4_000,
        )

    def test_computes_mid_context_budget_with_rounding(self) -> None:
        """128k context window applies 1000-unit rounding."""
        budget = compute_summary_budget(128_000)

        assert budget == CompactionSummaryBudget(
            target_chars=15_000,
            limit_chars=26_000,
            truncate_chars=29_000,
            max_output_tokens=6_500,
        )

    def test_computes_large_context_budget_with_max_clamp(self) -> None:
        """Large context window applies upper-bound clamp."""
        budget = compute_summary_budget(200_000)

        assert budget == CompactionSummaryBudget(
            target_chars=24_000,
            limit_chars=32_000,
            truncate_chars=36_000,
            max_output_tokens=8_000,
        )

    def test_unknown_context_uses_128k_fallback(self) -> None:
        """Use 128k fallback when context window is unknown."""
        assert compute_summary_budget(None) == compute_summary_budget(128_000)

    def test_char_guard_allows_tolerance_before_truncating(self) -> None:
        """Do not truncate below or equal to the 110% limit threshold."""
        budget = CompactionSummaryBudget(
            target_chars=12_000,
            limit_chars=16_000,
            truncate_chars=18_000,
            max_output_tokens=4_000,
        )
        summary = "a" * 17_999

        assert enforce_summary_char_budget(summary, budget) == summary

    def test_char_guard_truncates_with_note(self) -> None:
        """Summary over threshold is simply truncated with a note."""
        budget = CompactionSummaryBudget(
            target_chars=12_000,
            limit_chars=16_000,
            truncate_chars=18_000,
            max_output_tokens=4_000,
        )

        result = enforce_summary_char_budget("a" * 20_000, budget)

        assert len(result) <= budget.truncate_chars
        assert result.endswith("[Truncated by Azents compaction guard.]")


class TestSummaryPrompt:
    def test_prompt_is_handoff_checkpoint_oriented(self) -> None:
        """Compaction prompt requires handoff checkpoint."""
        assert "durable handoff checkpoint" in SUMMARY_SYSTEM_PROMPT
        assert "not a narrative conversation summary" in SUMMARY_SYSTEM_PROMPT
        assert "Do not answer the user" in SUMMARY_SYSTEM_PROMPT
        assert "Do not continue the task" in SUMMARY_SYSTEM_PROMPT
        assert "Do not fill the budget unnecessarily" in SUMMARY_SYSTEM_PROMPT
        assert "Needs verification" in SUMMARY_SYSTEM_PROMPT
        assert "Do not include full logs" in SUMMARY_SYSTEM_PROMPT

    def test_prompt_requires_checkpoint_sections(self) -> None:
        """Checkpoint prompt fixes sections required for handoff."""
        for section in [
            "## Goal",
            "## Durable Instructions",
            "## Current State",
            "## Completed Work",
            "## Pending Work",
            "## Decisions and Rationale",
            "## Relevant Files and Symbols",
            "## Verification",
            "## External References",
            "## Notes for Next Agent",
        ]:
            assert section in SUMMARY_USER_TEMPLATE
        assert "existing checkpoints" in SUMMARY_USER_TEMPLATE
        assert "Do not copy previous checkpoints verbatim" in SUMMARY_USER_TEMPLATE
        assert "Do not duplicate preserved tail content" in SUMMARY_USER_TEMPLATE


class TestSummarizeTextWithModel:
    async def test_sends_summary_prompt_as_top_level_instructions(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Send system prompt as top-level instructions."""
        calls: list[dict[str, object]] = []

        async def fake_aresponses(**kwargs: object) -> _ResponsesOutputText:
            calls.append(dict(kwargs))
            return _ResponsesOutputText()

        monkeypatch.setattr(
            "azents.engine.context.compaction.aresponses",
            fake_aresponses,
        )

        result = await summarize_text_with_model(
            provider=LLMProvider.CHATGPT_OAUTH,
            model="gpt-5.5",
            credential_kwargs={
                "api_key": "test-key",
                "api_base": "https://chatgpt.com/backend-api/codex/responses",
            },
            system_prompt="summarize system",
            user_prompt="summarize user\n",
            conversation_text="[User]: hello",
            max_tokens=4000,
            session_id="session-1",
        )

        assert result == "summary"
        assert len(calls) == 1
        call = calls[0]
        assert call["instructions"] == "summarize system"
        assert call["stream"] is True
        assert call["max_output_tokens"] is None
        assert call["text"] == {"format": {"type": "text"}, "verbosity": "low"}
        assert call["input"] == [
            {"role": "user", "content": "summarize user\n[User]: hello"}
        ]

    async def test_omits_max_output_tokens_for_openai_responses_family(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """OpenAI/Codex Responses compaction call omits output token field."""
        calls: list[dict[str, object]] = []

        async def fake_aresponses(**kwargs: object) -> _ResponsesOutputText:
            calls.append(dict(kwargs))
            return _ResponsesOutputText()

        monkeypatch.setattr(
            "azents.engine.context.compaction.aresponses",
            fake_aresponses,
        )

        await summarize_text_with_model(
            provider=LLMProvider.OPENAI,
            model="gpt-5.5",
            credential_kwargs={"api_key": "test-key"},
            system_prompt="summarize system",
            user_prompt="summarize user\n",
            conversation_text="[User]: hello",
            max_tokens=4000,
            session_id="session-1",
        )

        assert calls[0]["stream"] is True
        assert calls[0]["max_output_tokens"] is None
        assert calls[0]["text"] == {"format": {"type": "text"}, "verbosity": "low"}

    async def test_extracts_streaming_summary_text_helper(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Streaming response extraction helper keeps supporting legacy response."""
        guarded_streams: list[object] = []

        async def fake_aresponses(**kwargs: object) -> object:
            calls.append(dict(kwargs))

            async def stream() -> AsyncIterator[_ResponsesStreamEvent]:
                yield _ResponsesStreamEvent({"delta": "sum"})
                yield _ResponsesStreamEvent({"delta": "mary"})

            return stream()

        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            "azents.engine.context.compaction.aresponses",
            fake_aresponses,
        )
        monkeypatch.setattr(
            "azents.engine.context.compaction.guard_litellm_streaming_logging",
            guarded_streams.append,
        )

        result = await summarize_text_with_model(
            provider=LLMProvider.ANTHROPIC,
            model="claude-sonnet-4-5",
            credential_kwargs={"api_key": "test-key"},
            system_prompt="summarize system",
            user_prompt="summarize user\n",
            conversation_text="[User]: hello",
            max_tokens=4000,
            session_id="session-1",
        )

        assert result == "summary"
        assert calls[0]["stream"] is True
        assert calls[0]["max_output_tokens"] == 4000
        assert calls[0]["text"] == {"format": {"type": "text"}, "verbosity": "low"}
        assert len(guarded_streams) == 1

    async def test_extracts_streaming_summary_text_from_item_delta(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Streaming response extraction helper also supports item.delta shape."""

        async def fake_aresponses(**kwargs: object) -> object:
            calls.append(dict(kwargs))

            async def stream() -> AsyncIterator[_ResponsesStreamEvent]:
                yield _ResponsesStreamEvent(
                    {"type": "ResponseTextDeltaEvent", "item": {"delta": "sum"}}
                )
                yield _ResponsesStreamEvent(
                    {"type": "ResponseTextDeltaEvent", "item": {"delta": "mary"}}
                )

            return stream()

        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            "azents.engine.context.compaction.aresponses",
            fake_aresponses,
        )

        result = await summarize_text_with_model(
            provider=LLMProvider.CHATGPT_OAUTH,
            model="gpt-5.5",
            credential_kwargs={"api_key": "test-key"},
            system_prompt="summarize system",
            user_prompt="summarize user\n",
            conversation_text="[User]: hello",
            max_tokens=4000,
            session_id="session-1",
        )

        assert result == "summary"
        assert calls[0]["stream"] is True

    async def test_extracts_streaming_summary_text_from_completed_response(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """When there is no delta, extract summary from completed response output."""

        async def fake_aresponses(**kwargs: object) -> object:
            calls.append(dict(kwargs))

            async def stream() -> AsyncIterator[_ResponsesStreamEvent]:
                yield _ResponsesStreamEvent(
                    {
                        "type": "ResponseCompletedEvent",
                        "response": {
                            "output": [
                                {
                                    "type": "message",
                                    "content": [
                                        {"type": "output_text", "text": "summary"}
                                    ],
                                }
                            ]
                        },
                    }
                )

            return stream()

        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            "azents.engine.context.compaction.aresponses",
            fake_aresponses,
        )

        result = await summarize_text_with_model(
            provider=LLMProvider.CHATGPT_OAUTH,
            model="gpt-5.5",
            credential_kwargs={"api_key": "test-key"},
            system_prompt="summarize system",
            user_prompt="summarize user\n",
            conversation_text="[User]: hello",
            max_tokens=4000,
            session_id="session-1",
        )

        assert result == "summary"
        assert calls[0]["stream"] is True

    async def test_extracts_streaming_summary_text_from_output_text_done(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Streaming response extraction helper supports done event text."""

        async def fake_aresponses(**kwargs: object) -> object:
            calls.append(dict(kwargs))

            async def stream() -> AsyncIterator[_ResponsesStreamEvent]:
                yield _ResponsesStreamEvent(
                    {
                        "type": "response.output_text.done",
                        "text": "summary",
                    }
                )

            return stream()

        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            "azents.engine.context.compaction.aresponses",
            fake_aresponses,
        )

        result = await summarize_text_with_model(
            provider=LLMProvider.CHATGPT_OAUTH,
            model="gpt-5.5",
            credential_kwargs={"api_key": "test-key"},
            system_prompt="summarize system",
            user_prompt="summarize user\n",
            conversation_text="[User]: hello",
            max_tokens=4000,
            session_id="session-1",
        )

        assert result == "summary"
        assert calls[0]["stream"] is True

    async def test_done_text_takes_precedence_over_delta_fragments(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Use completed text from done event instead of delta fragments."""

        async def fake_aresponses(**kwargs: object) -> object:
            calls.append(dict(kwargs))

            async def stream() -> AsyncIterator[_ResponsesStreamEvent]:
                yield _ResponsesStreamEvent(
                    {"type": "response.output_text.delta", "delta": "partial"}
                )
                yield _ResponsesStreamEvent(
                    {
                        "type": "response.output_text.done",
                        "text": "final summary",
                    }
                )

            return stream()

        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            "azents.engine.context.compaction.aresponses",
            fake_aresponses,
        )

        result = await summarize_text_with_model(
            provider=LLMProvider.CHATGPT_OAUTH,
            model="gpt-5.5",
            credential_kwargs={"api_key": "test-key"},
            system_prompt="summarize system",
            user_prompt="summarize user\n",
            conversation_text="[User]: hello",
            max_tokens=4000,
            session_id="session-1",
        )

        assert result == "final summary"
        assert calls[0]["stream"] is True

    async def test_extracts_summary_text_from_response_output_text_dict(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Use output_text from non-stream dict response as summary too."""

        async def fake_aresponses(**kwargs: object) -> dict[str, object]:
            calls.append(dict(kwargs))
            return {"output_text": "summary"}

        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            "azents.engine.context.compaction.aresponses",
            fake_aresponses,
        )

        result = await summarize_text_with_model(
            provider=LLMProvider.CHATGPT_OAUTH,
            model="gpt-5.5",
            credential_kwargs={"api_key": "test-key"},
            system_prompt="summarize system",
            user_prompt="summarize user\n",
            conversation_text="[User]: hello",
            max_tokens=4000,
            session_id="session-1",
        )

        assert result == "summary"
        assert calls[0]["stream"] is True

    async def test_retries_context_window_error_with_older_input_omitted(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Context-window-exceeded stream error retries after omitting older input."""

        async def fake_aresponses(**kwargs: object) -> object:
            calls.append(dict(kwargs))

            async def failed_stream() -> AsyncIterator[_ResponsesStreamEvent]:
                yield _ResponsesStreamEvent(
                    {
                        "type": "error",
                        "error": {
                            "code": "context_length_exceeded",
                            "message": (
                                "Your input exceeds the context window of this "
                                "model. Please adjust your input and try again."
                            ),
                        },
                    }
                )

            async def completed_stream() -> AsyncIterator[_ResponsesStreamEvent]:
                yield _ResponsesStreamEvent(
                    {"type": "response.output_text.done", "text": "summary"}
                )

            if len(calls) == 1:
                return failed_stream()
            return completed_stream()

        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            "azents.engine.context.compaction.aresponses",
            fake_aresponses,
        )
        conversation_text = "\n".join(
            [
                "[User]: OLDEST_SHOULD_BE_OMITTED " + ("old " * 500),
                "[Assistant]: " + ("middle " * 20),
                "[User]: recent tail",
            ]
        )

        result = await summarize_text_with_model(
            provider=LLMProvider.CHATGPT_OAUTH,
            model="gpt-5.4-mini",
            credential_kwargs={"api_key": "test-key"},
            system_prompt="summarize system",
            user_prompt="summarize user\n",
            conversation_text=conversation_text,
            max_tokens=4000,
            session_id="session-1",
        )

        assert result == "summary"
        assert len(calls) == 2
        retry_input = calls[1]["input"]
        assert isinstance(retry_input, list)
        retry_message = retry_input[0]
        assert isinstance(retry_message, dict)
        retry_content = retry_message["content"]
        assert isinstance(retry_content, str)
        assert "Older compaction input omitted" in retry_content
        assert "OLDEST_SHOULD_BE_OMITTED" not in retry_content
        assert "[Assistant]: middle" in retry_content
        assert retry_content.endswith("[User]: recent tail")

    async def test_non_context_stream_error_fails_without_retry(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Non-context-window stream error fails without retry."""

        async def fake_aresponses(**kwargs: object) -> object:
            calls.append(dict(kwargs))

            async def stream() -> AsyncIterator[_ResponsesStreamEvent]:
                yield _ResponsesStreamEvent(
                    {
                        "type": "response.failed",
                        "response": {
                            "error": {
                                "code": "bad_request",
                                "message": "The request is invalid.",
                            }
                        },
                    }
                )

            return stream()

        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            "azents.engine.context.compaction.aresponses",
            fake_aresponses,
        )

        with pytest.raises(CompactionFailedError, match="bad_request"):
            await summarize_text_with_model(
                provider=LLMProvider.CHATGPT_OAUTH,
                model="gpt-5.4-mini",
                credential_kwargs={"api_key": "test-key"},
                system_prompt="summarize system",
                user_prompt="summarize user\n",
                conversation_text="[User]: hello",
                max_tokens=4000,
                session_id="session-1",
            )

        assert len(calls) == 1

    async def test_retries_litellm_context_window_exception(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """LiteLLM context window exception follows the same retry path."""

        async def fake_aresponses(**kwargs: object) -> object:
            calls.append(dict(kwargs))
            if len(calls) == 1:
                raise ContextWindowExceededError(
                    "input exceeds context window",
                    model="gpt-5.4-mini",
                    llm_provider="openai",
                )

            async def completed_stream() -> AsyncIterator[_ResponsesStreamEvent]:
                yield _ResponsesStreamEvent(
                    {"type": "response.output_text.done", "text": "summary"}
                )

            return completed_stream()

        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            "azents.engine.context.compaction.aresponses",
            fake_aresponses,
        )
        conversation_text = "\n".join(
            [
                "[User]: OLDEST_SHOULD_BE_OMITTED " + ("old " * 500),
                "[Assistant]: " + ("middle " * 20),
                "[User]: recent tail",
            ]
        )

        result = await summarize_text_with_model(
            provider=LLMProvider.CHATGPT_OAUTH,
            model="gpt-5.4-mini",
            credential_kwargs={"api_key": "test-key"},
            system_prompt="summarize system",
            user_prompt="summarize user\n",
            conversation_text=conversation_text,
            max_tokens=4000,
            session_id="session-1",
        )

        assert result == "summary"
        assert len(calls) == 2
        retry_input = calls[1]["input"]
        assert isinstance(retry_input, list)
        retry_message = retry_input[0]
        assert isinstance(retry_message, dict)
        retry_content = retry_message["content"]
        assert isinstance(retry_content, str)
        assert "Older compaction input omitted" in retry_content
        assert "OLDEST_SHOULD_BE_OMITTED" not in retry_content
        assert retry_content.endswith("[User]: recent tail")
