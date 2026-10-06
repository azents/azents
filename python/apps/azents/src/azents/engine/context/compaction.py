"""Context compaction summary generation.

Converts event history into a structured summary through an LLM call.
"""

import dataclasses
import logging
from collections.abc import Awaitable
from typing import Protocol

from azcommon.logging import bind_extra

from azents.core.agent import SelectableModelCandidate
from azents.engine.model_factory_types import ModelSDKFactories
from azents.engine.model_stream import (
    ModelStreamCallContext,
    ModelStreamWatchdog,
)
from azents.engine.provider_errors import SDK_PROVIDER_ERRORS, map_model_provider_error
from azents.engine.provider_model_operation import call_model_operation_text_with_usage
from azents.engine.responses import ResponsesOutputError
from azents.engine.run.errors import (
    CompactionFailedError,
    CompactionModelStreamTimeoutError,
    ModelCallError,
    ModelStreamTimeoutError,
)
from azents.engine.run.model_transport import ModelTransportState
from azents.engine.run.provider_failure import (
    ModelProviderFailure,
    model_provider_failure,
)
from azents.engine.run.resolve import effective_model_output_tokens

logger = logging.getLogger(__name__)
_SUMMARY_CHARS_PER_TOKEN = 4
_SUMMARY_DEFAULT_CONTEXT_WINDOW_TOKENS = 128_000
_SUMMARY_TARGET_CONTEXT_RATIO = 0.03
_SUMMARY_LIMIT_CONTEXT_RATIO = 0.08
_SUMMARY_TRUNCATE_TOLERANCE_RATIO = 1.1
_MIN_SUMMARY_TARGET_CHARS = 12_000
_MAX_SUMMARY_TARGET_CHARS = 24_000
_MIN_SUMMARY_LIMIT_CHARS = 16_000
_MAX_SUMMARY_LIMIT_CHARS = 50_000
_SUMMARY_ROUNDING_CHARS = 1_000
_SUMMARY_TRUNCATION_NOTE = "\n\n[Truncated by Azents compaction guard.]"


@dataclasses.dataclass(frozen=True)
class CompactionSummaryBudget:
    """Compaction summary output budget."""

    target_chars: int
    limit_chars: int
    truncate_chars: int


class SummaryModelCall(Protocol):
    """Summary model call function interface."""

    def __call__(
        self,
        *,
        candidate: SelectableModelCandidate,
        credential_kwargs: dict[str, object],
        effective_input_tokens: int,
        transport_state: ModelTransportState,
        system_prompt: str,
        user_prompt: str,
        conversation_text: str,
        session_id: str | None = None,
    ) -> Awaitable[str]:
        """Call the summary model."""

        ...


_SUMMARY_SYSTEM_PROMPT = """\
You are a context compaction engine for a long-running agent.

Produce an execution-ready handoff checkpoint that lets the next agent continue
from the most advanced validated state.

Reconstruct the current task by applying the transcript chronologically. Treat
user messages, completed actions, tool results, and later corrections as state
transitions that update the working direction.

Identify the current active objective, the execution state that is true now,
completed work, the next concrete actions, and the constraints and decisions
that still affect those actions.

Update existing checkpoints with later transcript evidence. Consolidate replaced
directions into the current state instead of carrying them forward as competing
instructions.

Make the checkpoint operational. Lead with the active objective and execution
state, preserve the furthest verified progress, and order next actions by
execution priority. Include commands, outcomes, errors, paths, branches, PRs,
IDs, and conclusions when they help the next agent act. Use Needs verification
only for uncertainty that materially affects the next action.

Scale checkpoint detail to task complexity. Use concise structure to eliminate
repetition and conversational narration while retaining continuation-relevant
state and evidence. For complex or multi-stage work, preserve the details needed
to continue directly from the checkpoint, including evidence of completed work
and conclusions from resolved questions. Keep simple checkpoints brief and let
task complexity determine length.

This is an internal handoff. Output only the checkpoint.
"""

