"""Backend-neutral Runtime transfer state-store contract harness."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Protocol, cast
from uuid import uuid4

import pytest

from azents.core.redis import create_redis_client
from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferCleanupStatus,
    RuntimeTransferConfig,
    RuntimeTransferDirection,
    RuntimeTransferFailure,
    RuntimeTransferObject,
    RuntimeTransferOutcome,
    RuntimeTransferPhase,
)
from azents.runtime.transfer.memory import InMemoryRuntimeTransferStateStore
from azents.runtime.transfer.redis import RedisRuntimeTransferStateStore
from azents.runtime.transfer.store import RuntimeTransferStateStore

_TEST_STARTED_AT = datetime.now(timezone.utc)


class _Clock:
    """Mutable timezone-aware test clock."""

    def __init__(self, now: datetime) -> None:
        """Initialize the clock.

        :param now: Initial authoritative time.
        """
        self.now = now

    def __call__(self) -> datetime:
        """Return the current authoritative time."""
        return self.now


class _RedisNamespaceCleaner(Protocol):
    """Redis namespace commands used only by the test fixture."""

    async def scan(
        self,
        *,
        cursor: int,
        match: str,
        count: int,
    ) -> tuple[int, list[bytes]]: ...

    async def delete(self, *keys: bytes) -> int: ...


class _RedisRetentionInspector(Protocol):
    """Redis commands used only for physical retention assertions."""

    async def delete(self, *names: str) -> int: ...

    async def get(self, name: str) -> object: ...

    async def pttl(self, name: str) -> int: ...

    async def zscore(self, name: str, value: str) -> float | None: ...


@dataclass(frozen=True)
class _StoreHarness:
    """Backend-neutral store and deterministic time dependencies."""

    store: RuntimeTransferStateStore
    clock: _Clock
    config: RuntimeTransferConfig


@pytest.fixture(params=("memory", "redis"), ids=("memory", "redis"))
async def store_harness(
    request: pytest.FixtureRequest,
) -> AsyncIterator[_StoreHarness]:
    """Create one memory or real-Redis contract harness."""
    clock = _Clock(_TEST_STARTED_AT)
    config = RuntimeTransferConfig(
        per_runtime_attempts=2,
        per_runtime_bytes=10,
        deployment_attempts=2,
        deployment_bytes=10,
        admission_lease=timedelta(minutes=5),
        consumer_lease=timedelta(minutes=1),
        terminal_ttl=timedelta(minutes=5),
        list_page_size=2,
    )
    if request.param == "memory":
        store: RuntimeTransferStateStore = InMemoryRuntimeTransferStateStore(
            config=config,
            clock=clock,
        )
        yield _StoreHarness(store=store, clock=clock, config=config)
        return

    redis_url = request.getfixturevalue("redis_url")
    client = create_redis_client(redis_url)
    namespace = f"azents:runtime:transfer:test:{uuid4().hex}"
    store = RedisRuntimeTransferStateStore(
        redis=client,
        config=config,
        clock=clock,
        namespace=namespace,
    )
    try:
        yield _StoreHarness(store=store, clock=clock, config=config)
    finally:
        await _delete_transfer_namespace(
            cast(_RedisNamespaceCleaner, client),
            namespace,
        )
        await client.aclose()


async def _delete_transfer_namespace(
    client: _RedisNamespaceCleaner,
    namespace: str,
) -> None:
    """Iteratively delete one test-only transfer namespace without ``KEYS``."""
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


def _admission() -> RuntimeTransferAdmission:
    """Return one explicit metadata-only upload admission."""
    return RuntimeTransferAdmission(
        transfer_id="transfer",
        attempt_id="attempt",
        direction=RuntimeTransferDirection.UPLOAD,
        runtime_id="runtime",
        desired_generation=1,
        operation_id="operation",
        session_id=None,
        runtime_path="/workspace/file",
        overwrite=False,
        expected_size=1,
        expected_sha256="a" * 64,
        product_maximum_size=10,
        provider_maximum_size=10,
        deadline_at=_TEST_STARTED_AT + timedelta(minutes=5),
        source_expires_at=None,
        resource_class="default",
    )


@pytest.mark.asyncio
async def test_admits_and_gets_current_preparing_attempt(
    store_harness: _StoreHarness,
) -> None:
    """The contract returns one current PREPARING attempt with one-hour expiry."""
    admitted = await store_harness.store.admit(_admission(), lease_id="lease")

    assert admitted is not None
    assert admitted.phase is RuntimeTransferPhase.PREPARING
    assert admitted.logical_expires_at == store_harness.clock.now + timedelta(hours=1)
    assert await store_harness.store.get("transfer") == admitted


@pytest.mark.asyncio
async def test_rejects_invalid_size_and_expired_source_without_record(
    store_harness: _StoreHarness,
) -> None:
    """Rejected admission does not create observable state."""
    rejected = replace(_admission(), transfer_id="large", expected_size=11)
    assert await store_harness.store.admit(rejected, lease_id="lease") is None
    assert await store_harness.store.get("large") is None
    expired = replace(
        _admission(),
        transfer_id="expired",
        source_expires_at=store_harness.clock.now,
    )
    assert await store_harness.store.admit(expired, lease_id="lease") is None
    assert await store_harness.store.get("expired") is None


@pytest.mark.asyncio
async def test_admission_lease_expiry_reclaims_capacity_and_fences_old_owner(
    store_harness: _StoreHarness,
) -> None:
    """One access reclaims all expired leases before admitting new work."""
    first = await store_harness.store.admit(
        replace(_admission(), transfer_id="first", expected_size=5),
        lease_id="first-lease",
    )
    second = await store_harness.store.admit(
        replace(_admission(), transfer_id="second", expected_size=5),
        lease_id="second-lease",
    )
    assert first is not None and second is not None

    store_harness.clock.now += store_harness.config.admission_lease
    replacement = await store_harness.store.admit(
        replace(_admission(), transfer_id="replacement", expected_size=10),
        lease_id="replacement-lease",
    )

    assert replacement is not None
    assert (
        await store_harness.store.mark_ready(
            "first",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            expected_revision=first.revision,
            object=RuntimeTransferObject("stale-object", 5, "a" * 64),
        )
        is None
    )


@pytest.mark.asyncio
async def test_duplicate_capacity_expiry_retry_pagination_and_purge(
    store_harness: _StoreHarness,
) -> None:
    """Admission capacity, expiry, retry, stale page, and purge are observable."""
    first = await store_harness.store.admit(
        replace(
            _admission(),
            source_expires_at=store_harness.clock.now + timedelta(seconds=1),
        ),
        lease_id="lease",
    )
    assert first is not None
    assert await store_harness.store.admit(_admission(), lease_id="other") == first
    blocked = replace(_admission(), transfer_id="other")
    second = await store_harness.store.admit(blocked, lease_id="other")
    assert second is not None
    assert (
        await store_harness.store.admit(
            replace(_admission(), transfer_id="third"),
            lease_id="third",
        )
        is None
    )
    store_harness.clock.now += timedelta(minutes=2)
    stale = await store_harness.store.list_stale(cursor=None, limit=1)
    assert len(stale.records) == 1
    with pytest.raises(ValueError):
        await store_harness.store.list_stale(cursor=None, limit=0)
    expired = await store_harness.store.get("transfer")
    assert expired is not None
    assert expired.terminal_outcome is RuntimeTransferOutcome.EXPIRED
    retry = replace(_admission(), attempt_id="retry")
    current = await store_harness.store.admit(retry, lease_id="retry")
    assert current is not None and current.admission.attempt_id == "retry"
    assert (
        await store_harness.store.record_cleanup(
            "transfer",
            attempt_id="attempt",
            expected_revision=expired.revision,
            status=RuntimeTransferCleanupStatus.PENDING,
        )
        is not None
    )
    store_harness.clock.now += timedelta(minutes=6)
    assert await store_harness.store.purge_terminal(limit=10) >= 1
    assert (await store_harness.store.get("transfer")) is not None


@pytest.mark.asyncio
async def test_download_lifecycle_fences_stream_claim_and_progress(
    store_harness: _StoreHarness,
) -> None:
    """Download lifecycle fences mutations and keeps latest bounded progress."""
    admission = replace(
        _admission(),
        transfer_id="download",
        direction=RuntimeTransferDirection.DOWNLOAD,
        expected_size=3,
        product_maximum_size=3,
        provider_maximum_size=3,
    )
    admitted = await store_harness.store.admit(admission, lease_id="download-lease")
    assert admitted is not None
    object = RuntimeTransferObject("download-object", 3, "a" * 64)

    assert (
        await store_harness.store.mark_ready(
            "download",
            attempt_id="wrong",
            runtime_id="runtime",
            desired_generation=1,
            expected_revision=admitted.revision,
            object=object,
        )
        is None
    )
    assert (
        await store_harness.store.mark_ready(
            "download",
            attempt_id="attempt",
            runtime_id="wrong",
            desired_generation=1,
            expected_revision=admitted.revision,
            object=object,
        )
        is None
    )
    assert (
        await store_harness.store.mark_ready(
            "download",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=2,
            expected_revision=admitted.revision,
            object=object,
        )
        is None
    )
    assert (
        await store_harness.store.mark_ready(
            "download",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            expected_revision=admitted.revision + 1,
            object=object,
        )
        is None
    )
    assert (
        await store_harness.store.mark_ready(
            "download",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            expected_revision=admitted.revision,
            object=RuntimeTransferObject("wrong-size", 2, "a" * 64),
        )
        is None
    )
    assert (
        await store_harness.store.mark_ready(
            "download",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            expected_revision=admitted.revision,
            object=RuntimeTransferObject("wrong-sha", 3, "b" * 64),
        )
        is None
    )
    ready = await store_harness.store.mark_ready(
        "download",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        expected_revision=admitted.revision,
        object=object,
    )
    assert ready is not None

    claims = await asyncio.gather(
        *(
            store_harness.store.claim_stream(
                "download",
                attempt_id="attempt",
                runtime_id="runtime",
                desired_generation=1,
                accepted_runner_generation=2,
                expected_revision=ready.revision,
                claim_id=claim_id,
            )
            for claim_id in ("stream-one", "stream-two")
        )
    )
    winners = [record for record in claims if record is not None]
    assert len(winners) == 1
    stream = winners[0]
    assert stream.stream_claim_id in {"stream-one", "stream-two"}
    assert stream.accepted_runner_generation == 2
    assert (
        await store_harness.store.record_progress(
            "download",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            accepted_runner_generation=3,
            claim_id=stream.stream_claim_id or "",
            expected_revision=stream.revision,
            bytes_transferred=1,
        )
        is None
    )
    assert (
        await store_harness.store.record_progress(
            "download",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            accepted_runner_generation=2,
            claim_id="stale-claim",
            expected_revision=stream.revision,
            bytes_transferred=1,
        )
        is None
    )
    assert (
        await store_harness.store.record_progress(
            "download",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            accepted_runner_generation=2,
            claim_id=stream.stream_claim_id or "",
            expected_revision=stream.revision,
            bytes_transferred=4,
        )
        is None
    )
    progress = await store_harness.store.record_progress(
        "download",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        claim_id=stream.stream_claim_id or "",
        expected_revision=stream.revision,
        bytes_transferred=2,
    )
    assert progress is not None
    assert progress.progress is not None
    assert progress.progress.bytes_transferred == 2
    assert progress.progress.observed_at == store_harness.clock.now
    assert progress.logical_expires_at == stream.logical_expires_at
    assert (
        await store_harness.store.record_progress(
            "download",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            accepted_runner_generation=2,
            claim_id=stream.stream_claim_id or "",
            expected_revision=progress.revision,
            bytes_transferred=1,
        )
        is None
    )
    latest = await store_harness.store.record_progress(
        "download",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        claim_id=stream.stream_claim_id or "",
        expected_revision=progress.revision,
        bytes_transferred=3,
    )
    assert latest is not None
    assert latest.progress is not None
    assert latest.progress.bytes_transferred == 3
    assert latest.logical_expires_at == stream.logical_expires_at
    assert (
        await store_harness.store.begin_verification(
            "download",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            accepted_runner_generation=2,
            claim_id=stream.stream_claim_id or "",
            expected_revision=latest.revision + 1,
        )
        is None
    )
    verifying = await store_harness.store.begin_verification(
        "download",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        claim_id=stream.stream_claim_id or "",
        expected_revision=latest.revision,
    )
    assert verifying is not None
    assert (
        await store_harness.store.mark_committed(
            "download",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            accepted_runner_generation=2,
            claim_id=stream.stream_claim_id or "",
            expected_revision=verifying.revision,
            actual_size=2,
            actual_sha256="a" * 64,
        )
        is None
    )
    assert (
        await store_harness.store.mark_committed(
            "download",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            accepted_runner_generation=2,
            claim_id=stream.stream_claim_id or "",
            expected_revision=verifying.revision,
            actual_size=3,
            actual_sha256="b" * 64,
        )
        is None
    )
    committed = await store_harness.store.mark_committed(
        "download",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        claim_id=stream.stream_claim_id or "",
        expected_revision=verifying.revision,
        actual_size=3,
        actual_sha256="a" * 64,
    )
    assert committed is not None
    assert committed.phase is RuntimeTransferPhase.COMMITTED
    terminal = await store_harness.store.settle(
        "download",
        attempt_id="attempt",
        expected_revision=committed.revision,
        outcome=RuntimeTransferOutcome.SUCCEEDED,
        failure=None,
    )
    assert terminal is not None
    assert terminal.terminal_outcome is RuntimeTransferOutcome.SUCCEEDED
    assert (
        await store_harness.store.publish_available(
            "download",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            accepted_runner_generation=2,
            claim_id=stream.stream_claim_id or "",
            expected_revision=terminal.revision,
            actual_size=3,
            actual_sha256="a" * 64,
        )
        is None
    )


@pytest.mark.asyncio
async def test_upload_lifecycle_consumer_claim_abandon_expiry_and_acknowledgement(
    store_harness: _StoreHarness,
) -> None:
    """Upload consumers are fenced, reclaimable, and acknowledged exactly once."""
    admitted = await store_harness.store.admit(
        replace(_admission(), transfer_id="upload"),
        lease_id="upload-lease",
    )
    assert admitted is not None
    object = RuntimeTransferObject("upload-object", 1, "a" * 64)
    ready = await store_harness.store.mark_ready(
        "upload",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        expected_revision=admitted.revision,
        object=object,
    )
    assert ready is not None
    stream = await store_harness.store.claim_stream(
        "upload",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        expected_revision=ready.revision,
        claim_id="upload-stream",
    )
    assert stream is not None
    verifying = await store_harness.store.begin_verification(
        "upload",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        claim_id="upload-stream",
        expected_revision=stream.revision,
    )
    assert verifying is not None
    assert (
        await store_harness.store.mark_committed(
            "upload",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            accepted_runner_generation=2,
            claim_id="upload-stream",
            expected_revision=verifying.revision,
            actual_size=1,
            actual_sha256="a" * 64,
        )
        is None
    )
    available = await store_harness.store.publish_available(
        "upload",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        claim_id="upload-stream",
        expected_revision=verifying.revision,
        actual_size=1,
        actual_sha256="a" * 64,
    )
    assert available is not None

    claims = await asyncio.gather(
        *(
            store_harness.store.claim_consumer(
                "upload",
                attempt_id="attempt",
                expected_revision=available.revision,
                claim_id=claim_id,
            )
            for claim_id in ("consumer-one", "consumer-two")
        )
    )
    winners = [record for record in claims if record is not None]
    assert len(winners) == 1
    consuming = winners[0]
    assert consuming.consumer_claim_id in {"consumer-one", "consumer-two"}
    assert (
        await store_harness.store.acknowledge_consumer(
            "upload",
            attempt_id="attempt",
            expected_revision=consuming.revision,
            claim_id="wrong-consumer",
        )
        is None
    )
    assert (
        await store_harness.store.acknowledge_consumer(
            "upload",
            attempt_id="attempt",
            expected_revision=consuming.revision + 1,
            claim_id=consuming.consumer_claim_id or "",
        )
        is None
    )
    abandoned = await store_harness.store.abandon_consumer(
        "upload",
        attempt_id="attempt",
        expected_revision=consuming.revision,
        claim_id=consuming.consumer_claim_id or "",
    )
    assert abandoned is not None
    assert abandoned.phase is RuntimeTransferPhase.AVAILABLE
    reclaimed = await store_harness.store.claim_consumer(
        "upload",
        attempt_id="attempt",
        expected_revision=abandoned.revision,
        claim_id="consumer-reclaimed",
    )
    assert reclaimed is not None
    store_harness.clock.now += timedelta(minutes=2)
    available_after_expiry = await store_harness.store.get("upload")
    assert available_after_expiry is not None
    assert available_after_expiry.phase is RuntimeTransferPhase.AVAILABLE
    assert (
        await store_harness.store.acknowledge_consumer(
            "upload",
            attempt_id="attempt",
            expected_revision=reclaimed.revision,
            claim_id="consumer-reclaimed",
        )
        is None
    )
    final_claim = await store_harness.store.claim_consumer(
        "upload",
        attempt_id="attempt",
        expected_revision=available_after_expiry.revision,
        claim_id="consumer-final",
    )
    assert final_claim is not None
    consumed = await store_harness.store.acknowledge_consumer(
        "upload",
        attempt_id="attempt",
        expected_revision=final_claim.revision,
        claim_id="consumer-final",
    )
    assert consumed is not None
    assert consumed.phase is RuntimeTransferPhase.CONSUMED
    store_harness.clock.now += timedelta(minutes=2)
    retained = await store_harness.store.get("upload")
    assert retained is not None
    assert retained.phase is RuntimeTransferPhase.CONSUMED


@pytest.mark.asyncio
async def test_consumer_and_admission_expiry_reclaim_capacity_atomically(
    store_harness: _StoreHarness,
) -> None:
    """Simultaneous lease expiry releases both claim and admission capacity."""
    admitted = await store_harness.store.admit(
        replace(_admission(), transfer_id="simultaneous"),
        lease_id="simultaneous-lease",
    )
    assert admitted is not None
    ready = await store_harness.store.mark_ready(
        "simultaneous",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        expected_revision=admitted.revision,
        object=RuntimeTransferObject("object", 1, "a" * 64),
    )
    assert ready is not None
    stream = await store_harness.store.claim_stream(
        "simultaneous",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        expected_revision=ready.revision,
        claim_id="stream",
    )
    assert stream is not None
    verifying = await store_harness.store.begin_verification(
        "simultaneous",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        claim_id="stream",
        expected_revision=stream.revision,
    )
    assert verifying is not None
    available = await store_harness.store.publish_available(
        "simultaneous",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        claim_id="stream",
        expected_revision=verifying.revision,
        actual_size=1,
        actual_sha256="a" * 64,
    )
    assert available is not None

    store_harness.clock.now += timedelta(minutes=4)
    blocker = await store_harness.store.admit(
        replace(_admission(), transfer_id="blocker", expected_size=9),
        lease_id="blocker-lease",
    )
    assert blocker is not None
    consuming = await store_harness.store.claim_consumer(
        "simultaneous",
        attempt_id="attempt",
        expected_revision=available.revision,
        claim_id="consumer",
    )
    assert consuming is not None

    store_harness.clock.now += timedelta(minutes=1)
    replacement = await store_harness.store.admit(
        replace(_admission(), transfer_id="after-reclaim"),
        lease_id="replacement-lease",
    )

    assert replacement is not None
    reclaimed = await store_harness.store.get("simultaneous")
    assert reclaimed is not None
    assert reclaimed.phase is RuntimeTransferPhase.AVAILABLE


@pytest.mark.asyncio
async def test_cancellation_fences_concurrent_verification_and_terminal_settlement(
    store_harness: _StoreHarness,
) -> None:
    """Cancellation wins its revision race and permits only cancellation settlement."""
    admitted = await store_harness.store.admit(
        replace(_admission(), transfer_id="cancellation"),
        lease_id="cancellation-lease",
    )
    assert admitted is not None
    ready = await store_harness.store.mark_ready(
        "cancellation",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        expected_revision=admitted.revision,
        object=RuntimeTransferObject("cancellation-object", 1, "a" * 64),
    )
    assert ready is not None
    stream = await store_harness.store.claim_stream(
        "cancellation",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        expected_revision=ready.revision,
        claim_id="cancellation-stream",
    )
    assert stream is not None
    cancelled = await store_harness.store.request_cancellation(
        "cancellation",
        attempt_id="attempt",
        expected_revision=stream.revision,
    )
    assert cancelled is not None
    assert (
        await store_harness.store.request_cancellation(
            "cancellation",
            attempt_id="attempt",
            expected_revision=stream.revision,
        )
        == cancelled
    )
    assert (
        await store_harness.store.record_progress(
            "cancellation",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            accepted_runner_generation=2,
            claim_id="cancellation-stream",
            expected_revision=cancelled.revision,
            bytes_transferred=1,
        )
        is None
    )
    assert (
        await store_harness.store.begin_verification(
            "cancellation",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            accepted_runner_generation=2,
            claim_id="cancellation-stream",
            expected_revision=cancelled.revision,
        )
        is None
    )
    assert (
        await store_harness.store.settle(
            "cancellation",
            attempt_id="attempt",
            expected_revision=cancelled.revision,
            outcome=RuntimeTransferOutcome.SUCCEEDED,
            failure=None,
        )
        is None
    )
    terminal = await store_harness.store.settle(
        "cancellation",
        attempt_id="attempt",
        expected_revision=cancelled.revision,
        outcome=RuntimeTransferOutcome.CANCELLED,
        failure=None,
    )
    assert terminal is not None
    assert (
        await store_harness.store.settle(
            "cancellation",
            attempt_id="attempt",
            expected_revision=cancelled.revision,
            outcome=RuntimeTransferOutcome.CANCELLED,
            failure=None,
        )
        == terminal
    )
    assert (
        await store_harness.store.request_cancellation(
            "cancellation",
            attempt_id="attempt",
            expected_revision=stream.revision,
        )
        == terminal
    )
    assert (
        await store_harness.store.settle(
            "cancellation",
            attempt_id="attempt",
            expected_revision=cancelled.revision,
            outcome=RuntimeTransferOutcome.FAILED,
            failure=None,
        )
        is None
    )


@pytest.mark.asyncio
async def test_stale_pagination_remains_stable_when_prior_page_mutates(
    store_harness: _StoreHarness,
) -> None:
    """Updating a processed record cannot skip the next stale record."""
    for transfer_id in ("page-a", "page-b", "page-c"):
        admitted = await store_harness.store.admit(
            replace(_admission(), transfer_id=transfer_id),
            lease_id=f"{transfer_id}-lease",
        )
        assert admitted is not None
        terminal = await store_harness.store.settle(
            transfer_id,
            attempt_id="attempt",
            expected_revision=admitted.revision,
            outcome=RuntimeTransferOutcome.FAILED,
            failure=RuntimeTransferFailure.STREAM,
        )
        assert terminal is not None

    first_page = await store_harness.store.list_stale(cursor=None, limit=1)
    assert len(first_page.records) == 1
    assert first_page.cursor is not None
    first = first_page.records[0]
    mutated = await store_harness.store.record_cleanup(
        first.admission.transfer_id,
        attempt_id=first.admission.attempt_id,
        expected_revision=first.revision,
        status=RuntimeTransferCleanupStatus.PENDING,
    )
    assert mutated is not None

    second_page = await store_harness.store.list_stale(
        cursor=first_page.cursor,
        limit=1,
    )

    assert len(second_page.records) == 1
    assert second_page.records[0].admission.transfer_id != first.admission.transfer_id


@pytest.mark.asyncio
async def test_stale_pagination_continues_after_prior_member_expires(
    store_harness: _StoreHarness,
) -> None:
    """Removing a prior page member cannot skip its successor."""
    terminals = []
    for transfer_id in ("expiry-page-a", "expiry-page-b", "expiry-page-c"):
        admitted = await store_harness.store.admit(
            replace(_admission(), transfer_id=transfer_id),
            lease_id=f"{transfer_id}-lease",
        )
        assert admitted is not None
        terminal = await store_harness.store.settle(
            transfer_id,
            attempt_id="attempt",
            expected_revision=admitted.revision,
            outcome=RuntimeTransferOutcome.FAILED,
            failure=RuntimeTransferFailure.STREAM,
        )
        assert terminal is not None
        terminals.append(terminal)
        store_harness.clock.now += timedelta(minutes=1)

    first_page = await store_harness.store.list_stale(cursor=None, limit=1)
    assert len(first_page.records) == 1
    assert first_page.cursor is not None
    assert first_page.records[0].admission.transfer_id == "expiry-page-a"

    first_expiry = terminals[0].terminal_expires_at
    assert first_expiry is not None
    store_harness.clock.now = first_expiry
    second_page = await store_harness.store.list_stale(
        cursor=first_page.cursor,
        limit=1,
    )

    assert len(second_page.records) == 1
    assert second_page.records[0].admission.transfer_id == "expiry-page-b"


@pytest.mark.asyncio
async def test_final_manifest_matches_ready_object_without_admission_sha(
    store_harness: _StoreHarness,
) -> None:
    """Final integrity evidence must match READY even without an admission SHA."""
    admission = replace(
        _admission(),
        transfer_id="object-manifest",
        direction=RuntimeTransferDirection.DOWNLOAD,
        expected_sha256=None,
    )
    admitted = await store_harness.store.admit(admission, lease_id="lease")
    assert admitted is not None
    ready = await store_harness.store.mark_ready(
        "object-manifest",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        expected_revision=admitted.revision,
        object=RuntimeTransferObject("object", 1, "a" * 64),
    )
    assert ready is not None
    stream = await store_harness.store.claim_stream(
        "object-manifest",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        expected_revision=ready.revision,
        claim_id="stream",
    )
    assert stream is not None
    verifying = await store_harness.store.begin_verification(
        "object-manifest",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        claim_id="stream",
        expected_revision=stream.revision,
    )
    assert verifying is not None
    assert (
        await store_harness.store.mark_committed(
            "object-manifest",
            attempt_id="attempt",
            runtime_id="runtime",
            desired_generation=1,
            accepted_runner_generation=2,
            claim_id="stream",
            expected_revision=verifying.revision,
            actual_size=1,
            actual_sha256="b" * 64,
        )
        is None
    )
    committed = await store_harness.store.mark_committed(
        "object-manifest",
        attempt_id="attempt",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        claim_id="stream",
        expected_revision=verifying.revision,
        actual_size=1,
        actual_sha256="a" * 64,
    )
    assert committed is not None


@pytest.mark.asyncio
async def test_success_requires_direction_final_phase(
    store_harness: _StoreHarness,
) -> None:
    """Fresh preparation cannot be settled as successful."""
    admitted = await store_harness.store.admit(
        replace(_admission(), transfer_id="premature-success"),
        lease_id="lease",
    )
    assert admitted is not None
    assert (
        await store_harness.store.settle(
            "premature-success",
            attempt_id="attempt",
            expected_revision=admitted.revision,
            outcome=RuntimeTransferOutcome.SUCCEEDED,
            failure=None,
        )
        is None
    )


@pytest.mark.asyncio
async def test_redis_terminal_keys_expire_together(
    redis_url: str,
) -> None:
    """Valkey physically expires terminal record, pointer, and index bucket."""
    client = create_redis_client(redis_url)
    namespace = f"azents:runtime:transfer:ttl-test:{uuid4().hex}"
    clock = _Clock(datetime(2035, 1, 1, tzinfo=timezone.utc))
    config = RuntimeTransferConfig(
        per_runtime_attempts=1,
        per_runtime_bytes=10,
        deployment_attempts=1,
        deployment_bytes=10,
        admission_lease=timedelta(minutes=1),
        consumer_lease=timedelta(minutes=1),
        terminal_ttl=timedelta(seconds=2),
        list_page_size=1,
    )
    store = RedisRuntimeTransferStateStore(
        redis=client,
        config=config,
        clock=clock,
        namespace=namespace,
    )
    inspector = cast(_RedisRetentionInspector, client)
    try:
        admission = replace(
            _admission(),
            transfer_id="physical-terminal-expiry",
            deadline_at=clock.now + timedelta(minutes=1),
        )
        admitted = await store.admit(admission, lease_id="lease")
        assert admitted is not None
        terminal = await store.settle(
            "physical-terminal-expiry",
            attempt_id="attempt",
            expected_revision=admitted.revision,
            outcome=RuntimeTransferOutcome.FAILED,
            failure=RuntimeTransferFailure.STREAM,
        )
        assert terminal is not None
        assert terminal.terminal_expires_at is not None
        record_key = store.keys.record("physical-terminal-expiry", "attempt")
        pointer_key = store.keys.current("physical-terminal-expiry")
        bucket_key = store.keys.terminal_bucket(terminal.terminal_expires_at)

        record_ttl = await inspector.pttl(record_key)
        pointer_ttl = await inspector.pttl(pointer_key)
        bucket_ttl = await inspector.pttl(bucket_key)
        assert 0 < record_ttl <= 2_000
        assert 0 < pointer_ttl <= 2_000
        assert 0 < bucket_ttl <= 2_000
        assert await inspector.zscore(bucket_key, record_key) == 0.0
        assert await inspector.zscore(store.keys.stale_index(), record_key) is None

        await asyncio.sleep(1.1)

        assert await store.get("physical-terminal-expiry") == terminal
        refreshed_record_ttl = await inspector.pttl(record_key)
        refreshed_pointer_ttl = await inspector.pttl(pointer_key)
        refreshed_bucket_ttl = await inspector.pttl(bucket_key)
        assert 0 < refreshed_record_ttl <= 1_200
        assert 0 < refreshed_pointer_ttl <= 1_200
        assert 0 < refreshed_bucket_ttl <= 1_200

        await asyncio.sleep(1.1)

        assert await inspector.get(record_key) is None
        assert await inspector.get(pointer_key) is None
        assert await inspector.get(bucket_key) is None
    finally:
        await _delete_transfer_namespace(
            cast(_RedisNamespaceCleaner, client),
            namespace,
        )
        await client.aclose()


@pytest.mark.asyncio
async def test_redis_new_current_pointer_outlives_old_terminal_ttl(
    redis_url: str,
) -> None:
    """A retry clears the prior terminal pointer TTL before old metadata expires."""
    client = create_redis_client(redis_url)
    namespace = f"azents:runtime:transfer:pointer-test:{uuid4().hex}"
    clock = _Clock(datetime(2035, 1, 1, tzinfo=timezone.utc))
    config = RuntimeTransferConfig(
        per_runtime_attempts=1,
        per_runtime_bytes=10,
        deployment_attempts=1,
        deployment_bytes=10,
        admission_lease=timedelta(minutes=1),
        consumer_lease=timedelta(minutes=1),
        terminal_ttl=timedelta(seconds=2),
        list_page_size=1,
    )
    store = RedisRuntimeTransferStateStore(
        redis=client,
        config=config,
        clock=clock,
        namespace=namespace,
    )
    inspector = cast(_RedisRetentionInspector, client)
    try:
        admission = replace(
            _admission(),
            transfer_id="retry-pointer",
            deadline_at=clock.now + timedelta(minutes=1),
        )
        admitted = await store.admit(admission, lease_id="old-lease")
        assert admitted is not None
        terminal = await store.settle(
            "retry-pointer",
            attempt_id="attempt",
            expected_revision=admitted.revision,
            outcome=RuntimeTransferOutcome.FAILED,
            failure=RuntimeTransferFailure.STREAM,
        )
        assert terminal is not None
        retry = await store.admit(
            replace(admission, attempt_id="retry"),
            lease_id="retry-lease",
        )
        assert retry is not None
        pointer_key = store.keys.current("retry-pointer")
        retry_key = store.keys.record("retry-pointer", "retry")

        assert await inspector.pttl(pointer_key) == -1
        assert await inspector.get(pointer_key) in {retry_key, retry_key.encode()}

        await asyncio.sleep(2.1)

        assert await inspector.get(pointer_key) in {retry_key, retry_key.encode()}
        assert await store.get("retry-pointer") == retry
    finally:
        await _delete_transfer_namespace(
            cast(_RedisNamespaceCleaner, client),
            namespace,
        )
        await client.aclose()


@pytest.mark.asyncio
async def test_redis_stale_pagination_continues_after_dangling_members(
    redis_url: str,
) -> None:
    """Dangling index members yield a cursor instead of hiding later work."""
    client = create_redis_client(redis_url)
    namespace = f"azents:runtime:transfer:stale-page-test:{uuid4().hex}"
    clock = _Clock(datetime(2035, 1, 1, tzinfo=timezone.utc))
    config = RuntimeTransferConfig(
        per_runtime_attempts=3,
        per_runtime_bytes=10,
        deployment_attempts=3,
        deployment_bytes=10,
        admission_lease=timedelta(minutes=1),
        consumer_lease=timedelta(minutes=1),
        terminal_ttl=timedelta(minutes=1),
        list_page_size=1,
    )
    store = RedisRuntimeTransferStateStore(
        redis=client,
        config=config,
        clock=clock,
        namespace=namespace,
    )
    inspector = cast(_RedisRetentionInspector, client)
    try:
        transfer_ids_by_key: dict[str, str] = {}
        for transfer_id in ("dangling-a", "dangling-b", "dangling-c"):
            admitted = await store.admit(
                replace(_admission(), transfer_id=transfer_id),
                lease_id=f"{transfer_id}-lease",
            )
            assert admitted is not None
            released = await store.release_admission(
                transfer_id,
                attempt_id="attempt",
                lease_id=f"{transfer_id}-lease",
            )
            assert released is not None
            transfer_ids_by_key[store.keys.record(transfer_id, "attempt")] = transfer_id

        ordered_keys = sorted(transfer_ids_by_key)
        assert await inspector.delete(*ordered_keys[:2]) == 2

        first_page = await store.list_stale(cursor=None, limit=1)
        assert first_page.records == ()
        assert first_page.cursor is not None

        second_page = await store.list_stale(
            cursor=first_page.cursor,
            limit=1,
        )
        assert tuple(
            record.admission.transfer_id for record in second_page.records
        ) == (transfer_ids_by_key[ordered_keys[2]],)
    finally:
        await _delete_transfer_namespace(
            cast(_RedisNamespaceCleaner, client),
            namespace,
        )
        await client.aclose()


@pytest.mark.asyncio
async def test_terminal_metadata_expires_on_access(
    store_harness: _StoreHarness,
) -> None:
    """Terminal metadata is no longer observable at the configured boundary."""
    admitted = await store_harness.store.admit(
        replace(_admission(), transfer_id="terminal-expiry"),
        lease_id="lease",
    )
    assert admitted is not None
    terminal = await store_harness.store.settle(
        "terminal-expiry",
        attempt_id="attempt",
        expected_revision=admitted.revision,
        outcome=RuntimeTransferOutcome.FAILED,
        failure=RuntimeTransferFailure.STREAM,
    )
    assert terminal is not None
    assert terminal.terminal_expires_at is not None

    store_harness.clock.now = terminal.terminal_expires_at

    assert (
        await store_harness.store.request_cancellation(
            "terminal-expiry",
            attempt_id="attempt",
            expected_revision=terminal.revision,
        )
        is None
    )
    assert (
        await store_harness.store.record_cleanup(
            "terminal-expiry",
            attempt_id="attempt",
            expected_revision=terminal.revision,
            status=RuntimeTransferCleanupStatus.PENDING,
        )
        is None
    )
    assert await store_harness.store.get("terminal-expiry") is None


@pytest.mark.asyncio
async def test_terminal_release_cleanup_and_historical_attempt_authority(
    store_harness: _StoreHarness,
) -> None:
    """Terminal history cannot mutate a newer current attempt."""
    admitted = await store_harness.store.admit(
        replace(_admission(), transfer_id="historical"),
        lease_id="old-lease",
    )
    assert admitted is not None
    pending_cleanup = await store_harness.store.record_cleanup(
        "historical",
        attempt_id="attempt",
        expected_revision=admitted.revision,
        status=RuntimeTransferCleanupStatus.PENDING,
    )
    assert pending_cleanup is not None
    assert (
        await store_harness.store.record_cleanup(
            "historical",
            attempt_id="attempt",
            expected_revision=admitted.revision,
            status=RuntimeTransferCleanupStatus.PENDING,
        )
        == pending_cleanup
    )
    released = await store_harness.store.release_admission(
        "historical",
        attempt_id="attempt",
        lease_id="old-lease",
    )
    assert released == pending_cleanup
    assert (
        await store_harness.store.release_admission(
            "historical",
            attempt_id="attempt",
            lease_id="old-lease",
        )
        == released
    )
    terminal = await store_harness.store.settle(
        "historical",
        attempt_id="attempt",
        expected_revision=pending_cleanup.revision,
        outcome=RuntimeTransferOutcome.FAILED,
        failure=None,
    )
    assert terminal is not None
    assert (
        await store_harness.store.settle(
            "historical",
            attempt_id="attempt",
            expected_revision=terminal.revision,
            outcome=RuntimeTransferOutcome.FAILED,
            failure=None,
        )
        == terminal
    )
    complete_cleanup = await store_harness.store.record_cleanup(
        "historical",
        attempt_id="attempt",
        expected_revision=terminal.revision,
        status=RuntimeTransferCleanupStatus.COMPLETE,
    )
    assert complete_cleanup is not None
    assert (
        await store_harness.store.record_cleanup(
            "historical",
            attempt_id="attempt",
            expected_revision=terminal.revision,
            status=RuntimeTransferCleanupStatus.COMPLETE,
        )
        == complete_cleanup
    )
    retry = await store_harness.store.admit(
        replace(_admission(), transfer_id="historical", attempt_id="retry"),
        lease_id="retry-lease",
    )
    assert retry is not None
    old_cleanup = await store_harness.store.record_cleanup(
        "historical",
        attempt_id="attempt",
        expected_revision=complete_cleanup.revision,
        status=RuntimeTransferCleanupStatus.RETRYABLE_FAILURE,
    )
    assert old_cleanup is not None
    current = await store_harness.store.get("historical")
    assert current == retry
    assert (
        await store_harness.store.release_admission(
            "historical",
            attempt_id="attempt",
            lease_id="old-lease",
        )
        == old_cleanup
    )
    assert await store_harness.store.get("historical") == retry
    assert (
        await store_harness.store.settle(
            "historical",
            attempt_id="attempt",
            expected_revision=old_cleanup.revision,
            outcome=RuntimeTransferOutcome.FAILED,
            failure=None,
        )
        == old_cleanup
    )
    assert await store_harness.store.get("historical") == retry
