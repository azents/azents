"""Focused first-group tests for in-memory Runtime transfer state."""

import asyncio
from dataclasses import fields, is_dataclass
from datetime import datetime, timedelta, timezone

import pytest

from azents.runtime.transfer.data import (
    RuntimeTransferAdmission,
    RuntimeTransferCancellationReason,
    RuntimeTransferConfig,
    RuntimeTransferDirection,
    RuntimeTransferFailure,
    RuntimeTransferObject,
    RuntimeTransferOutcome,
    RuntimeTransferRecord,
)
from azents.runtime.transfer.memory import InMemoryRuntimeTransferStateStore


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


_NOW = datetime(2026, 7, 25, tzinfo=timezone.utc)
_DIGEST = "a" * 64


def _config(*, attempts: int = 2, bytes_limit: int = 10) -> RuntimeTransferConfig:
    return RuntimeTransferConfig(
        attempts,
        bytes_limit,
        attempts,
        bytes_limit,
        timedelta(minutes=1),
        timedelta(minutes=1),
        timedelta(seconds=30),
        timedelta(minutes=5),
        2,
    )


def _admission(
    transfer: str, attempt: str, *, size: int = 1, source: datetime | None = None
) -> RuntimeTransferAdmission:
    return RuntimeTransferAdmission(
        transfer,
        attempt,
        RuntimeTransferDirection.UPLOAD,
        "runtime",
        1,
        "operation",
        None,
        None,
        "/workspace/file",
        False,
        size,
        _DIGEST,
        10,
        10,
        _NOW + timedelta(minutes=5),
        source,
        "default",
    )


async def _claim_stream(
    store: InMemoryRuntimeTransferStateStore,
    transfer_id: str,
    *,
    attempt_id: str,
    runtime_id: str,
    desired_generation: int,
    accepted_runner_generation: int,
    expected_revision: int,
    claim_id: str,
) -> RuntimeTransferRecord | None:
    """Bind one test dispatch before claiming its bounded stream."""
    del expected_revision
    ready = await store.get(transfer_id)
    if ready is None:
        return None
    dispatch_id = f"dispatch:{transfer_id}"
    request_id = f"request:{transfer_id}"
    bound = await store.bind_dispatch(
        transfer_id,
        attempt_id=attempt_id,
        runtime_id=runtime_id,
        desired_generation=desired_generation,
        accepted_runner_generation=accepted_runner_generation,
        expected_revision=ready.revision,
        dispatch_id=dispatch_id,
        dispatch_request_id=request_id,
    )
    if bound is None:
        return None
    deliverable = await store.mark_dispatch_deliverable(
        transfer_id,
        attempt_id=attempt_id,
        expected_revision=bound.revision,
        dispatch_id=dispatch_id,
        dispatch_request_id=request_id,
    )
    if deliverable is None:
        return None
    return await store.claim_stream(
        transfer_id,
        attempt_id=attempt_id,
        runtime_id=runtime_id,
        desired_generation=desired_generation,
        accepted_runner_generation=accepted_runner_generation,
        expected_revision=deliverable.revision,
        claim_id=claim_id,
        owner_replica_id="test-replica",
    )


