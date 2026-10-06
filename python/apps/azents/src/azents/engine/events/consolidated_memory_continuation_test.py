"""Changed aggregate prefixes cannot continue hidden stored model context."""

import pytest

from azents.core.historical_memory_consolidation import ConsolidationScope
from azents.core.historical_memory_context import (
    build_memory_context_snapshot,
    filter_memory_context_snapshot,
    render_memory_context_snapshot,
)
from azents.engine.events.protocols import NativeModelRequest
from azents.engine.events.responses_continuation import ResponsesContinuationPlanner
from azents.testing.consolidated_context import CONTEXT_FIXTURE_TIME, context_entry


@pytest.mark.parametrize("placement", ["instructions", "input"])
@pytest.mark.parametrize("change", ["denial", "refresh"])
def test_changed_unit_forces_complete_replay_without_stored_response_identity(
    placement: str,
    change: str,
) -> None:
    team = context_entry(
        scope=ConsolidationScope.TEAM, text="Denied Team sentinel", exact_bytes=None
    )
    personal = context_entry(
        scope=ConsolidationScope.USER,
        text="Permitted personal sentinel",
        exact_bytes=None,
    )
    snapshot = build_memory_context_snapshot(
        boundary_head_event_id=None,
        created_at=CONTEXT_FIXTURE_TIME,
        saved_entries=[],
        historical_entries=[team, personal],
    )
    before = render_memory_context_snapshot(snapshot)
    if change == "denial":
        changed_snapshot = filter_memory_context_snapshot(
            snapshot,
            available_saved_ids=set(),
            available_scopes={personal.unit.scope},
        )
    else:
        changed_snapshot = build_memory_context_snapshot(
            boundary_head_event_id=None,
            created_at=CONTEXT_FIXTURE_TIME,
            saved_entries=[],
            historical_entries=[
                context_entry(
                    scope=ConsolidationScope.TEAM,
                    text="Refreshed Team sentinel",
                    exact_bytes=None,
                ),
                personal,
            ],
        )
    after = render_memory_context_snapshot(changed_snapshot)
    planner = ResponsesContinuationPlanner()
    previous_input: list[dict[str, object]] = [
        {"role": "user", "content": "Synthetic question"}
    ]
    kwargs: dict[str, object] = {
        "instructions": before
        if placement == "instructions"
        else "Stable instructions",
        "store": True,
    }
    if placement == "input":
        previous_input.insert(0, {"role": "system", "content": before})
    previous = NativeModelRequest(
        native_replay_context=None,
        model="fixture",
        input=previous_input,
        tools=[],
        kwargs=kwargs,
    )
    output: dict[str, object] = {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "Synthetic answer"}],
    }
    planner.record_completion(
        previous, response_id="stored-denied-context", output_items=[output]
    )
    delta: dict[str, object] = {"role": "user", "content": "Next question"}
    unchanged = NativeModelRequest(
        native_replay_context=None,
        model="fixture",
        input=[*previous.input, output, delta],
        tools=[],
        kwargs=previous.kwargs,
    )
    assert planner.plan(unchanged).previous_response_id == "stored-denied-context"
    current_input = [*previous.input, output, delta]
    current_kwargs = dict(previous.kwargs)
    if placement == "instructions":
        current_kwargs["instructions"] = after
    else:
        current_input[0] = {"role": "system", "content": after}
    changed = NativeModelRequest(
        native_replay_context=None,
        model="fixture",
        input=current_input,
        tools=[],
        kwargs=current_kwargs,
    )
    plan = planner.plan(changed)
    assert plan.previous_response_id is None
    assert plan.input_items == current_input
    assert "Denied Team sentinel" not in str(changed.input) + str(changed.kwargs)
    assert "Permitted personal sentinel" in str(changed.input) + str(changed.kwargs)
    assert ("Refreshed Team sentinel" in str(changed.input) + str(changed.kwargs)) == (
        change == "refresh"
    )
