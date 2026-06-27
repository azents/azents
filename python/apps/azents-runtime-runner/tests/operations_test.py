"""Runner operation handler tests."""

from pathlib import Path

import pytest
from azents_runtime_control.runner import (
    JsonValue,
    RunnerBodyChunk,
    RunnerOperationEnvelope,
    RunnerOperationEvent,
    RuntimeRunnerEventType,
)

from azents_runtime_runner.operations import RunnerOperations
from azents_runtime_runner.workspace import Workspace


class _FakeClient:
    def __init__(self) -> None:
        self.events: list[RunnerOperationEvent] = []

    async def append_runner_event(self, event: RunnerOperationEvent) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_bash_operation_emits_stdout_and_final_success(tmp_path: Path) -> None:
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="bash",
            payload={"command": "printf hello"},
        )
    )

    assert [event.event_type for event in client.events] == [
        RuntimeRunnerEventType.ACCEPTED,
        RuntimeRunnerEventType.STDOUT,
        RuntimeRunnerEventType.FINAL_SUCCESS,
    ]
    assert client.events[1].payload == {"text": "hello"}
    assert client.events[-1].payload == {"exit_code": 0}


@pytest.mark.asyncio
async def test_file_write_read_and_list_stay_in_workspace(tmp_path: Path) -> None:
    client = _FakeClient()
    workspace = Workspace(str(tmp_path))
    operations = RunnerOperations(client=client, workspace=workspace)

    await operations.handle(
        _operation(
            operation_type="file.write",
            payload={"path": "nested/report.txt"},
            body_chunks=(RunnerBodyChunk(chunk_id=1, data=b"hello", final=True),),
        )
    )
    await operations.handle(
        _operation(
            operation_type="file.read",
            payload={"path": "nested/report.txt"},
        )
    )
    await operations.handle(
        _operation(
            operation_type="file.list",
            payload={"path": "nested"},
        )
    )

    final_payloads = [
        event.payload
        for event in client.events
        if event.event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    ]
    assert final_payloads[0] == {"bytes_written": 5}
    assert final_payloads[1] == {"bytes_read": 5}
    assert final_payloads[2] == {
        "entries": [
            {
                "path": f"{tmp_path}/nested/report.txt",
                "type": "file",
                "size_bytes": 5,
            }
        ]
    }


@pytest.mark.asyncio
async def test_file_list_supports_file_path(tmp_path: Path) -> None:
    file_path = tmp_path / "nested" / "report.txt"
    file_path.parent.mkdir()
    file_path.write_text("hello")
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.list",
            payload={"path": str(file_path)},
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    assert client.events[-1].payload == {
        "entries": [
            {
                "path": f"{tmp_path}/nested/report.txt",
                "type": "file",
                "size_bytes": 5,
            }
        ]
    }


@pytest.mark.asyncio
async def test_file_list_recursive_with_excludes(tmp_path: Path) -> None:
    (tmp_path / "src" / "nested").mkdir(parents=True)
    (tmp_path / "src" / "nested" / "report.txt").write_text("hello")
    (tmp_path / "src" / "app.txt").write_text("hello")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("hello")
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.list",
            payload={
                "path": str(tmp_path),
                "recursive": True,
                "exclude_patterns": ["node_modules"],
            },
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    raw_entries = client.events[-1].payload.get("entries")
    assert isinstance(raw_entries, list)
    paths = []
    for entry in raw_entries:
        assert isinstance(entry, dict)
        path = entry.get("path")
        assert isinstance(path, str)
        paths.append(path)
    assert f"{tmp_path}/src" in paths
    assert f"{tmp_path}/src/app.txt" in paths
    assert f"{tmp_path}/src/nested/report.txt" in paths
    assert all("node_modules" not in path for path in paths)


@pytest.mark.asyncio
async def test_file_stat_reports_regular_file(tmp_path: Path) -> None:
    file_path = tmp_path / "AGENTS.md"
    file_path.write_text("hello")
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.stat",
            payload={"path": str(file_path)},
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    assert client.events[-1].payload == {
        "path": str(file_path),
        "kind": "file",
        "size_bytes": 5,
        "symlink": False,
    }


