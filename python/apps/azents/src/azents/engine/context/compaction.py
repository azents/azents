"""Context compaction summary generation.

Converts event history into a structured summary through an LLM call.
"""

import dataclasses
import logging
from collections.abc import Awaitable
from typing import Protocol

from azcommon.logging import bind_extra
from litellm.exceptions import ContextWindowExceededError, OpenAIError

from azents.core.enums import LLMProvider
from azents.engine.responses import (
    ResponsesOutputError,
    call_responses_model,
    extract_response_text,
    responses_max_output_tokens,
)
from azents.engine.run.errors import (
    CompactionContextWindowExceededError,
    CompactionFailedError,
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
_SUMMARY_CONTEXT_RETRY_KEEP_RATIOS = (0.70, 0.45, 0.25, 0.12)
_SUMMARY_CONTEXT_OMISSION_MARKER = (
    "[Older compaction input omitted because it exceeded the summary model "
    "context window.]"
)
_SUMMARY_CONTEXT_LINE_TRUNCATION_MARKER = (
    "\n\n[Compaction input line middle omitted because one rendered event exceeded "
    "the retry budget.]\n\n"
)


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
        model: str,
        credential_kwargs: dict[str, object],
        system_prompt: str,
        user_prompt: str,
        conversation_text: str,
        max_tokens: int,
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
    provider: LLMProvider,
    model: str,
    credential_kwargs: dict[str, object],
    system_prompt: str,
    user_prompt: str,
    conversation_text: str,
    max_tokens: int,
    session_id: str | None = None,
) -> str:
    """Create compaction summary with LiteLLM Responses API."""
    endpoint_max_tokens = responses_max_output_tokens(provider, max_tokens)

    L = bind_extra(
        logger,
        {
            "provider": provider.value,
            "model": model,
            "session_id": session_id,
            "conversation_chars": len(conversation_text),
            "conversation_estimated_tokens": _estimated_tokens(conversation_text),
            "requested_max_tokens": max_tokens,
            "endpoint_max_output_tokens": endpoint_max_tokens,
        },
    )
    current_conversation_text = conversation_text
    retry_index = 0
    attempt = 1
    while True:
        try:
            L.info(
                "Compaction summary LiteLLM Responses call starting",
                extra={
                    "attempt": attempt,
                    "input_chars": len(current_conversation_text),
                    "input_estimated_tokens": _estimated_tokens(
                        current_conversation_text
                    ),
                },
            )
            summary = await _summarize_text_attempt(
                provider=provider,
                model=model,
                credential_kwargs=credential_kwargs,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                conversation_text=current_conversation_text,
                endpoint_max_tokens=endpoint_max_tokens,
            )
        except CompactionContextWindowExceededError:
            if retry_index >= len(_SUMMARY_CONTEXT_RETRY_KEEP_RATIOS):
                raise
            keep_ratio = _SUMMARY_CONTEXT_RETRY_KEEP_RATIOS[retry_index]
            retry_index += 1
            current_conversation_text = _truncate_context_retry_text(
                conversation_text,
                keep_chars=int(len(conversation_text) * keep_ratio),
            )
            L.warning(
                "Compaction summary input exceeded model context window; retrying "
                "with older input omitted",
                extra={
                    "failed_attempt": attempt,
                    "next_attempt": attempt + 1,
                    "keep_ratio": keep_ratio,
                    "retry_input_chars": len(current_conversation_text),
                    "retry_input_estimated_tokens": _estimated_tokens(
                        current_conversation_text
                    ),
                },
            )
            attempt += 1
            continue
        L.info(
            "Compaction summary LiteLLM Responses call completed",
            extra={
                "attempt": attempt,
                "input_chars": len(current_conversation_text),
                "summary_chars": len(summary),
                "summary_estimated_tokens": _estimated_tokens(summary),
            },
        )
        return summary


