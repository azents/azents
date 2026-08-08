"""Runtime Runner transfer manager and filesystem safety tests."""

import asyncio
import dataclasses
import hashlib
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import grpc
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

from azents_runtime_runner.containment import DirectExecutionBackend
from azents_runtime_runner.transfer import RunnerTransferManager


@pytest.fixture
def tmpfs_path(tmp_path: Path) -> Path:
    """Provide an ordinary writable parent filesystem for transfer tests."""
    return tmp_path


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


class _FailingBlockingControl(_Control):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def append_runner_transfer_result(self, result: RunnerTransferResult) -> None:
        del result
        self.entered.set()
        await self.release.wait()
        raise RuntimeError("injected result sink failure")


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
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
    )
    intent = _intent(Path("/tmp/unused"), deadline_at=datetime.now(UTC))

    await asyncio.wait_for(manager.handle_intent(intent), timeout=0.1)
    await asyncio.wait_for(control.entered.wait(), timeout=1)

    assert transfer.download_calls == 0
    control.release.set()
    assert (await _result(control)).failure is RunnerTransferFailure.PROTOCOL_VIOLATION
    await manager.close()


@pytest.mark.asyncio
async def test_invalid_intent_logs_bounded_validation_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Intent rejection identifies the failed check without logging its path."""
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(),
        accepted_generation=lambda: 2,
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
    )
    intent = _intent(Path("/workspace/agent/private-name.txt"))

    await manager.handle_intent(intent)

    assert (await _result(control)).failure is RunnerTransferFailure.PROTOCOL_VIOLATION
    failure = next(
        record
        for record in caplog.records
        if record.getMessage() == "Runtime Runner transfer failed"
    )
    assert failure.__dict__["failure_source"] == "intent_admission"
    assert failure.__dict__["failure_reason"] == "runner_generation_mismatch"
    assert failure.__dict__["grpc_status"] is None
    assert "private-name.txt" not in str(failure.__dict__)
    await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("grpc_detail", ["Transfer is unavailable", "Upload failed"])
async def test_upload_logs_server_grpc_rejection_reason(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    grpc_detail: str,
) -> None:
    """Data-RPC rejection logs the server-owned reason and status."""
    source = tmp_path / "source.bin"
    data = b"upload bytes"
    source.write_bytes(data)

    class _RejectedTransfer(_Transfer):
        async def upload(
            self,
            identity: RunnerTransferIdentity,
            frames: AsyncIterator[RunnerDownloadChunk | RunnerUploadComplete],
            *,
            timeout: float,
        ) -> RunnerUploadResult:
            del identity, frames, timeout
            metadata = grpc.aio.Metadata()
            raise grpc.aio.AioRpcError(
                grpc.StatusCode.FAILED_PRECONDITION,
                metadata,
                metadata,
                grpc_detail,
                None,
            )

    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_RejectedTransfer(),
        accepted_generation=lambda: 1,
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
    )

    await manager.handle_intent(
        _intent(
            source,
            direction=RunnerTransferDirection.UPLOAD,
            data=data,
        )
    )

    assert (await _result(control)).failure is RunnerTransferFailure.PROTOCOL_VIOLATION
    failure = next(
        record
        for record in caplog.records
        if record.getMessage() == "Runtime Runner transfer failed"
    )
    assert failure.__dict__["failure_source"] == "grpc"
    assert failure.__dict__["failure_reason"] == grpc_detail
    assert failure.__dict__["grpc_status"] == "FAILED_PRECONDITION"
    await manager.close()


@pytest.mark.asyncio
async def test_download_rejects_symlink_parent_without_touching_target(
    tmpfs_path: Path,
) -> None:
    """Download traversal never follows a substituted destination parent."""
    outside = tmpfs_path / "outside"
    outside.mkdir()
    link = tmpfs_path / "link"
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
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
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
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
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
async def test_download_atomically_replaces_existing_destination(
    tmpfs_path: Path,
) -> None:
    """Verified content replaces an existing destination without privileged staging."""
    destination = tmpfs_path / "destination.bin"
    destination.write_bytes(b"old")
    data = b"new verified content"
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
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
    )

    await manager.handle_intent(_intent(destination, data=data))

    result = await _result(control)
    assert result.outcome is RunnerTransferOutcome.SUCCEEDED
    assert result.destination_committed is True
    assert destination.read_bytes() == data
    assert not list(tmpfs_path.glob(".azents-transfer-*"))
    await manager.close()


@pytest.mark.asyncio
async def test_untrusted_transfer_identifiers_cannot_escape_staging_directory(
    tmpfs_path: Path,
) -> None:
    """Random staging names ignore untrusted transfer identifiers."""
    destination = tmpfs_path / "destination.bin"
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
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
    )
    intent = _intent(
        destination,
        data=data,
        transfer_id="../../attacker-controlled/path",
    )

    await manager.handle_intent(intent)

    assert (await _result(control)).outcome is RunnerTransferOutcome.SUCCEEDED
    assert destination.read_bytes() == data
    assert not list(tmpfs_path.parent.glob("attacker-controlled"))
    await manager.close()


@pytest.mark.asyncio
async def test_exact_duplicate_intent_reuses_one_completed_result(
    tmpfs_path: Path,
) -> None:
    """An exact repeated instruction cannot publish the destination twice."""
    destination = tmpfs_path / "destination.bin"
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
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
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
    tmpfs_path: Path,
) -> None:
    """Cancellation targets the matching active task and cleans its staging file."""
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

    destination = tmpfs_path / "destination.bin"
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_BlockingTransfer(),
        accepted_generation=lambda: 1,
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
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
    assert not list(tmpfs_path.glob(".azents-transfer-*"))
    release.set()
    await manager.close()


@pytest.mark.asyncio
async def test_conflicting_intent_for_active_identity_is_rejected_without_second_rpc(
    tmpfs_path: Path,
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
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
    )
    intent = _intent(tmpfs_path / "destination.bin", data=data)

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
async def test_successful_upload_leaves_no_mutable_snapshot_path(
    tmpfs_path: Path,
) -> None:
    """A completed upload removes its same-directory snapshot."""
    source = tmpfs_path / "source.bin"
    data = b"upload bytes"
    source.write_bytes(data)
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(),
        accepted_generation=lambda: 1,
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
    )

    await manager.handle_intent(
        _intent(
            source,
            direction=RunnerTransferDirection.UPLOAD,
            data=data,
        )
    )

    assert (await _result(control)).outcome is RunnerTransferOutcome.SUCCEEDED
    assert not list(tmpfs_path.glob(".azents-transfer-*"))
    assert not list(tmpfs_path.glob(".azents-transfer-orphans"))
    await manager.close()


@pytest.mark.asyncio
async def test_upload_rejects_fifo_without_blocking_control(tmpfs_path: Path) -> None:
    """A FIFO source is rejected without synchronously blocking the event loop."""
    fifo = tmpfs_path / "source.fifo"
    os.mkfifo(fifo)
    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(),
        accepted_generation=lambda: 1,
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
    )
    heartbeat_completed = asyncio.Event()

    async def heartbeat() -> None:
        heartbeat_completed.set()

    await manager.handle_intent(
        _intent(
            fifo,
            direction=RunnerTransferDirection.UPLOAD,
            data=b"",
        )
    )
    await asyncio.wait_for(heartbeat(), timeout=0.1)

    result = await _result(control)
    assert heartbeat_completed.is_set()
    assert result.outcome is RunnerTransferOutcome.FAILED
    assert result.failure is RunnerTransferFailure.PROTOCOL_VIOLATION
    await manager.close()


@pytest.mark.asyncio
async def test_download_cleans_same_directory_stage_after_cancellation(
    tmpfs_path: Path,
) -> None:
    """An interrupted download removes its randomly named staging file."""
    started = asyncio.Event()
    release = asyncio.Event()
    data = b"pending"

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

    control = _Control()
    manager = RunnerTransferManager(
        control=control,
        transfer=_BlockingTransfer(),
        accepted_generation=lambda: 1,
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
    )
    intent = _intent(tmpfs_path / "destination.bin", data=data)

    await manager.handle_intent(intent)
    await asyncio.wait_for(started.wait(), timeout=1)

    assert len(list(tmpfs_path.glob(".azents-transfer-*"))) == 1
    await manager.handle_cancel(
        RunnerTransferCancel(
            identity=intent.identity,
            operation_id=intent.operation_id,
            dispatch_id=intent.dispatch_id,
            reason=RunnerTransferCancelReason.CALLER,
        )
    )
    assert (await _result(control)).outcome is RunnerTransferOutcome.CANCELLED
    assert not list(tmpfs_path.glob(".azents-transfer-*"))
    release.set()
    await manager.close()


@pytest.mark.asyncio
async def test_download_fails_closed_when_staging_file_cannot_be_created() -> None:
    """A helper-observed unwritable parent returns a bounded failure."""
    destination = Path("/sys/azents-transfer-test/destination.bin")
    data = b"safe"
    control = _Control()
    transfer = _Transfer(
        (
            RunnerDownloadChunk(offset=0, data=data),
            RunnerDownloadComplete(
                actual_size=len(data), sha256=hashlib.sha256(data).hexdigest()
            ),
        )
    )

    manager = RunnerTransferManager(
        control=control,
        transfer=transfer,
        accepted_generation=lambda: 1,
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
    )

    await manager.handle_intent(_intent(destination, data=data))

    result = await _result(control)
    assert result.outcome is RunnerTransferOutcome.FAILED
    assert result.failure is RunnerTransferFailure.DESTINATION_FAILED
    assert transfer.download_calls == 0
    assert not destination.exists()
    await manager.close()


@pytest.mark.asyncio
async def test_close_does_not_wait_for_blocked_result_sink(tmpfs_path: Path) -> None:
    """Control result backpressure cannot prevent transfer-manager shutdown."""
    data = b"verified"
    control = _BlockingControl()
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
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
    )

    await manager.handle_intent(_intent(tmpfs_path / "destination.bin", data=data))
    await asyncio.wait_for(control.entered.wait(), timeout=1)

    await asyncio.wait_for(manager.close(), timeout=0.1)


@pytest.mark.asyncio
async def test_bounded_result_queue_backpressures_without_dropping_terminal_results(
    tmpfs_path: Path,
) -> None:
    """A full result queue delays admission instead of losing a terminal result."""
    control = _BlockingControl()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(),
        accepted_generation=lambda: 1,
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
        max_tombstones=1,
    )
    expired_at = datetime.now(UTC)
    first = _intent(
        tmpfs_path / "first.bin",
        deadline_at=expired_at,
        transfer_id="transfer-1",
    )
    second = _intent(
        tmpfs_path / "second.bin",
        deadline_at=expired_at,
        transfer_id="transfer-2",
    )
    third = _intent(
        tmpfs_path / "third.bin",
        deadline_at=expired_at,
        transfer_id="transfer-3",
    )

    await manager.handle_intent(first)
    await asyncio.wait_for(control.entered.wait(), timeout=1)
    await manager.handle_intent(second)
    third_admission = asyncio.create_task(manager.handle_intent(third))
    await asyncio.sleep(0)

    assert not third_admission.done()
    control.release.set()
    await asyncio.wait_for(third_admission, timeout=1)
    await asyncio.wait_for(
        _wait_for_result_count(control, expected=3),
        timeout=1,
    )

    assert [result.identity.transfer_id for result in control.results] == [
        "transfer-1",
        "transfer-2",
        "transfer-3",
    ]
    assert all(
        result.failure is RunnerTransferFailure.PROTOCOL_VIOLATION
        for result in control.results
    )
    await manager.close()


async def _wait_for_result_count(control: _Control, *, expected: int) -> None:
    while len(control.results) < expected:
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_failed_result_sink_unblocks_queue_and_shutdown(
    tmpfs_path: Path,
) -> None:
    """A disconnected result sink cannot wedge later admission or close."""
    control = _FailingBlockingControl()
    manager = RunnerTransferManager(
        control=control,
        transfer=_Transfer(),
        accepted_generation=lambda: 1,
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
        max_tombstones=1,
    )
    expired_at = datetime.now(UTC)
    first = _intent(
        tmpfs_path / "first.bin",
        deadline_at=expired_at,
        transfer_id="transfer-1",
    )
    second = _intent(
        tmpfs_path / "second.bin",
        deadline_at=expired_at,
        transfer_id="transfer-2",
    )
    third = _intent(
        tmpfs_path / "third.bin",
        deadline_at=expired_at,
        transfer_id="transfer-3",
    )
    fourth = _intent(
        tmpfs_path / "fourth.bin",
        deadline_at=expired_at,
        transfer_id="transfer-4",
    )

    await manager.handle_intent(first)
    await asyncio.wait_for(control.entered.wait(), timeout=1)
    await manager.handle_intent(second)
    third_admission = asyncio.create_task(manager.handle_intent(third))
    fourth_admission = asyncio.create_task(manager.handle_intent(fourth))
    await asyncio.sleep(0)
    assert not third_admission.done()
    assert not fourth_admission.done()

    control.release.set()
    await asyncio.wait_for(
        asyncio.gather(third_admission, fourth_admission),
        timeout=1,
    )
    await asyncio.wait_for(manager.close(), timeout=0.1)


@pytest.mark.asyncio
async def test_post_publication_cancellation_waits_for_successful_result_enqueue(
    tmpfs_path: Path,
) -> None:
    """A cancellation after publication cannot erase the committed success result."""
    control = _BlockingControl()
    data = b"committed"
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
        execution_backend=DirectExecutionBackend(),
        workspace_path=Path("/tmp"),
        max_tombstones=1,
    )
    expired_at = datetime.now(UTC)
    first = _intent(
        tmpfs_path / "first.bin",
        deadline_at=expired_at,
        transfer_id="transfer-1",
    )
    second = _intent(
        tmpfs_path / "second.bin",
        deadline_at=expired_at,
        transfer_id="transfer-2",
    )
    destination = tmpfs_path / "destination.bin"
    committed = _intent(destination, data=data, transfer_id="transfer-3")

    await manager.handle_intent(first)
    await asyncio.wait_for(control.entered.wait(), timeout=1)
    await manager.handle_intent(second)
    await manager.handle_intent(committed)
    await asyncio.wait_for(_wait_for_path(destination), timeout=1)

    await manager.handle_cancel(
        RunnerTransferCancel(
            identity=committed.identity,
            operation_id=committed.operation_id,
            dispatch_id=committed.dispatch_id,
            reason=RunnerTransferCancelReason.CALLER,
        )
    )
    control.release.set()
    await asyncio.wait_for(
        _wait_for_result_count(control, expected=3),
        timeout=1,
    )

    committed_result = control.results[-1]
    assert destination.read_bytes() == data
    assert committed_result.identity == committed.identity
    assert committed_result.outcome is RunnerTransferOutcome.SUCCEEDED
    assert committed_result.destination_committed is True
    await manager.close()


async def _wait_for_path(path: Path) -> None:
    while not path.exists():
        await asyncio.sleep(0)
