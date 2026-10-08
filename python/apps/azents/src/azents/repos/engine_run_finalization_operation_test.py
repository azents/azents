"""Completed Engine terminal branch, atomicity and publication-data regressions."""

import asyncio
import copy
import dataclasses
from typing import Literal

import pytest

from azents.core.enums import (
    AgentRunParentResultDeliveryState,
    AgentRunStatus,
    EventKind,
)
from azents.core.model_operation import ModelOperationKind
from azents.engine.events.types import RunMarkerPayload
from azents.repos.engine_operation_test_support import (
    RUN_ID,
    SESSION_ID,
    FailurePoint,
    assistant_event,
    metadata_admission,
    operation_fixture,
    running_run,
    token_usage,
)
from azents.repos.engine_output_operation import ModelOutputAdmission
from azents.repos.model_operation_completion import ModelOperationCompletion


def _completion() -> ModelOperationCompletion:
    """Carry the exact foreground authority previously captured by Worker."""
    return ModelOperationCompletion(
        workspace_id="workspace-1",
        session_id=SESSION_ID,
        run_id=RUN_ID,
        owner_generation=1,
        operation_kind=ModelOperationKind.FOREGROUND,
    )


async def test_model_completion_commits_marker_settlement_delivery_and_pins() -> None:
    """Keep foreground settlement and terminal projection in one closed session."""
    output = assistant_event()
    fixture = operation_fixture(
        run=running_run(),
        events=[output],
        prompt=None,
        failure_point=None,
        failure=None,
    )

    marker = await fixture.finalization.complete_model_run(
        session_id=SESSION_ID,
        run_id=RUN_ID,
        output_events=[output],
        completion=_completion(),
    )

    manager = fixture.manager
    assert not manager.active
    assert manager.commits == 1
    assert len(manager.sessions) == 1
    assert manager.order == [
        "find_marker",
        "append:run_marker",
        "completion",
        "prelock",
        "terminal",
        "delivery",
        "pins",
        "commit",
    ]
    assert marker.external_id == f"run-marker:{RUN_ID}:completed"
    assert manager.state.completions == [_completion()]
    assert manager.state.deliveries == [RUN_ID]
    assert manager.state.released_pins == [RUN_ID]
    run = manager.state.run
    assert run is not None
    assert run.status is AgentRunStatus.COMPLETED
    assert run.terminal_result_event_id == output.id
    assert run.terminal_result_message == "final response"
    assert run.last_completed_event_id is None


@pytest.mark.parametrize(
    "point",
    ["marker", "completion", "prelock", "terminal", "delivery", "pins", "commit"],
)
async def test_late_terminal_failure_rolls_back_marker_success_delivery_and_pins(
    point: FailurePoint,
) -> None:
    """Preserve committed model output while abandoning only terminal writes."""
    output = assistant_event()
    fixture = operation_fixture(
        run=running_run(),
        events=[output],
        prompt=None,
        failure_point=point,
        failure=ValueError("terminal failed"),
    )
    before = copy.deepcopy(fixture.manager.state)

    with pytest.raises(ValueError, match="terminal failed"):
        await fixture.finalization.complete_model_run(
            session_id=SESSION_ID,
            run_id=RUN_ID,
            output_events=[output],
            completion=_completion(),
        )

    assert fixture.manager.state == before
    assert fixture.manager.state.events == [output]
    assert fixture.manager.commits == 0
    assert fixture.manager.rollbacks == 1
    assert not fixture.manager.active


async def test_terminal_cancellation_rolls_back_earlier_settlement_and_delivery() -> (
    None
):
    """Cancellation at pin release aborts the same whole terminal atomic group."""
    output = assistant_event()
    fixture = operation_fixture(
        run=running_run(),
        events=[output],
        prompt=None,
        failure_point="pins",
        failure=asyncio.CancelledError(),
    )
    before = copy.deepcopy(fixture.manager.state)

    with pytest.raises(asyncio.CancelledError):
        await fixture.finalization.complete_model_run(
            session_id=SESSION_ID,
            run_id=RUN_ID,
            output_events=[output],
            completion=_completion(),
        )

    assert fixture.manager.state == before
    assert fixture.manager.rollbacks == 1
    assert not fixture.manager.active


async def test_early_stop_has_terminal_group_but_no_marker_or_model_success() -> None:
    """Do not invent transcript or success writes before a stopped model turn."""
    fixture = operation_fixture(
        run=running_run(),
        events=[],
        prompt=None,
        failure_point=None,
        failure=None,
    )

    await fixture.finalization.interrupt_before_turn(run_id=RUN_ID)

    assert fixture.manager.state.events == []
    assert fixture.manager.state.completions == []
    assert fixture.manager.state.run is not None
    assert fixture.manager.state.run.status is AgentRunStatus.INTERRUPTED
    assert fixture.manager.order == [
        "prelock",
        "terminal",
        "delivery",
        "pins",
        "commit",
    ]
    assert not fixture.manager.active


