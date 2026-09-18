"""Backend-neutral Workspace upload metadata-store contract tests."""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Protocol, cast
from uuid import uuid4

import pytest

from azents.core.redis import create_redis_client
from azents.runtime.transfer.workspace_upload import (
    WorkspaceUploadAdmission,
    WorkspaceUploadCleanupStatus,
    WorkspaceUploadConfig,
    WorkspaceUploadFailure,
    WorkspaceUploadOutcome,
    WorkspaceUploadPhase,
)
from azents.runtime.transfer.workspace_upload_memory import (
    InMemoryWorkspaceUploadStore,
)
from azents.runtime.transfer.workspace_upload_redis import (
    RedisWorkspaceUploadStore,
    _RedisClient,
)
from azents.runtime.transfer.workspace_upload_store import WorkspaceUploadStore

_TEST_STARTED_AT = datetime(2026, 9, 17, tzinfo=timezone.utc)


class _Clock:
    """Mutable timezone-aware test clock."""

    def __init__(self, now: datetime) -> None:
        """Initialize the authoritative test time."""
        self.now = now

    def __call__(self) -> datetime:
        """Return the current authoritative test time."""
        return self.now


class _RedisNamespaceCleaner(Protocol):
    """Redis commands used to remove one isolated test namespace."""

    async def scan(
        self,
        *,
        cursor: int,
        match: str,
        count: int,
    ) -> tuple[int, list[bytes]]: ...

    async def delete(self, *keys: bytes) -> int: ...


@dataclass(frozen=True)
class _StoreHarness:
    """Backend-neutral store and deterministic time dependencies."""

    store: WorkspaceUploadStore
    clock: _Clock
    config: WorkspaceUploadConfig


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
    payload = bytes(index % 251 for index in range(size))
    return WorkspaceUploadAdmission(
        upload_id=upload_id,
        requester_user_id=requester_user_id,
        workspace_id="workspace",
        agent_id="agent",
        runtime_id="runtime",
        desired_generation=1,
        session_id=None,
        deadline_at=_TEST_STARTED_AT + timedelta(minutes=5),
        destination_directory="/workspace/agent",
        filename=f"{upload_id}.txt",
        destination_path=f"/workspace/agent/{upload_id}.txt",
        expected_size=size,
        media_type="text/plain",
        expected_sha256=hashlib.sha256(payload).hexdigest(),
    )


@pytest.fixture(
    params=("memory", "redis"),
    ids=("memory", "redis"),
)
async def store_harness(
    request: pytest.FixtureRequest,
) -> AsyncIterator[_StoreHarness]:
    """Create one Memory or real-Redis Workspace upload store."""
    clock = _Clock(_TEST_STARTED_AT)
    config = _config()
    if request.param == "memory":
        yield _StoreHarness(
            store=InMemoryWorkspaceUploadStore(config=config, clock=clock),
            clock=clock,
            config=config,
        )
        return

    redis_url = request.getfixturevalue("redis_url")
    client = create_redis_client(redis_url)
    namespace = f"azents:runtime:workspace-upload:test:{uuid4().hex}"
    store = RedisWorkspaceUploadStore(
        redis=cast(_RedisClient, client),
        config=config,
        clock=clock,
        namespace=namespace,
    )
    try:
        yield _StoreHarness(store=store, clock=clock, config=config)
    finally:
        await _delete_namespace(
            cast(_RedisNamespaceCleaner, client),
            namespace,
        )
        await client.aclose()


async def _delete_namespace(
    client: _RedisNamespaceCleaner,
    namespace: str,
) -> None:
    """Iteratively delete one test namespace without using ``KEYS``."""
    cursor = 0
    while True:
        cursor, keys = await client.scan(
            cursor=cursor,
            match=f"{namespace}:*",
            count=100,
        )
        if keys:
            await client.delete(*keys)
        if cursor == 0:
            return


@pytest.mark.asyncio
async def test_create_is_idempotent_scope_bound_and_capacity_limited(
    store_harness: _StoreHarness,
) -> None:
    """Create returns one operation only to its exact requester authority."""
    store = store_harness.store
    admission = _admission()

    created = await store.create(admission)

    assert created is not None
    assert await store.create(admission) == created
    assert (
        await store.get(
            admission.upload_id,
            requester_user_id="other",
            workspace_id="workspace",
            agent_id="agent",
        )
        is None
    )
    assert await store.create(_admission("second", size=8)) is None


