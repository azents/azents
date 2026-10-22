"""Typed process lifecycle observation transport round trips."""

from datetime import UTC, datetime

import pytest
from azents_runtime_control.grpc_runner_client import (
    _event_message,
    _operation_payload,
    runner_event_from_message,
)
from azents_runtime_control.process_observation import (
    ProcessCompletion,
    ProcessObservation,
)
from azents_runtime_control.proto import runtime_runner_control_pb2
from azents_runtime_control.runner import RunnerOperationEvent, RuntimeRunnerEventType

from azents.runtime.control_protocol.grpc.runner_server import _copy_operation_payload


def test_observe_operation_and_result_round_trip() -> None:
    request = runtime_runner_control_pb2.RunnerOperationRequest()
    _copy_operation_payload(
        request, "process.observe", {"after_revision": 9, "timeout_ms": 30_000}
    )
    assert request.WhichOneof("payload") == "process_observe"
    assert _operation_payload(request) == {"after_revision": 9, "timeout_ms": 30_000}
    observation = ProcessObservation(
        revision=10,
        running_count=1,
        completed=(ProcessCompletion("proc-1", "exited"),),
    )
    event = RunnerOperationEvent(
        request_id="request-1",
        runtime_id="runtime-1",
        generation=2,
        event_type=RuntimeRunnerEventType.FINAL_SUCCESS,
        payload={"process_observation": observation.to_payload()},
        created_at=datetime.now(UTC),
        final=True,
    )
    encoded = _event_message(event)
    assert encoded.final_success.WhichOneof("result") == "process_observe"
    decoded = runner_event_from_message(encoded, request_id="request-1")
    assert (
        ProcessObservation.from_payload(decoded.payload["process_observation"])
        == observation
    )


@pytest.mark.parametrize("detached", [True, False])
def test_execution_participation_survives_transport(detached: bool) -> None:
    request = runtime_runner_control_pb2.RunnerOperationRequest()
    _copy_operation_payload(
        request,
        "process.start",
        {
            "command": "read line",
            "yield_time_ms": 250,
            "max_output_bytes": 1024,
            "fire_and_forget": detached,
        },
    )
    assert _operation_payload(request)["fire_and_forget"] is detached