@pytest.mark.parametrize("suppressed", [False, True])
async def test_polled_completion_retains_existing_parent_disposition(
    suppressed: bool,
) -> None:
    """Polling completion adds no marker or foreground settlement."""
    fixture = operation_fixture(
        run=running_run(),
        events=[],
        prompt=None,
        failure_point=None,
        failure=None,
    )

    await fixture.finalization.complete_polled_run(
        run_id=RUN_ID,
        suppress_parent_result=suppressed,
    )

    assert fixture.manager.state.events == []
    assert fixture.manager.state.completions == []
    assert fixture.manager.state.run is not None
    assert fixture.manager.state.run.status is AgentRunStatus.COMPLETED
    assert fixture.manager.state.released_pins == [RUN_ID]
    if suppressed:
        assert fixture.manager.state.deliveries == []
        assert fixture.manager.state.run.parent_result_delivery_state is (
            AgentRunParentResultDeliveryState.SUPPRESSED
        )
        assert fixture.manager.order == [
            "prelock",
            "terminal",
            "suppress_parent",
            "pins",
            "commit",
        ]
    else:
        assert fixture.manager.state.deliveries == [RUN_ID]
    assert not fixture.manager.active


async def test_bridge_completion_suppresses_parent_without_marker_or_success() -> None:
    """Keep bridge completion's unconditional parent suppression distinct."""
    fixture = operation_fixture(
        run=running_run(),
        events=[],
        prompt=None,
        failure_point=None,
        failure=None,
    )

    await fixture.finalization.complete_bridged_run(run_id=RUN_ID)

    assert fixture.manager.state.events == []
    assert fixture.manager.state.completions == []
    assert fixture.manager.state.deliveries == []
    assert fixture.manager.state.run is not None
    assert fixture.manager.state.run.parent_result_delivery_state is (
        AgentRunParentResultDeliveryState.SUPPRESSED
    )
    assert fixture.manager.state.released_pins == [RUN_ID]


@pytest.mark.parametrize(
    "status", [None, AgentRunStatus.COMPLETED, AgentRunStatus.RUNNING]
)
async def test_tool_stop_marker_is_conditional_on_current_running_state(
    status: AgentRunStatus | None,
) -> None:
    """A settled or missing Run is not overwritten after Tool-stop repair."""
    run = (
        None if status is None else running_run().model_copy(update={"status": status})
    )
    fixture = operation_fixture(
        run=run,
        events=[],
        prompt=None,
        failure_point=None,
        failure=None,
    )

    marker = await fixture.finalization.interrupt_after_tool_stop_if_running(
        session_id=SESSION_ID,
        run_id=RUN_ID,
    )

    assert fixture.manager.state.completions == []
    assert not fixture.manager.active
    if status is AgentRunStatus.RUNNING:
        assert marker is not None
        assert fixture.manager.state.run is not None
        assert fixture.manager.state.run.status is AgentRunStatus.INTERRUPTED
        assert fixture.manager.state.deliveries == [RUN_ID]
    else:
        assert marker is None
        assert fixture.manager.state.run == run
        assert fixture.manager.state.events == []
        assert fixture.manager.state.released_pins == []
        assert fixture.manager.order == ["read_run", "commit"]


async def test_turn_limit_has_marker_but_no_foreground_completion() -> None:
    """Return no publication object from the existing turn-limit terminal branch."""
    fixture = operation_fixture(
        run=running_run(),
        events=[],
        prompt=None,
        failure_point=None,
        failure=None,
    )

    result = await fixture.finalization.interrupt_turn_limit(
        session_id=SESSION_ID,
        run_id=RUN_ID,
    )

    assert result is None
    assert len(fixture.manager.state.events) == 1
    assert (
        fixture.manager.state.events[0].external_id
        == f"run-marker:{RUN_ID}:interrupted"
    )
    assert fixture.manager.state.completions == []
    assert not fixture.manager.active


async def test_partial_interruption_has_only_events_marker_and_terminal_group() -> None:
    """Do not compose usage, snapshot, retry clear or success into user interruption."""
    partial = assistant_event()
    fixture = operation_fixture(
        run=running_run(),
        events=[],
        prompt=None,
        failure_point=None,
        failure=None,
    )

    interrupted = await fixture.finalization.interrupt_model_stream(
        session_id=SESSION_ID,
        run_id=RUN_ID,
        assistant_events=[partial],
    )

    assert len(interrupted.events) == 1
    assert interrupted.run_marker.kind is EventKind.RUN_MARKER
    assert fixture.manager.state.completions == []
    assert fixture.manager.state.run is not None
    assert (
        fixture.manager.state.run.terminal_result_event_id == interrupted.events[0].id
    )
    assert fixture.manager.state.run.terminal_result_message == "final response"
    assert fixture.manager.order == [
        "append:assistant_message",
        "find_marker",
        "append:run_marker",
        "prelock",
        "terminal",
        "delivery",
        "pins",
        "commit",
    ]
    assert not fixture.manager.active


