"""Routine source bookkeeping and immutable admitted execution contracts."""

import datetime

import pytest
from pydantic import ValidationError

from azents.core.routine import (
    RoutineDeliveryStatus,
    RoutineObjectiveOutcome,
    RoutineScope,
    RoutineWorkResult,
)
from azents.core.routine_execution import (
    RoutineAdmittedContext,
    RoutineCheckState,
    RoutineExecutionState,
    RoutineSourceInput,
)
from azents.core.routine_judgment_test import candidate

_NOW = datetime.datetime(2026, 10, 18, tzinfo=datetime.UTC)


def execution(scope: RoutineScope) -> RoutineExecutionState:
    """Construct one admitted item without fabricating an ordinary Run."""
    return RoutineExecutionState(
        context=RoutineAdmittedContext(
            execution_id="occurrence-a",
            judgment_id="judgment-a",
            scope=scope,
            candidate=candidate(),
            admitted_at=_NOW,
        ),
        phase="admitted",
        current_run_id=None,
        started_at=None,
        completed_at=None,
        work=None,
        delivery_status=None,
        delivery_error=None,
    )


@pytest.mark.parametrize("judgment_id", [None, "queued-inbox-judgment"])
def test_source_bookkeeping_round_trip(judgment_id: str | None) -> None:
    state = RoutineCheckState(
        last_tick_at=_NOW,
        last_action_at=None,
        source_inputs=(
            RoutineSourceInput(routine_id="routine-a", events=candidate().events),
        ),
        queued_judgment_id=judgment_id,
    )
    assert RoutineCheckState.model_validate_json(state.model_dump_json()) == state
    assert state.last_action_at is None
    assert state.queued_judgment_id == judgment_id


def test_duplicate_source_identity_is_not_admitted() -> None:
    with pytest.raises(ValidationError, match="unique"):
        item = RoutineSourceInput(routine_id="routine-a", events=candidate().events)
        RoutineCheckState(
            last_tick_at=None,
            last_action_at=None,
            source_inputs=(item, item),
            queued_judgment_id=None,
        )


@pytest.mark.parametrize("phase", ["admitted", "started", "completed", "cancelled"])
def test_phase_contract_separates_start_completion_and_delivery(phase: str) -> None:
    original = execution(RoutineScope("workspace", "agent", "session"))
    values = original.model_dump()
    values["phase"] = phase
    if phase in {"started", "completed"}:
        values.update(current_run_id="ordinary-run", started_at=_NOW)
    if phase in {"completed", "cancelled"}:
        values["completed_at"] = _NOW
    if phase == "completed":
        values.update(
            work=RoutineWorkResult(
                objective_outcome=RoutineObjectiveOutcome.FAILED,
                result="The source could not be reached.",
                next_hint="Check the source at the next opportunity.",
                notify=False,
                message=None,
            ),
            delivery_status=RoutineDeliveryStatus.NOT_REQUESTED,
        )
    state = RoutineExecutionState.model_validate(values)
    assert state.incomplete == (phase in {"admitted", "started"})
    assert RoutineExecutionState.model_validate_json(state.model_dump_json()) == state


@pytest.mark.parametrize(
    "changes",
    [
        {"phase": "started"},
        {"current_run_id": "invented-run"},
        {"phase": "completed", "completed_at": _NOW},
        {"phase": "cancelled"},
        {"delivery_status": "delivered"},
        {"started_at": datetime.datetime(2026, 10, 18)},
    ],
)
def test_invalid_or_fabricated_execution_phase_is_rejected(
    changes: dict[str, object],
) -> None:
    values = execution(RoutineScope("workspace", "agent", "session")).model_dump()
    with pytest.raises(ValidationError):
        RoutineExecutionState.model_validate({**values, **changes})
