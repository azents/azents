"""Canonical ordinary-execution text for immutable admitted Routine context."""

import datetime
import json

from azents.core.routine_execution import RoutineExecutionRef, RoutineExecutionState

ROUTINE_COMPACTION_HEADING = "## Current Routine Obligations"


def replace_routine_compaction_snapshot(
    summary: str, states: tuple[RoutineExecutionState, ...]
) -> str:
    """Replace only this owned section while retaining other hook summaries."""
    marker = f"\n\n{ROUTINE_COMPACTION_HEADING}"
    start = summary.find(marker)
    if start == -1 and summary.startswith(ROUTINE_COMPACTION_HEADING):
        start = 0
    base = summary
    if start != -1:
        section_start = start + (2 if start else 0)
        end = summary.find("\n\n## ", section_start + 3)
        base = summary[:start] if end == -1 else summary[:start] + summary[end:]
    base = base.rstrip()
    incomplete = ordered_incomplete_routines(states)
    if not incomplete:
        return base
    snapshot = (
        ROUTINE_COMPACTION_HEADING
        + "\n\n"
        + render_routine_execution_input(incomplete, continuation=True)
    )
    return f"{base}\n\n{snapshot}" if base else snapshot


def routine_execution_ref(state: RoutineExecutionState) -> RoutineExecutionRef:
    """Project identity and title without copying a mutable definition."""
    return RoutineExecutionRef(
        routine_id=state.context.candidate.routine_id,
        execution_id=state.context.execution_id,
        slug=state.context.candidate.slug,
        title=state.context.candidate.content.title,
    )


def ordered_incomplete_routines(
    states: tuple[RoutineExecutionState, ...],
) -> tuple[RoutineExecutionState, ...]:
    """Order no-history items first, then oldest prior execution and exact identity."""
    return tuple(
        sorted(
            (state for state in states if state.incomplete),
            key=lambda state: (
                state.context.candidate.last_executed_at is not None,
                state.context.candidate.last_executed_at
                or datetime.datetime.min.replace(tzinfo=datetime.UTC),
                state.context.candidate.routine_id,
                state.context.execution_id,
            ),
        )
    )


def render_routine_execution_input(
    states: tuple[RoutineExecutionState, ...], *, continuation: bool
) -> str:
    """Render admitted work only; judgment never invents another objective."""
    if not states or not all(state.incomplete for state in states):
        raise ValueError("Routine input requires incomplete admitted work.")
    ordered = ordered_incomplete_routines(states) if continuation else states
    full_contexts = ordered[:1] if continuation else ordered
    contexts = [
        {
            "execution_id": state.context.execution_id,
            **state.context.candidate.model_dump(mode="json"),
        }
        for state in full_contexts
    ]
    content = (
        "Continue these admitted Session Routine occurrences through ordinary "
        "Agent execution. Use each stored objective and source context as given. "
        "Record a result and next-check hint for each occurrence, including an "
        "honest failed investigation. Choose notify separately; silent work is "
        "valid. A result settles only that occurrence, not other Routine work, "
        "ordinary Session work or Channel Work. Existing action permissions still "
        "apply. Do not recreate objectives or infer a mandatory notification.\n\n"
        "Admitted contexts:\n" + json.dumps(contexts, ensure_ascii=False)
    )
    if continuation and len(ordered) > 1:
        content += (
            "\n\nOther incomplete occurrences (use the Routine context tool to "
            "read another full admitted context):\n"
            + json.dumps(
                [routine_execution_ref(state).model_dump() for state in ordered[1:]],
                ensure_ascii=False,
            )
        )
    return content
