"""Process wait ingress validation."""

import pytest
from azents_runtime_control.process_observation import ProcessObservation
from azents_runtime_control.runner import JsonValue

from azents_runtime_runner.operation_payloads import (
    OperationPayloadError,
    ProcessObservePayload,
    decode_operation_payload,
)


@pytest.mark.parametrize("operation_type", ["process.start", "process.write"])
@pytest.mark.parametrize("window", [10_001, 300_000])
def test_shell_yield_cap_is_enforced_at_runner_ingress(
    operation_type: str, window: int
) -> None:
    with pytest.raises(OperationPayloadError, match="at most 10000"):
        decode_operation_payload(
            operation_type,
            {
                "command": "true",
                "process_id": "proc-1",
                "yield_time_ms": window,
            },
        )


def test_observe_accepts_time_and_position_without_target_ids() -> None:
    assert decode_operation_payload(
        "process.observe",
        {
            "after_revision": 9,
            "timeout_ms": 900_000,
        },
    ) == ProcessObservePayload(after_revision=9, timeout_ms=900_000)


@pytest.mark.parametrize(
    "payload",
    [
        {"revision": -1, "running_count": 0, "completed": []},
        {"revision": True, "running_count": 0, "completed": []},
        {
            "revision": 1,
            "running_count": 0,
            "completed": [{"process_id": "p", "status": "running"}],
        },
        {"revision": 1, "running_count": 0, "completed": [], "stdout": "unexpected"},
    ],
)
def test_malformed_observation_is_rejected(payload: JsonValue) -> None:
    with pytest.raises(ValueError):
        ProcessObservation.from_payload(payload)