@pytest.mark.asyncio
async def test_list_object_handles_tracks_ingress_pending_and_source(
    store_harness: _StoreHarness,
) -> None:
    """The live-object snapshot includes every retained cleanup handle."""
    store = store_harness.store
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
            actual_sha256=hashlib.sha256(bytes(range(3))).hexdigest(),
        ),
        expected_revision=uploading.revision,
    )
    assert finalized is not None
    finalized_handles = await store.list_object_handles()
    assert finalized_handles.ingress_handles == frozenset({"ingress"})
    assert finalized_handles.source_handles == frozenset({"source"})


@pytest.mark.asyncio
async def test_compare_and_set_fences_stale_revisions_and_authority_changes(
    store_harness: _StoreHarness,
) -> None:
    """Only the current revision can update immutable upload authority."""
    store = store_harness.store
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
    assert updated.updated_at == store_harness.clock.now
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
async def test_ingress_claim_and_progress_fence_exact_scope_revision_and_claim(
    store_harness: _StoreHarness,
) -> None:
    """Ingress mutation requires exact requester scope, revision, and claim."""
    store = store_harness.store
    created = await store.create(_admission())
    assert created is not None
    uploading = await store.compare_and_set(
        replace(
            created,
            phase=WorkspaceUploadPhase.UPLOADING,
            ingress_handle="ingress",
        ),
        expected_revision=created.revision,
    )
    assert uploading is not None

    assert (
        await store.claim_ingress(
            uploading.admission.upload_id,
            requester_user_id="other",
            workspace_id="workspace",
            agent_id="agent",
            expected_revision=uploading.revision,
            claim_id="claim",
        )
        is None
    )
    claimed = await store.claim_ingress(
        uploading.admission.upload_id,
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=uploading.revision,
        claim_id="claim",
    )
    assert claimed is not None
    assert claimed.ingress_claim_id == "claim"
    assert (
        await store.renew_ingress_lease(
            claimed.admission.upload_id,
            requester_user_id="requester",
            workspace_id="workspace",
            agent_id="agent",
            expected_revision=claimed.revision,
            claim_id="other-claim",
        )
        is None
    )
    renewed = await store.renew_ingress_lease(
        claimed.admission.upload_id,
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=claimed.revision,
        claim_id="claim",
    )
    assert renewed is not None
    assert (
        await store.record_ingress_progress(
            renewed.admission.upload_id,
            requester_user_id="requester",
            workspace_id="workspace",
            agent_id="agent",
            expected_revision=renewed.revision,
            claim_id="claim",
            received_size=renewed.received_size - 1,
        )
        is None
    )
    progressed = await store.record_ingress_progress(
        renewed.admission.upload_id,
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=renewed.revision,
        claim_id="claim",
        received_size=2,
    )
    assert progressed is not None
    assert progressed.received_size == 2


@pytest.mark.asyncio
async def test_cancellation_without_ingress_worker_is_terminal_immediately(
    store_harness: _StoreHarness,
) -> None:
    """An admitted upload without an ingress claim can be cancelled immediately."""
    store = store_harness.store
    created = await store.create(_admission())
    assert created is not None
    uploading = await store.compare_and_set(
        replace(
            created,
            phase=WorkspaceUploadPhase.UPLOADING,
            ingress_handle="ingress",
        ),
        expected_revision=created.revision,
    )
    assert uploading is not None
    assert uploading.ingress_claim_id is None
    assert uploading.ingress_lease_expires_at is None

    cancelled = await store.request_cancellation(
        uploading.admission.upload_id,
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=uploading.revision,
    )

    assert cancelled is not None
    assert cancelled.phase is WorkspaceUploadPhase.CANCELLED
    assert cancelled.outcome is WorkspaceUploadOutcome.CANCELLED
    assert cancelled.failure is WorkspaceUploadFailure.CANCELLED


