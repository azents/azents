"""Runtime Runner transfer manager and filesystem safety tests."""

import asyncio
import dataclasses
import hashlib
import json
import os
import threading
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from azents_runtime_control.grpc_runner_transfer_client import (
    RunnerDownloadChunk,
    RunnerDownloadComplete,
    RunnerUploadComplete,
    RunnerUploadResult,
)
from azents_runtime_control.runner_transfer import (
    RunnerTransferCancel,
    RunnerTransferCancelReason,
    RunnerTransferDirection,
    RunnerTransferFailure,
    RunnerTransferIdentity,
    RunnerTransferIntent,
    RunnerTransferOutcome,
    RunnerTransferResult,
)
from azents_runtime_control.transfer import (
    RUNNER_TRANSFER_CAPABILITY,
    RUNNER_TRANSFER_PROTOCOL_VERSION,
)

from azents_runtime_runner.transfer import RunnerTransferManager


class _Control:
    def __init__(self) -> None:
        self.results: list[RunnerTransferResult] = []
        self.result_ready = asyncio.Event()

    async def append_runner_transfer_result(self, result: RunnerTransferResult) -> None:
        self.results.append(result)
        self.result_ready.set()


class _BlockingControl(_Control):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def append_runner_transfer_result(self, result: RunnerTransferResult) -> None:
        self.entered.set()
        await self.release.wait()
        await super().append_runner_transfer_result(result)


class _Transfer:
    def __init__(
        self,
        frames: tuple[RunnerDownloadChunk | RunnerDownloadComplete, ...] = (),
    ) -> None:
        self.frames = frames
        self.download_calls = 0
        self.upload_calls = 0

    async def download(
        self,
        identity: RunnerTransferIdentity,
        *,
        timeout: float,
    ) -> AsyncIterator[RunnerDownloadChunk | RunnerDownloadComplete]:
        del identity, timeout
        self.download_calls += 1
        for frame in self.frames:
            yield frame

    async def upload(
        self,
        identity: RunnerTransferIdentity,
        frames: AsyncIterator[RunnerDownloadChunk | RunnerUploadComplete],
        *,
        timeout: float,
    ) -> RunnerUploadResult:
        del identity, timeout
        self.upload_calls += 1
        actual_size = 0
        digest = hashlib.sha256()
        async for frame in frames:
            if isinstance(frame, RunnerDownloadChunk):
                actual_size += len(frame.data)
                digest.update(frame.data)
        return RunnerUploadResult(actual_size=actual_size, sha256=digest.hexdigest())


async def _result(control: _Control) -> RunnerTransferResult:
    await asyncio.wait_for(control.result_ready.wait(), timeout=1)
    assert control.results
    return control.results[-1]


def _intent(
    path: Path,
    *,
    direction: RunnerTransferDirection = RunnerTransferDirection.DOWNLOAD,
    data: bytes = b"transfer bytes",
    deadline_at: datetime | None = None,
    transfer_id: str = "transfer-1",
) -> RunnerTransferIntent:
    return RunnerTransferIntent(
        identity=RunnerTransferIdentity(
            transfer_id=transfer_id,
            attempt_id="attempt-1",
            runtime_id="runtime-1",
            runner_generation=1,
        ),
        direction=direction,
        operation_id="operation-1",
        owner_session_id="session-1",
        runtime_path=str(path),
        overwrite=True,
        expected_size=len(data),
        expected_sha256=(
            hashlib.sha256(data).hexdigest()
            if direction is RunnerTransferDirection.DOWNLOAD
            else None
        ),
        deadline_at=deadline_at or datetime.now(UTC) + timedelta(minutes=1),
        protocol_version=RUNNER_TRANSFER_PROTOCOL_VERSION,
        capability=RUNNER_TRANSFER_CAPABILITY,
        dispatch_id="dispatch-1",
    )


@pytest.mark.asyncio
async def test_invalid_intent_does_not_block_control_receiver() -> None:
    """Admission returns before a blocked metadata result can be delivered."""
    control = _BlockingControl()
    transfer = _Transfer()
    manager = RunnerTransferManager(
        control=control,
        transfer=transfer,
        accepted_generation=lambda: 1,
    )
    intent = _intent(Path("/tmp/unused"), deadline_at=datetime.now(UTC))

    await asyncio.wait_for(manager.handle_intent(intent), timeout=0.1)
    await asyncio.wait_for(control.entered.wait(), timeout=1)

    assert transfer.download_calls == 0
    control.release.set()
    assert (await _result(control)).failure is RunnerTransferFailure.PROTOCOL_VIOLATION
    await manager.close()


