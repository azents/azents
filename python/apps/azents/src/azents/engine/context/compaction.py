"""Context compaction summary generation.

Converts event history into a structured summary through an LLM call.
"""

import dataclasses
import logging
from collections.abc import Awaitable
from typing import Protocol

from azcommon.logging import bind_extra
from litellm.exceptions import OpenAIError as LiteLLMOpenAIError
from openai import OpenAIError as OpenAIBaseError

from azents.core.enums import LLMProvider
from azents.engine.events.litellm_responses import map_litellm_provider_error
from azents.engine.events.openai_responses import call_openai_responses_text
from azents.engine.model_stream import (
    ModelStreamCallContext,
    ModelStreamWatchdog,
)
from azents.engine.responses import (
    DEFAULT_RESPONSES_TEXT_CONFIG,
    ResponsesOutputError,
    call_responses_model,
    extract_response_text,
    responses_max_output_tokens,
)
from azents.engine.run.errors import (
    CompactionFailedError,
    CompactionModelStreamTimeoutError,
    ModelCallError,
    ModelStreamTimeoutError,
)
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    model_provider_failure,
)

logger = logging.getLogger(__name__)
_SUMMARY_CHARS_PER_TOKEN = 4
_SUMMARY_DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000
_SUMMARY_TARGET_CONTEXT_RATIO = 0.03
_SUMMARY_LIMIT_CONTEXT_RATIO = 0.05
_SUMMARY_TRUNCATE_TOLERANCE_RATIO = 1.1
_MIN_SUMMARY_TARGET_CHARS = 12_000
_MAX_SUMMARY_TARGET_CHARS = 24_000
_MIN_SUMMARY_LIMIT_CHARS = 16_000
_MAX_SUMMARY_LIMIT_CHARS = 32_000
_SUMMARY_ROUNDING_CHARS = 1_000
_SUMMARY_TRUNCATION_NOTE = "\n\n[Truncated by Azents compaction guard.]"


@dataclasses.dataclass(frozen=True)
class CompactionSummaryBudget:
    """Compaction summary output budget."""

    target_chars: int
    limit_chars: int
    truncate_chars: int
    max_output_tokens: int


class SummaryModelCall(Protocol):
    """Summary model call function interface."""

    def __call__(
        self,
        *,
        provider: LLMProvider,
        provider_integration_id: str | None,
        model: str,
        credential_kwargs: dict[str, object],
        system_prompt: str,
        user_prompt: str,
        conversation_text: str,
        max_output_tokens: int,
        session_id: str | None = None,
    ) -> Awaitable[str]:
        """Call the summary model."""

        ...


_SUMMARY_SYSTEM_PROMPT = """\
You are a context compaction engine for a long-running coding agent.

Produce a durable handoff checkpoint, not a narrative conversation summary.
The next agent should be able to continue the task without reading the compacted
transcript.

This is not a user-facing answer. Do not answer the user. Do not continue the task.
Only output the checkpoint.

Use the budget only for durable continuation state.
Do not fill the budget unnecessarily.
Prefer concise bullets over prose. Do not invent details. If something is unclear,
mark it as Needs verification.

Do not include full logs unless exact text is required. For tool results,
preserve only commands, outcomes, error messages, paths, IDs, and conclusions
needed to continue.
"""

