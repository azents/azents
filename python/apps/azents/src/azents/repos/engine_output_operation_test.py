"""Completed Engine output admission atomicity and serialization regressions."""

import asyncio
import copy

import pytest

from azents.core.enums import AgentRunPhase, EventKind
from azents.engine.events.types import (
    ActiveToolCall,
    ClientToolCallPayload,
    ClientToolResultPayload,
    OutputTextPart,
    SystemPromptAnalysisPayload,
    TurnMarkerPayload,
)
from azents.repos.engine_operation_test_support import (
    NOW,
    RUN_ID,
    SESSION_ID,
    FailurePoint,
    assistant_event,
    metadata_admission,
    operation_fixture,
    running_run,
    token_usage,
    tool_call_event,
)
from azents.repos.engine_output_operation import ModelOutputAdmission


def _admission(
    prompt: SystemPromptAnalysisPayload | None,
) -> ModelOutputAdmission:
    """Provide model Events, metadata and usage without any Engine callback."""
    return ModelOutputAdmission(
        session_id=SESSION_ID,
        run_id=RUN_ID,
        owner_generation=7,
        events=[assistant_event(), tool_call_event()],
        usage=token_usage(),
        inference_state=None,
        system_prompt_analysis=prompt,
        metadata_admission=metadata_admission(),
    )


async def test_model_output_commits_all_members_before_detached_return() -> None:
    """Use one completed session for metadata, Events, prompt and active calls."""
    prompt = SystemPromptAnalysisPayload()
    fixture = operation_fixture(
        run=running_run(), events=[], prompt=None, failure_point=None, failure=None
    )

    admitted = await fixture.output.admit_model_output(_admission(prompt))

    manager = fixture.manager
    assert not manager.active
    assert manager.commits == 1
    assert manager.rollbacks == 0
    assert len(manager.sessions) == 1
    assert manager.order == [
        "metadata",
        "append:assistant_message",
        "append:client_tool_call",
        "append:turn_marker",
        "snapshot_replace",
        "retry",
        "phase",
        "commit",
    ]
    assert admitted.events == manager.state.events[:2]
    assert admitted.turn_marker is manager.state.events[-1]
    usage_payload = admitted.turn_marker.payload
    assert isinstance(usage_payload, TurnMarkerPayload)
    assert usage_payload.usage == token_usage()
    assert admitted.events[0].adapter == "test"
    assert admitted.events[0].provider == "test"
    assert admitted.events[0].model == "test"
    assert admitted.events[0].native_format == "responses"
    assert admitted.events[0].schema_version == "1"
    assert admitted.events[1].external_id == f"tool-call:{RUN_ID}:call-1"
    assert manager.state.prompt is prompt
    assert manager.state.metadata == [metadata_admission()]
    assert manager.state.completions == []
    run = manager.state.run
    assert run is not None
    assert run.phase is AgentRunPhase.EXECUTING_TOOLS
    assert run.retry_state is None
    assert len(run.active_tool_calls) == 1
    active = run.active_tool_calls[0]
    assert active.call_id == "call-1"
    assert active.arguments == "{}"
    assert active.owner_generation == 7
    assert active.wire_dialect == "json_function"
    assert active.started_at.tzinfo is not None


async def test_model_output_without_usage_deletes_stale_prompt_and_clears_retry() -> (
    None
):
    """Keep empty optional fields semantic rather than skipping their mutations."""
    fixture = operation_fixture(
        run=running_run(),
        events=[],
        prompt=SystemPromptAnalysisPayload(),
        failure_point=None,
        failure=None,
    )
    admission = ModelOutputAdmission(
        session_id=SESSION_ID,
        run_id=RUN_ID,
        owner_generation=1,
        events=[assistant_event()],
        usage=None,
        inference_state=None,
        system_prompt_analysis=None,
        metadata_admission=None,
    )

    admitted = await fixture.output.admit_model_output(admission)

    assert fixture.manager.commits == 1
    assert not fixture.manager.active
    assert admitted.turn_marker is None
    assert len(fixture.manager.state.events) == 1
    assert fixture.manager.state.prompt is None
    assert fixture.manager.order == [
        "append:assistant_message",
        "snapshot_delete",
        "retry",
        "commit",
    ]
    assert fixture.manager.state.completions == []


