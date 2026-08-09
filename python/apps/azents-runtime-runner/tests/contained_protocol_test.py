"""Contained helper framed protocol and client tests."""

import asyncio
import hashlib
import io
import subprocess
import sys
from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from azents_runtime_runner.contained_async_protocol import read_async_frame
from azents_runtime_runner.contained_client import (
    ContainedHelperSession,
    ContainedOperationClient,
    ContainedOperationEvent,
)
from azents_runtime_runner.contained_protocol import (
    ContainedProtocolError,
    FrameKind,
    encode_binary_frame,
    encode_control_frame,
    read_sync_frame,
)
from azents_runtime_runner.containment import (
    DirectExecutionBackend,
    ExecutionProcess,
    ExecutionSpec,
    ProcessTerminationResult,
)


class _FakeProcess:
    def __init__(self, *, terminal: bytes | None) -> None:
        self._stdout = asyncio.StreamReader()
        self._stderr = asyncio.StreamReader()
        self._returncode: int | None = None
        self._waited = asyncio.Event()
        self.writes: list[bytes] = []
        self.terminated = False
        if terminal is not None:
            self._stdout.feed_data(terminal)
            self._stdout.feed_eof()
            self._stderr.feed_eof()
            self._returncode = 0
            self._waited.set()

    @property
    def stdout(self) -> asyncio.StreamReader:
        return self._stdout

    @property
    def stderr(self) -> asyncio.StreamReader:
        return self._stderr

    @property
    def returncode(self) -> int | None:
        return self._returncode

    async def wait(self) -> int:
        await self._waited.wait()
        assert self._returncode is not None
        return self._returncode

    async def write_stdin(self, data: bytes) -> None:
        self.writes.append(data)

    async def terminate_descendants(
        self,
        *,
        terminate_timeout_seconds: float,
        kill_timeout_seconds: float,
    ) -> ProcessTerminationResult:
        del terminate_timeout_seconds, kill_timeout_seconds
        self.terminated = True
        self._returncode = -15
        self._stdout.feed_eof()
        self._stderr.feed_eof()
        self._waited.set()
        return ProcessTerminationResult(
            already_exited=False,
            escalated=False,
            timed_out=False,
        )


class _FakeBackend:
    def __init__(self, processes: list[_FakeProcess]) -> None:
        self._processes = processes
        self.started = asyncio.Event()
        self.start_count = 0
        self.specs: list[ExecutionSpec] = []

    @property
    def kind(self) -> str:
        return "fake"

    @property
    def helper_python_path(self) -> str:
        return "/fake/python"

    def agent_environment(
        self,
        *,
        workspace_path: str,
        operation_environment: Mapping[str, str],
    ) -> Mapping[str, str]:
        del workspace_path
        return dict(operation_environment)

    async def qualify(self) -> None:
        return

    async def start(self, spec: ExecutionSpec) -> ExecutionProcess:
        self.specs.append(spec)
        process = self._processes.pop(0)
        self.start_count += 1
        self.started.set()
        return process

    async def close(self) -> None:
        return


def test_sync_protocol_round_trips_control_and_binary_frames() -> None:
    reader = io.BytesIO(
        encode_control_frame({"kind": "request", "value": 3})
        + encode_binary_frame(b"binary")
    )

    control = read_sync_frame(reader)
    binary = read_sync_frame(reader)

    assert control.kind is FrameKind.CONTROL
    assert control.control == {"kind": "request", "value": 3}
    assert binary.kind is FrameKind.BINARY
    assert binary.binary == b"binary"