_SUMMARY_USER_TEMPLATE = """\
Create an updated handoff checkpoint for the full compacted transcript below.
The runtime may append bounded recent user-message and transcript excerpts after
your checkpoint for immediate continuity. Still summarize durable state from the
whole compacted transcript; do not assume any raw event will remain available
outside this checkpoint.

If existing checkpoints are present, integrate them into one updated checkpoint.
Do not copy previous checkpoints verbatim. Keep durable instructions and
still-relevant decisions. Drop obsolete details unless they are needed to
continue. Prefer the latest transcript evidence when there is a conflict.

Required output sections:
## Goal
## Durable Instructions
## Current State
## Completed Work
## Pending Work
## Decisions and Rationale
## Relevant Files and Symbols
## Verification
## External References
## Notes for Next Agent

Guidelines:
- Use concise bullets.
- Preserve actionable state, not conversational filler.
- Include branches, PRs, issues, commands, test results, errors, file paths,
  symbols, and external IDs only when needed to continue.
- Mark uncertain or stale information as Needs verification.
- If the compacted transcript shows that a Skill is actively being followed for
  unfinished work, include an "Active Skill" subsection in the checkpoint. A
  Skill is active when its instructions, checklist, workflow stage, or
  constraints are still needed to continue pending work. For each active Skill,
  preserve the Skill name and exact SKILL.md path if known, why it is still
  active, the current workflow/checklist stage, Skill-specific constraints or
  output format, and concrete next actions required by that Skill. Do not list
  every loaded Skill; omit Skills that were only inspected, used for completed
  work, or no longer constrain pending work.
- Do not answer the user or perform the next task.

Here is the compacted transcript to checkpoint:

"""

SUMMARY_SYSTEM_PROMPT = _SUMMARY_SYSTEM_PROMPT
SUMMARY_USER_TEMPLATE = _SUMMARY_USER_TEMPLATE


def compute_summary_budget(
    context_window_tokens: int | None,
) -> CompactionSummaryBudget:
    """Calculate compaction summary budget based on model context window."""
    effective_context_window = (
        context_window_tokens
        if context_window_tokens is not None and context_window_tokens > 0
        else _SUMMARY_DEFAULT_CONTEXT_WINDOW_TOKENS
    )
    target_chars = _clamp(
        _round_to_nearest_1000(
            int(
                effective_context_window
                * _SUMMARY_TARGET_CONTEXT_RATIO
                * _SUMMARY_CHARS_PER_TOKEN
            )
        ),
        _MIN_SUMMARY_TARGET_CHARS,
        _MAX_SUMMARY_TARGET_CHARS,
    )
    limit_chars = _clamp(
        _round_to_nearest_1000(
            int(
                effective_context_window
                * _SUMMARY_LIMIT_CONTEXT_RATIO
                * _SUMMARY_CHARS_PER_TOKEN
            )
        ),
        _MIN_SUMMARY_LIMIT_CHARS,
        _MAX_SUMMARY_LIMIT_CHARS,
    )
    truncate_chars = _round_up_to_nearest_1000(
        int(limit_chars * _SUMMARY_TRUNCATE_TOLERANCE_RATIO)
    )
    return CompactionSummaryBudget(
        target_chars=target_chars,
        limit_chars=limit_chars,
        truncate_chars=truncate_chars,
        max_output_tokens=limit_chars // _SUMMARY_CHARS_PER_TOKEN,
    )


def enforce_summary_char_budget(
    summary: str,
    budget: CompactionSummaryBudget,
) -> str:
    """Apply runtime char guard to compaction summary."""
    if len(summary) <= budget.truncate_chars:
        return summary
    prefix_budget = max(0, budget.truncate_chars - len(_SUMMARY_TRUNCATION_NOTE))
    return summary[:prefix_budget].rstrip() + _SUMMARY_TRUNCATION_NOTE