@pytest.mark.parametrize(
    "point",
    ["metadata", "events", "turn_marker", "snapshot", "retry", "phase", "commit"],
)
async def test_late_model_output_failure_rolls_back_the_whole_atomic_group(
    point: FailurePoint,
) -> None:
    """Never return partially admitted metadata, Events, prompt or Tool state."""
    fixture = operation_fixture(
        run=running_run(),
        events=[],
        prompt=SystemPromptAnalysisPayload(),
        failure_point=point,
        failure=ValueError("late admission failure"),
    )
    before = copy.deepcopy(fixture.manager.state)

    with pytest.raises(ValueError, match="late admission failure"):
        await fixture.output.admit_model_output(_admission(None))

    assert fixture.manager.state == before
    assert not fixture.manager.active
    assert fixture.manager.commits == 0
    assert fixture.manager.rollbacks == 1
    assert len(fixture.manager.sessions) == 1


async def test_model_output_cancellation_aborts_prior_metadata_and_events() -> None:
    """Propagate cancellation after later state writes with no partial commit."""
    fixture = operation_fixture(
        run=running_run(),
        events=[],
        prompt=SystemPromptAnalysisPayload(),
        failure_point="phase",
        failure=asyncio.CancelledError(),
    )
    before = copy.deepcopy(fixture.manager.state)

    with pytest.raises(asyncio.CancelledError):
        await fixture.output.admit_model_output(_admission(None))

    assert fixture.manager.state == before
    assert fixture.manager.rollbacks == 1
    assert fixture.manager.commits == 0
    assert not fixture.manager.active


async def test_generated_client_result_commits_metadata_before_result_run_lock() -> (
    None
):
    """Compose the existing canonical result primitive without splitting metadata."""
    call_event = tool_call_event()
    call = call_event.payload
    assert isinstance(call, ClientToolCallPayload)
    run = running_run().model_copy(
        update={
            "active_tool_calls": [
                ActiveToolCall(
                    call_id=call.call_id,
                    name=call.name,
                    arguments=call.arguments,
                    wire_dialect=call.wire_dialect,
                    started_at=NOW,
                    owner_generation=1,
                )
            ],
        }
    )
    fixture = operation_fixture(
        run=run, events=[call_event], prompt=None, failure_point=None, failure=None
    )
    result = ClientToolResultPayload(
        call_id=call.call_id,
        name=call.name,
        wire_dialect=call.wire_dialect,
        status="completed",
        output=[OutputTextPart(text="stored image")],
    )

    event = await fixture.output.admit_client_tool_result(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        call=call,
        result=result,
        metadata_admission=metadata_admission(),
    )

    assert not fixture.manager.active
    assert fixture.manager.commits == 1
    assert len(fixture.manager.sessions) == 1
    assert event.external_id == f"tool-result:{RUN_ID}:call-1"
    assert event.kind is EventKind.CLIENT_TOOL_RESULT
    assert fixture.manager.state.metadata == [metadata_admission()]
    assert fixture.manager.state.run is not None
    assert fixture.manager.state.run.active_tool_calls == []
    assert fixture.manager.state.run.phase is AgentRunPhase.APPENDING_EVENTS
    order = fixture.manager.order
    assert order.index("metadata") < order.index("append:client_tool_result")
    assert order.index("append:client_tool_result") < order.index("lock_run")
    assert order[-1] == "commit"


@pytest.mark.parametrize("point", ["events", "phase", "commit"])
async def test_generated_client_result_failure_restores_metadata_and_active_owner(
    point: FailurePoint,
) -> None:
    """Keep generated-file result ownership atomic through every later failure."""
    call_event = tool_call_event()
    call = call_event.payload
    assert isinstance(call, ClientToolCallPayload)
    run = running_run().model_copy(
        update={
            "active_tool_calls": [
                ActiveToolCall(
                    call_id=call.call_id,
                    name=call.name,
                    arguments=call.arguments,
                    wire_dialect=call.wire_dialect,
                    started_at=NOW,
                    owner_generation=1,
                )
            ],
        }
    )
    fixture = operation_fixture(
        run=run,
        events=[call_event],
        prompt=None,
        failure_point=point,
        failure=ValueError("result admission failed"),
    )
    before = copy.deepcopy(fixture.manager.state)

    with pytest.raises(ValueError, match="result admission failed"):
        await fixture.output.admit_client_tool_result(
            run_id=RUN_ID,
            session_id=SESSION_ID,
            call=call,
            result=ClientToolResultPayload(
                call_id=call.call_id,
                name=call.name,
                wire_dialect=call.wire_dialect,
                status="completed",
                output=[OutputTextPart(text="stored image")],
            ),
            metadata_admission=metadata_admission(),
        )

    assert fixture.manager.state == before
    assert fixture.manager.commits == 0
    assert fixture.manager.rollbacks == 1
    assert not fixture.manager.active