@pytest.mark.asyncio
async def test_download_rejects_symlink_parent_without_touching_target(
    tmp_path: Path,
) -> None:
    """Download traversal never follows a substituted destination parent."""
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    data = b"safe"
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(
            (
                RunnerDownloadChunk(offset=0, data=data),
                RunnerDownloadComplete(
                    actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
                ),
            )
        ),
        accepted_generation=lambda: 1,
    )

    await manager.handle_intent(_intent(link / "destination.bin", data=data))

    result = await _result(control)
    assert result.outcome is RunnerTransferOutcome.FAILED
    assert result.failure is RunnerTransferFailure.DESTINATION_FAILED
    assert not (outside / "destination.bin").exists()
    await manager.close()


@pytest.mark.asyncio
async def test_upload_local_io_failure_emits_valid_integrity_result(
    tmp_path: Path,
) -> None:
    """An unreadable upload source cannot suppress a bounded transfer result."""
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(),
        accepted_generation=lambda: 1,
    )

    await manager.handle_intent(
        _intent(
            tmp_path / "missing.bin",
            direction=RunnerTransferDirection.UPLOAD,
        )
    )

    result = await _result(control)
    assert result.outcome is RunnerTransferOutcome.FAILED
    assert result.failure is RunnerTransferFailure.INTEGRITY_FAILED
    assert result.destination_committed is False
    await manager.close()


