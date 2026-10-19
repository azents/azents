"""Initial Routine input is complete; idle continuation focuses one oldest item."""

import datetime

from azents.core.routine import RoutineScope
from azents.core.routine_execution import RoutineAdmittedContext, RoutineExecutionState
from azents.core.routine_execution_test import execution
from azents.core.routine_judgment_test import candidate
from azents.core.routine_presentation import (
    ordered_incomplete_routines,
    render_routine_execution_input,
    replace_routine_compaction_snapshot,
)


def _item(
    name: str, *, objective: str, previous: datetime.datetime | None
) -> RoutineExecutionState:
    base = execution(RoutineScope("workspace", "agent", "session"))
    context = candidate(name)
    context = context.model_copy(
        update={
            "content": context.content.model_copy(update={"objective": objective}),
            "last_executed_at": previous,
        }
    )
    return base.model_copy(
        update={
            "context": RoutineAdmittedContext(
                execution_id=f"occurrence-{name}",
                judgment_id="judgment-a",
                scope=base.context.scope,
                candidate=context,
                admitted_at=base.context.admitted_at,
            ),
        }
    )


def test_initial_input_keeps_all_stored_objectives_and_prior_context() -> None:
    first = _item("a", objective="First exact stored objective", previous=None)
    second = _item(
        "b",
        objective="Second exact stored objective",
        previous=datetime.datetime(2026, 10, 17, tzinfo=datetime.UTC),
    )
    rendered = render_routine_execution_input((first, second), continuation=False)
    assert first.context.candidate.content.objective in rendered
    assert second.context.candidate.content.objective in rendered
    assert '"last_executed_at": "2026-10-17T00:00:00Z"' in rendered
    assert '"latest_work": null' in rendered
    assert "occurrence-a" in rendered and "occurrence-b" in rendered
    assert "not other Routine work" in rendered


def test_continuation_has_first_full_context_then_other_identities_only() -> None:
    no_history = _item("no-history", objective="FIRST FULL CONTEXT", previous=None)
    old = _item(
        "old",
        objective="OLDER OBJECTIVE OMITTED FROM SUMMARY",
        previous=datetime.datetime(2026, 10, 16, tzinfo=datetime.UTC),
    )
    new = _item(
        "new",
        objective="NEWER OBJECTIVE OMITTED FROM SUMMARY",
        previous=datetime.datetime(2026, 10, 17, tzinfo=datetime.UTC),
    )
    assert ordered_incomplete_routines((new, no_history, old)) == (no_history, old, new)
    rendered = render_routine_execution_input((new, no_history, old), continuation=True)
    assert "FIRST FULL CONTEXT" in rendered
    assert "OLDER OBJECTIVE OMITTED FROM SUMMARY" not in rendered
    assert "NEWER OBJECTIVE OMITTED FROM SUMMARY" not in rendered
    assert "occurrence-old" in rendered and "occurrence-new" in rendered
    assert rendered.index("occurrence-old") < rendered.index("occurrence-new")


def test_compaction_snapshot_replaces_only_its_owned_section() -> None:
    item = _item("a", objective="Stored objective", previous=None)
    summary = (
        "User context.\n\n## Current Routine Obligations\n\nObsolete work."
        "\n\n## Other Work\n\nPreserve this."
    )
    updated = replace_routine_compaction_snapshot(summary, (item,))
    assert "Obsolete work." not in updated
    assert "Stored objective" in updated
    assert "## Other Work\n\nPreserve this." in updated
    assert updated.count("## Current Routine Obligations") == 1
    assert replace_routine_compaction_snapshot(updated, (item,)) == updated
    removed = replace_routine_compaction_snapshot(updated, ())
    assert "Current Routine Obligations" not in removed
    assert "Stored objective" not in removed
    assert "User context." in removed and "Preserve this." in removed


def test_compaction_keeps_every_objective_in_deterministic_order() -> None:
    first = _item("first", objective="First full objective", previous=None)
    second = _item(
        "second",
        objective="Second full objective",
        previous=datetime.datetime(2026, 10, 17, tzinfo=datetime.UTC),
    )
    rendered = replace_routine_compaction_snapshot("User context.", (second, first))
    assert "First full objective" in rendered and "Second full objective" in rendered
    assert rendered.count('"objective"') == 2
    assert rendered.index("occurrence-first") < rendered.index("occurrence-second")
    assert replace_routine_compaction_snapshot(rendered, (first, second)) == rendered