@pytest.mark.asyncio
async def test_file_stat_reports_symlink_without_following_it(tmp_path: Path) -> None:
    target_path = tmp_path / "target.txt"
    target_path.write_text("hello")
    link_path = tmp_path / "link.txt"
    link_path.symlink_to(target_path)
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.stat",
            payload={"path": str(link_path)},
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    assert client.events[-1].payload == {
        "path": str(link_path),
        "kind": "symlink",
        "size_bytes": None,
        "symlink": True,
        "real_path": str(target_path),
        "resolved_kind": "file",
    }


@pytest.mark.asyncio
async def test_file_stat_missing_path_returns_final_error(tmp_path: Path) -> None:
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.stat",
            payload={"path": str(tmp_path / "missing.txt")},
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_ERROR
    assert client.events[-1].payload["error_code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_file_grep_searches_workspace_files(tmp_path: Path) -> None:
    (tmp_path / "src" / "nested").mkdir(parents=True)
    (tmp_path / "src" / "nested" / "report.txt").write_text("needle\nskip\nneedle")
    (tmp_path / "src" / "app.txt").write_text("needle")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("needle")
    (tmp_path / "bin.dat").write_bytes(b"\xff\xfe\x00\x01")
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.grep",
            payload={
                "path": str(tmp_path),
                "pattern": "needle",
                "recursive": True,
                "exclude_patterns": ["node_modules"],
                "max_lines_per_file": 1,
            },
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    payload = client.events[-1].payload
    assert payload["searched_file_count"] == 3
    assert payload["matched_file_count"] == 2
    raw_files = payload.get("files")
    assert isinstance(raw_files, list)
    paths = []
    for raw_file in raw_files:
        assert isinstance(raw_file, dict)
        path = raw_file.get("path")
        assert isinstance(path, str)
        paths.append(path)
    assert f"{tmp_path}/src/app.txt" in paths
    assert f"{tmp_path}/src/nested/report.txt" in paths
    assert all("node_modules" not in path for path in paths)


@pytest.mark.asyncio
async def test_file_grep_invalid_regex_returns_final_error(tmp_path: Path) -> None:
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.grep",
            payload={"path": str(tmp_path), "pattern": "["},
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_ERROR
    assert client.events[-1].payload["error_code"] == "INVALID_REGEX"


@pytest.mark.asyncio
async def test_relative_paths_stay_under_workspace(tmp_path: Path) -> None:
    (tmp_path / "inside.txt").write_text("hello")
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.read",
            payload={"path": "inside.txt"},
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS


@pytest.mark.asyncio
async def test_absolute_paths_outside_workspace_are_allowed(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("hello")
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.read",
            payload={"path": str(outside)},
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS


@pytest.mark.asyncio
async def test_file_grep_skips_symlink_escape(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("needle")
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").symlink_to("/usr/local/bin/python3.14")
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.grep",
            payload={
                "path": str(tmp_path),
                "pattern": "needle",
                "recursive": True,
                "exclude_patterns": [],
            },
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    payload = client.events[-1].payload
    assert payload["searched_file_count"] == 1
    raw_files = payload.get("files")
    assert isinstance(raw_files, list)
    assert len(raw_files) == 1
    raw_file = raw_files[0]
    assert isinstance(raw_file, dict)
    assert raw_file["path"] == f"{tmp_path}/src/app.py"


@pytest.mark.asyncio
async def test_file_grep_stops_at_searched_file_limit(tmp_path: Path) -> None:
    """file.grep stops at the searched file limit."""
    for index in range(3):
        (tmp_path / f"file-{index}.txt").write_text("nothing")
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.grep",
            payload={
                "path": str(tmp_path),
                "pattern": "needle",
                "recursive": True,
                "max_searched_files": 2,
            },
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    payload = client.events[-1].payload
    assert payload["searched_file_count"] == 2
    assert payload["truncated"] is True
    assert payload["stopped_reason"] == "searched_file_limit"


@pytest.mark.asyncio
async def test_file_grep_stops_at_scanned_byte_limit(tmp_path: Path) -> None:
    """file.grep stops at the scanned byte limit."""
    (tmp_path / "large.txt").write_text("a" * 20)
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.grep",
            payload={
                "path": str(tmp_path),
                "pattern": "needle",
                "recursive": True,
                "max_scanned_bytes": 10,
            },
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    payload = client.events[-1].payload
    assert payload["searched_file_count"] == 1
    assert payload["truncated"] is True
    assert payload["stopped_reason"] == "scanned_byte_limit"


@pytest.mark.asyncio
async def test_process_start_quick_command_returns_exit_snapshot(
    tmp_path: Path,
) -> None:
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="process.start",
            payload={"command": "printf hello", "yield_time_ms": 1000},
        )
    )

    assert [event.event_type for event in client.events] == [
        RuntimeRunnerEventType.ACCEPTED,
        RuntimeRunnerEventType.PROCESS_OUTPUT,
        RuntimeRunnerEventType.FINAL_SUCCESS,
    ]
    assert client.events[1].payload["stream"] == "stdout"
    assert client.events[1].payload["text"] == "hello"
    final = client.events[-1].payload
    assert final["status"] == "exited"
    assert final["exit_code"] == 0
    assert final["stdout"] == "hello"
    assert final["stderr"] == ""


@pytest.mark.asyncio
async def test_process_write_empty_stdin_polls_running_process(tmp_path: Path) -> None:
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="process.start",
            payload={
                "command": (
                    "python -c 'import sys, time; "
                    'print("ready", flush=True); '
                    "line=sys.stdin.readline().strip(); "
                    'print(f"echo:{line}", flush=True)\''
                ),
                "yield_time_ms": 100,
            },
        )
    )
    start_final = client.events[-1].payload
    process_id = start_final["process_id"]
    assert isinstance(process_id, str)
    assert start_final["status"] == "running"
    assert start_final["stdout"] == "ready\n"

    await operations.handle(
        _operation(
            operation_type="process.write",
            payload={
                "process_id": process_id,
                "stdin": "world\n",
                "yield_time_ms": 1000,
            },
        )
    )

    write_final = client.events[-1].payload
    assert write_final["process_id"] == process_id
    assert write_final["status"] == "exited"
    assert write_final["exit_code"] == 0
    assert write_final["stdout"] == "echo:world\n"

    await operations.handle(
        _operation(
            operation_type="process.write",
            payload={"process_id": process_id, "stdin": "", "yield_time_ms": 0},
        )
    )

    missing_final = client.events[-1].payload
    assert missing_final["process_id"] == process_id
    assert missing_final["status"] == "missing"
    assert missing_final["missing_reason"] == "consumed"


