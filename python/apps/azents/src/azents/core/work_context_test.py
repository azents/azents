"""Execution-independent admitted work context contracts."""

import pytest

from azents.core.routine_execution import RoutineExecutionRef
from azents.core.work_context import WorkContext


def _routine(name: str) -> RoutineExecutionRef:
    return RoutineExecutionRef(
        routine_id=f"routine-{name}",
        execution_id=f"occurrence-{name}",
        slug=name,
        title=name,
    )


def test_context_carries_multiple_independent_occurrences() -> None:
    first, second = _routine("first"), _routine("second")
    context = WorkContext(
        scheduled_cycle_ids=(),
        routine_executions=(first,),
        unrelated_input=False,
    ).merge(
        WorkContext(
            scheduled_cycle_ids=(),
            routine_executions=(second,),
            unrelated_input=False,
        )
    )
    assert context.routine_only
    assert context.routine_executions == (first, second)
    assert context.contains_routine(
        routine_id=first.routine_id, execution_id=first.execution_id
    )
    assert not context.contains_routine(
        routine_id=first.routine_id, execution_id=second.execution_id
    )


def test_common_context_merge_is_idempotent() -> None:
    context = WorkContext(
        scheduled_cycle_ids=("c" * 32,),
        routine_executions=(_routine("first"),),
        unrelated_input=False,
    )
    assert context.merge(context) == context
    assert WorkContext.empty().merge(context) == context
    assert context.merge(WorkContext.empty()) == context
    assert not context.routine_only


def test_ordinary_input_cannot_acquire_routine_only_archive_authority() -> None:
    context = WorkContext(
        scheduled_cycle_ids=(),
        routine_executions=(_routine("first"),),
        unrelated_input=False,
    ).merge(
        WorkContext(
            scheduled_cycle_ids=(),
            routine_executions=(),
            unrelated_input=True,
        )
    )
    assert not context.routine_only
    assert context.routine_executions == (_routine("first"),)


def test_multiple_scheduled_cycles_remain_independently_selectable() -> None:
    first = WorkContext(
        scheduled_cycle_ids=("a" * 32,),
        routine_executions=(),
        unrelated_input=False,
    )
    second = first.model_copy(update={"scheduled_cycle_ids": ("b" * 32,)})
    combined = first.merge(second)
    assert combined.scheduled_cycle_ids == ("a" * 32, "b" * 32)
    assert combined.merge(first) == combined
    assert first.scheduled_cycle_ids == ("a" * 32,)


def test_conflicting_occurrence_identity_cannot_overwrite_carried_authority() -> None:
    original = _routine("first")
    context = WorkContext(
        scheduled_cycle_ids=(),
        routine_executions=(original,),
        unrelated_input=False,
    )
    replaced = original.model_copy(update={"routine_id": "unrelated-definition"})
    with pytest.raises(ValueError, match="conflicting Routine"):
        context.merge(context.model_copy(update={"routine_executions": (replaced,)}))


def test_context_round_trip_does_not_require_transcript_or_run_identity() -> None:
    context = WorkContext(
        scheduled_cycle_ids=("a" * 32,),
        routine_executions=(_routine("first"),),
        unrelated_input=True,
    )
    assert WorkContext.model_validate_json(context.model_dump_json()) == context


def test_duplicate_occurrence_identity_is_rejected() -> None:
    first = _routine("first")
    duplicate = _routine("second").model_copy(
        update={"execution_id": first.execution_id}
    )
    with pytest.raises(ValueError, match="must be unique"):
        WorkContext(
            scheduled_cycle_ids=(),
            routine_executions=(first, duplicate),
            unrelated_input=False,
        )
