"""Deterministic Workspace upload Runtime delivery reconciliation tests."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from azents.runtime.coordination.data import (
    RuntimeConnectionKind,
    RuntimeFencedMutationResult,
    RuntimeOperationMetadata,
    RuntimeRequestEnvelope,
)
from azents.runtime.coordination.memory import InMemoryRuntimeCoordinationStore
from azents.runtime.transfer.coordinator import (
    RuntimeTransferCoordinator,
    runner_request_stream_id,
)
from azents.runtime.transfer.data import (
    RuntimeTransferConfig,
    RuntimeTransferDestinationConflictEvidence,
    RuntimeTransferFailure,
    RuntimeTransferOutcome,
    RuntimeTransferPhase,
    RuntimeTransferRecord,
)
from azents.runtime.transfer.memory import InMemoryRuntimeTransferStateStore
from azents.runtime.transfer.workspace_upload import (
    WorkspaceUploadAdmission,
    WorkspaceUploadCleanupStatus,
    WorkspaceUploadConfig,
    WorkspaceUploadDeliveryOutcome,
    WorkspaceUploadFailure,
    WorkspaceUploadOutcome,
    WorkspaceUploadPhase,
    WorkspaceUploadRecord,
)
from azents.runtime.transfer.workspace_upload_coordinator import (
    WorkspaceUploadCoordinator,
    WorkspaceUploadReconcileResult,
)
from azents.runtime.transfer.workspace_upload_memory import (
    InMemoryWorkspaceUploadStore,
)
from azents.runtime.transfer.workspace_upload_object import WorkspaceUploadObjectStore
from azents.runtime.transfer.workspace_upload_reconciliation import (
    WorkspaceUploadRuntimeReconciliationHandler,
)
from azents.runtime.transfer.workspace_upload_test_support import _S3
from azents.testing.runtime_coordination import publish_next_test_connection

_NOW = datetime(2026, 9, 17, tzinfo=UTC)


class _Clock:
    """Mutable timezone-aware clock for state-machine tests."""

    def __init__(self, now: datetime = _NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        """Return the current deterministic time."""
        return self.now


class _Factory:
    """Return deterministic identifiers in the order requested by a test."""

    def __init__(self, *values: str) -> None:
        self.values: Iterator[str] = iter(values)

    def __call__(self) -> str:
        """Return the next preselected identifier."""
        return next(self.values)


class _RuntimeCleanup:
    """Delete only the exact opaque Runtime artifacts in cleanup evidence."""

    def __init__(self, s3: _S3) -> None:
        self.s3 = s3
        self.records: list[RuntimeTransferRecord] = []

    async def cleanup(self, record: RuntimeTransferRecord) -> None:
        """Delete the bounded artifacts named by one Runtime cleanup record."""
        self.records.append(record)
        handles = (
            record.preparation_object_handle,
            record.pre_ready_object_handle,
            None if record.object is None else record.object.key,
        )
        for handle in handles:
            if handle is not None:
                await self.s3.delete("internal-bucket", f"runtime-transfer/{handle}")


class _ObservedRuntimeCoordinationStore(InMemoryRuntimeCoordinationStore):
    """Expose request publication as an explicit test synchronization boundary."""

    def __init__(self) -> None:
        super().__init__()
        self.request_appended = asyncio.Event()

    async def append_operation_request_if_connection_current(
        self,
        *,
        connection_kind: RuntimeConnectionKind,
        connection_subject_id: str,
        connection_generation: int,
        metadata: RuntimeOperationMetadata,
        envelope: RuntimeRequestEnvelope,
        ttl_seconds: int | None,
    ) -> RuntimeFencedMutationResult[RuntimeOperationMetadata]:
        """Append one fenced operation request and signal after persistence."""
        result = await super().append_operation_request_if_connection_current(
            connection_kind=connection_kind,
            connection_subject_id=connection_subject_id,
            connection_generation=connection_generation,
            metadata=metadata,
            envelope=envelope,
            ttl_seconds=ttl_seconds,
        )
        if result.value is not None and result.value.request_cursor is not None:
            self.request_appended.set()
        return result

    async def append_request(
        self,
        stream_id: str,
        envelope: RuntimeRequestEnvelope,
    ) -> str:
        """Append one request and signal observers after it is authoritative."""
        cursor = await super().append_request(stream_id, envelope)
        self.request_appended.set()
        return cursor


@dataclass
class _Harness:
    """Fully wired in-memory Workspace and Runtime transfer components."""

    clock: _Clock
    s3: _S3
    workspace_store: InMemoryWorkspaceUploadStore
    workspace_coordinator: WorkspaceUploadCoordinator
    handler: WorkspaceUploadRuntimeReconciliationHandler
    runtime_state: InMemoryRuntimeTransferStateStore
    runtime_coordination: _ObservedRuntimeCoordinationStore
    transfer_coordinator: RuntimeTransferCoordinator
    runtime_cleanup: _RuntimeCleanup


def _workspace_config(
    *,
    upload_ttl: timedelta = timedelta(minutes=1),
) -> WorkspaceUploadConfig:
    """Return bounded Workspace upload metadata settings."""
    return WorkspaceUploadConfig(
        maximum_file_size=16,
        maximum_active_uploads_per_requester_agent=2,
        maximum_active_bytes_per_requester_agent=32,
        maximum_active_uploads=4,
        maximum_active_bytes=64,
        ingress_lease=timedelta(seconds=10),
        reconciliation_lease=timedelta(seconds=10),
        cleanup_lease=timedelta(seconds=10),
        upload_ttl=upload_ttl,
        terminal_ttl=timedelta(minutes=1),
        list_page_size=2,
    )


def _runtime_config() -> RuntimeTransferConfig:
    """Return bounded Runtime Transfer settings for one test harness."""
    return RuntimeTransferConfig(
        per_runtime_attempts=8,
        per_runtime_bytes=64,
        deployment_attempts=16,
        deployment_bytes=128,
        admission_lease=timedelta(minutes=5),
        consumer_lease=timedelta(minutes=1),
        stream_lease=timedelta(seconds=30),
        terminal_ttl=timedelta(minutes=1),
        list_page_size=4,
    )


def _admission(
    upload_id: str = "upload",
    *,
    deadline_offset: timedelta = timedelta(minutes=5),
    expected_size: int = 3,
) -> WorkspaceUploadAdmission:
    """Return one requester-bound upload admission."""
    return WorkspaceUploadAdmission(
        upload_id=upload_id,
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        runtime_id="runtime",
        desired_generation=1,
        session_id=None,
        deadline_at=_NOW + deadline_offset,
        destination_directory="/workspace/agent",
        filename=f"{upload_id}.txt",
        destination_path=f"/workspace/agent/{upload_id}.txt",
        expected_size=expected_size,
        media_type="text/plain",
        expected_sha256=hashlib.sha256(b"abc").hexdigest(),
    )


def _harness(
    *,
    upload_ttl: timedelta = timedelta(minutes=1),
    status_poll_interval: timedelta = timedelta(milliseconds=1),
) -> _Harness:
    """Build a fully wired Runtime and Workspace upload state machine."""
    clock = _Clock()
    s3 = _S3(now=clock.now)
    workspace_config = _workspace_config(upload_ttl=upload_ttl)
    workspace_store = InMemoryWorkspaceUploadStore(
        config=workspace_config,
        clock=clock,
    )
    object_store = WorkspaceUploadObjectStore(
        s3_service=s3,
        bucket="internal-bucket",
        ingress_object_prefix="workspace-upload-ingress",
        source_object_prefix="workspace-upload-sources",
        ticket_ttl=timedelta(minutes=1),
        multipart_copy_threshold=3,
        multipart_part_size=3,
        clock=clock,
    )
    runtime_state = InMemoryRuntimeTransferStateStore(
        config=_runtime_config(),
        clock=clock,
    )
    runtime_coordination = _ObservedRuntimeCoordinationStore()
    runtime_cleanup = _RuntimeCleanup(s3)
    transfer_coordinator = RuntimeTransferCoordinator(
        state_store=runtime_state,
        coordination_store=runtime_coordination,
        cleanup=runtime_cleanup,
        clock=clock,
    )
    delivery_ids = _Factory("delivery-1", "delivery-2")
    transfer_ids = _Factory("transfer-1", "transfer-2")
    transfer_attempt_ids = _Factory("transfer-attempt-1", "transfer-attempt-2")
    handler = WorkspaceUploadRuntimeReconciliationHandler(
        store=workspace_store,
        object_store=object_store,
        transfer_coordinator=transfer_coordinator,
        product_maximum_size=16,
        provider_maximum_size=16,
        status_poll_interval=status_poll_interval,
        clock=clock,
        delivery_attempt_id_factory=delivery_ids,
        transfer_id_factory=transfer_ids,
        transfer_attempt_id_factory=transfer_attempt_ids,
        transfer_lease_id_factory=_Factory("transfer-lease-1", "transfer-lease-2"),
        dispatch_id_factory=_Factory("dispatch-1", "dispatch-2"),
    )
    workspace_coordinator = WorkspaceUploadCoordinator(
        store=workspace_store,
        object_store=object_store,
        reconciliation_handler=handler,
        ingress_handle_factory=_Factory("1" * 32, "2" * 32),
        source_handle_factory=_Factory("a" * 32, "b" * 32),
        claim_id_factory=_Factory(
            "workspace-claim-1",
            "workspace-claim-2",
            "workspace-claim-3",
            "workspace-claim-4",
        ),
        clock=clock,
        terminal_ttl=workspace_config.terminal_ttl,
        delivery_attempt_id_factory=delivery_ids,
        transfer_id_factory=transfer_ids,
        transfer_attempt_id_factory=transfer_attempt_ids,
    )
    return _Harness(
        clock=clock,
        s3=s3,
        workspace_store=workspace_store,
        workspace_coordinator=workspace_coordinator,
        handler=handler,
        runtime_state=runtime_state,
        runtime_coordination=runtime_coordination,
        transfer_coordinator=transfer_coordinator,
        runtime_cleanup=runtime_cleanup,
    )


async def _stage(
    harness: _Harness,
    *,
    admission: WorkspaceUploadAdmission | None = None,
    body: bytes = b"abc",
) -> WorkspaceUploadRecord:
    """Create, direct-upload, and finalize one upload."""
    selected = admission or _admission(
        expected_size=len(body),
    )
    created = await harness.workspace_coordinator.create(selected)
    assert created is not None
    assert created.ingress_handle is not None
    harness.s3.seed(
        harness.handler.object_store.ingress_identity(created.ingress_handle),
        body,
        content_type=selected.media_type,
    )
    finalized = await harness.workspace_coordinator.finalize(
        selected.upload_id,
        requester_user_id=selected.requester_user_id,
        workspace_id=selected.workspace_id,
        agent_id=selected.agent_id,
        expected_revision=created.revision,
    )
    assert finalized is not None
    return finalized


async def _start_until_dispatch(
    harness: _Harness,
    upload_id: str = "upload",
) -> tuple[
    asyncio.Task[WorkspaceUploadReconcileResult],
    WorkspaceUploadRecord,
]:
    """Run reconciliation until the metadata-only Runner intent is enqueued."""
    await _publish_runner_generation(harness, connection_id="runner-1")
    task = asyncio.create_task(
        harness.workspace_coordinator.reconcile(
            reconciliation_cursor=None,
            cleanup_cursor=None,
            limit=2,
        )
    )
    await asyncio.wait_for(
        harness.runtime_coordination.request_appended.wait(),
        timeout=2,
    )
    request = await harness.runtime_coordination.claim_next_request(
        runner_request_stream_id("runtime", 1),
        consumer_group="workspace-upload-test",
        consumer_id=f"runner-{upload_id}",
        block_ms=0,
    )
    assert request is not None
    current = await harness.workspace_coordinator.get(
        upload_id,
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
    )
    assert current is not None
    return task, current


async def _runtime_for_upload(
    harness: _Harness,
    upload: WorkspaceUploadRecord,
) -> RuntimeTransferRecord:
    """Read the Runtime record for the current Workspace delivery attempt."""
    attempt = upload.delivery_attempts[-1]
    runtime = await harness.runtime_state.get(attempt.transfer_id)
    assert runtime is not None
    return runtime


async def _complete_download(
    harness: _Harness,
    runtime: RuntimeTransferRecord,
    *,
    body: bytes = b"abc",
) -> RuntimeTransferRecord:
    """Drive one enqueued direct download through claim and commit."""
    accepted_generation = runtime.accepted_runner_generation
    assert accepted_generation is not None
    claimed = await harness.runtime_state.claim_direct_object(
        runtime.admission.transfer_id,
        attempt_id=runtime.admission.attempt_id,
        runtime_id=runtime.admission.runtime_id,
        desired_generation=runtime.admission.desired_generation,
        accepted_runner_generation=accepted_generation,
        claim_id="runner-stream",
        owner_replica_id="runner",
    )
    assert claimed is not None
    verifying = await harness.runtime_state.begin_verification(
        runtime.admission.transfer_id,
        attempt_id=runtime.admission.attempt_id,
        runtime_id=runtime.admission.runtime_id,
        desired_generation=runtime.admission.desired_generation,
        accepted_runner_generation=accepted_generation,
        claim_id="runner-stream",
        expected_revision=claimed.revision,
    )
    assert verifying is not None
    terminal = await harness.runtime_state.confirm_download_commit(
        runtime.admission.transfer_id,
        attempt_id=runtime.admission.attempt_id,
        runtime_id=runtime.admission.runtime_id,
        desired_generation=runtime.admission.desired_generation,
        accepted_runner_generation=accepted_generation,
        claim_id="runner-stream",
        expected_revision=verifying.revision,
        actual_size=len(body),
        actual_sha256=hashlib.sha256(body).hexdigest(),
    )
    assert terminal is not None
    assert terminal.phase is RuntimeTransferPhase.TERMINAL
    return terminal


async def _publish_runner_generation(
    harness: _Harness,
    *,
    connection_id: str,
) -> None:
    """Publish a newer Runner connection generation for generation fencing."""
    await publish_next_test_connection(
        harness.runtime_coordination,
        kind=RuntimeConnectionKind.RUNNER,
        subject_id="runtime",
        connection_id=connection_id,
        owner_replica_id="runner",
        connected_at=harness.clock.now,
        heartbeat_at=harness.clock.now,
        ttl_seconds=60,
        metadata={},
    )


async def _current_upload(harness: _Harness) -> WorkspaceUploadRecord:
    """Read the requester-bound current Workspace record."""
    current = await harness.workspace_coordinator.get(
        "upload",
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
    )
    assert current is not None
    return current


@pytest.mark.asyncio
async def test_successful_copy_dispatch_and_runner_commit_settle_upload() -> None:
    """Verified source copy and Runner commit project one successful upload."""
    harness = _harness()
    await _stage(harness)
    task, upload = await _start_until_dispatch(harness)
    runtime = await _runtime_for_upload(harness, upload)

    await _complete_download(harness, runtime)
    await asyncio.wait_for(task, timeout=2)

    current = await _current_upload(harness)
    attempt = current.delivery_attempts[-1]
    assert current.phase is WorkspaceUploadPhase.SUCCEEDED
    assert current.outcome is WorkspaceUploadOutcome.SUCCEEDED
    assert attempt.outcome is WorkspaceUploadDeliveryOutcome.SUCCEEDED
    assert attempt.failure is None
    assert harness.s3.copied == [
        (
            harness.s3.copied[0][0],
            harness.s3.copied[0][1],
        )
    ]

    await harness.workspace_coordinator.reconcile(
        reconciliation_cursor=None,
        cleanup_cursor=None,
        limit=2,
    )
    cleaned = await _current_upload(harness)
    assert cleaned.cleanup_status is WorkspaceUploadCleanupStatus.COMPLETE
    assert {item.key for item in harness.s3.deleted} >= {
        "workspace-upload-ingress/" + ("1" * 32),
        "workspace-upload-sources/" + ("a" * 32),
    }


@pytest.mark.asyncio
async def test_conflict_projection_requires_exact_precondition() -> None:
    """Conflict evidence is projected safely and exact evidence fences overwrite."""
    harness = _harness()
    await _stage(harness)
    task, upload = await _start_until_dispatch(harness)
    runtime = await _runtime_for_upload(harness, upload)
    conflict = RuntimeTransferDestinationConflictEvidence(
        kind="file",
        size=7,
        modified_at=_NOW,
        conflict_precondition=b"opaque-conflict",
    )
    settled = await harness.runtime_state.settle(
        runtime.admission.transfer_id,
        attempt_id=runtime.admission.attempt_id,
        expected_revision=runtime.revision,
        outcome=RuntimeTransferOutcome.FAILED,
        failure=RuntimeTransferFailure.DESTINATION_CONFLICT,
        destination_conflict=conflict,
    )
    assert settled is not None
    await asyncio.wait_for(task, timeout=2)

    current = await _current_upload(harness)
    latest = current.delivery_attempts[-1]
    expected_token = (
        base64.urlsafe_b64encode(b"opaque-conflict").decode("ascii").rstrip("=")
    )
    assert current.phase is WorkspaceUploadPhase.CONFLICTED
    assert latest.outcome is WorkspaceUploadDeliveryOutcome.CONFLICTED
    assert latest.failure is WorkspaceUploadFailure.DESTINATION_CONFLICT
    assert latest.conflict_revision == expected_token
    assert latest.destination_evidence is not None
    assert latest.destination_evidence.size == 7

    assert (
        await harness.workspace_coordinator.retry(
            "upload",
            requester_user_id="requester",
            workspace_id="workspace",
            agent_id="agent",
            expected_revision=current.revision - 1,
            current_delivery_number=1,
            overwrite=True,
            conflict_precondition=expected_token,
        )
        is None
    )
    retried = await harness.workspace_coordinator.retry(
        "upload",
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=current.revision,
        current_delivery_number=1,
        overwrite=True,
        conflict_precondition=expected_token,
    )
    assert retried is not None
    assert retried.phase is WorkspaceUploadPhase.MOVING_TO_RUNTIME
    assert len(retried.delivery_attempts) == 2
    second = retried.delivery_attempts[-1]
    assert second.number == 2
    assert second.overwrite is True
    assert second.conflict_precondition == expected_token
    assert second.transfer_id != latest.transfer_id
    assert second.transfer_attempt_id != latest.transfer_attempt_id


@pytest.mark.asyncio
async def test_cancellation_before_runtime_commit_projects_cancelled_attempt() -> None:
    """Workspace cancellation fences an enqueued Runtime attempt before commit."""
    harness = _harness()
    await _stage(harness)
    task, upload = await _start_until_dispatch(harness)

    cancelled = await harness.workspace_coordinator.cancel(
        "upload",
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=upload.revision,
        current_delivery_number=1,
    )
    assert cancelled is not None
    assert cancelled.cancellation_requested_at is not None
    await asyncio.wait_for(task, timeout=2)

    current = await _current_upload(harness)
    runtime = await _runtime_for_upload(harness, current)
    assert current.phase is WorkspaceUploadPhase.CANCELLED
    assert current.outcome is WorkspaceUploadOutcome.CANCELLED
    assert current.failure is WorkspaceUploadFailure.CANCELLED
    assert runtime.phase is RuntimeTransferPhase.TERMINAL
    assert runtime.terminal_outcome is RuntimeTransferOutcome.CANCELLED


@pytest.mark.asyncio
async def test_successful_runtime_commit_wins_over_later_workspace_cancellation() -> (
    None
):
    """A cancellation observed after the Runtime commit cannot overwrite success."""
    harness = _harness(status_poll_interval=timedelta(hours=1))
    await _stage(harness)
    task, upload = await _start_until_dispatch(harness)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    runtime = await _runtime_for_upload(harness, upload)
    await _complete_download(harness, runtime)
    cancelled = await harness.workspace_coordinator.cancel(
        "upload",
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=upload.revision,
        current_delivery_number=1,
    )
    assert cancelled is not None
    assert cancelled.cancellation_requested_at is not None

    await harness.handler.reconcile(cancelled)
    current = await _current_upload(harness)
    assert current.phase is WorkspaceUploadPhase.SUCCEEDED
    assert current.outcome is WorkspaceUploadOutcome.SUCCEEDED
    assert current.cancellation_requested_at is None


@pytest.mark.asyncio
async def test_runner_generation_replacement_fences_delivery_and_stale_cas() -> None:
    """A replaced Runner generation yields retryable fencing."""
    harness = _harness()
    await _stage(harness)
    task, upload = await _start_until_dispatch(harness)
    await _publish_runner_generation(harness, connection_id="runner-2")

    observed = await harness.transfer_coordinator.reconcile_generations(page_size=2)
    assert observed == 1
    await asyncio.wait_for(task, timeout=2)

    current = await _current_upload(harness)
    assert current.phase is WorkspaceUploadPhase.RETRYABLE_FAILURE
    assert current.failure is WorkspaceUploadFailure.FENCED
    assert current.delivery_attempts[-1].outcome is (
        WorkspaceUploadDeliveryOutcome.RETRYABLE_FAILURE
    )
    assert (
        await harness.workspace_coordinator.cancel(
            "upload",
            requester_user_id="requester",
            workspace_id="workspace",
            agent_id="agent",
            expected_revision=current.revision - 1,
            current_delivery_number=1,
        )
        is None
    )


@pytest.mark.asyncio
async def test_integrity_mismatch_retains_and_cleans_pre_ready_transfer_object() -> (
    None
):
    """Copy verification failure retains cleanup evidence before settlement."""
    harness = _harness()
    harness.s3.transfer_sha256_override = "b" * 64
    await _stage(harness)

    await asyncio.wait_for(
        harness.workspace_coordinator.reconcile(
            reconciliation_cursor=None,
            cleanup_cursor=None,
            limit=2,
        ),
        timeout=2,
    )

    current = await _current_upload(harness)
    assert current.phase is WorkspaceUploadPhase.FAILED
    assert current.outcome is WorkspaceUploadOutcome.FAILED
    assert current.failure is WorkspaceUploadFailure.INTEGRITY
    assert current.cleanup_status is WorkspaceUploadCleanupStatus.COMPLETE

    assert not any(key.startswith("workspace-upload-") for key in harness.s3.objects)


@pytest.mark.asyncio
async def test_runtime_deadline_expiry_projects_expired_upload() -> None:
    """A Runtime deadline expires delivery without expiring Workspace metadata."""
    harness = _harness(upload_ttl=timedelta(minutes=10))
    await _stage(
        harness,
        admission=_admission(
            deadline_offset=timedelta(seconds=5),
        ),
    )
    task, _ = await _start_until_dispatch(harness)
    harness.clock.now = _NOW + timedelta(seconds=10)

    await asyncio.wait_for(task, timeout=2)
    current = await _current_upload(harness)
    assert current.phase is WorkspaceUploadPhase.EXPIRED
    assert current.outcome is WorkspaceUploadOutcome.EXPIRED
    assert current.failure is WorkspaceUploadFailure.EXPIRED
    assert (
        current.delivery_attempts[-1].outcome is WorkspaceUploadDeliveryOutcome.EXPIRED
    )
