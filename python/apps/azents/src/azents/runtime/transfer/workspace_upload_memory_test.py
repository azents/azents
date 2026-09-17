"""Focused Memory Workspace upload store contract tests."""

import asyncio
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from azents.runtime.transfer.workspace_upload import (
    WorkspaceUploadAdmission,
    WorkspaceUploadCleanupStatus,
    WorkspaceUploadConfig,
    WorkspaceUploadPhase,
)
from azents.runtime.transfer.workspace_upload_memory import InMemoryWorkspaceUploadStore

_NOW = datetime(2026, 9, 17, tzinfo=timezone.utc)


class _Clock:
    """Mutable timezone-aware test clock."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _config() -> WorkspaceUploadConfig:
    """Return a small deterministic metadata-store configuration."""
    return WorkspaceUploadConfig(
        maximum_file_size=10,
        maximum_active_uploads_per_requester_agent=1,
        maximum_active_bytes_per_requester_agent=10,
        maximum_active_uploads=2,
        maximum_active_bytes=12,
        ingress_lease=timedelta(seconds=10),
        reconciliation_lease=timedelta(seconds=10),
        cleanup_lease=timedelta(seconds=10),
        upload_ttl=timedelta(minutes=1),
        terminal_ttl=timedelta(minutes=1),
        list_page_size=2,
    )


def _admission(
    upload_id: str = "upload",
    *,
    requester_user_id: str = "requester",
    size: int = 3,
) -> WorkspaceUploadAdmission:
    """Return one bounded upload admission."""
    return WorkspaceUploadAdmission(
        upload_id=upload_id,
        requester_user_id=requester_user_id,
        workspace_id="workspace",
        agent_id="agent",
        runtime_id="runtime",
        desired_generation=1,
        session_id=None,
        deadline_at=_NOW + timedelta(minutes=5),
        destination_directory="/workspace/agent",
        filename=f"{upload_id}.txt",
        destination_path=f"/workspace/agent/{upload_id}.txt",
        expected_size=size,
        media_type="text/plain",
        expected_sha256=hashlib.sha256(b"abc"[:size]).hexdigest(),
    )


def _store(clock: _Clock) -> InMemoryWorkspaceUploadStore:
    """Build one deterministic process-local store."""
    return InMemoryWorkspaceUploadStore(config=_config(), clock=clock)


@pytest.mark.asyncio
async def test_create_is_idempotent_scope_bound_and_capacity_limited() -> None:
    """Create returns one operation only to its exact requester authority."""
    clock = _Clock(_NOW)
    store = _store(clock)
    admission = _admission()

    created = await store.create(admission)

    assert created is not None
    assert await store.create(admission) == created
    assert (
        await store.get(
            "upload",
            requester_user_id="other",
            workspace_id="workspace",
            agent_id="agent",
        )
        is None
    )
    assert await store.create(_admission("second", size=8)) is None


@pytest.mark.asyncio
async def test_list_object_handles_tracks_ingress_pending_and_source() -> None:
    """The live-object snapshot includes every retained cleanup handle."""
    clock = _Clock(_NOW)
    store = _store(clock)
    created = await store.create(_admission())
    assert created is not None
    uploading = await store.compare_and_set(
        replace(
            created,
            phase=WorkspaceUploadPhase.UPLOADING,
            ingress_handle="ingress",
            pending_source_handle="pending",
        ),
        expected_revision=created.revision,
    )
    assert uploading is not None

    pending_handles = await store.list_object_handles()
    assert pending_handles.ingress_handles == frozenset({"ingress"})
    assert pending_handles.source_handles == frozenset({"pending"})

    finalized = await store.compare_and_set(
        replace(
            uploading,
            phase=WorkspaceUploadPhase.MOVING_TO_RUNTIME,
            pending_source_handle=None,
            source_handle="source",
            actual_size=3,
            actual_sha256=hashlib.sha256(b"abc").hexdigest(),
        ),
        expected_revision=uploading.revision,
    )
    assert finalized is not None
    finalized_handles = await store.list_object_handles()
    assert finalized_handles.ingress_handles == frozenset({"ingress"})
    assert finalized_handles.source_handles == frozenset({"source"})


@pytest.mark.asyncio
async def test_compare_and_set_fences_stale_revisions_and_authority_changes() -> None:
    """Only the current revision can update the immutable upload operation."""
    clock = _Clock(_NOW)
    store = _store(clock)
    created = await store.create(_admission())
    assert created is not None

    updating = replace(
        created,
        phase=WorkspaceUploadPhase.UPLOADING,
        received_size=1,
    )
    updated = await store.compare_and_set(updating, expected_revision=created.revision)

    assert updated is not None
    assert updated.revision == 2
    assert updated.updated_at == clock.now
    assert (
        await store.compare_and_set(updating, expected_revision=created.revision)
        is None
    )
    changed_authority = replace(
        updated,
        admission=replace(updated.admission, runtime_id="other-runtime"),
    )
    assert (
        await store.compare_and_set(
            changed_authority,
            expected_revision=updated.revision,
        )
        is None
    )


@pytest.mark.asyncio
async def test_reconciliation_claim_is_exclusive_until_lease_expires() -> None:
    """A stale reconciler cannot hold or reacquire another owner's lease."""
    clock = _Clock(_NOW)
    store = _store(clock)
    created = await store.create(_admission())
    assert created is not None
    moving = await store.compare_and_set(
        replace(
            created,
            phase=WorkspaceUploadPhase.MOVING_TO_RUNTIME,
            source_handle="opaque-source",
            actual_size=3,
            actual_sha256="a" * 64,
        ),
        expected_revision=created.revision,
    )
    assert moving is not None

    first = await store.claim_reconciliation(
        "upload",
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=moving.revision,
        claim_id="first",
    )
    assert first is not None
    assert (
        await store.claim_reconciliation(
            "upload",
            requester_user_id="requester",
            workspace_id="workspace",
            agent_id="agent",
            expected_revision=first.revision,
            claim_id="second",
        )
        is None
    )
    clock.now += _config().reconciliation_lease
    second = await store.claim_reconciliation(
        "upload",
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=first.revision,
        claim_id="second",
    )
    assert second is not None
    assert second.reconciliation_claim_id == "second"