def _round_to_nearest_1000(value: int) -> int:
    """Round integer to nearest 1000."""
    return (
        (value + (_SUMMARY_ROUNDING_CHARS // 2))
        // _SUMMARY_ROUNDING_CHARS
        * _SUMMARY_ROUNDING_CHARS
    )


def _round_up_to_nearest_1000(value: int) -> int:
    """Round integer up to nearest 1000."""
    return (
        (value + _SUMMARY_ROUNDING_CHARS - 1)
        // _SUMMARY_ROUNDING_CHARS
        * _SUMMARY_ROUNDING_CHARS
    )


def _clamp(value: int, minimum: int, maximum: int) -> int:
    """Clamp integer to the specified range."""
    return max(minimum, min(value, maximum))


async def summarize_text_with_model(
    *,
    watchdog: ModelStreamWatchdog,
    provider: LLMProvider,
    provider_integration_id: str | None,
    model: str,
    credential_kwargs: dict[str, object],
    system_prompt: str,
    user_prompt: str,
    conversation_text: str,
    max_output_tokens: int,
    session_id: str | None = None,
) -> str:
    """Create one compaction summary model attempt."""
    endpoint_max_output_tokens = responses_max_output_tokens(
        provider,
        max_output_tokens,
    )

    L = bind_extra(
        logger,
        {
            "provider": provider.value,
            "provider_integration_id": provider_integration_id,
            "model": model,
            "session_id": session_id,
            "conversation_chars": len(conversation_text),
            "conversation_estimated_tokens": _estimated_tokens(conversation_text),
            "requested_max_output_tokens": max_output_tokens,
            "endpoint_max_output_tokens": endpoint_max_output_tokens,
        },
    )
    L.info(
        "Compaction summary model call starting",
        extra={
            "attempt": 1,
            "input_chars": len(conversation_text),
            "input_estimated_tokens": _estimated_tokens(conversation_text),
        },
    )
    summary = await _summarize_text_attempt(
        watchdog=watchdog,
        provider=provider,
        provider_integration_id=provider_integration_id,
        model=model,
        credential_kwargs=credential_kwargs,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        conversation_text=conversation_text,
        endpoint_max_output_tokens=endpoint_max_output_tokens,
        session_id=session_id,
    )
    L.info(
        "Compaction summary model call completed",
        extra={
            "attempt": 1,
            "input_chars": len(conversation_text),
            "summary_chars": len(summary),
            "summary_estimated_tokens": _estimated_tokens(summary),
        },
    )
    return summary


async def _summarize_text_attempt(
    *,
    watchdog: ModelStreamWatchdog,
    provider: LLMProvider,
    provider_integration_id: str | None,
    model: str,
    credential_kwargs: dict[str, object],
    system_prompt: str,
    user_prompt: str,
    conversation_text: str,
    endpoint_max_output_tokens: int | None,
    session_id: str | None,
) -> str:
    """Try creating summary once with LiteLLM Responses API."""
    timeout_policy = watchdog.resolve_policy(
        provider=provider.value,
        model=model,
        inference_profile=None,
    )
    call_context = ModelStreamCallContext(
        call_kind="compaction",
        provider=provider.value,
        provider_integration_id=provider_integration_id,
        model=model,
        session_id=session_id,
        run_id=None,
        attempt_number=None,
        check_stop=None,
    )
    try:
        input_items: list[dict[str, object]] = [
            {"role": "user", "content": user_prompt + conversation_text}
        ]
        if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
            return await call_openai_responses_text(
                provider=provider,
                model=model,
                credential_kwargs=credential_kwargs,
                input_items=input_items,
                instructions=system_prompt,
                text=DEFAULT_RESPONSES_TEXT_CONFIG,
                watchdog=watchdog,
                timeout_policy=timeout_policy,
                call_context=call_context,
            )
        response = await call_responses_model(
            provider=provider,
            model=model,
            credential_kwargs=credential_kwargs,
            input_items=input_items,
            instructions=system_prompt,
            stream=True,
            max_output_tokens=endpoint_max_output_tokens,
            watchdog=watchdog,
            timeout_policy=timeout_policy,
            call_context=call_context,
        )
        return await extract_response_text(response)
    except ModelProviderFailure:
        raise
    except ModelStreamTimeoutError as exc:
        raise CompactionModelStreamTimeoutError(exc) from exc
    except ResponsesOutputError as exc:
        raise model_provider_failure(
            operation="compaction",
            provider=provider.value,
            model=model,
            integration=provider_integration_id,
            provider_message=exc.message,
            status_code=None,
            provider_code=exc.code,
            provider_error_type=exc.event_type,
        ) from None
    except ModelCallError as exc:
        raise CompactionFailedError(exc.user_message) from exc
    except (LiteLLMOpenAIError, OpenAIBaseError) as exc:
        failure = map_litellm_provider_error(exc, call_context=call_context)
        raise failure from None


def _estimated_tokens(text: str) -> int:
    """Return rough token estimate based on string length."""

    return len(text) // 4
