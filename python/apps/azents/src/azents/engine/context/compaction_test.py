"""Context compaction tests."""

import httpx2
import pytest
from anthropic import BadRequestError
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
from azents.engine.model_factories import get_model_sdk_factories
from azents.engine.run.errors import (
    CompactionModelStreamTimeoutError,
    ModelStreamTimeoutError,
)
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    ModelProviderFailureCategory,
)
from azents.testing.model_stream import make_test_model_stream_watchdog


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
            limit_chars=41_000,
            truncate_chars=46_000,
            max_output_tokens=10_250,
        )

    def test_computes_large_context_budget_with_max_clamp(self) -> None:
        """Large context window applies upper-bound clamp."""
        budget = compute_summary_budget(200_000)

        assert budget == CompactionSummaryBudget(
            target_chars=24_000,
            limit_chars=50_000,
            truncate_chars=55_000,
            max_output_tokens=12_500,
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
    def test_prompt_builds_execution_ready_current_state(self) -> None:
        """Compaction prompt reconstructs an actionable current state."""
        prompt = " ".join(SUMMARY_SYSTEM_PROMPT.split())

        assert "execution-ready handoff checkpoint" in prompt
        assert "applying the transcript chronologically" in prompt
        assert "state transitions that update the working direction" in prompt
        assert "most advanced validated state" in prompt
        assert "furthest verified progress" in prompt
        assert "order next actions by execution priority" in prompt
        assert "Scale checkpoint detail to task complexity" in prompt
        assert "retaining continuation-relevant state and evidence" in prompt
        assert "including evidence of completed work" in prompt
        assert "let task complexity determine length" in prompt
        assert "Needs verification" in prompt
        assert "Output only the checkpoint" in prompt

    def test_prompt_requires_checkpoint_sections(self) -> None:
        """Checkpoint prompt fixes sections required for handoff."""
        template = " ".join(SUMMARY_USER_TEMPLATE.split())

        for section in [
            "## Active Objective",
            "## Current Execution State",
            "## Completed Work",
            "## Next Actions",
            "## Active Constraints and Decisions",
            "## Relevant Files and Identifiers",
            "## Verification",
            "## References",
        ]:
            assert section in SUMMARY_USER_TEMPLATE
        assert "Process the transcript in chronological order" in template
        assert "Later user direction updates the active objective" in template
        assert "Completed actions update the execution state" in template
        assert "previous state to update" in template
        assert "furthest completed and verified progress" in template
        assert "concrete, ordered" in template
        assert "Scale checkpoint detail to task complexity" in template
        assert "retaining continuation-relevant state and evidence" in template
        assert "including evidence of completed work" in template
        assert "let complexity determine length" in template
        assert "bounded recent user-message and transcript excerpts" in template


class TestSummarizeTextWithModel:
    async def test_converts_stream_timeout_to_compaction_failure(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Preserve timeout classification across the compaction boundary."""
        timeout = ModelStreamTimeoutError(
            timeout_kind="parsed_event_idle",
            deadline_seconds=5,
            elapsed_seconds=5,
            call_kind="compaction",
            provider="openai",
            model="gpt-test",
        )

        async def raise_timeout(**kwargs: object) -> str:
            del kwargs
            raise timeout

        monkeypatch.setattr(
            "azents.engine.context.compaction.call_openai_responses_text",
            raise_timeout,
        )

        with pytest.raises(CompactionModelStreamTimeoutError) as raised:
            await summarize_text_with_model(
                assembly_metadata=None,
                sdk_factories=get_model_sdk_factories(),
                watchdog=make_test_model_stream_watchdog(),
                provider=LLMProvider.OPENAI,
                provider_integration_id=None,
                model="gpt-test",
                credential_kwargs={"api_key": "test-key"},
                system_prompt="summarize system",
                user_prompt="summarize user\n",
                conversation_text="[User]: hello",
                max_output_tokens=4000,
                session_id="session-1",
            )

        assert raised.value.failure_code == "model_stream_idle_timeout"
        assert raised.value.timeout_kind == "parsed_event_idle"

    async def test_sends_summary_prompt_as_top_level_instructions(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """Send system prompt as top-level instructions."""
        calls: list[dict[str, object]] = []

        async def fake_openai_responses_text(**kwargs: object) -> str:
            calls.append(dict(kwargs))
            return "summary"

        monkeypatch.setattr(
            "azents.engine.context.compaction.call_openai_responses_text",
            fake_openai_responses_text,
        )

        result = await summarize_text_with_model(
            assembly_metadata=None,
            sdk_factories=get_model_sdk_factories(),
            watchdog=make_test_model_stream_watchdog(),
            provider=LLMProvider.CHATGPT_OAUTH,
            provider_integration_id=None,
            model="gpt-5.5",
            credential_kwargs={
                "api_key": "test-key",
                "api_base": "https://chatgpt.com/backend-api/codex/responses",
            },
            system_prompt="summarize system",
            user_prompt="summarize user\n",
            conversation_text="[User]: hello",
            max_output_tokens=4000,
            session_id="session-1",
        )

        assert result == "summary"
        assert len(calls) == 1
        call = calls[0]
        assert call["provider"] == LLMProvider.CHATGPT_OAUTH
        assert call["instructions"] == "summarize system"
        assert "max_output_tokens" not in call
        assert call["text"] == {"format": {"type": "text"}, "verbosity": "low"}
        assert call["input_items"] == [
            {"role": "user", "content": "summarize user\n[User]: hello"}
        ]

    async def test_omits_max_output_tokens_for_openai_responses_family(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """OpenAI/Codex Responses compaction call omits output token field."""
        calls: list[dict[str, object]] = []

        async def fake_openai_responses_text(**kwargs: object) -> str:
            calls.append(dict(kwargs))
            return "summary"

        monkeypatch.setattr(
            "azents.engine.context.compaction.call_openai_responses_text",
            fake_openai_responses_text,
        )

        await summarize_text_with_model(
            assembly_metadata=None,
            sdk_factories=get_model_sdk_factories(),
            watchdog=make_test_model_stream_watchdog(),
            provider=LLMProvider.OPENAI,
            provider_integration_id=None,
            model="gpt-5.5",
            credential_kwargs={"api_key": "test-key"},
            system_prompt="summarize system",
            user_prompt="summarize user\n",
            conversation_text="[User]: hello",
            max_output_tokens=4000,
            session_id="session-1",
        )

        assert calls[0]["provider"] == LLMProvider.OPENAI
        assert "max_output_tokens" not in calls[0]
        assert calls[0]["text"] == {"format": {"type": "text"}, "verbosity": "low"}


async def test_replacement_summary_uses_single_authorized_model_text_operation(
    monkeypatch: MonkeyPatch,
) -> None:
    """Replacement compaction keeps the selected ID, prompts and output budget."""
    calls: list[dict[str, object]] = []

    async def text_operation(**kwargs: object) -> str:
        calls.append(kwargs)
        return "summary"

    monkeypatch.setattr(
        "azents.engine.context.compaction.call_provider_text", text_operation
    )
    summary = await summarize_text_with_model(
        assembly_metadata=None,
        sdk_factories=get_model_sdk_factories(),
        watchdog=make_test_model_stream_watchdog(),
        provider=LLMProvider.ANTHROPIC,
        provider_integration_id="integration",
        model="publisher/exact/model",
        credential_kwargs={"api_key": "synthetic"},
        system_prompt="System summary instructions",
        user_prompt="User summary prefix\n",
        conversation_text="[User]: hello",
        max_output_tokens=4000,
        session_id="session-1",
    )
    assert summary == "summary"
    assert len(calls) == 1
    assert calls[0]["model"] == "publisher/exact/model"
    assert calls[0]["instructions"] == "System summary instructions"
    assert calls[0]["input_text"] == "User summary prefix\n[User]: hello"
    assert calls[0]["max_output_tokens"] == 4000
    assert calls[0]["text"] is None


async def test_replacement_context_error_is_safe_and_never_retried_internally(
    monkeypatch: MonkeyPatch,
) -> None:
    """The SDK's context failure retains its existing classified operation."""
    attempts = 0

    async def fail_context(**kwargs: object) -> str:
        nonlocal attempts
        attempts += 1
        request = httpx2.Request("POST", "https://synthetic.test/messages")
        raise BadRequestError(
            "Context exhausted",
            response=httpx2.Response(400, request=request),
            body={
                "error": {
                    "type": "context_length_exceeded",
                    "message": "Input too long",
                }
            },
        )

    monkeypatch.setattr(
        "azents.engine.context.compaction.call_provider_text", fail_context
    )
    with pytest.raises(ModelProviderFailure) as caught:
        await summarize_text_with_model(
            assembly_metadata=None,
            sdk_factories=get_model_sdk_factories(),
            watchdog=make_test_model_stream_watchdog(),
            provider=LLMProvider.ANTHROPIC,
            provider_integration_id="integration",
            model="publisher/exact/model",
            credential_kwargs={"api_key": "synthetic"},
            system_prompt="Summary instructions",
            user_prompt="Summary prefix\n",
            conversation_text="[User]: hello",
            max_output_tokens=4000,
            session_id="session-1",
        )
    assert attempts == 1
    assert caught.value.operation == "compaction"
    assert caught.value.category is ModelProviderFailureCategory.CONTEXT_LIMIT
    assert caught.value.route_model == "publisher/exact/model"