@pytest.mark.asyncio
async def test_expiry_does_not_reconstruct_state_and_schedules_source_cleanup() -> None:
    """Expiry terminalizes volatile metadata and retains no object-residue authority."""
    clock = _Clock(_NOW)
    store = _store(clock)
    created = await store.create(_admission())
    assert created is not None
    uploading = await store.compare_and_set(
        replace(
            created,
            phase=WorkspaceUploadPhase.UPLOADING,
            source_handle="opaque-source",
            actual_size=3,
            actual_sha256="a" * 64,
            received_size=3,
        ),
        expected_revision=created.revision,
    )
    assert uploading is not None

    clock.now += _config().upload_ttl
    expired = await store.get(
        "upload",
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
    )

    assert expired is not None
    assert expired.phase is WorkspaceUploadPhase.EXPIRED
    assert expired.cleanup_status is WorkspaceUploadCleanupStatus.PENDING
    assert expired.source_handle == "opaque-source"
    claimed = await store.claim_cleanup(
        "upload",
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=expired.revision,
        claim_id="cleanup",
    )
    assert claimed is not None
    assert claimed.cleanup_status is WorkspaceUploadCleanupStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_concurrent_create_allows_one_scoped_capacity_winner() -> None:
    """The single lock makes concurrent requester-Agent admission deterministic."""
    clock = _Clock(_NOW)
    store = _store(clock)

    results = await asyncio.gather(
        store.create(_admission("one")),
        store.create(_admission("two")),
    )

    assert sum(result is not None for result in results) == 1
