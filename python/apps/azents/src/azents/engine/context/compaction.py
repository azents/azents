"""Context compaction summary generation.

Converts event history into a structured summary through an LLM call.
"""

import dataclasses
import logging
import os
from collections.abc import AsyncIterable, Awaitable
from typing import Protocol, runtime_checkable

from azcommon.logging import bind_extra
from litellm.exceptions import ContextWindowExceededError, OpenAIError
from litellm.responses.main import aresponses
from openai.types.responses.response_input_param import ResponseInputParam
from openai.types.responses.response_text_config_param import ResponseTextConfigParam
from pydantic import TypeAdapter

from azents.core.enums import LLMProvider
from azents.engine.events.litellm_responses import (
    guard_litellm_streaming_logging,
)
from azents.engine.run.errors import (
    CompactionContextWindowExceededError,
    CompactionFailedError,
)

logger = logging.getLogger(__name__)
_RESPONSE_INPUT_ADAPTER: TypeAdapter[ResponseInputParam] = TypeAdapter(
    ResponseInputParam
)
_RESPONSE_TEXT_ADAPTER: TypeAdapter[ResponseTextConfigParam] = TypeAdapter(
    ResponseTextConfigParam
)
_SUMMARY_TEXT_CONFIG: ResponseTextConfigParam = _RESPONSE_TEXT_ADAPTER.validate_python(
    {"format": {"type": "text"}, "verbosity": "low"}
)

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


@dataclasses.dataclass(frozen=True)
class _ResponsesEndpointKwargs:
    """Endpoint kwargs to pass to Responses call."""

    api_key: str | None = None
    api_base: str | None = None
    base_url: str | None = None
    custom_llm_provider: str | None = None
    store: bool | None = None


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


@runtime_checkable
class _ResponseWithOutputText(Protocol):
    """Response with Responses output_text attribute."""

    output_text: str


@runtime_checkable
class _ResponseWithOutput(Protocol):
    """Response with Responses output list attribute."""

    output: list[object]


@runtime_checkable
class _ModelDumpable(Protocol):
    """Object supporting Pydantic-style model_dump."""

    def model_dump(self, *, mode: str = "python") -> dict[str, object]:
        """Convert object to dict."""
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
Create an updated handoff checkpoint for the compacted transcript below.
The recent raw tail may be preserved separately by the runtime. Summarize only
the compacted transcript provided here. Do not duplicate preserved tail content,
but do not omit durable state from the compacted transcript just because a raw
tail exists.

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

_RESPONSES_API_PROVIDERS: frozenset[LLMProvider] = frozenset(
    {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}
)


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
    endpoint_kwargs = _responses_endpoint_kwargs(
        credential_kwargs,
        provider=provider,
    )
    endpoint_max_tokens = _responses_max_output_tokens(provider, max_tokens)

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
                model=model,
                endpoint_kwargs=endpoint_kwargs,
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
    model: str,
    endpoint_kwargs: _ResponsesEndpointKwargs,
    system_prompt: str,
    user_prompt: str,
    conversation_text: str,
    endpoint_max_tokens: int | None,
) -> str:
    """Try creating summary once with LiteLLM Responses API."""
    input_payload = _RESPONSE_INPUT_ADAPTER.validate_python(
        [
            {"role": "user", "content": user_prompt + conversation_text},
        ]
    )
    try:
        response = await aresponses(
            model=model,
            input=input_payload,
            instructions=system_prompt,
            stream=True,
            max_output_tokens=endpoint_max_tokens,
            text=_SUMMARY_TEXT_CONFIG,
            custom_llm_provider=endpoint_kwargs.custom_llm_provider,
            store=endpoint_kwargs.store,
            api_key=endpoint_kwargs.api_key,
            api_base=endpoint_kwargs.api_base,
            base_url=endpoint_kwargs.base_url,
        )
        if isinstance(response, AsyncIterable):
            guard_litellm_streaming_logging(response)
        return await _extract_response_text(response)
    except ContextWindowExceededError as exc:
        raise _compaction_error_from_litellm_exception(exc) from exc
    except OpenAIError as exc:
        raise _compaction_error_from_litellm_exception(exc) from exc


