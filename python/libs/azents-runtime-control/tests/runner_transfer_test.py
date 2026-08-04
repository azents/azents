"""Runner transfer shared value validation tests."""

from datetime import UTC, datetime

import pytest
from google.protobuf import timestamp_pb2

from azents_runtime_control.grpc_runner_client import (
    runner_transfer_cancel_from_message,
    runner_transfer_intent_from_message,
    runner_transfer_result_from_message,
)
from azents_runtime_control.proto import (
    runtime_runner_control_pb2,
    runtime_runner_transfer_pb2,
)
from azents_runtime_control.runner_transfer import (
    RunnerTransferCancelReason,
    RunnerTransferDirection,
    RunnerTransferFailure,
    RunnerTransferIdentity,
    RunnerTransferOutcome,
    RunnerTransferResult,
)


@pytest.mark.parametrize(
    ("direction", "committed"),
    [
        (RunnerTransferDirection.DOWNLOAD, True),
        (RunnerTransferDirection.UPLOAD, False),
    ],
)
def test_successful_result_accepts_exact_directional_commit_evidence(
    direction: RunnerTransferDirection,
    committed: bool,
) -> None:
    result = RunnerTransferResult(
        identity=_identity(),
        operation_id="operation-1",
        dispatch_id="dispatch-1",
        direction=direction,
        outcome=RunnerTransferOutcome.SUCCEEDED,
        actual_size=3,
        sha256="a" * 64,
        destination_committed=committed,
        failure=None,
    )

    assert result.actual_size == 3


def test_transfer_intent_maps_all_optional_field_presence() -> None:
    """Preserve explicitly supplied falsey optional transfer intent values."""
    deadline_at = datetime(2026, 7, 25, 12, 30, tzinfo=UTC)
    message = runtime_runner_control_pb2.RunnerTransferIntent(
        identity=_identity_message(),
        direction=runtime_runner_transfer_pb2.TRANSFER_DIRECTION_DOWNLOAD,
        operation_id="operation-1",
        runtime_path="/workspace/output.txt",
        deadline_at=_timestamp(deadline_at),
        protocol_version="2026-07-25",
        capability="file.transfer.v1",
        dispatch_id="dispatch-1",
    )
    message.owner_session_id = ""
    message.overwrite = False
    message.expected_size = 0
    message.expected_sha256 = ""

    intent = runner_transfer_intent_from_message(message)

    assert intent.identity == _identity()
    assert intent.direction is RunnerTransferDirection.DOWNLOAD
    assert intent.owner_session_id == ""
    assert intent.overwrite is False
    assert intent.expected_size == 0
    assert intent.expected_sha256 == ""
    assert intent.deadline_at == deadline_at


def test_transfer_intent_maps_absent_optional_fields_to_none() -> None:
    """Keep omitted transfer intent optional fields distinct from falsey values."""
    message = runtime_runner_control_pb2.RunnerTransferIntent(
        identity=_identity_message(),
        direction=runtime_runner_transfer_pb2.TRANSFER_DIRECTION_UPLOAD,
        operation_id="operation-1",
        runtime_path="/workspace/input.txt",
        deadline_at=_timestamp(datetime(2026, 7, 25, tzinfo=UTC)),
        protocol_version="2026-07-25",
        capability="file.transfer.v1",
        dispatch_id="dispatch-1",
    )

    intent = runner_transfer_intent_from_message(message)

    assert intent.direction is RunnerTransferDirection.UPLOAD
    assert intent.owner_session_id is None
    assert intent.overwrite is None
    assert intent.expected_size is None
    assert intent.expected_sha256 is None


@pytest.mark.parametrize(
    ("proto_reason", "reason"),
    [
        (
            runtime_runner_control_pb2.RUNNER_TRANSFER_CANCEL_REASON_CALLER,
            RunnerTransferCancelReason.CALLER,
        ),
        (
            runtime_runner_control_pb2.RUNNER_TRANSFER_CANCEL_REASON_DEADLINE,
            RunnerTransferCancelReason.DEADLINE,
        ),
        (
            runtime_runner_control_pb2.RUNNER_TRANSFER_CANCEL_REASON_SUPERSEDED,
            RunnerTransferCancelReason.SUPERSEDED,
        ),
        (
            runtime_runner_control_pb2.RUNNER_TRANSFER_CANCEL_REASON_SHUTDOWN,
            RunnerTransferCancelReason.SHUTDOWN,
        ),
    ],
)
def test_transfer_cancel_maps_each_reason(
    proto_reason: runtime_runner_control_pb2.RunnerTransferCancelReason.ValueType,
    reason: RunnerTransferCancelReason,
) -> None:
    """Map every bounded protobuf cancellation reason."""
    cancel = runner_transfer_cancel_from_message(
        runtime_runner_control_pb2.RunnerTransferCancel(
            identity=_identity_message(),
            operation_id="operation-1",
            dispatch_id="dispatch-1",
            reason=proto_reason,
        )
    )

    assert cancel.identity == _identity()
    assert cancel.reason is reason


