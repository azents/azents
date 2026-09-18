"""Focused tests for direct-object Workspace upload coordination."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from azcommon.infra.s3.service import S3ObjectIdentity

from azents.runtime.transfer.workspace_upload import (
    WorkspaceUploadAdmission,
    WorkspaceUploadCleanupStatus,
    WorkspaceUploadConfig,
    WorkspaceUploadFailure,
    WorkspaceUploadPhase,
    WorkspaceUploadRecord,
)
from azents.runtime.transfer.workspace_upload_coordinator import (
    WorkspaceUploadCoordinator,
)
from azents.runtime.transfer.workspace_upload_memory import InMemoryWorkspaceUploadStore
from azents.runtime.transfer.workspace_upload_object import WorkspaceUploadObjectStore
from azents.runtime.transfer.workspace_upload_test_support import _S3

_NOW = datetime(2026, 9, 17, tzinfo=UTC)
_BODY = b"abc"
_SHA256 = hashlib.sha256(_BODY).hexdigest()


class _Clock:
    """Mutable timezone-aware test clock."""

    def __init__(self) -> None:
        self.now = _NOW

    def __call__(self) -> datetime:
        """Return the deterministic test time."""
        return self.now


class _Reconciler:
    """Capture claimed delivery records without implementing Runtime transfer."""

    def __init__(self) -> None:
        self.records: list[str] = []

    async def reconcile(self, record: WorkspaceUploadRecord) -> None:
        """Record the claimed upload identifier."""
        self.records.append(record.admission.upload_id)


def _config() -> WorkspaceUploadConfig:
    """Return bounded metadata settings for coordinator tests."""
    return WorkspaceUploadConfig(
        maximum_file_size=16,
        maximum_active_uploads_per_requester_agent=2,
        maximum_active_bytes_per_requester_agent=32,
        maximum_active_uploads=2,
        maximum_active_bytes=32,
        ingress_lease=timedelta(seconds=10),
        reconciliation_lease=timedelta(seconds=10),
        cleanup_lease=timedelta(seconds=10),
        upload_ttl=timedelta(minutes=1),
        terminal_ttl=timedelta(minutes=1),
        list_page_size=2,
    )


def _admission() -> WorkspaceUploadAdmission:
    """Return one requester-bound upload admission."""
    return WorkspaceUploadAdmission(
        upload_id="upload",
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        runtime_id="runtime",
        desired_generation=1,
        session_id=None,
        deadline_at=_NOW + timedelta(minutes=5),
        destination_directory="/workspace/agent",
        filename="report.txt",
        destination_path="/workspace/agent/report.txt",
        expected_size=len(_BODY),
        media_type="text/plain",
        expected_sha256=_SHA256,
    )


def _coordinator(
    store: InMemoryWorkspaceUploadStore,
    clock: _Clock,
    s3: _S3,
    reconciler: _Reconciler,
) -> tuple[WorkspaceUploadCoordinator, WorkspaceUploadObjectStore]:
    """Build one fully injected direct-object coordinator facade."""
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
    return (
        WorkspaceUploadCoordinator(
            store=store,
            object_store=object_store,
            reconciliation_handler=reconciler,
            ingress_handle_factory=lambda: "1" * 32,
            source_handle_factory=lambda: "d" * 32,
            claim_id_factory=lambda: "claim",
            clock=clock,
            terminal_ttl=timedelta(minutes=1),
        ),
        object_store,
    )


async def _create_and_seed(
    coordinator: WorkspaceUploadCoordinator,
    object_store: WorkspaceUploadObjectStore,
    s3: _S3,
) -> WorkspaceUploadRecord:
    """Create one operation and publish the browser's direct PUT result."""
    created = await coordinator.create(_admission())
    assert created is not None
    assert created.ingress_handle is not None
    s3.seed(
        object_store.ingress_identity(created.ingress_handle),
        _BODY,
        content_type="text/plain",
    )
    return created


@pytest.mark.asyncio
async def test_cancelled_ingress_is_cleaned_after_operation_expiry() -> None:
    """Cancelled direct ingress is terminalized and cleaned before metadata purge."""
    clock = _Clock()
    store = InMemoryWorkspaceUploadStore(config=_config(), clock=clock)
    s3 = _S3(now=clock.now)
    reconciler = _Reconciler()
    coordinator, object_store = _coordinator(store, clock, s3, reconciler)
    created = await coordinator.create(_admission())
    assert created is not None
    assert created.ingress_handle is not None
    cancelled = await coordinator.cancel(
        "upload",
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=created.revision,
    )
    assert cancelled is not None
    assert cancelled.phase is WorkspaceUploadPhase.CANCELLED
    assert cancelled.cancellation_requested_at is None
    assert cancelled.cleanup_status is WorkspaceUploadCleanupStatus.PENDING

    result = await coordinator.reconcile(
        reconciliation_cursor=None,
        cleanup_cursor=None,
        limit=2,
    )

    assert result.cleaned == 1
    current = await coordinator.get(
        "upload",
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
    )
    assert current is not None
    assert current.cleanup_status is WorkspaceUploadCleanupStatus.COMPLETE
    assert s3.deleted == [
        S3ObjectIdentity(
            bucket="internal-bucket",
            key=object_store.ingress_identity(created.ingress_handle).key,
        )
    ]


@pytest.mark.asyncio
async def test_retry_without_source_is_rejected() -> None:
    """Delivery retry requires a verified immutable source."""
    clock = _Clock()
    store = InMemoryWorkspaceUploadStore(config=_config(), clock=clock)
    s3 = _S3(now=clock.now)
    reconciler = _Reconciler()
    coordinator, _object_store = _coordinator(store, clock, s3, reconciler)
    created = await coordinator.create(_admission())
    assert created is not None
    retryable = await store.compare_and_set(
        replace(
            created,
            phase=WorkspaceUploadPhase.RETRYABLE_FAILURE,
            failure=WorkspaceUploadFailure.INGRESS,
        ),
        expected_revision=created.revision,
    )
    assert retryable is not None

    assert (
        await coordinator.retry(
            "upload",
            requester_user_id="requester",
            workspace_id="workspace",
            agent_id="agent",
            expected_revision=retryable.revision,
            current_delivery_number=0,
        )
        is None
    )


@pytest.mark.asyncio
async def test_finalize_claims_direct_ingress_and_reconcile_starts_delivery() -> None:
    """Verified direct ingress becomes an immutable source for reconciliation."""
    clock = _Clock()
    store = InMemoryWorkspaceUploadStore(config=_config(), clock=clock)
    s3 = _S3(now=clock.now)
    reconciler = _Reconciler()
    coordinator, object_store = _coordinator(store, clock, s3, reconciler)
    created = await _create_and_seed(coordinator, object_store, s3)

    finalized = await coordinator.finalize(
        "upload",
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=created.revision,
    )
    assert finalized is not None
    assert finalized.phase is WorkspaceUploadPhase.MOVING_TO_RUNTIME
    assert finalized.source_handle == "d" * 32
    assert finalized.actual_sha256 == _SHA256

    result = await coordinator.reconcile(
        reconciliation_cursor=None,
        cleanup_cursor=None,
        limit=2,
    )

    assert result.reconciled == 1
    assert reconciler.records == ["upload"]
