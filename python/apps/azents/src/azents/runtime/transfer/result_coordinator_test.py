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
from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferConfig,
    RuntimeTransferDirection,
    RuntimeTransferObject,
    RuntimeTransferOutcome,
    RuntimeTransferRecord,
)
from azents.runtime.transfer.memory import InMemoryRuntimeTransferStateStore
from azents.runtime.transfer.result_coordinator import (
    RuntimeRunnerTransferResultCoordinator,
)

_NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)
_DIGEST = "a" * 64


@pytest.mark.asyncio
async def test_download_success_marks_committed_settles_and_appends_final() -> None:
    harness = await _harness(RuntimeTransferDirection.DOWNLOAD)
    record = await harness.claim_stream()

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
    assert replies[0].event.payload["success"] is True


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


async def _harness(direction: RuntimeTransferDirection) -> _Harness:
    state = InMemoryRuntimeTransferStateStore(config=_config(), clock=lambda: _NOW)
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
    return _Harness(
        state,
        coordination,
        control,
        RuntimeRunnerTransferResultCoordinator(
            state_store=state,
            coordination_store=coordination,
            control_protocol=control,
            clock=lambda: _NOW,
        ),
        direction,
    )


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