def test_transfer_result_rejects_present_empty_sha256() -> None:
    """Present SHA-256 evidence must contain one exact lowercase digest."""
    with pytest.raises(ValueError, match="sha256"):
        runner_transfer_result_from_message(
            runtime_runner_control_pb2.RunnerTransferResult(
                identity=_identity_message(),
                operation_id="operation-1",
                dispatch_id="dispatch-1",
                outcome=runtime_runner_control_pb2.RUNNER_TRANSFER_OUTCOME_FAILED,
                actual_size=0,
                sha256="",
                destination_committed=False,
                failure=(
                    runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_STREAM_FAILED
                ),
            ),
            direction=RunnerTransferDirection.DOWNLOAD,
        )


@pytest.mark.parametrize(
    ("identity", "operation_id", "dispatch_id"),
    [
        (
            RunnerTransferIdentity("", "attempt-1", "runtime-1", 2),
            "operation-1",
            "dispatch-1",
        ),
        (
            RunnerTransferIdentity("transfer-1", "attempt-1", "runtime-1", 0),
            "operation-1",
            "dispatch-1",
        ),
        (
            RunnerTransferIdentity("transfer-1", "attempt-1", "runtime-1", 2),
            "o" * 129,
            "dispatch-1",
        ),
        (
            RunnerTransferIdentity("transfer-1", "attempt-1", "runtime-1", 2),
            "operation-1",
            "d" * 129,
        ),
    ],
)
def test_result_rejects_unbounded_lookup_identity(
    identity: RunnerTransferIdentity,
    operation_id: str,
    dispatch_id: str,
) -> None:
    with pytest.raises(ValueError):
        RunnerTransferResult(
            identity=identity,
            operation_id=operation_id,
            dispatch_id=dispatch_id,
            direction=RunnerTransferDirection.UPLOAD,
            outcome=RunnerTransferOutcome.FAILED,
            actual_size=None,
            sha256=None,
            destination_committed=False,
            failure=RunnerTransferFailure.STREAM_FAILED,
        )


@pytest.mark.parametrize(
    ("outcome", "size", "sha", "committed", "failure"),
    [
        (RunnerTransferOutcome.SUCCEEDED, None, None, True, None),
        (RunnerTransferOutcome.SUCCEEDED, 3, "a" * 64, False, None),
        (
            RunnerTransferOutcome.FAILED,
            3,
            None,
            False,
            RunnerTransferFailure.STREAM_FAILED,
        ),
        (RunnerTransferOutcome.FAILED, None, None, False, None),
        (
            RunnerTransferOutcome.CANCELLED,
            None,
            None,
            False,
            RunnerTransferFailure.STREAM_FAILED,
        ),
    ],
)
def test_result_rejects_contradictory_optional_field_matrix(
    outcome: RunnerTransferOutcome,
    size: int | None,
    sha: str | None,
    committed: bool,
    failure: RunnerTransferFailure | None,
) -> None:
    with pytest.raises(ValueError):
        RunnerTransferResult(
            identity=_identity(),
            operation_id="operation-1",
            dispatch_id="dispatch-1",
            direction=RunnerTransferDirection.DOWNLOAD,
            outcome=outcome,
            actual_size=size,
            sha256=sha,
            destination_committed=committed,
            failure=failure,
        )


def _identity() -> RunnerTransferIdentity:
    return RunnerTransferIdentity(
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        runner_generation=2,
    )


def _identity_message() -> runtime_runner_transfer_pb2.TransferIdentity:
    return runtime_runner_transfer_pb2.TransferIdentity(
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        runner_generation=2,
    )


def _timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    message = timestamp_pb2.Timestamp()
    message.FromDatetime(value)
    return message
