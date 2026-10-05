"""Typed, redacted deterministic runtime hook fixture summaries."""

import pytest

from azents.engine.hooks.testing import _summarize_context
from azents.engine.hooks.types import (
    AfterToolCallHookContext,
    CompactionSummaryHookContext,
    RuntimeHibernateHookContext,
    TurnEndHookContext,
)


@pytest.mark.parametrize(
    ("context", "specific_fields"),
    [
        (
            RuntimeHibernateHookContext(
                workspace_id=None,
                agent_id="agent-1",
                session_id=None,
                agent_runtime_id="runtime-1",
            ),
            {"agent_runtime_id": "runtime-1"},
        ),
        (
            TurnEndHookContext(
                workspace_id="workspace-1",
                agent_id="agent-1",
                session_id="session-1",
                run_id="run-1",
                reason="completed",
                turn_index=2,
            ),
            {"run_id": "run-1", "reason": "completed", "turn_index": 2},
        ),
        (
            AfterToolCallHookContext(
                workspace_id="workspace-1",
                agent_id="agent-1",
                session_id="session-1",
                run_id="run-1",
                tool_name="read",
                toolkit_slug="runtime",
                args_json="sensitive-raw-marker",
                output_text="sensitive-raw-marker",
                error_message="sensitive-raw-marker",
            ),
            {"run_id": "run-1", "tool_name": "read", "toolkit_slug": "runtime"},
        ),
        (
            CompactionSummaryHookContext(
                workspace_id="workspace-1",
                agent_id="agent-1",
                session_id="session-1",
                run_id="run-1",
                compaction_id="compaction-1",
                reason="manual_command",
                covered_until_event_id="event-1",
                summary="sensitive-raw-marker",
                continuity_history="sensitive-raw-marker",
            ),
            {
                "run_id": "run-1",
                "compaction_id": "compaction-1",
                "reason": "manual_command",
                "covered_until_event_id": "event-1",
            },
        ),
    ],
)
def test_typed_hook_summary_preserves_keys_and_redaction(
    context: (
        RuntimeHibernateHookContext
        | TurnEndHookContext
        | AfterToolCallHookContext
        | CompactionSummaryHookContext
    ),
    specific_fields: dict[str, str | int],
) -> None:
    """Concrete context variants retain the same safe identifier-only shape."""
    summary = _summarize_context(context)
    expected: dict[str, str | int | None] = {
        "workspace_id": context.workspace_id,
        "agent_id": context.agent_id,
        "session_id": context.session_id,
        "run_id": None,
        "tool_name": None,
        "toolkit_slug": None,
        "turn_index": None,
        "reason": None,
        "agent_runtime_id": None,
        "compaction_id": None,
        "covered_until_event_id": None,
    }
    expected.update(specific_fields)
    assert summary == expected
    assert "sensitive-raw-marker" not in repr(summary)