def test_common_helper_import_excludes_async_and_specialized_modules() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import azents_runtime_runner.contained_helper; "
                "unexpected = sorted("
                "set(sys.modules) & "
                "{'asyncio', "
                "'azents_runtime_runner.contained_async_protocol', "
                "'azents_runtime_runner.contained_apply_patch', "
                "'azents_runtime_runner.contained_git', "
                "'azents_runtime_runner.contained_transfer'}"
                "); "
                "print('\\n'.join(unexpected)); "
                "raise SystemExit(bool(unexpected))"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    ("operation", "helper_module"),
    [
        ("file.list", "azents_runtime_runner.contained_helper"),
        ("list_git_refs", "azents_runtime_runner.contained_git_helper"),
        ("file.apply_patch", "azents_runtime_runner.contained_apply_patch_helper"),
        ("transfer.upload", "azents_runtime_runner.contained_transfer_helper"),
        ("transfer.download", "azents_runtime_runner.contained_transfer_helper"),
    ],
)
async def test_client_selects_operation_specific_helper_entrypoint(
    tmp_path: Path,
    operation: str,
    helper_module: str,
) -> None:
    process = _FakeProcess(terminal=None)
    backend = _FakeBackend([process])

    session = await ContainedHelperSession.start(
        backend=backend,
        workspace_path=tmp_path,
        operation=operation,
        metadata={"body_count": 0},
    )
    await session.terminate()

    assert backend.specs[0].argv == ("/fake/python", "-m", helper_module)


@pytest.mark.asyncio
async def test_async_protocol_rejects_truncated_frame() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(encode_control_frame({"kind": "request"})[:-1])
    reader.feed_eof()

    with pytest.raises(ContainedProtocolError, match="ended unexpectedly"):
        await read_async_frame(reader)


@pytest.mark.asyncio
async def test_direct_backend_runs_bundled_helper_ping(tmp_path: Path) -> None:
    session = await ContainedHelperSession.start(
        backend=DirectExecutionBackend(),
        workspace_path=tmp_path,
        operation="ping",
        metadata={"value": "ok"},
    )

    frame = await session.receive()
    diagnostic = await session.finish()

    assert frame.control == {
        "kind": "event",
        "event_type": "final_success",
        "payload": {"metadata": {"value": "ok"}},
        "binary_follows": False,
        "final": True,
    }
    assert diagnostic.text == ""
    assert diagnostic.truncated is False


@pytest.mark.asyncio
async def test_direct_backend_runs_git_helper_entrypoint(tmp_path: Path) -> None:
    events: list[ContainedOperationEvent] = []
    client = ContainedOperationClient(
        backend=DirectExecutionBackend(),
        workspace_path=tmp_path,
    )

    async def handle_event(event: ContainedOperationEvent) -> None:
        events.append(event)

    await client.run(
        operation="discover_managed_git_worktrees",
        payload={},
        body_chunks=(),
        deadline_at=None,
        event_handler=handle_event,
    )

    assert events == [
        ContainedOperationEvent(
            event_type="final_success",
            payload={"discovered_worktrees": []},
            binary=None,
            final=True,
        )
    ]


@pytest.mark.asyncio
async def test_direct_backend_runs_apply_patch_helper_entrypoint(
    tmp_path: Path,
) -> None:
    events: list[ContainedOperationEvent] = []
    client = ContainedOperationClient(
        backend=DirectExecutionBackend(),
        workspace_path=tmp_path,
    )
    patch = (
        b"*** Begin Patch\n*** Add File: added.txt\n+helper boundary\n*** End Patch\n"
    )

    async def handle_event(event: ContainedOperationEvent) -> None:
        events.append(event)

    await client.run(
        operation="file.apply_patch",
        payload={
            "base_path": str(tmp_path),
            "total_bytes": len(patch),
            "schema_version": 1,
        },
        body_chunks=(patch,),
        deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        event_handler=handle_event,
    )

    assert events[-1].event_type == "final_success"
    assert (tmp_path / "added.txt").read_text() == "helper boundary\n"


