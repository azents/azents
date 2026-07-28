"""Trusted Runner transfer result coordinator tests."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from azents_runtime_control.runner_transfer import (
    RunnerTransferDirection,
    RunnerTransferFailure,
    RunnerTransferIdentity,
    RunnerTransferOutcome,
    RunnerTransferResult,
)

from azents.runtime.control_protocol.service import RuntimeControlProtocolService
from azents.runtime.coordination.data import (
    RuntimeConnectionKind,
    RuntimeCoordinationTarget,
    RuntimeOperationMetadata,
    RuntimeOperationStatus,
    RuntimeOperationTransferDirection,
)
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.runtime.transfer.coordinator import RuntimeTransferCoordinator
from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferCleanupStatus,
    RuntimeTransferConfig,
    RuntimeTransferDirection,
    RuntimeTransferObject,
    RuntimeTransferOutcome,
    RuntimeTransferRecord,
)
from azents.runtime.transfer.data import (
    RuntimeTransferFailure as StateTransferFailure,
)
from azents.runtime.transfer.memory import InMemoryRuntimeTransferStateStore
from azents.runtime.transfer.result_coordinator import (
    RuntimeRunnerTransferResultCoordinator,
)

_NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
_DIGEST = "a" * 64


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _Cleanup:
    def __init__(self) -> None:
        self.records: list[RuntimeTransferRecord] = []

    async def cleanup(self, record: RuntimeTransferRecord) -> None:
        self.records.append(record)


@pytest.mark.asyncio
async def test_download_success_marks_committed_settles_and_appends_final() -> None:
    cleanup = _Cleanup()
    harness = await _harness(RuntimeTransferDirection.DOWNLOAD, cleanup=cleanup)
    streaming = await harness.claim_stream()
    record = await harness.state.begin_verification(
        "transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=1,
        accepted_runner_generation=1,
        claim_id=streaming.stream_claim_id or "",
        expected_revision=streaming.revision,
    )
    assert record is not None

    await harness.coordinator.handle(
        _result(
            direction=RunnerTransferDirection.DOWNLOAD,
            outcome=RunnerTransferOutcome.SUCCEEDED,
            committed=True,
            failure=None,
        ),
        request_id="runner-result-1",
    )

    settled = await harness.state.get("transfer-1")
    assert settled is not None
    assert settled.terminal_outcome is RuntimeTransferOutcome.SUCCEEDED
    assert settled.cleanup_status is RuntimeTransferCleanupStatus.COMPLETE
    assert len(cleanup.records) == 1
    assert cleanup.records[0].completed_object_cleanup_required is True
    replies = await harness.control.read_replies(
        reply_stream_id="reply-1",
        after_cursor=None,
        limit=10,
    )
    assert len(replies) == 1
    assert replies[0].event.final is True
    assert replies[0].event.payload["success"] is True
    assert record.stream_claim_id is not None


@pytest.mark.asyncio
async def test_upload_success_requires_authoritative_available_manifest() -> None:
    harness = await _harness(RuntimeTransferDirection.UPLOAD)
    streaming = await harness.claim_stream()
    verifying = await harness.state.begin_verification(
        "transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=1,
        accepted_runner_generation=1,
        claim_id=streaming.stream_claim_id or "",
        expected_revision=streaming.revision,
    )
    assert verifying is not None
    available = await harness.state.publish_available(
        "transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=1,
        accepted_runner_generation=1,
        claim_id=verifying.stream_claim_id or "",
        expected_revision=verifying.revision,
        actual_size=3,
        actual_sha256=_DIGEST,
    )
    assert available is not None
    responsibility = await harness.state.record_completed_object_cleanup(
        "transfer-1",
        attempt_id="attempt-1",
        expected_revision=available.revision,
        status=RuntimeTransferCleanupStatus.RETRYABLE_FAILURE,
        multipart_cleanup_required=False,
        completed_object_cleanup_required=True,
    )
    assert responsibility is not None
    committed_response = await harness.state.commit_upload_response(
        "transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=1,
        accepted_runner_generation=1,
        claim_id=responsibility.stream_claim_id or "",
        expected_revision=responsibility.revision,
        actual_size=3,
        actual_sha256=_DIGEST,
    )
    assert committed_response is not None

    await harness.coordinator.handle(
        _result(
            direction=RunnerTransferDirection.UPLOAD,
            outcome=RunnerTransferOutcome.SUCCEEDED,
            committed=False,
            failure=None,
        ),
        request_id="runner-result-1",
    )

    current = await harness.state.get("transfer-1")
    assert current is not None
    assert current.phase.value == "available"
    replies = await harness.control.read_replies(
        reply_stream_id="reply-1", after_cursor=None, limit=10
    )
    assert len(replies) == 1
    assert replies[0].event.request_id == "request-1"
    assert replies[0].event.payload["success"] is True


@pytest.mark.asyncio
async def test_upload_success_cannot_cross_cancel_requested_operation() -> None:
    """A late Runner success cannot replace durable cancellation authority."""
    harness = await _harness(RuntimeTransferDirection.UPLOAD)
    available = await _publish_upload_available(harness)
    await harness.coordination.update_operation_status(
        "operation-1",
        status=RuntimeOperationStatus.CANCEL_REQUESTED,
        updated_at=_NOW,
        final_event_cursor=None,
    )

    await harness.coordinator.handle(
        _result(
            direction=RunnerTransferDirection.UPLOAD,
            outcome=RunnerTransferOutcome.SUCCEEDED,
            committed=False,
            failure=None,
        ),
        request_id="late-runner-success",
    )

    current = await harness.state.get("transfer-1")
    assert current is not None
    assert current == available
    assert current.runner_result_confirmed_at is None
    assert (
        await harness.control.read_replies(
            reply_stream_id="reply-1",
            after_cursor=None,
            limit=10,
        )
        == []
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runner_failure", "expected_outcome", "expected_failure"),
    [
        (
            RunnerTransferFailure.STREAM_FAILED,
            RuntimeTransferOutcome.FAILED,
            StateTransferFailure.STREAM,
        ),
        (
            RunnerTransferFailure.DEADLINE_EXCEEDED,
            RuntimeTransferOutcome.EXPIRED,
            StateTransferFailure.EXPIRED,
        ),
    ],
)
async def test_upload_failure_preserves_completed_object_cleanup_and_reason(
    runner_failure: RunnerTransferFailure,
    expected_outcome: RuntimeTransferOutcome,
    expected_failure: StateTransferFailure,
) -> None:
    """Completed upload failures retain exact delete retry and deadline evidence."""
    harness = await _harness(RuntimeTransferDirection.UPLOAD)
    await _publish_upload_available(harness, commit_response=False)

    await harness.coordinator.handle(
        _result(
            direction=RunnerTransferDirection.UPLOAD,
            outcome=RunnerTransferOutcome.FAILED,
            committed=False,
            failure=runner_failure,
            size=None,
            sha256=None,
        ),
        request_id=f"runner-failure:{runner_failure.value}",
    )

    current = await harness.state.get("transfer-1")
    assert current is not None
    assert current.terminal_outcome is expected_outcome
    assert current.failure is expected_failure
    assert current.completed_object_cleanup_required is True
    assert current.multipart_cleanup_handle is None


@pytest.mark.asyncio
async def test_runner_failure_after_deadline_settles_expired() -> None:
    """A late Runner stream failure cannot defeat effective deadline authority."""
    clock = _Clock(_NOW)
    harness = await _harness(RuntimeTransferDirection.UPLOAD, clock=clock)
    await _publish_upload_available(harness, commit_response=False)
    clock.now = _NOW + timedelta(minutes=5)

    await harness.coordinator.handle(
        _result(
            direction=RunnerTransferDirection.UPLOAD,
            outcome=RunnerTransferOutcome.FAILED,
            committed=False,
            failure=RunnerTransferFailure.STREAM_FAILED,
            size=None,
            sha256=None,
        ),
        request_id="late-runner-failure",
    )

    current = await harness.state.get("transfer-1")
    assert current is not None
    assert current.terminal_outcome is RuntimeTransferOutcome.EXPIRED
    assert current.failure is StateTransferFailure.EXPIRED


@pytest.mark.asyncio
async def test_download_success_requires_authoritative_completion_barrier() -> None:
    """Runner success cannot advance a download that Control still sees streaming."""
    harness = await _harness(RuntimeTransferDirection.DOWNLOAD)
    await harness.claim_stream()

    await harness.coordinator.handle(
        _result(
            direction=RunnerTransferDirection.DOWNLOAD,
            outcome=RunnerTransferOutcome.SUCCEEDED,
            committed=True,
            failure=None,
        ),
        request_id="runner-result-before-control-completion",
    )

    record = await harness.state.get("transfer-1")
    assert record is not None
    assert record.phase.value == "streaming"
    assert (
        await harness.control.read_replies(
            reply_stream_id="reply-1",
            after_cursor=None,
            limit=10,
        )
        == []
    )


@pytest.mark.asyncio
async def test_mismatched_manifest_or_terminal_state_never_appends_success() -> None:
    harness = await _harness(RuntimeTransferDirection.DOWNLOAD)
    await harness.claim_stream()
    result = _result(
        direction=RunnerTransferDirection.DOWNLOAD,
        outcome=RunnerTransferOutcome.SUCCEEDED,
        committed=True,
        failure=None,
        sha256="b" * 64,
    )

    await harness.coordinator.handle(result, request_id="runner-result-1")
    await harness.coordinator.handle(result, request_id="runner-result-2")

    record = await harness.state.get("transfer-1")
    assert record is not None
    assert record.phase.value == "streaming"
    assert (
        await harness.control.read_replies(
            reply_stream_id="reply-1", after_cursor=None, limit=10
        )
        == []
    )


@pytest.mark.asyncio
async def test_failure_settles_once_and_late_result_cannot_replace_authority() -> None:
    harness = await _harness(RuntimeTransferDirection.DOWNLOAD)
    await harness.claim_stream()
    failed = _result(
        direction=RunnerTransferDirection.DOWNLOAD,
        outcome=RunnerTransferOutcome.FAILED,
        committed=False,
        failure=RunnerTransferFailure.INTEGRITY_FAILED,
        size=None,
        sha256=None,
    )

    await harness.coordinator.handle(failed, request_id="runner-result-1")
    await harness.coordinator.handle(failed, request_id="runner-result-2")

    record = await harness.state.get("transfer-1")
    assert record is not None
    assert record.terminal_outcome is RuntimeTransferOutcome.FAILED
    replies = await harness.control.read_replies(
        reply_stream_id="reply-1", after_cursor=None, limit=10
    )
    assert len(replies) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result_factory",
    [
        lambda result: replace(
            result,
            identity=replace(result.identity, attempt_id="wrong-attempt"),
        ),
        lambda result: replace(
            result,
            identity=replace(result.identity, runner_generation=2),
        ),
        lambda result: replace(result, dispatch_id="wrong-dispatch"),
        lambda result: replace(
            result,
            direction=RunnerTransferDirection.UPLOAD,
            destination_committed=False,
        ),
    ],
)
async def test_wrong_correlation_never_changes_state_or_reply(
    result_factory: Callable[[RunnerTransferResult], RunnerTransferResult],
) -> None:
    """Reject mismatched identity, generation, dispatch, or direction evidence."""
    harness = await _harness(RuntimeTransferDirection.DOWNLOAD)
    await harness.claim_stream()
    result = result_factory(
        _result(
            direction=RunnerTransferDirection.DOWNLOAD,
            outcome=RunnerTransferOutcome.SUCCEEDED,
            committed=True,
            failure=None,
        )
    )

    await harness.coordinator.handle(result, request_id="runner-result-1")

    record = await harness.state.get("transfer-1")
    assert record is not None
    assert record.phase.value == "streaming"
    assert (
        await harness.control.read_replies(
            reply_stream_id="reply-1",
            after_cursor=None,
            limit=10,
        )
        == []
    )


class _Harness:
    def __init__(
        self,
        state: InMemoryRuntimeTransferStateStore,
        coordination: InMemoryRuntimeCoordinationStore,
        control: RuntimeControlProtocolService,
        coordinator: RuntimeRunnerTransferResultCoordinator,
        direction: RuntimeTransferDirection,
    ) -> None:
        self.state = state
        self.coordination = coordination
        self.control = control
        self.coordinator = coordinator
        self.direction = direction

    async def claim_stream(self) -> RuntimeTransferRecord:
        admitted = await self.state.admit(
            _admission(self.direction),
            lease_id="lease-1",
        )
        assert admitted is not None
        ready = await self.state.mark_ready(
            "transfer-1",
            attempt_id="attempt-1",
            runtime_id="runtime-1",
            desired_generation=1,
            expected_revision=admitted.revision,
            object=RuntimeTransferObject("object-1", 3, _DIGEST),
        )
        assert ready is not None
        bound = await self.state.bind_dispatch(
            "transfer-1",
            attempt_id="attempt-1",
            runtime_id="runtime-1",
            desired_generation=1,
            accepted_runner_generation=1,
            expected_revision=ready.revision,
            dispatch_id="dispatch-1",
            dispatch_request_id="request-1",
        )
        assert bound is not None
        deliverable = await self.state.mark_dispatch_deliverable(
            "transfer-1",
            attempt_id="attempt-1",
            expected_revision=bound.revision,
            dispatch_id="dispatch-1",
            dispatch_request_id="request-1",
        )
        assert deliverable is not None
        enqueued = await self.state.mark_dispatch_enqueued(
            "transfer-1",
            attempt_id="attempt-1",
            operation_id="operation-1",
            expected_revision=deliverable.revision,
            dispatch_id="dispatch-1",
        )
        assert enqueued is not None
        streaming = await self.state.claim_stream(
            "transfer-1",
            attempt_id="attempt-1",
            runtime_id="runtime-1",
            desired_generation=1,
            accepted_runner_generation=1,
            expected_revision=enqueued.revision,
            claim_id="claim-1",
            owner_replica_id="replica-1",
        )
        assert streaming is not None
        return streaming


async def _harness(
    direction: RuntimeTransferDirection,
    *,
    cleanup: _Cleanup | None = None,
    clock: Callable[[], datetime] | None = None,
) -> _Harness:
    clock = clock or (lambda: _NOW)
    state = InMemoryRuntimeTransferStateStore(config=_config(), clock=clock)
    coordination = InMemoryRuntimeCoordinationStore()
    await coordination.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="connection-1",
        owner_replica_id="replica-1",
        connected_at=_NOW,
        heartbeat_at=datetime.now(UTC),
        ttl_seconds=60,
        metadata={},
    )
    operation = RuntimeOperationMetadata(
        operation_id="operation-1",
        runtime_id="runtime-1",
        target=RuntimeCoordinationTarget.RUNNER,
        generation=1,
        operation_type="file.transfer.v1",
        transfer_id="transfer-1",
        transfer_attempt_id="attempt-1",
        transfer_dispatch_id="dispatch-1",
        transfer_direction=RuntimeOperationTransferDirection(direction.value),
        request_stream_id="request-1",
        reply_stream_id="reply-1",
        status=RuntimeOperationStatus.ACTIVE,
        created_at=_NOW,
        updated_at=_NOW,
        deadline_at=_NOW + timedelta(minutes=5),
        body_stream_id=None,
        last_heartbeat_at=None,
        last_event_at=None,
        cancel_requested_at=None,
        final_event_cursor=None,
    )
    await coordination.put_operation(operation, ttl_seconds=60)
    control = RuntimeControlProtocolService(coordination)
    terminal_coordinator = RuntimeTransferCoordinator(
        state_store=state,
        coordination_store=coordination,
        cleanup=cleanup,
        clock=clock,
    )
    return _Harness(
        state,
        coordination,
        control,
        RuntimeRunnerTransferResultCoordinator(
            state_store=state,
            coordination_store=coordination,
            control_protocol=control,
            terminal_coordinator=terminal_coordinator,
            clock=clock,
        ),
        direction,
    )


async def _publish_upload_available(
    harness: _Harness,
    *,
    commit_response: bool = True,
) -> RuntimeTransferRecord:
    streaming = await harness.claim_stream()
    verifying = await harness.state.begin_verification(
        "transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=1,
        accepted_runner_generation=1,
        claim_id=streaming.stream_claim_id or "",
        expected_revision=streaming.revision,
    )
    assert verifying is not None
    available = await harness.state.publish_available(
        "transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=1,
        accepted_runner_generation=1,
        claim_id=verifying.stream_claim_id or "",
        expected_revision=verifying.revision,
        actual_size=3,
        actual_sha256=_DIGEST,
    )
    assert available is not None
    responsibility = await harness.state.record_completed_object_cleanup(
        "transfer-1",
        attempt_id="attempt-1",
        expected_revision=available.revision,
        status=RuntimeTransferCleanupStatus.RETRYABLE_FAILURE,
        multipart_cleanup_required=False,
        completed_object_cleanup_required=True,
    )
    assert responsibility is not None
    if not commit_response:
        return responsibility
    committed = await harness.state.commit_upload_response(
        "transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=1,
        accepted_runner_generation=1,
        claim_id=responsibility.stream_claim_id or "",
        expected_revision=responsibility.revision,
        actual_size=3,
        actual_sha256=_DIGEST,
    )
    assert committed is not None
    return committed


def _admission(direction: RuntimeTransferDirection) -> RuntimeTransferAdmission:
    return RuntimeTransferAdmission(
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        direction=direction,
        runtime_id="runtime-1",
        desired_generation=1,
        operation_id="operation-1",
        session_id=None,
        agent_id=None,
        runtime_path="/workspace/file",
        overwrite=False,
        expected_size=3,
        expected_sha256=_DIGEST,
        product_maximum_size=10,
        provider_maximum_size=10,
        deadline_at=_NOW + timedelta(minutes=5),
        source_expires_at=None,
        resource_class="file",
    )


def _result(
    *,
    direction: RunnerTransferDirection,
    outcome: RunnerTransferOutcome,
    committed: bool,
    failure: RunnerTransferFailure | None,
    size: int | None = 3,
    sha256: str | None = _DIGEST,
) -> RunnerTransferResult:
    return RunnerTransferResult(
        identity=RunnerTransferIdentity(
            transfer_id="transfer-1",
            attempt_id="attempt-1",
            runtime_id="runtime-1",
            runner_generation=1,
        ),
        operation_id="operation-1",
        dispatch_id="dispatch-1",
        direction=direction,
        outcome=outcome,
        actual_size=size,
        sha256=sha256,
        destination_committed=committed,
        failure=failure,
    )


def _config() -> RuntimeTransferConfig:
    return RuntimeTransferConfig(
        per_runtime_attempts=4,
        per_runtime_bytes=100,
        deployment_attempts=4,
        deployment_bytes=100,
        admission_lease=timedelta(minutes=5),
        consumer_lease=timedelta(minutes=1),
        stream_lease=timedelta(seconds=30),
        terminal_ttl=timedelta(minutes=5),
        list_page_size=10,
    )