_SUMMARY_USER_TEMPLATE = """\
Create an updated execution checkpoint for the full compacted transcript below.
The runtime may append bounded recent user-message and transcript excerpts after
your checkpoint for immediate continuity. Build the checkpoint from the whole
compacted transcript because other raw events may no longer be available.

Process the transcript in chronological order and fold changes into one current
working state. Later user direction updates the active objective. Completed
actions update the execution state. Later tool and repository observations
update earlier assumptions.

Use an existing checkpoint as the previous state to update, not as a separate
direction to preserve alongside newer work. Keep historical or replaced
approaches only when they explain an active constraint or prevent duplicated
investigation.

Required output sections:
## Active Objective
## Current Execution State
## Completed Work
## Next Actions
## Active Constraints and Decisions
## Relevant Files and Identifiers
## Verification
## References

Guidelines:
- Scale checkpoint detail to task complexity and let complexity determine length.
- Use concise bullets to eliminate repetition and conversational narration while
  retaining continuation-relevant state and evidence.
- For complex or multi-stage work, preserve the details needed to continue
  directly from the checkpoint, including evidence of completed work and
  conclusions from resolved questions.
- Describe the current working state rather than narrating the conversation.
- Start from the furthest completed and verified progress.
- Make Next Actions concrete, ordered, and directly useful for continuing work.
- Include branches, PRs, issues, commands, test results, errors, file paths,
  symbols, and external IDs only when needed to continue.
- If the compacted transcript shows that a Skill is actively being followed for
  unfinished work, include an "Active Skill" subsection in the checkpoint. A
  Skill is active when its instructions, checklist, workflow stage, or
  constraints are still needed to continue pending work. For each active Skill,
  preserve the Skill name and exact SKILL.md path if known, why it is still
  active, the current workflow/checklist stage, Skill-specific constraints or
  output format, and concrete next actions required by that Skill. Do not list
  every loaded Skill; omit Skills that were only inspected, used for completed
  work, or no longer constrain pending work.

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
    sdk_factories: ModelSDKFactories,
    watchdog: ModelStreamWatchdog,
    candidate: SelectableModelCandidate,
    credential_kwargs: dict[str, object],
    effective_input_tokens: int,
    websocket_enabled: bool,
    transport_state: ModelTransportState | None,
    system_prompt: str,
    user_prompt: str,
    conversation_text: str,
    session_id: str | None = None,
) -> str:
    """Create a checkpoint through the captured model's ordinary request contract."""
    selection = candidate.model_selection
    call_context = ModelStreamCallContext(
        call_kind="compaction",
        provider=selection.provider.value,
        provider_integration_id=selection.llm_provider_integration_id,
        model=selection.model_identifier,
        session_id=session_id,
        run_id=None,
        attempt_number=None,
        check_stop=None,
    )
    L = bind_extra(
        logger,
        {
            "provider": selection.provider.value,
            "provider_integration_id": selection.llm_provider_integration_id,
            "model": selection.model_identifier,
            "session_id": session_id,
            "conversation_chars": len(conversation_text),
            "conversation_estimated_tokens": _estimated_tokens(conversation_text),
            "requested_max_output_tokens": effective_model_output_tokens(
                selection, candidate.settings
            ),
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
    try:
        result = await call_model_operation_text_with_usage(
            sdk_factories=sdk_factories,
            watchdog=watchdog,
            selection=selection,
            settings=candidate.settings,
            credential_kwargs=credential_kwargs,
            effective_input_tokens=effective_input_tokens,
            websocket_enabled=websocket_enabled,
            instructions=system_prompt,
            input_text=user_prompt + conversation_text,
            call_context=call_context,
            transport_state=transport_state,
        )
    except ModelProviderFailure:
        raise
    except ModelStreamTimeoutError as exc:
        raise CompactionModelStreamTimeoutError(exc) from exc
    except ResponsesOutputError as exc:
        raise model_provider_failure(
            operation="compaction",
            provider=selection.provider.value,
            model=selection.model_identifier,
            integration=selection.llm_provider_integration_id,
            provider_message=exc.message,
            status_code=None,
            provider_code=exc.code,
            provider_error_type=exc.event_type,
            provider_error_param=exc.param,
        ) from None
    except ModelCallError as exc:
        raise CompactionFailedError(exc.user_message) from exc
    except SDK_PROVIDER_ERRORS as exc:
        raise map_model_provider_error(exc, call_context=call_context) from None
    summary = result.text
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


def _estimated_tokens(text: str) -> int:
    """Return rough token estimate based on string length."""

    return len(text) // 4
