"""Forced process cleanup boundary diagnostics and cancellation."""

import asyncio
from pathlib import Path

import pytest
from azents_runtime_control.runner import RunnerOperationEvent

from azents_runtime_runner.execution import (
    DirectExecutionBackend,
    ProcessTerminationResult,
)
from azents_runtime_runner.main import StructuredLogFormatter
from azents_runtime_runner.operations import (
    RunnerOperations,
    _ManagedProcess,
    _ProcessOutputBuffer,
)
from azents_runtime_runner.workspace import Workspace


class _Sink:
    async def append_runner_event(self, event: RunnerOperationEvent) -> None:
        del event


class _CleanupProcess:
    def __init__(self, failure: Exception | None, release: asyncio.Event) -> None:
        self.failure = failure
        self.release = release
        self.started = asyncio.Event()
        self.finished = asyncio.Event()
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.returncode: int | None = None

    async def wait(self) -> int:
        await self.finished.wait()
        return 0

    async def write_stdin(self, data: bytes) -> None:
        del data

    async def terminate_descendants(
        self,
        *,
        terminate_timeout_seconds: float,
        kill_timeout_seconds: float,
    ) -> ProcessTerminationResult:
        del terminate_timeout_seconds, kill_timeout_seconds
        self.started.set()
        try:
            await self.release.wait()
            if self.failure is not None:
                raise self.failure from ValueError("CLEANUP_PRIVATE_CAUSE")
            self.returncode = 0
            return ProcessTerminationResult(
                already_exited=False, escalated=True, timed_out=False
            )
        finally:
            self.finished.set()


def _record(process: _CleanupProcess, process_id: str) -> _ManagedProcess:
    return _ManagedProcess(
        process_id=process_id,
        generation=7,
        owner_session_id="session-fixture",
        process=process,
        stdout=_ProcessOutputBuffer(max_unread_bytes=1),
        stderr=_ProcessOutputBuffer(max_unread_bytes=1),
        created_at=1,
        last_accessed_at=1,
        fire_and_forget=False,
    )


@pytest.mark.parametrize("failure_type", [PermissionError, RuntimeError])
async def test_forced_cleanup_logs_failure_once_and_finishes_other_records(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    failure_type: type[Exception],
) -> None:
    release = asyncio.Event()
    release.set()
    denied = _CleanupProcess(failure_type("CLEANUP_PRIVATE_VALUE"), release)
    healthy = _CleanupProcess(None, release)
    operations = RunnerOperations(
        browser_manager=None,
        client=_Sink(),
        workspace=Workspace(str(tmp_path)),
        execution_backend=DirectExecutionBackend(),
    )
    try:
        await operations._force_terminate_processes(
            (_record(denied, "denied"), _record(healthy, "healthy"))
        )
    finally:
        await operations.close()
    assert healthy.finished.is_set()
    assert healthy.returncode == 0
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.getMessage() == "Runtime Runner forced process cleanup failed"
    assert record.__dict__["process_id"] == "denied"
    assert record.__dict__["runner_generation"] == 7
    assert record.__dict__["owner_session_id"] == "session-fixture"
    assert record.__dict__["error_type"] == failure_type.__name__
    assert any(
        frame["function"] == "terminate_descendants"
        for frame in record.__dict__["error_frames"]
    )
    assert record.exc_info is not None
    assert record.exc_info[2] is None
    rendered = StructuredLogFormatter().format(record)
    assert "runner_operation_failed" in rendered
    assert "CLEANUP_PRIVATE_VALUE" not in rendered
    assert "CLEANUP_PRIVATE_CAUSE" not in rendered
    assert "raise self.failure" not in rendered


async def test_forced_cleanup_owner_cancellation_drains_children_without_error_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    release = asyncio.Event()
    processes = (_CleanupProcess(None, release), _CleanupProcess(None, release))
    operations = RunnerOperations(
        browser_manager=None,
        client=_Sink(),
        workspace=Workspace(str(tmp_path)),
        execution_backend=DirectExecutionBackend(),
    )
    cleanup = asyncio.create_task(
        operations._force_terminate_processes(
            tuple(
                _record(process, str(index)) for index, process in enumerate(processes)
            )
        )
    )
    try:
        async with asyncio.timeout(5):
            await asyncio.gather(*(process.started.wait() for process in processes))
            cleanup.cancel()
            with pytest.raises(asyncio.CancelledError):
                await cleanup
        assert all(process.finished.is_set() for process in processes)
        assert not caplog.records
    finally:
        cleanup.cancel()
        await asyncio.gather(cleanup, return_exceptions=True)
        await operations.close()