def _responses_endpoint_kwargs(
    credential_kwargs: dict[str, object],
    *,
    provider: LLMProvider,
) -> _ResponsesEndpointKwargs:
    """Normalize credential kwargs to Responses endpoint kwargs."""
    api_key = _optional_string(credential_kwargs.get("api_key"), "api_key")
    api_base = _optional_string(credential_kwargs.get("api_base"), "api_base")
    base_url = _optional_string(credential_kwargs.get("base_url"), "base_url")
    custom_llm_provider = _optional_string(
        credential_kwargs.get("custom_llm_provider"),
        "custom_llm_provider",
    )
    store = _optional_bool(credential_kwargs.get("store"), "store")

    if provider not in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        return _ResponsesEndpointKwargs(
            api_key=api_key,
            api_base=api_base,
            base_url=base_url,
            custom_llm_provider=custom_llm_provider,
            store=store,
        )

    custom_llm_provider = custom_llm_provider or "openai"
    base_url = base_url or api_base
    if base_url is None and provider == LLMProvider.OPENAI:
        base_url = os.environ.get("AZ_OPENAI_BASE_URL")
    api_base = api_base or base_url
    if provider == LLMProvider.CHATGPT_OAUTH:
        store = False if store is None else store
    return _ResponsesEndpointKwargs(
        api_key=api_key,
        api_base=api_base,
        base_url=base_url,
        custom_llm_provider=custom_llm_provider,
        store=store,
    )


def _responses_max_output_tokens(provider: LLMProvider, max_tokens: int) -> int | None:
    """Return output token limit to pass to Responses endpoint."""
    if provider in {LLMProvider.OPENAI, LLMProvider.CHATGPT_OAUTH}:
        # Codex-compatible Responses endpoints reject max_output_tokens on
        # compaction-style calls; enforce our summary budget after generation.
        return None
    if max_tokens <= 0:
        return None
    return max_tokens


def _optional_string(value: object, name: str) -> str | None:
    """Validate credential string option."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    msg = f"{name} must be a string"
    raise TypeError(msg)


def _optional_bool(value: object, name: str) -> bool | None:
    """Validate credential bool option."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    msg = f"{name} must be a bool"
    raise TypeError(msg)


async def _extract_response_text(response: object) -> str:
    """Extract assistant text from LiteLLM/OpenAI Responses response."""
    if isinstance(response, AsyncIterable):
        return await _extract_stream_response_text(response)

    if isinstance(response, _ResponseWithOutputText) and response.output_text:
        return response.output_text

    raw_response = _model_dump(response)
    raw_texts = _extract_response_output_text(raw_response)
    if raw_texts:
        return "\n".join(raw_texts)

    if not isinstance(response, _ResponseWithOutput):
        return ""

    parts: list[str] = []
    for item in response.output:
        raw = _model_dump(item)
        if raw.get("type") != "message":
            continue
        content = raw.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


async def _extract_stream_response_text(response: AsyncIterable[object]) -> str:
    """Extract assistant text from Streaming Responses event."""
    deltas: list[str] = []
    completed_texts: list[str] = []
    async for event in response:
        raw = _model_dump(event)
        stream_error = _stream_error(raw)
        if stream_error is not None:
            raise stream_error
        delta = _text_delta(raw)
        if delta:
            deltas.append(delta)
        text = _event_text(raw)
        if text:
            completed_texts.append(text)
        raw_item = raw.get("item")
        item = _model_dump(raw_item)
        if item.get("type") == "message":
            text = _extract_message_item_text(item)
            if text:
                completed_texts.append(text)
        nested_item = _model_dump(item.get("item"))
        if nested_item.get("type") == "message":
            text = _extract_message_item_text(nested_item)
            if text:
                completed_texts.append(text)
        response_dict = _model_dump(raw.get("response"))
        completed_texts.extend(_extract_response_output_text(response_dict))
        item_response_dict = _model_dump(item.get("response"))
        completed_texts.extend(_extract_response_output_text(item_response_dict))
    if completed_texts:
        return "\n".join(_dedupe_adjacent(completed_texts))
    if deltas:
        return "".join(deltas)
    return ""