@pytest.mark.asyncio
async def test_download_reports_success_after_post_publication_directory_fsync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A published verified destination is never reported as uncommitted."""
    destination = tmp_path / "destination.bin"
    destination.write_bytes(b"old")
    data = b"new verified content"
    control = _Control()
    original_fsync = os.fsync
    calls = 0

    def fail_parent_fsync(fd: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected parent fsync failure")
        original_fsync(fd)

    monkeypatch.setattr("azents_runtime_runner.transfer.os.fsync", fail_parent_fsync)
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(
            (
                RunnerDownloadChunk(offset=0, data=data),
                RunnerDownloadComplete(
                    actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
                ),
            )
        ),
        accepted_generation=lambda: 1,
    )

    await manager.handle_intent(_intent(destination, data=data))

    result = await _result(control)
    assert result.outcome is RunnerTransferOutcome.SUCCEEDED
    assert result.destination_committed is True
    assert destination.read_bytes() == data
    await manager.close()


@pytest.mark.asyncio
async def test_untrusted_transfer_identifiers_cannot_escape_staging_directory(
    tmp_path: Path,
) -> None:
    """Attempt-owned staging remains local when identifiers contain separators."""
    destination = tmp_path / "destination.bin"
    data = b"staged safely"
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(
            (
                RunnerDownloadChunk(offset=0, data=data),
                RunnerDownloadComplete(
                    actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
                ),
            )
        ),
        accepted_generation=lambda: 1,
    )
    intent = _intent(
        destination,
        data=data,
        transfer_id="../../attacker-controlled/path",
    )

    await manager.handle_intent(intent)

    assert (await _result(control)).outcome is RunnerTransferOutcome.SUCCEEDED
    assert destination.read_bytes() == data
    assert not list(tmp_path.parent.glob("attacker-controlled"))
    await manager.close()


@pytest.mark.asyncio
async def test_exact_duplicate_intent_reuses_one_completed_result(
    tmp_path: Path,
) -> None:
    """An exact repeated instruction cannot publish the destination twice."""
    destination = tmp_path / "destination.bin"
    data = b"deduplicated"
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(
            (
                RunnerDownloadChunk(offset=0, data=data),
                RunnerDownloadComplete(
                    actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
                ),
            )
        ),
        accepted_generation=lambda: 1,
    )
    intent = _intent(destination, data=data)

    await manager.handle_intent(intent)
    assert (await _result(control)).outcome is RunnerTransferOutcome.SUCCEEDED
    await asyncio.sleep(0.01)
    await manager.handle_intent(intent)
    await asyncio.sleep(0)

    assert len(control.results) == 2
    assert control.results[0] == control.results[1]
    assert destination.read_bytes() == data
    await manager.close()


@pytest.mark.asyncio
async def test_exact_cancel_emits_cancelled_result_without_publication(
    tmp_path: Path,
) -> None:
    """Cancellation targets the matching active task and removes its staging file."""
    data = b"pending"
    started = asyncio.Event()
    release = asyncio.Event()

    class _BlockingTransfer(_Transfer):
        async def download(
            self,
            identity: RunnerTransferIdentity,
            *,
            timeout: float,
        ) -> AsyncIterator[RunnerDownloadChunk | RunnerDownloadComplete]:
            del identity, timeout
            started.set()
            await release.wait()
            yield RunnerDownloadChunk(offset=0, data=data)
            yield RunnerDownloadComplete(
                actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
            )

    destination = tmp_path / "destination.bin"
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_BlockingTransfer(),
        accepted_generation=lambda: 1,
    )
    intent = _intent(destination, data=data)

    await manager.handle_intent(intent)
    await asyncio.wait_for(started.wait(), timeout=1)
    await manager.handle_cancel(
        RunnerTransferCancel(
            identity=intent.identity,
            operation_id=intent.operation_id,
            dispatch_id=intent.dispatch_id,
            reason=RunnerTransferCancelReason.CALLER,
        )
    )

    result = await _result(control)
    assert result.outcome is RunnerTransferOutcome.CANCELLED
    assert result.failure is RunnerTransferFailure.CANCELLED
    assert not destination.exists()
    assert not list(tmp_path.glob(".azents-transfer-*"))
    release.set()
    await manager.close()


@pytest.mark.asyncio
async def test_conflicting_intent_for_active_identity_is_rejected_without_second_rpc(
    tmp_path: Path,
) -> None:
    """One transfer attempt cannot be repurposed with another dispatch identity."""
    data = b"pending"
    started = asyncio.Event()
    release = asyncio.Event()

    class _BlockingTransfer(_Transfer):
        async def download(
            self,
            identity: RunnerTransferIdentity,
            *,
            timeout: float,
        ) -> AsyncIterator[RunnerDownloadChunk | RunnerDownloadComplete]:
            del identity, timeout
            self.download_calls += 1
            started.set()
            await release.wait()
            yield RunnerDownloadChunk(offset=0, data=data)
            yield RunnerDownloadComplete(
                actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
            )

    control = _Control()
    transfer = _BlockingTransfer()
    manager = RunnerTransferManager(
        control=control,
        transfer=transfer,
        accepted_generation=lambda: 1,
    )
    intent = _intent(tmp_path / "destination.bin", data=data)

    await manager.handle_intent(intent)
    await asyncio.wait_for(started.wait(), timeout=1)
    await manager.handle_intent(dataclasses.replace(intent, dispatch_id="dispatch-2"))

    result = await _result(control)
    assert result.failure is RunnerTransferFailure.PROTOCOL_VIOLATION
    assert transfer.download_calls == 1
    release.set()
    await manager.handle_cancel(
        RunnerTransferCancel(
            identity=intent.identity,
            operation_id=intent.operation_id,
            dispatch_id=intent.dispatch_id,
            reason=RunnerTransferCancelReason.CALLER,
        )
    )
    await manager.close()


@pytest.mark.asyncio
async def test_upload_snapshot_keeps_control_work_and_cancellation_responsive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slow snapshot I/O yields the event loop for Control work and cancellation."""
    source = tmp_path / "source.bin"
    source.write_bytes(b"x" * (2 * 1024 * 1024))
    entered_read = threading.Event()
    release_read = threading.Event()
    original_read = os.read

    def block_first_read(fd: int, size: int) -> bytes:
        if not entered_read.is_set():
            entered_read.set()
            release_read.wait(timeout=1)
        return original_read(fd, size)

    monkeypatch.setattr("azents_runtime_runner.transfer.os.read", block_first_read)
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(),
        accepted_generation=lambda: 1,
    )
    intent = _intent(
        source,
        direction=RunnerTransferDirection.UPLOAD,
        data=b"x" * (2 * 1024 * 1024),
    )

    await manager.handle_intent(intent)
    assert await asyncio.to_thread(entered_read.wait, 1)
    heartbeat_completed = asyncio.Event()
    ordinary_control_completed = asyncio.Event()

    async def heartbeat() -> None:
        heartbeat_completed.set()

    async def ordinary_control_operation() -> None:
        ordinary_control_completed.set()

    await asyncio.wait_for(
        asyncio.gather(
            heartbeat(),
            ordinary_control_operation(),
            manager.handle_cancel(
                RunnerTransferCancel(
                    identity=intent.identity,
                    operation_id=intent.operation_id,
                    dispatch_id=intent.dispatch_id,
                    reason=RunnerTransferCancelReason.CALLER,
                )
            ),
        ),
        timeout=0.1,
    )
    assert heartbeat_completed.is_set()
    assert ordinary_control_completed.is_set()
    release_read.set()

    result = await _result(control)
    assert result.outcome is RunnerTransferOutcome.CANCELLED
    assert not list(tmp_path.glob(".azents-transfer-*"))
    await manager.close()


