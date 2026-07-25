"""Runtime transfer coordinator dispatch and repair tests."""

from datetime import UTC, datetime, timedelta

import pytest

from azents.runtime.coordination.data import (
    RuntimeConnectionKind,
    RuntimeCoordinationTarget,
)
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.runtime.transfer.coordinator import (
    RuntimeTransferCoordinator,
    object_handle_for,
)
from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferConfig,
    RuntimeTransferDirection,
    RuntimeTransferDispatchStatus,
    RuntimeTransferFailure,
    RuntimeTransferOutcome,
)
from azents.runtime.transfer.memory import InMemoryRuntimeTransferStateStore

_NOW = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


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