@pytest.mark.parametrize(
    "invalid", ["missing_run", "status", "cycle", "event", "message"]
)
async def test_scheduled_completion_preserves_all_existing_eligibility_predicates(
    invalid: Literal["missing_run", "status", "cycle", "event", "message"],
) -> None:
    """A recovery check cannot terminalize an ineligible or incomplete Run."""
    run = running_run().model_copy(
        update={
            "scheduled_task_cycle_id": "c" * 32,
            "terminal_result_event_id": "e" * 32,
            "terminal_result_message": "scheduled result",
        }
    )
    if invalid == "missing_run":
        run = None
    elif invalid == "status":
        run = run.model_copy(update={"status": AgentRunStatus.COMPLETED})
    elif invalid == "cycle":
        run = run.model_copy(update={"scheduled_task_cycle_id": None})
    elif invalid == "event":
        run = run.model_copy(update={"terminal_result_event_id": None})
    else:
        run = run.model_copy(update={"terminal_result_message": None})
    fixture = operation_fixture(
        run=run,
        events=[],
        prompt=None,
        failure_point=None,
        failure=None,
    )

    marker = await fixture.finalization.complete_committed_scheduled_result(
        session_id=SESSION_ID,
        run_id=RUN_ID,
        completion=_completion(),
    )

    assert marker is None
    assert fixture.manager.state.run == run
    assert fixture.manager.state.events == []
    assert fixture.manager.state.completions == []
    assert fixture.manager.state.released_pins == []
    assert fixture.manager.order == ["read_run", "commit"]
    assert not fixture.manager.active


@pytest.mark.parametrize("completion", [None, _completion()])
async def test_scheduled_completion_uses_committed_result_and_nullable_success(
    completion: ModelOperationCompletion | None,
) -> None:
    """Recover the exact durable scheduled result with no new model work."""
    fixture = operation_fixture(
        run=running_run().model_copy(
            update={
                "scheduled_task_cycle_id": "c" * 32,
                "terminal_result_event_id": "e" * 32,
                "terminal_result_message": "scheduled result",
            }
        ),
        events=[],
        prompt=None,
        failure_point=None,
        failure=None,
    )

    marker = await fixture.finalization.complete_committed_scheduled_result(
        session_id=SESSION_ID,
        run_id=RUN_ID,
        completion=completion,
    )

    assert marker is not None
    assert isinstance(marker.payload, RunMarkerPayload)
    assert marker.payload.status == "completed"
    assert fixture.manager.state.run is not None
    assert fixture.manager.state.run.status is AgentRunStatus.COMPLETED
    assert fixture.manager.state.run.terminal_result_event_id == "e" * 32
    assert fixture.manager.state.run.terminal_result_message == "scheduled result"
    assert fixture.manager.state.completions == (
        [] if completion is None else [completion]
    )
    assert fixture.manager.state.released_pins == [RUN_ID]
    assert not fixture.manager.active


async def test_terminal_failure_does_not_coalesce_prior_output_transaction() -> None:
    """The existing output commit survives a later foreground settlement failure."""
    fixture = operation_fixture(
        run=running_run(),
        events=[],
        prompt=None,
        failure_point=None,
        failure=None,
    )
    admitted = await fixture.output.admit_model_output(
        ModelOutputAdmission(
            session_id=SESSION_ID,
            run_id=RUN_ID,
            owner_generation=1,
            events=[assistant_event()],
            usage=token_usage(),
            inference_state=None,
            system_prompt_analysis=None,
            metadata_admission=metadata_admission(),
        )
    )
    committed_output = copy.deepcopy(fixture.manager.state)
    fixture.manager.failure_point = "completion"
    fixture.manager.failure = ValueError("foreground settlement failed")

    with pytest.raises(ValueError, match="foreground settlement failed"):
        await fixture.finalization.complete_model_run(
            session_id=SESSION_ID,
            run_id=RUN_ID,
            output_events=admitted.events,
            completion=_completion(),
        )

    assert fixture.manager.state == committed_output
    assert fixture.manager.commits == 1
    assert fixture.manager.rollbacks == 1
    assert len(fixture.manager.sessions) == 2
    assert not fixture.manager.active


@pytest.mark.parametrize("branch", ["model", "bridge"])
async def test_existing_nullable_delivery_and_pin_collaborators_remain_optional(
    branch: Literal["model", "bridge"],
) -> None:
    """Do not add fallback finalization or pin effects to old None collaborators."""
    fixture = operation_fixture(
        run=running_run(),
        events=[],
        prompt=None,
        failure_point=None,
        failure=None,
    )
    repository = dataclasses.replace(
        fixture.finalization,
        terminal_finalization_repository=None,
        model_file_pin_repository=None,
    )

    if branch == "model":
        await repository.complete_model_run(
            session_id=SESSION_ID,
            run_id=RUN_ID,
            output_events=[],
            completion=None,
        )
        assert fixture.manager.order == [
            "find_marker",
            "append:run_marker",
            "terminal",
            "commit",
        ]
    else:
        await repository.complete_bridged_run(run_id=RUN_ID)
        assert fixture.manager.order == ["terminal", "suppress_parent", "commit"]

    assert fixture.manager.state.deliveries == []
    assert fixture.manager.state.released_pins == []
    assert fixture.manager.state.completions == []
    assert not fixture.manager.active