@pytest.mark.asyncio
async def test_process_output_is_bounded_and_reports_truncation(tmp_path: Path) -> None:
    client = _FakeClient()
    operations = RunnerOperations(
        client=client,
        workspace=Workspace(str(tmp_path)),
        process_max_unread_bytes=10,
    )

    await operations.handle(
        _operation(
            operation_type="process.start",
            payload={
                "command": 'python -c \'print("0123456789abcdef", end="")\'',
                "yield_time_ms": 1000,
                "max_output_bytes": 4,
            },
        )
    )

    final = client.events[-1].payload
    assert final["status"] == "exited"
    assert final["stdout"] == "cdef"
    assert final["stdout_truncated"] is True
    assert final["stdout_omitted_bytes"] == 12


@pytest.mark.asyncio
async def test_process_quota_prunes_oldest_process(tmp_path: Path) -> None:
    client = _FakeClient()
    operations = RunnerOperations(
        client=client,
        workspace=Workspace(str(tmp_path)),
        max_process_count=1,
    )

    await operations.handle(
        _operation(
            operation_type="process.start",
            payload={"command": "sleep 10", "yield_time_ms": 0},
        )
    )
    process_id = client.events[-1].payload["process_id"]
    assert isinstance(process_id, str)

    await operations.handle(
        _operation(
            operation_type="process.start",
            payload={"command": "printf second", "yield_time_ms": 1000},
        )
    )
    await operations.handle(
        _operation(
            operation_type="process.write",
            payload={"process_id": process_id, "stdin": "", "yield_time_ms": 0},
        )
    )

    final = client.events[-1].payload
    assert final["process_id"] == process_id
    assert final["status"] == "terminated"
    assert final["missing_reason"] == "quota_pruned"


def _operation(
    *,
    operation_type: str,
    payload: dict[str, JsonValue],
    body_chunks: tuple[RunnerBodyChunk, ...] = (),
) -> RunnerOperationEnvelope:
    return RunnerOperationEnvelope(
        request_id="request-1",
        runtime_id="runtime-1",
        runner_generation=1,
        operation_type=operation_type,
        payload=payload,
        reply_stream_id="reply:request-1",
        body_stream_id=None,
        body_chunks=body_chunks,
        background=False,
        deadline_at=None,
    )