@pytest.mark.asyncio
async def test_direct_backend_runs_transfer_upload_helper_entrypoint(
    tmp_path: Path,
) -> None:
    events: list[ContainedOperationEvent] = []
    client = ContainedOperationClient(
        backend=DirectExecutionBackend(),
        workspace_path=tmp_path,
    )
    data = b"upload through specialized helper"
    source = tmp_path / "source.bin"
    source.write_bytes(data)

    async def handle_event(event: ContainedOperationEvent) -> None:
        events.append(event)

    await client.run(
        operation="transfer.upload",
        payload={
            "runtime_path": str(source),
            "expected_size": len(data),
            "expected_sha256": hashlib.sha256(data).hexdigest(),
        },
        body_chunks=(),
        deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        event_handler=handle_event,
    )

    assert b"".join(event.binary or b"" for event in events) == data
    assert events[-1].event_type == "final_success"


@pytest.mark.asyncio
async def test_direct_backend_runs_transfer_download_helper_entrypoint(
    tmp_path: Path,
) -> None:
    events: list[ContainedOperationEvent] = []
    client = ContainedOperationClient(
        backend=DirectExecutionBackend(),
        workspace_path=tmp_path,
    )
    data = b"download through specialized helper"
    digest = hashlib.sha256(data).hexdigest()
    destination = tmp_path / "destination.bin"

    async def input_chunks() -> AsyncIterator[bytes]:
        yield data

    async def handle_event(event: ContainedOperationEvent) -> None:
        events.append(event)

    await client.run_streaming_input(
        operation="transfer.download",
        payload={
            "runtime_path": str(destination),
            "expected_size": len(data),
            "expected_sha256": digest,
            "overwrite": False,
        },
        input_chunks=input_chunks(),
        completion_factory=lambda: {
            "actual_size": len(data),
            "sha256": digest,
        },
        deadline_at=datetime.now(UTC) + timedelta(seconds=5),
        event_handler=handle_event,
    )

    assert destination.read_bytes() == data
    assert events[-1].event_type == "final_success"


@pytest.mark.asyncio
async def test_cancelled_operation_sends_cancel_and_terminates_helper(
    tmp_path: Path,
) -> None:
    process = _FakeProcess(terminal=None)
    backend = _FakeBackend([process])
    client = ContainedOperationClient(
        backend=backend,
        workspace_path=tmp_path,
    )

    async def handle_event(event: ContainedOperationEvent) -> None:
        del event

    task = asyncio.create_task(
        client.run(
            operation="file.list",
            payload={"path": str(tmp_path)},
            body_chunks=(),
            deadline_at=None,
            event_handler=handle_event,
        )
    )
    await asyncio.wait_for(backend.started.wait(), timeout=1)
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert process.terminated is True
    assert backend.specs[0].argv[0] == "/fake/python"
    assert len(process.writes) == 2
    cancel = read_sync_frame(io.BytesIO(process.writes[1]))
    assert cancel.control == {"kind": "cancel"}


@pytest.mark.asyncio
async def test_blocked_helper_does_not_block_unrelated_operation(
    tmp_path: Path,
) -> None:
    blocked = _FakeProcess(terminal=None)
    completed = _FakeProcess(
        terminal=encode_control_frame(
            {
                "kind": "event",
                "event_type": "final_success",
                "payload": {"entries": []},
                "binary_follows": False,
                "final": True,
            }
        )
    )
    backend = _FakeBackend([blocked, completed])
    client = ContainedOperationClient(
        backend=backend,
        workspace_path=tmp_path,
    )

    async def handle_event(event: ContainedOperationEvent) -> None:
        del event

    first = asyncio.create_task(
        client.run(
            operation="file.list",
            payload={"path": str(tmp_path)},
            body_chunks=(),
            deadline_at=None,
            event_handler=handle_event,
        )
    )
    await asyncio.wait_for(backend.started.wait(), timeout=1)
    second = asyncio.create_task(
        client.run(
            operation="file.list",
            payload={"path": str(tmp_path)},
            body_chunks=(),
            deadline_at=None,
            event_handler=handle_event,
        )
    )

    await asyncio.wait_for(second, timeout=1)
    assert first.done() is False
    assert backend.start_count == 2

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