@pytest.mark.asyncio
async def test_clock_admission_duplicate_and_per_file_validation() -> None:
    """Store owns one aware clock and does not gate independent admissions."""
    naive = InMemoryRuntimeTransferStateStore(
        config=_config(), clock=lambda: datetime(2026, 7, 25)
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        await naive.get("missing")
    clock = _Clock(_NOW)
    store = InMemoryRuntimeTransferStateStore(config=_config(attempts=1), clock=clock)
    first = await store.admit(_admission("one", "a"), lease_id="lease")
    assert first is not None
    assert first.logical_expires_at == _NOW + timedelta(hours=1)
    assert await store.admit(_admission("one", "a"), lease_id="other") == first
    assert await store.admit(_admission("two", "a"), lease_id="lease") is not None
    assert await store.admit(_admission("bad", "a", size=11), lease_id="lease") is None
    assert (
        await store.admit(_admission("old", "a", source=_NOW), lease_id="lease") is None
    )


@pytest.mark.asyncio
async def test_concurrent_admission_retry_expiry_and_pagination() -> None:
    """Independent admissions, expiry, retry, and stale pages remain stable."""
    clock = _Clock(_NOW)
    store = InMemoryRuntimeTransferStateStore(config=_config(attempts=1), clock=clock)
    results = await asyncio.gather(
        *(store.admit(_admission(name, "a"), lease_id=name) for name in ("one", "two"))
    )
    admitted = [item for item in results if item is not None]
    assert len(admitted) == 2
    winner = next(item for item in admitted if item.admission.transfer_id == "one")
    assert (
        await store.admit(_admission(winner.admission.transfer_id, "b"), lease_id="b")
        is None
    )
    clock.now += timedelta(minutes=2)
    stale = await store.list_stale(cursor=None, limit=1)
    assert (
        stale.records
        and stale.records[0].admission.transfer_id == winner.admission.transfer_id
    )
    assert (
        await store.mark_ready(
            winner.admission.transfer_id,
            attempt_id="a",
            runtime_id="runtime",
            desired_generation=1,
            expected_revision=winner.revision,
            object=__import__(
                "azents.runtime.transfer.data", fromlist=["RuntimeTransferObject"]
            ).RuntimeTransferObject("key", 1, _DIGEST),
        )
        is None
    )
    current = await store.get(winner.admission.transfer_id)
    assert current is not None
    settled = await store.settle(
        winner.admission.transfer_id,
        attempt_id="a",
        expected_revision=current.revision,
        outcome=RuntimeTransferOutcome.FAILED,
        failure=RuntimeTransferFailure.STREAM,
    )
    assert settled is not None
    retry = await store.admit(
        _admission(winner.admission.transfer_id, "b"), lease_id="b"
    )
    assert retry is not None
    assert (winner.admission.transfer_id, "a") in store.records
    with pytest.raises(ValueError):
        await store.list_stale(cursor=None, limit=0)


@pytest.mark.asyncio
async def test_logical_expiry_purge_restart_and_metadata_only() -> None:
    """Logical expiry terminalizes, purge preserves newer current, and state is safe."""
    clock = _Clock(_NOW)
    store = InMemoryRuntimeTransferStateStore(config=_config(), clock=clock)
    record = await store.admit(
        _admission("one", "a", source=_NOW + timedelta(seconds=1)), lease_id="lease"
    )
    assert record is not None
    clock.now += timedelta(seconds=2)
    expired = await store.get("one")
    assert (
        expired is not None
        and expired.terminal_outcome is RuntimeTransferOutcome.EXPIRED
    )
    retry = await store.admit(_admission("one", "b"), lease_id="lease-b")
    assert retry is not None
    clock.now += timedelta(minutes=6)
    assert await store.purge_terminal(limit=10) >= 1
    assert store.current_attempts["one"] == "b"
    restarted = InMemoryRuntimeTransferStateStore(config=_config(), clock=clock)
    assert await restarted.get("one") is None
    _assert_safe(store.records)


def _assert_safe(value: object) -> None:
    """Reject binary/credential/URL-shaped data recursively."""
    if isinstance(value, bytes):
        raise AssertionError("state contains bytes")
    if isinstance(value, str):
        assert "://" not in value
        assert "credential" not in value.lower()
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_safe(key)
            _assert_safe(item)
    elif isinstance(value, (tuple, list, set)):
        for item in value:
            _assert_safe(item)
    elif is_dataclass(value):
        for field in fields(value):
            _assert_safe(getattr(value, field.name))


@pytest.mark.asyncio
async def test_ready_stream_progress_and_download_commit() -> None:
    """Ready/stream/progress flow is fenced and direction-valid."""
    clock = _Clock(_NOW)
    store = InMemoryRuntimeTransferStateStore(config=_config(), clock=clock)
    admission = RuntimeTransferAdmission(
        "download",
        "a",
        RuntimeTransferDirection.DOWNLOAD,
        "runtime",
        1,
        "operation",
        None,
        None,
        "/workspace/file",
        False,
        3,
        _DIGEST,
        3,
        3,
        _NOW + timedelta(minutes=5),
        None,
        "default",
    )
    record = await store.admit(admission, lease_id="lease")
    assert record is not None
    assert (
        await store.mark_ready(
            "download",
            attempt_id="wrong",
            runtime_id="runtime",
            desired_generation=1,
            expected_revision=record.revision,
            object=RuntimeTransferObject("object", 3, _DIGEST),
        )
        is None
    )
    ready = await store.mark_ready(
        "download",
        attempt_id="a",
        runtime_id="runtime",
        desired_generation=1,
        expected_revision=record.revision,
        object=RuntimeTransferObject("object", 3, _DIGEST),
    )
    assert ready is not None and ready.revision == 2
    claims = await asyncio.gather(
        *(
            _claim_stream(
                store,
                "download",
                attempt_id="a",
                runtime_id="runtime",
                desired_generation=1,
                accepted_runner_generation=2,
                expected_revision=ready.revision,
                claim_id=value,
            )
            for value in ("one", "two")
        )
    )
    stream = next(item for item in claims if item is not None)
    assert (
        stream.stream_claim_id in {"one", "two"}
        and stream.accepted_runner_generation == 2
    )
    expiry = stream.logical_expires_at
    progress = await store.record_progress(
        "download",
        attempt_id="a",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        claim_id=stream.stream_claim_id or "",
        expected_revision=stream.revision,
        bytes_transferred=2,
    )
    assert (
        progress is not None
        and progress.progress is not None
        and progress.logical_expires_at == expiry
    )
    assert (
        await store.record_progress(
            "download",
            attempt_id="a",
            runtime_id="runtime",
            desired_generation=1,
            accepted_runner_generation=2,
            claim_id=stream.stream_claim_id or "",
            expected_revision=progress.revision,
            bytes_transferred=1,
        )
        is None
    )
    verifying = await store.begin_verification(
        "download",
        attempt_id="a",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        claim_id=stream.stream_claim_id or "",
        expected_revision=progress.revision,
    )
    assert verifying is not None
    committed = await store.mark_committed(
        "download",
        attempt_id="a",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        claim_id=stream.stream_claim_id or "",
        expected_revision=verifying.revision,
        actual_size=3,
        actual_sha256=_DIGEST,
    )
    assert committed is not None and committed.phase.name == "COMMITTED"
    assert (
        await store.publish_available(
            "download",
            attempt_id="a",
            runtime_id="runtime",
            desired_generation=1,
            accepted_runner_generation=2,
            claim_id=stream.stream_claim_id or "",
            expected_revision=committed.revision,
            actual_size=3,
            actual_sha256=_DIGEST,
        )
        is None
    )


@pytest.mark.asyncio
async def test_upload_consumer_cancellation_terminal_and_historical_safety() -> None:
    """Upload consumer and terminal operations retain exact-attempt authority."""
    clock = _Clock(_NOW)
    store = InMemoryRuntimeTransferStateStore(config=_config(), clock=clock)
    record = await store.admit(_admission("upload", "a"), lease_id="lease")
    assert record is not None
    ready = await store.mark_ready(
        "upload",
        attempt_id="a",
        runtime_id="runtime",
        desired_generation=1,
        expected_revision=record.revision,
        object=RuntimeTransferObject("object", 1, _DIGEST),
    )
    assert ready is not None
    stream = await _claim_stream(
        store,
        "upload",
        attempt_id="a",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        expected_revision=ready.revision,
        claim_id="stream",
    )
    assert stream is not None
    verifying = await store.begin_verification(
        "upload",
        attempt_id="a",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        claim_id="stream",
        expected_revision=stream.revision,
    )
    assert verifying is not None
    available = await store.publish_available(
        "upload",
        attempt_id="a",
        runtime_id="runtime",
        desired_generation=1,
        accepted_runner_generation=2,
        claim_id="stream",
        expected_revision=verifying.revision,
        actual_size=1,
        actual_sha256=_DIGEST,
    )
    assert available is not None
    claims = await asyncio.gather(
        *(
            store.claim_consumer(
                "upload",
                attempt_id="a",
                expected_revision=available.revision,
                claim_id=value,
            )
            for value in ("one", "two")
        )
    )
    consuming = next(item for item in claims if item is not None)
    assert consuming.consumer_claim_id in {"one", "two"}
    clock.now += timedelta(minutes=2)
    reclaimed = await store.get("upload")
    assert reclaimed is not None and reclaimed.phase.name == "AVAILABLE"
    assert (
        await store.acknowledge_consumer(
            "upload",
            attempt_id="a",
            expected_revision=consuming.revision,
            claim_id=consuming.consumer_claim_id or "",
        )
        is None
    )
    cancelled = await store.request_cancellation(
        "upload",
        attempt_id="a",
        expected_revision=reclaimed.revision,
        reason=RuntimeTransferCancellationReason.CALLER,
    )
    assert cancelled is not None
    assert (
        await store.request_cancellation(
            "upload",
            attempt_id="a",
            expected_revision=cancelled.revision,
            reason=RuntimeTransferCancellationReason.CALLER,
        )
        == cancelled
    )
    assert (
        await store.settle(
            "upload",
            attempt_id="a",
            expected_revision=cancelled.revision,
            outcome=RuntimeTransferOutcome.SUCCEEDED,
            failure=None,
        )
        is None
    )
    terminal = await store.settle(
        "upload",
        attempt_id="a",
        expected_revision=cancelled.revision,
        outcome=RuntimeTransferOutcome.CANCELLED,
        failure=RuntimeTransferFailure.CANCELLED,
    )
    assert terminal is not None
    assert (
        await store.record_cleanup(
            "upload",
            attempt_id="a",
            expected_revision=terminal.revision,
            status=__import__(
                "azents.runtime.transfer.data",
                fromlist=["RuntimeTransferCleanupStatus"],
            ).RuntimeTransferCleanupStatus.PENDING,
            cleanup_failure=None,
        )
        is not None
    )