def _orphan_name(index: int) -> str:
    return f".azents-transfer-download-{index:032x}-{index + 1:032x}"


def _write_orphan_journal(
    root: Path,
    parent: Path,
    name: str,
    *,
    device: int,
    inode: int,
    created_at: datetime,
) -> None:
    journal = root / ".azents-transfer-orphans"
    journal.mkdir(mode=0o700, exist_ok=True)
    (journal / f"{name}.json").write_text(
        json.dumps(
            {
                "parent": str(parent),
                "name": name,
                "device": device,
                "inode": inode,
                "created_at": created_at.isoformat(),
            },
            separators=(",", ":"),
        )
    )


@pytest.mark.asyncio
async def test_startup_orphan_reclaim_removes_only_verified_expired_file(
    tmp_path: Path,
) -> None:
    """Startup reclaim removes one expired inode-bound regular staging file."""
    parent = tmp_path / "target"
    parent.mkdir()
    name = _orphan_name(1)
    candidate = parent / name
    candidate.write_bytes(b"orphan")
    identity = candidate.stat()
    _write_orphan_journal(
        tmp_path,
        parent,
        name,
        device=identity.st_dev,
        inode=identity.st_ino,
        created_at=datetime.now(UTC) - timedelta(hours=1, seconds=1),
    )
    manager = RunnerTransferManager(
        control=_Control(),
        transfer=_Transfer(),
        accepted_generation=lambda: 1,
        orphan_root=str(tmp_path),
    )

    await manager.start()

    assert not candidate.exists()
    assert not list((tmp_path / ".azents-transfer-orphans").iterdir())
    await manager.close()


@pytest.mark.asyncio
async def test_orphan_reclaim_preserves_forged_symlink_and_fresh_records(
    tmp_path: Path,
) -> None:
    """Hostile journal input never follows a symlink or reclaims before one hour."""
    parent = tmp_path / "target"
    parent.mkdir()
    target = tmp_path / "outside.bin"
    target.write_bytes(b"outside")
    symlink_name = _orphan_name(2)
    symlink = parent / symlink_name
    symlink.symlink_to(target)
    target_identity = target.stat()
    _write_orphan_journal(
        tmp_path,
        parent,
        symlink_name,
        device=target_identity.st_dev,
        inode=target_identity.st_ino,
        created_at=datetime.now(UTC) - timedelta(hours=1, seconds=1),
    )
    fresh_name = _orphan_name(3)
    fresh = parent / fresh_name
    fresh.write_bytes(b"fresh")
    fresh_identity = fresh.stat()
    _write_orphan_journal(
        tmp_path,
        parent,
        fresh_name,
        device=fresh_identity.st_dev,
        inode=fresh_identity.st_ino,
        created_at=datetime.now(UTC) - timedelta(minutes=59),
    )
    manager = RunnerTransferManager(
        control=_Control(),
        transfer=_Transfer(),
        accepted_generation=lambda: 1,
        orphan_root=str(tmp_path),
    )

    reclaimed = await manager.reclaim_orphans()

    assert reclaimed == 0
    assert symlink.is_symlink()
    assert target.read_bytes() == b"outside"
    assert fresh.read_bytes() == b"fresh"
    await manager.close()


@pytest.mark.asyncio
async def test_background_orphan_reclaim_is_bounded_and_eventually_reclaims(
    tmp_path: Path,
) -> None:
    """The background worker scans bounded pages and reclaims later records."""
    parent = tmp_path / "target"
    parent.mkdir()
    for index in range(101):
        name = _orphan_name(index + 10)
        candidate = parent / name
        candidate.write_bytes(b"orphan")
        identity = candidate.stat()
        _write_orphan_journal(
            tmp_path,
            parent,
            name,
            device=identity.st_dev,
            inode=identity.st_ino,
            created_at=datetime.now(UTC) - timedelta(hours=1, seconds=1),
        )
    manager = RunnerTransferManager(
        control=_Control(),
        transfer=_Transfer(),
        accepted_generation=lambda: 1,
        orphan_root=str(tmp_path),
        orphan_reclaim_interval_seconds=0.01,
    )

    await manager.reclaim_orphans()

    assert len(list(parent.iterdir())) == 1
    await manager.start()
    await asyncio.sleep(0.05)

    assert list(parent.iterdir()) == []
    await manager.close()