async def _summarize_text_attempt(
    *,
    provider: LLMProvider,
    model: str,
    credential_kwargs: dict[str, object],
    system_prompt: str,
    user_prompt: str,
    conversation_text: str,
    endpoint_max_tokens: int | None,
) -> str:
    """Try creating summary once with LiteLLM Responses API."""
    try:
        response = await call_responses_model(
            provider=provider,
            model=model,
            credential_kwargs=credential_kwargs,
            input_items=[{"role": "user", "content": user_prompt + conversation_text}],
            instructions=system_prompt,
            stream=True,
            max_output_tokens=endpoint_max_tokens,
        )
        return await extract_response_text(response)
    except ResponsesOutputError as exc:
        raise _compaction_error_from_responses_output(exc) from exc
    except ContextWindowExceededError as exc:
        raise _compaction_error_from_litellm_exception(exc) from exc
    except OpenAIError as exc:
        raise _compaction_error_from_litellm_exception(exc) from exc


def _compaction_error_from_responses_output(
    exc: ResponsesOutputError,
) -> CompactionFailedError:
    """Convert shared Responses output error to compaction exception hierarchy."""
    message = exc.message
    if message:
        if _is_context_window_exceeded(code=exc.code, message=message):
            return CompactionContextWindowExceededError(
                _format_summary_model_error(code=exc.code, message=message)
            )
        if isinstance(exc.code, str) and exc.code:
            return CompactionFailedError(
                f"Compaction summary model failed: {exc.code}: {message}"
            )
        return CompactionFailedError(f"Compaction summary model failed: {message}")
    return CompactionFailedError(f"Compaction summary model failed: {exc.event_type}")


def _compaction_error_from_litellm_exception(
    exc: Exception,
) -> CompactionFailedError:
    """Convert LiteLLM exception to compaction exception hierarchy."""
    message = str(exc)
    code = getattr(exc, "code", None)
    if isinstance(exc, ContextWindowExceededError) or _is_context_window_exceeded(
        code=code,
        message=message,
    ):
        return CompactionContextWindowExceededError(
            _format_summary_model_error(code=code, message=message)
        )
    return CompactionFailedError(
        _format_summary_model_error(code=code, message=message)
    )


def _format_summary_model_error(*, code: object, message: str) -> str:
    """Format summary model error message as an internal, non-user-facing error."""
    if isinstance(code, str) and code:
        return f"Compaction summary model failed: {code}: {message}"
    return f"Compaction summary model failed: {message}"


def _is_context_window_exceeded(*, code: object, message: object) -> bool:
    """Determine whether provider error is context window exceeded."""
    if code == "context_length_exceeded":
        return True
    if not isinstance(message, str):
        return False
    normalized = message.lower()
    return "context window" in normalized and (
        "exceed" in normalized or "too long" in normalized
    )


def _truncate_context_retry_text(text: str, *, keep_chars: int) -> str:
    """Omit oldest rendered event lines from summary input."""
    if keep_chars <= 0:
        return _SUMMARY_CONTEXT_OMISSION_MARKER[:keep_chars]
    if len(text) <= keep_chars:
        return text

    marker_cost = len(_SUMMARY_CONTEXT_OMISSION_MARKER) + 1
    remaining = max(0, keep_chars - marker_cost)
    selected: list[str] = []
    for line in reversed(text.splitlines()):
        line_cost = len(line) + 1
        if line_cost <= remaining:
            selected.append(line)
            remaining -= line_cost
            continue
        if not selected and remaining > 0:
            selected.append(_truncate_context_retry_line(line, keep_chars=remaining))
        break

    if not selected:
        return _SUMMARY_CONTEXT_OMISSION_MARKER[:keep_chars]
    selected.reverse()
    return "\n".join([_SUMMARY_CONTEXT_OMISSION_MARKER, *selected])


def _truncate_context_retry_line(line: str, *, keep_chars: int) -> str:
    """Preserve head/tail of one rendered event line and omit the middle."""
    if keep_chars <= 0:
        return ""
    marker_len = len(_SUMMARY_CONTEXT_LINE_TRUNCATION_MARKER)
    if len(line) <= keep_chars or keep_chars <= marker_len:
        return line[-keep_chars:]
    payload_chars = keep_chars - marker_len
    prefix_chars = payload_chars // 2
    suffix_chars = payload_chars - prefix_chars
    return (
        line[:prefix_chars].rstrip()
        + _SUMMARY_CONTEXT_LINE_TRUNCATION_MARKER
        + line[-suffix_chars:].lstrip()
    )


def _estimated_tokens(text: str) -> int:
    """Return rough token estimate based on string length."""

    return len(text) // 4