@pytest.mark.asyncio
async def test_reconciliation_claim_is_exclusive_until_lease_expires(
    store_harness: _StoreHarness,
) -> None:
    """A stale reconciler cannot hold another owner's lease."""
    store = store_harness.store
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
        moving.admission.upload_id,
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=moving.revision,
        claim_id="first",
    )
    assert first is not None
    assert (
        await store.claim_reconciliation(
            moving.admission.upload_id,
            requester_user_id="requester",
            workspace_id="workspace",
            agent_id="agent",
            expected_revision=first.revision,
            claim_id="second",
        )
        is None
    )
    store_harness.clock.now += store_harness.config.reconciliation_lease
    second = await store.claim_reconciliation(
        moving.admission.upload_id,
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=first.revision,
        claim_id="second",
    )
    assert second is not None
    assert second.reconciliation_claim_id == "second"


@pytest.mark.asyncio
async def test_expiry_does_not_reconstruct_state_and_schedules_source_cleanup(
    store_harness: _StoreHarness,
) -> None:
    """Expiry retains source authority for bounded cleanup and nothing else."""
    store = store_harness.store
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

    store_harness.clock.now += store_harness.config.upload_ttl
    expired = await store.get(
        uploading.admission.upload_id,
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
    )

    assert expired is not None
    assert expired.phase is WorkspaceUploadPhase.EXPIRED
    assert expired.cleanup_status is WorkspaceUploadCleanupStatus.PENDING
    assert expired.source_handle == "opaque-source"
    claimed = await store.claim_cleanup(
        expired.admission.upload_id,
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=expired.revision,
        claim_id="cleanup",
    )
    assert claimed is not None
    assert claimed.cleanup_status is WorkspaceUploadCleanupStatus.IN_PROGRESS


@pytest.mark.asyncio
async def test_terminal_purge_waits_for_cleanup_completion(
    store_harness: _StoreHarness,
) -> None:
    """Expired terminal metadata remains until cleanup is revision-fenced complete."""
    store = store_harness.store
    created = await store.create(_admission())
    assert created is not None
    moving = await store.compare_and_set(
        replace(
            created,
            phase=WorkspaceUploadPhase.MOVING_TO_RUNTIME,
            source_handle="source",
            actual_size=3,
            actual_sha256="a" * 64,
        ),
        expected_revision=created.revision,
    )
    assert moving is not None
    cancelled = await store.request_cancellation(
        moving.admission.upload_id,
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=moving.revision,
    )
    assert cancelled is not None
    assert cancelled.phase is WorkspaceUploadPhase.CANCELLED
    assert cancelled.outcome is WorkspaceUploadOutcome.CANCELLED
    assert cancelled.failure is WorkspaceUploadFailure.CANCELLED
    assert cancelled.cleanup_status is WorkspaceUploadCleanupStatus.PENDING
    assert cancelled.terminal_expires_at is not None

    store_harness.clock.now = cancelled.terminal_expires_at
    assert await store.purge_terminal(limit=store_harness.config.list_page_size) == 0
    assert (
        await store.get(
            cancelled.admission.upload_id,
            requester_user_id="requester",
            workspace_id="workspace",
            agent_id="agent",
        )
        == cancelled
    )

    cleanup_claimed = await store.claim_cleanup(
        cancelled.admission.upload_id,
        requester_user_id="requester",
        workspace_id="workspace",
        agent_id="agent",
        expected_revision=cancelled.revision,
        claim_id="cleanup",
    )
    assert cleanup_claimed is not None
    cleanup_complete = await store.compare_and_set(
        replace(
            cleanup_claimed,
            source_handle=None,
            actual_size=None,
            actual_sha256=None,
            cleanup_claim_id=None,
            cleanup_lease_expires_at=None,
            cleanup_status=WorkspaceUploadCleanupStatus.COMPLETE,
        ),
        expected_revision=cleanup_claimed.revision,
    )
    assert cleanup_complete is not None
    assert await store.purge_terminal(limit=store_harness.config.list_page_size) == 1
    assert (
        await store.get(
            cancelled.admission.upload_id,
            requester_user_id="requester",
            workspace_id="workspace",
            agent_id="agent",
        )
        is None
    )


@pytest.mark.asyncio
async def test_concurrent_create_allows_one_scoped_capacity_winner(
    store_harness: _StoreHarness,
) -> None:
    """The backend lock makes concurrent scoped admission deterministic."""
    results = await asyncio.gather(
        store_harness.store.create(_admission("one")),
        store_harness.store.create(_admission("two")),
    )

    assert sum(result is not None for result in results) == 1
