"""Runtime transfer coordinator dispatch and repair tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from azents.runtime.coordination.data import (
    RuntimeConnectionKind,
    RuntimeCoordinationTarget,
    RuntimeOperationStatus,
)
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.runtime.transfer.coordinator import (
    RuntimeTransferCoordinator,
    object_handle_for,
)
from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferCancellationReason,
    RuntimeTransferCleanupStatus,
    RuntimeTransferConfig,
    RuntimeTransferDirection,
    RuntimeTransferDispatchStatus,
    RuntimeTransferFailure,
    RuntimeTransferOutcome,
    RuntimeTransferRecord,
)
from azents.runtime.transfer.memory import InMemoryRuntimeTransferStateStore

_NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _Cleanup:
    def __init__(self) -> None:
        self.handles: list[str] = []
        self.preparation_handles: list[str] = []
        self.records: list[RuntimeTransferRecord] = []

    async def cleanup(self, record: RuntimeTransferRecord) -> None:
        self.records.append(record)
        if record.multipart_cleanup_handle is not None:
            self.handles.append(record.multipart_cleanup_handle)
        if record.preparation_multipart_cleanup_handle is not None:
            self.preparation_handles.append(record.preparation_multipart_cleanup_handle)


@pytest.mark.asyncio
async def test_dispatch_persists_metadata_only_intent_and_operation() -> None:
    state = InMemoryRuntimeTransferStateStore(config=_config(), clock=lambda: _NOW)
    coordination = InMemoryRuntimeCoordinationStore()
    await coordination.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="connection-1",
        owner_replica_id="replica-1",
        connected_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
        ttl_seconds=60,
        metadata={},
    )
    coordinator = RuntimeTransferCoordinator(
        state_store=state,
        coordination_store=coordination,
        cleanup=None,
        clock=lambda: _NOW,
    )
    admitted = await coordinator.admit(_admission(), lease_id="lease-1")
    assert admitted is not None
    ready = await coordinator.mark_ready(
        admitted,
        expected_revision=admitted.revision,
        object_handle=object_handle_for(admitted),
        size=3,
        sha256="a" * 64,
    )
    assert ready is not None

    dispatched = await coordinator.dispatch(
        ready,
        expected_revision=ready.revision,
        dispatch_id="dispatch-1",
    )

    assert dispatched.record.dispatch_status is RuntimeTransferDispatchStatus.ENQUEUED
    operation = await coordination.get_operation("operation-1")
    assert operation is not None
    assert operation.target is RuntimeCoordinationTarget.RUNNER
    assert operation.body_stream_id is None
    claimed = await coordination.claim_next_request(
        dispatched.request_stream_id,
        consumer_group="runner-1",
        consumer_id="consumer-1",
        block_ms=0,
    )
    assert claimed is not None
    assert claimed.envelope.operation_type == "file.transfer.v1"
    assert claimed.envelope.body_stream_id is None
    assert "bytes" not in claimed.envelope.payload


@pytest.mark.asyncio
async def test_generation_repair_fences_replaced_dispatch() -> None:
    state = InMemoryRuntimeTransferStateStore(config=_config(), clock=lambda: _NOW)
    coordination = InMemoryRuntimeCoordinationStore()
    await coordination.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="connection-1",
        owner_replica_id="replica-1",
        connected_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
        ttl_seconds=60,
        metadata={},
    )
    coordinator = RuntimeTransferCoordinator(
        state_store=state,
        coordination_store=coordination,
        cleanup=None,
        clock=lambda: _NOW,
    )
    admitted = await coordinator.admit(_admission(), lease_id="lease-1")
    assert admitted is not None
    ready = await coordinator.mark_ready(
        admitted,
        expected_revision=admitted.revision,
        object_handle=object_handle_for(admitted),
        size=3,
        sha256="a" * 64,
    )
    assert ready is not None
    await coordinator.dispatch(
        ready,
        expected_revision=ready.revision,
        dispatch_id="dispatch-1",
    )
    await coordination.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="connection-2",
        owner_replica_id="replica-2",
        connected_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
        ttl_seconds=60,
        metadata={},
    )

    await coordinator.reconcile_generations(page_size=10)

    record = await state.get("transfer-1")
    assert record is not None
    assert record.terminal_outcome is RuntimeTransferOutcome.SUPERSEDED
    assert record.failure is RuntimeTransferFailure.FENCED


@pytest.mark.asyncio
async def test_generation_fence_retains_multipart_cleanup_until_repair() -> None:
    """Terminal generation fencing preserves cleanup evidence for later abort."""
    clock = _Clock(_NOW)
    state = InMemoryRuntimeTransferStateStore(config=_config(), clock=clock)
    coordination = InMemoryRuntimeCoordinationStore()
    await coordination.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="connection-1",
        owner_replica_id="replica-1",
        connected_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
        ttl_seconds=60,
        metadata={},
    )
    coordinator = RuntimeTransferCoordinator(
        state_store=state,
        coordination_store=coordination,
        cleanup=None,
        clock=clock,
    )
    admitted = await coordinator.admit(
        replace(_admission(), direction=RuntimeTransferDirection.UPLOAD),
        lease_id="lease-1",
    )
    assert admitted is not None
    ready = await coordinator.mark_ready(
        admitted,
        expected_revision=admitted.revision,
        object_handle=object_handle_for(admitted),
        size=3,
        sha256="a" * 64,
    )
    assert ready is not None
    dispatched = await coordinator.dispatch(
        ready,
        expected_revision=ready.revision,
        dispatch_id="dispatch-1",
    )
    streaming = await state.claim_stream(
        "transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=1,
        accepted_runner_generation=1,
        expected_revision=dispatched.record.revision,
        claim_id="claim-1",
        owner_replica_id="replica-1",
    )
    assert streaming is not None
    handled = await state.record_multipart_cleanup_handle(
        "transfer-1",
        attempt_id="attempt-1",
        accepted_runner_generation=1,
        expected_revision=streaming.revision,
        claim_id="claim-1",
        owner_replica_id="replica-1",
        cleanup_handle="multipart-1",
    )
    assert handled is not None
    pending = await state.record_cleanup(
        "transfer-1",
        attempt_id="attempt-1",
        expected_revision=handled.revision,
        status=RuntimeTransferCleanupStatus.PENDING,
    )
    assert pending is not None
    await coordination.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="connection-2",
        owner_replica_id="replica-2",
        connected_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
        ttl_seconds=60,
        metadata={},
    )

    await coordinator.reconcile_generations(page_size=10)

    fenced = await state.get("transfer-1")
    assert fenced is not None
    assert fenced.phase.value == "terminal"
    assert fenced.multipart_cleanup_handle == "multipart-1"
    cleanup = _Cleanup()
    clock.now += timedelta(seconds=31)

    assert (
        await coordinator.repair_stale_stream_claims(
            cleanup=cleanup,
            page_size=10,
        )
        == 1
    )
    repaired = await state.get("transfer-1")
    assert repaired is not None
    assert cleanup.handles == ["multipart-1"]
    assert repaired.cleanup_status is RuntimeTransferCleanupStatus.COMPLETE
    assert repaired.multipart_cleanup_handle is None


@pytest.mark.asyncio
async def test_active_cancellation_persists_reason_and_appends_typed_envelope() -> None:
    """Cancellation is durable and routed with the stable transfer identity."""
    state = InMemoryRuntimeTransferStateStore(config=_config(), clock=lambda: _NOW)
    coordination = InMemoryRuntimeCoordinationStore()
    await coordination.register_connection(
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime-1",
        connection_id="connection-1",
        owner_replica_id="replica-1",
        connected_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
        ttl_seconds=60,
        metadata={},
    )
    coordinator = RuntimeTransferCoordinator(
        state_store=state,
        coordination_store=coordination,
        cleanup=None,
        clock=lambda: _NOW,
    )
    admitted = await coordinator.admit(_admission(), lease_id="lease-1")
    assert admitted is not None
    ready = await coordinator.mark_ready(
        admitted,
        expected_revision=admitted.revision,
        object_handle=object_handle_for(admitted),
        size=3,
        sha256="a" * 64,
    )
    assert ready is not None
    dispatched = await coordinator.dispatch(
        ready,
        expected_revision=ready.revision,
        dispatch_id="dispatch-1",
    )
    streaming = await state.claim_stream(
        "transfer-1",
        attempt_id="attempt-1",
        runtime_id="runtime-1",
        desired_generation=1,
        accepted_runner_generation=1,
        expected_revision=dispatched.record.revision,
        claim_id="claim-1",
        owner_replica_id="replica-1",
    )
    assert streaming is not None

    cancelled = await coordinator.cancel(
        streaming,
        expected_revision=streaming.revision,
        reason=RuntimeTransferCancellationReason.CALLER,
    )

    assert cancelled is not None
    assert cancelled.cancellation_reason is RuntimeTransferCancellationReason.CALLER
    operation = await coordination.get_operation("operation-1")
    assert operation is not None
    assert operation.status is RuntimeOperationStatus.CANCEL_REQUESTED
    intent = await coordination.claim_next_request(
        dispatched.request_stream_id,
        consumer_group="runner-1",
        consumer_id="consumer-1",
        block_ms=0,
    )
    assert intent is not None
    cancellation = await coordination.claim_next_request(
        dispatched.request_stream_id,
        consumer_group="runner-1",
        consumer_id="consumer-1",
        block_ms=0,
    )
    assert cancellation is not None
    assert cancellation.envelope.operation_type == "file.transfer.cancel.v1"
    assert cancellation.envelope.payload == {
        "transfer_id": "transfer-1",
        "attempt_id": "attempt-1",
        "runtime_id": "runtime-1",
        "runner_generation": 1,
        "operation_id": "operation-1",
        "dispatch_id": "dispatch-1",
        "reason": "caller",
    }


@pytest.mark.asyncio
async def test_ready_download_cancellation_cleans_before_terminal_release() -> None:
    """An immediate terminal transition still deletes the managed object."""
    state = InMemoryRuntimeTransferStateStore(config=_config(), clock=lambda: _NOW)
    cleanup = _Cleanup()
    coordinator = RuntimeTransferCoordinator(
        state_store=state,
        coordination_store=InMemoryRuntimeCoordinationStore(),
        cleanup=cleanup,
        clock=lambda: _NOW,
    )
    admitted = await coordinator.admit(_admission(), lease_id="lease-1")
    assert admitted is not None
    ready = await coordinator.mark_ready(
        admitted,
        expected_revision=admitted.revision,
        object_handle=object_handle_for(admitted),
        size=3,
        sha256="a" * 64,
    )
    assert ready is not None

    cancelled = await coordinator.cancel(
        ready,
        expected_revision=ready.revision,
        reason=RuntimeTransferCancellationReason.CALLER,
    )

    assert cancelled is not None
    assert cancelled.phase.value == "terminal"
    assert cancelled.cleanup_status is RuntimeTransferCleanupStatus.COMPLETE
    assert len(cleanup.records) == 1
    assert cleanup.records[0].completed_object_cleanup_required is True


@pytest.mark.asyncio
async def test_pre_ready_canonical_cleanup_survives_revalidation_or_ready_failure() -> (
    None
):
    """A rejected READY transition retains canonical deletion evidence."""
    state = InMemoryRuntimeTransferStateStore(config=_config(), clock=lambda: _NOW)
    cleanup = _Cleanup()
    coordinator = RuntimeTransferCoordinator(
        state_store=state,
        coordination_store=InMemoryRuntimeCoordinationStore(),
        cleanup=cleanup,
        clock=lambda: _NOW,
    )
    admitted = await coordinator.admit(_admission(), lease_id="lease-1")
    assert admitted is not None
    protected = await state.promote_preparation_cleanup(
        admitted.admission.transfer_id,
        attempt_id=admitted.admission.attempt_id,
        runtime_id=admitted.admission.runtime_id,
        desired_generation=admitted.admission.desired_generation,
        expected_revision=admitted.revision,
        preparation_object_handle=object_handle_for(admitted),
    )
    assert protected is not None

    rejected = await coordinator.mark_ready(
        admitted,
        expected_revision=admitted.revision,
        object_handle=object_handle_for(admitted),
        size=3,
        sha256="a" * 64,
    )
    assert rejected is None

    cancelled = await coordinator.cancel(
        protected,
        expected_revision=protected.revision,
        reason=RuntimeTransferCancellationReason.CALLER,
    )

    assert cancelled is not None
    assert cancelled.phase.value == "terminal"
    assert len(cleanup.records) == 1
    assert cleanup.records[0].preparation_object_handle == object_handle_for(admitted)


@pytest.mark.asyncio
async def test_worker_loss_reconciles_only_stale_vfs_multipart_cleanup() -> None:
    """A replacement attempt cannot inherit stale VFS multipart cleanup."""
    clock = _Clock(_NOW)
    state = InMemoryRuntimeTransferStateStore(config=_config(), clock=clock)
    cleanup = _Cleanup()
    coordinator = RuntimeTransferCoordinator(
        state_store=state,
        coordination_store=InMemoryRuntimeCoordinationStore(),
        cleanup=cleanup,
        clock=clock,
    )
    admitted = await coordinator.admit(_admission(), lease_id="lease-1")
    assert admitted is not None
    registered = await state.register_preparation_cleanup(
        admitted.admission.transfer_id,
        attempt_id=admitted.admission.attempt_id,
        runtime_id=admitted.admission.runtime_id,
        desired_generation=admitted.admission.desired_generation,
        expected_revision=admitted.revision,
        preparation_object_handle=object_handle_for(admitted),
        multipart_cleanup_handle="vfs-upload-old",
    )
    assert registered is not None

    clock.now = admitted.logical_expires_at
    expired = await state.get(admitted.admission.transfer_id)
    assert expired is not None
    assert expired.phase.value == "terminal"
    replacement = await coordinator.admit(
        replace(
            _admission(),
            attempt_id="attempt-2",
            operation_id="operation-2",
            deadline_at=clock.now + timedelta(minutes=5),
        ),
        lease_id="lease-2",
    )
    assert replacement is not None

    assert await coordinator.repair_terminal_correlations(page_size=10) == 1

    assert cleanup.preparation_handles == ["vfs-upload-old"]
    current = await state.get(admitted.admission.transfer_id)
    assert current is not None
    assert current.admission.attempt_id == "attempt-2"
    assert current.preparation_multipart_cleanup_handle is None


@pytest.mark.asyncio
async def test_terminal_authority_canonicalizes_elapsed_deadline() -> None:
    """Trusted late failure settlement cannot win after the effective deadline."""
    clock = _Clock(_NOW)
    state = InMemoryRuntimeTransferStateStore(config=_config(), clock=clock)
    coordinator = RuntimeTransferCoordinator(
        state_store=state,
        coordination_store=InMemoryRuntimeCoordinationStore(),
        cleanup=None,
        clock=clock,
    )
    admitted = await coordinator.admit(_admission(), lease_id="lease-1")
    assert admitted is not None
    clock.now = admitted.admission.deadline_at

    terminal = await coordinator.settle_terminal(
        admitted,
        outcome=RuntimeTransferOutcome.FAILED,
        failure=RuntimeTransferFailure.STREAM,
        cleanup_completed=False,
    )

    assert terminal is not None
    assert terminal.terminal_outcome is RuntimeTransferOutcome.EXPIRED
    assert terminal.failure is RuntimeTransferFailure.EXPIRED


def _admission() -> RuntimeTransferAdmission:
    return RuntimeTransferAdmission(
        transfer_id="transfer-1",
        attempt_id="attempt-1",
        direction=RuntimeTransferDirection.DOWNLOAD,
        runtime_id="runtime-1",
        desired_generation=1,
        operation_id="operation-1",
        session_id="session-1",
        agent_id="agent-1",
        runtime_path="/workspace/file.txt",
        overwrite=False,
        expected_size=3,
        expected_sha256="a" * 64,
        product_maximum_size=10,
        provider_maximum_size=10,
        deadline_at=_NOW + timedelta(minutes=5),
        source_expires_at=None,
        resource_class="file",
    )


def _config() -> RuntimeTransferConfig:
    return RuntimeTransferConfig(
        per_runtime_attempts=8,
        per_runtime_bytes=100,
        deployment_attempts=8,
        deployment_bytes=100,
        admission_lease=timedelta(minutes=5),
        consumer_lease=timedelta(minutes=1),
        stream_lease=timedelta(seconds=30),
        terminal_ttl=timedelta(minutes=5),
        list_page_size=10,
    )