def _stream_error(event: dict[str, object]) -> CompactionFailedError | None:
    """Convert Responses stream error event to compaction failure exception."""
    event_type = _event_type(event)
    if event_type not in {"error", "response.failed", "response.incomplete"}:
        return None

    error = _model_dump(event.get("error"))
    response = _model_dump(event.get("response"))
    response_error = _model_dump(response.get("error"))
    details = error or response_error
    if details:
        message = details.get("message")
        code = details.get("code")
        if isinstance(message, str) and message:
            if _is_context_window_exceeded(code=code, message=message):
                return CompactionContextWindowExceededError(
                    _format_summary_model_error(code=code, message=message)
                )
            if isinstance(code, str) and code:
                return CompactionFailedError(
                    f"Compaction summary model failed: {code}: {message}"
                )
            return CompactionFailedError(f"Compaction summary model failed: {message}")

    incomplete_details = _model_dump(response.get("incomplete_details"))
    reason = incomplete_details.get("reason")
    if isinstance(reason, str) and reason:
        if _is_context_window_exceeded(code=reason, message=reason):
            return CompactionContextWindowExceededError(
                f"Compaction summary model incomplete: {reason}"
            )
        return CompactionFailedError(f"Compaction summary model incomplete: {reason}")

    return CompactionFailedError(f"Compaction summary model failed: {event_type}")


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


def _event_type(event: dict[str, object]) -> str:
    """Return Responses stream event type as string."""
    event_type = event.get("type")
    if isinstance(event_type, str):
        return event_type
    value = getattr(event_type, "value", None)
    if isinstance(value, str):
        return value
    return str(event_type)


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


def _text_delta(event: dict[str, object]) -> str:
    """Extract text delta from Responses stream event."""
    delta = event.get("delta")
    if isinstance(delta, str) and delta:
        return delta
    item = _model_dump(event.get("item"))
    item_delta = item.get("delta")
    if isinstance(item_delta, str) and item_delta:
        return item_delta
    return ""


def _event_text(event: dict[str, object]) -> str:
    """Extract completed text field from Responses done event."""
    text = event.get("text")
    if isinstance(text, str) and text:
        return text
    item = _model_dump(event.get("item"))
    item_text = item.get("text")
    if isinstance(item_text, str) and item_text:
        return item_text
    part = _model_dump(event.get("part"))
    part_text = part.get("text")
    if isinstance(part_text, str) and part_text:
        return part_text
    return ""


def _extract_response_output_text(response: dict[str, object]) -> list[str]:
    """Extract message text from completed response output."""
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text:
        return [output_text]
    output = response.get("output")
    if not isinstance(output, list):
        return []
    messages: list[str] = []
    for item in output:
        raw_item = _model_dump(item)
        if raw_item.get("type") != "message":
            continue
        text = _extract_message_item_text(raw_item)
        if text:
            messages.append(text)
    return messages


def _extract_message_item_text(item: dict[str, object]) -> str:
    """Extract text part from Responses message output item."""
    content = item.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        raw_part = _model_dump(part)
        text = raw_part.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts)


def _dedupe_adjacent(texts: list[str]) -> list[str]:
    """Keep identical adjacent completed text only once."""
    deduped: list[str] = []
    for text in texts:
        if deduped and deduped[-1] == text:
            continue
        deduped.append(text)
    return deduped


def _model_dump(item: object) -> dict[str, object]:
    """Convert Pydantic/dict response item to dict."""
    if isinstance(item, dict):
        return item
    if isinstance(item, _ModelDumpable):
        return item.model_dump(mode="python")
    return {}


def _estimated_tokens(text: str) -> int:
    """Return rough token estimate based on string length."""

    return len(text) // 4
