"""Runner operation handler tests."""

import asyncio
import subprocess
import threading
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from azents_runtime_control.runner import (
    JsonValue,
    RunnerBodyChunk,
    RunnerOperationEnvelope,
    RunnerOperationEvent,
    RuntimeRunnerEventType,
)

from azents_runtime_runner.operations import (
    RunnerOperations,
    _extract_glob_dir_prefix,  # pyright: ignore[reportPrivateUsage] -- Validate root-prefix parsing without traversing the host root.
)
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
    entries = final_payloads[2].get("entries")
    assert isinstance(entries, list)
    entry = entries[0]
    assert isinstance(entry, dict)
    modified_at = entry.get("modified_at")
    assert isinstance(modified_at, str)
    assert entries == [
        {
            "path": f"{tmp_path}/nested/report.txt",
            "type": "file",
            "size_bytes": 5,
            "modified_at": modified_at,
        }
    ]


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
    payload = client.events[-1].payload
    entries = payload.get("entries")
    assert isinstance(entries, list)
    entry = entries[0]
    assert isinstance(entry, dict)
    modified_at = entry.get("modified_at")
    assert isinstance(modified_at, str)
    assert entries == [
        {
            "path": f"{tmp_path}/nested/report.txt",
            "type": "file",
            "size_bytes": 5,
            "modified_at": modified_at,
        }
    ]


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
async def test_file_glob_matches_runtime_entries_with_braces_and_excludes(
    tmp_path: Path,
) -> None:
    """Runner-native glob matches files in the Runtime filesystem."""
    (tmp_path / "src" / "nested").mkdir(parents=True)
    (tmp_path / "src" / "app.py").write_text("print('ok')")
    (tmp_path / "src" / "nested" / "report.txt").write_text("report")
    (tmp_path / "src" / "nested" / "image.png").write_bytes(b"png")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "ignored.py").write_text("ignored")
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.glob",
            payload={
                "pattern": f"{tmp_path}/**/*.{{py,txt}}",
                "exclude_patterns": ["node_modules"],
            },
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    raw_matches = client.events[-1].payload.get("matches")
    assert isinstance(raw_matches, list)
    assert [match["path"] for match in raw_matches if isinstance(match, dict)] == [
        f"{tmp_path}/src/app.py",
        f"{tmp_path}/src/nested/report.txt",
    ]


@pytest.mark.asyncio
async def test_file_glob_supports_question_mark_and_character_classes(
    tmp_path: Path,
) -> None:
    """Runner-native glob supports segment-local `?` and `[]` matching."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app1.py").write_text("one")
    (tmp_path / "src" / "appA.py").write_text("alpha")
    (tmp_path / "src" / "app-long.py").write_text("long")
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.glob",
            payload={"pattern": f"{tmp_path}/src/app?.[p]y"},
        )
    )

    raw_matches = client.events[-1].payload.get("matches")
    assert isinstance(raw_matches, list)
    assert [match["path"] for match in raw_matches if isinstance(match, dict)] == [
        f"{tmp_path}/src/app1.py",
        f"{tmp_path}/src/appA.py",
    ]


@pytest.mark.asyncio
async def test_file_glob_rejects_excessive_brace_expansion(tmp_path: Path) -> None:
    """Runner-native glob rejects brace expansions above the bounded limit."""
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.glob",
            payload={"pattern": f"{tmp_path}/" + "{a,b}" * 9},
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_ERROR
    assert client.events[-1].payload == {
        "error_code": "INVALID_PATTERN",
        "error_message": "Brace expansion exceeds the maximum of 256 alternatives.",
    }


@pytest.mark.asyncio
async def test_file_glob_returns_matching_directories(tmp_path: Path) -> None:
    """Runner-native glob returns directory entries as well as files."""
    (tmp_path / "skills" / "search").mkdir(parents=True)
    (tmp_path / "skills" / "search" / "SKILL.md").write_text("search")
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.glob",
            payload={"pattern": f"{tmp_path}/skills/*"},
        )
    )

    raw_matches = client.events[-1].payload.get("matches")
    assert isinstance(raw_matches, list)
    match = raw_matches[0]
    assert isinstance(match, dict)
    assert match["path"] == f"{tmp_path}/skills/search"
    assert match["type"] == "directory"


@pytest.mark.asyncio
@pytest.mark.parametrize("pattern", ["~", "~/*.txt", "~alice/*.txt"])
async def test_file_glob_rejects_tilde_expansion(
    tmp_path: Path,
    pattern: str,
) -> None:
    """Runner-native glob rejects process-dependent home expansion."""
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(operation_type="file.glob", payload={"pattern": pattern})
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_ERROR
    assert client.events[-1].payload == {
        "error_code": "INVALID_PATTERN",
        "error_message": (
            "Tilde expansion is not supported. Use an absolute runtime path."
        ),
    }


def test_glob_root_pattern_uses_filesystem_root_prefix() -> None:
    """A glob in the first absolute segment scans from the filesystem root."""
    assert _extract_glob_dir_prefix("/*.txt") == "/"
    assert _extract_glob_dir_prefix("/**/report.txt") == "/"


@pytest.mark.asyncio
async def test_blocked_file_list_does_not_block_unrelated_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blocked filesystem worker does not block unrelated Runner progress."""
    (tmp_path / "scan").mkdir()
    (tmp_path / "scan" / "entry.txt").write_text("scan")
    (tmp_path / "read.txt").write_text("ready")
    entered = threading.Event()
    release = threading.Event()

    def blocking_iter(
        path: Path,
        *,
        workspace: Workspace,
        recursive: bool,
        exclude_patterns: list[str],
        cancellation: threading.Event,
    ) -> Iterator[Path]:
        del workspace, recursive, exclude_patterns
        entered.set()
        release.wait(timeout=2)
        if not cancellation.is_set():
            yield path / "entry.txt"

    monkeypatch.setattr(
        "azents_runtime_runner.operations._iter_list_entries",
        blocking_iter,
    )
    client = _FakeClient()
    operations = RunnerOperations(
        client=client,
        workspace=Workspace(str(tmp_path)),
        max_file_operation_workers=2,
    )

    list_task = asyncio.create_task(
        operations.handle(
            _operation(
                operation_type="file.list",
                payload={"path": str(tmp_path / "scan"), "recursive": True},
            )
        )
    )
    assert await asyncio.to_thread(entered.wait, 1)

    await asyncio.wait_for(
        operations.handle(
            _operation(
                operation_type="file.read",
                payload={"path": str(tmp_path / "read.txt")},
            )
        ),
        timeout=0.5,
    )

    read_successes = [
        event
        for event in client.events
        if event.event_type == RuntimeRunnerEventType.FINAL_SUCCESS
        and event.payload == {"bytes_read": 5}
    ]
    assert len(read_successes) == 1
    assert not list_task.done()

    release.set()
    await list_task
    await operations.close()


@pytest.mark.asyncio
async def test_file_operation_executor_never_exceeds_worker_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queued filesystem work never exceeds the configured worker bound."""
    for index in range(4):
        (tmp_path / f"read-{index}.txt").write_text("ready")
    lock = threading.Lock()
    active_count = 0
    maximum_active_count = 0
    bound_reached = threading.Event()
    release = threading.Event()

    def blocking_read(
        path: Path,
        *,
        offset: int,
        max_bytes: int,
        cancellation: threading.Event,
    ) -> bytes:
        del path, offset, max_bytes, cancellation
        nonlocal active_count, maximum_active_count
        with lock:
            active_count += 1
            maximum_active_count = max(maximum_active_count, active_count)
            if active_count == 2:
                bound_reached.set()
        release.wait(timeout=2)
        with lock:
            active_count -= 1
        return b"ready"

    monkeypatch.setattr(
        "azents_runtime_runner.operations._read_file_bytes",
        blocking_read,
    )
    client = _FakeClient()
    operations = RunnerOperations(
        client=client,
        workspace=Workspace(str(tmp_path)),
        max_file_operation_workers=2,
    )
    tasks = [
        asyncio.create_task(
            operations.handle(
                _operation(
                    operation_type="file.read",
                    payload={"path": str(tmp_path / f"read-{index}.txt")},
                )
            )
        )
        for index in range(4)
    ]

    assert await asyncio.to_thread(bound_reached.wait, 1)
    await asyncio.sleep(0)
    assert maximum_active_count == 2
    assert sum(task.done() for task in tasks) == 0

    release.set()
    await asyncio.gather(*tasks)
    assert maximum_active_count == 2
    await operations.close()


@pytest.mark.asyncio
async def test_cancelled_file_list_signals_blocking_traversal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling a file operation signals its cooperative traversal token."""
    (tmp_path / "scan").mkdir()
    entered = threading.Event()
    release = threading.Event()
    captured_cancellation: list[threading.Event] = []

    def blocking_iter(
        path: Path,
        *,
        workspace: Workspace,
        recursive: bool,
        exclude_patterns: list[str],
        cancellation: threading.Event,
    ) -> Iterator[Path]:
        del workspace, recursive, exclude_patterns
        captured_cancellation.append(cancellation)
        entered.set()
        release.wait(timeout=2)
        if not cancellation.is_set():
            yield path / "entry.txt"

    monkeypatch.setattr(
        "azents_runtime_runner.operations._iter_list_entries",
        blocking_iter,
    )
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))
    task = asyncio.create_task(
        operations.handle(
            _operation(
                operation_type="file.list",
                payload={"path": str(tmp_path / "scan"), "recursive": True},
            )
        )
    )
    assert await asyncio.to_thread(entered.wait, 1)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(captured_cancellation) == 1
    assert captured_cancellation[0].is_set()
    release.set()
    await operations.close()


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
    payload = client.events[-1].payload
    modified_at = payload.get("modified_at")
    assert isinstance(modified_at, str)
    assert payload == {
        "path": str(file_path),
        "kind": "file",
        "size_bytes": 5,
        "symlink": False,
        "modified_at": modified_at,
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
    payload = client.events[-1].payload
    modified_at = payload.get("modified_at")
    assert isinstance(modified_at, str)
    assert payload == {
        "path": str(link_path),
        "kind": "symlink",
        "size_bytes": None,
        "symlink": True,
        "real_path": str(target_path),
        "resolved_kind": "file",
        "modified_at": modified_at,
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
            payload={
                "command": "printf hello",
                "yield_time_ms": 1000,
                "owner_session_id": "session-1",
            },
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
    assert final["status"] == "exited_unread"
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
                "owner_session_id": "session-1",
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
                "owner_session_id": "session-1",
            },
        )
    )

    write_final = client.events[-1].payload
    assert write_final["process_id"] == process_id
    assert write_final["status"] == "exited_unread"
    assert write_final["exit_code"] == 0
    assert write_final["stdout"] == "echo:world\n"

    await operations.handle(
        _operation(
            operation_type="process.write",
            payload={
                "process_id": process_id,
                "stdin": "",
                "yield_time_ms": 0,
                "owner_session_id": "session-1",
            },
        )
    )

    missing_final = client.events[-1].payload
    assert missing_final["process_id"] == process_id
    assert missing_final["status"] == "consumed"
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
                "owner_session_id": "session-1",
            },
        )
    )

    final = client.events[-1].payload
    assert final["status"] == "exited_unread"
    assert final["stdout"] == "cdef"
    assert final["stdout_truncated"] is True
    assert final["stdout_omitted_bytes"] == 12


@pytest.mark.asyncio
async def test_process_quota_prunes_oldest_process(tmp_path: Path) -> None:
    client = _FakeClient()
    operations = RunnerOperations(
        client=client,
        workspace=Workspace(str(tmp_path)),
        max_runtime_process_count=1,
    )

    await operations.handle(
        _operation(
            operation_type="process.start",
            payload={
                "command": "sleep 10",
                "yield_time_ms": 0,
                "owner_session_id": "session-1",
            },
        )
    )
    process_id = client.events[-1].payload["process_id"]
    assert isinstance(process_id, str)

    await operations.handle(
        _operation(
            operation_type="process.start",
            payload={
                "command": "printf second",
                "yield_time_ms": 1000,
                "owner_session_id": "session-1",
            },
        )
    )
    await operations.handle(
        _operation(
            operation_type="process.write",
            payload={
                "process_id": process_id,
                "stdin": "",
                "yield_time_ms": 0,
                "owner_session_id": "session-1",
            },
        )
    )

    final = client.events[-1].payload
    assert final["process_id"] == process_id
    assert final["status"] == "terminated"
    assert final["missing_reason"] == "runtime_quota_pruned"


@pytest.mark.asyncio
async def test_process_terminate_session_terminates_only_owned_processes(
    tmp_path: Path,
) -> None:
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    long_running = "exec python -c 'import time; time.sleep(30)'"
    await operations.handle(
        _operation(
            operation_type="process.start",
            payload={
                "command": long_running,
                "yield_time_ms": 0,
                "owner_session_id": "session-1",
            },
        )
    )
    owned_process_id = client.events[-1].payload["process_id"]
    assert isinstance(owned_process_id, str)
    assert client.events[-1].payload["status"] == "running"
    await operations.handle(
        _operation(
            operation_type="process.start",
            payload={
                "command": long_running,
                "yield_time_ms": 0,
                "owner_session_id": "session-2",
            },
        )
    )
    other_process_id = client.events[-1].payload["process_id"]
    assert isinstance(other_process_id, str)
    assert client.events[-1].payload["status"] == "running"

    await operations.handle(
        _operation(
            operation_type="process.terminate_session",
            payload={"owner_session_id": "session-1"},
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    assert client.events[-1].payload == {"terminated_count": 1}
    await operations.handle(
        _operation(
            operation_type="process.write",
            payload={
                "process_id": owned_process_id,
                "stdin": "",
                "yield_time_ms": 0,
                "owner_session_id": "session-1",
            },
        )
    )
    assert client.events[-1].payload["status"] == "terminated"
    assert client.events[-1].payload["missing_reason"] == "user_stop"

    await operations.handle(
        _operation(
            operation_type="process.write",
            payload={
                "process_id": other_process_id,
                "stdin": "",
                "yield_time_ms": 0,
                "owner_session_id": "session-2",
            },
        )
    )
    assert client.events[-1].payload["status"] == "running"


@pytest.mark.asyncio
async def test_file_bulk_delete_removes_multiple_files(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.bulk_delete",
            payload={"paths": ["a.txt", "b.txt"], "recursive": False},
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    assert client.events[-1].payload == {
        "deleted_paths": [f"{tmp_path}/a.txt", f"{tmp_path}/b.txt"]
    }
    assert not (tmp_path / "a.txt").exists()
    assert not (tmp_path / "b.txt").exists()


@pytest.mark.asyncio
async def test_file_bulk_move_moves_multiple_files_into_directory(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "archive").mkdir()
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="file.bulk_move",
            payload={
                "source_paths": ["a.txt", "b.txt"],
                "destination_directory": "archive",
                "overwrite": False,
            },
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    assert client.events[-1].payload == {
        "moved_entries": [
            {
                "source_path": f"{tmp_path}/a.txt",
                "destination_path": f"{tmp_path}/archive/a.txt",
            },
            {
                "source_path": f"{tmp_path}/b.txt",
                "destination_path": f"{tmp_path}/archive/b.txt",
            },
        ]
    }
    assert not (tmp_path / "a.txt").exists()
    assert (tmp_path / "archive" / "a.txt").read_text() == "a"
    assert (tmp_path / "archive" / "b.txt").read_text() == "b"


@pytest.mark.asyncio
async def test_git_list_refs_returns_branches_tags_and_head(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    _git(repo, "tag", "v1")
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="list_git_refs",
            payload={"source_project_path": str(repo)},
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    payload = client.events[-1].payload
    assert payload["default_branch"] == "main"
    assert isinstance(payload["head_commit"], str)
    raw_refs = payload.get("git_refs")
    assert isinstance(raw_refs, list)
    refs = {ref["ref"]: ref for ref in raw_refs if isinstance(ref, dict)}
    assert refs["refs/heads/main"]["default"] is True
    assert refs["refs/tags/v1"]["type"] == "tag"


@pytest.mark.asyncio
async def test_git_create_remove_worktree_and_delete_branch(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    worktree_path = tmp_path / ".azents" / "worktrees" / "session" / "repo"
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="create_git_worktree",
            payload={
                "source_project_path": str(repo),
                "worktree_path": str(worktree_path),
                "branch_name": "azents/session",
                "starting_ref": "main",
            },
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    create_payload = client.events[-1].payload
    assert create_payload["worktree_path"] == str(worktree_path)
    assert create_payload["branch_name"] == "azents/session"
    assert (worktree_path / "README.md").read_text() == "hello\n"
    assert any(
        event.event_type == RuntimeRunnerEventType.STDERR for event in client.events
    )

    await operations.handle(
        _operation(
            operation_type="remove_git_worktree",
            payload={
                "source_project_path": str(repo),
                "worktree_path": str(worktree_path),
                "force": True,
            },
        )
    )
    assert client.events[-1].payload == {"removed_worktree_path": str(worktree_path)}
    assert not worktree_path.exists()

    await operations.handle(
        _operation(
            operation_type="delete_git_branch",
            payload={
                "source_project_path": str(repo),
                "branch_name": "azents/session",
            },
        )
    )
    assert client.events[-1].payload == {"deleted_branch_name": "azents/session"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        ({"source_project_path": "not-a-repo"}, "not_git_repo"),
        (
            {
                "source_project_path": "repo",
                "worktree_path": "new-worktree",
                "branch_name": "azents/session",
                "starting_ref": "missing-ref",
            },
            "invalid_ref",
        ),
        (
            {
                "source_project_path": "repo",
                "worktree_path": "existing-path",
                "branch_name": "azents/session",
                "starting_ref": "main",
            },
            "worktree_path_exists",
        ),
        (
            {
                "source_project_path": "repo",
                "worktree_path": "new-worktree",
                "branch_name": "existing-branch",
                "starting_ref": "main",
            },
            "branch_exists",
        ),
    ],
)
async def test_git_create_worktree_semantic_failures(
    tmp_path: Path,
    payload: dict[str, JsonValue],
    error_code: str,
) -> None:
    repo = _init_git_repo(tmp_path / "repo")
    (tmp_path / "existing-path").mkdir()
    _git(repo, "branch", "existing-branch")
    normalized_payload: dict[str, JsonValue] = {}
    for key, value in payload.items():
        if key.endswith("path") and isinstance(value, str):
            normalized_payload[key] = str(tmp_path / value)
        else:
            normalized_payload[key] = value
    client = _FakeClient()
    operations = RunnerOperations(client=client, workspace=Workspace(str(tmp_path)))

    await operations.handle(
        _operation(
            operation_type="create_git_worktree",
            payload=normalized_payload,
        )
    )

    assert client.events[-1].event_type == RuntimeRunnerEventType.FINAL_ERROR
    assert client.events[-1].payload["error_code"] == error_code


def _operation(
    *,
    operation_type: str,
    payload: dict[str, JsonValue],
    body_chunks: tuple[RunnerBodyChunk, ...] = (),
    deadline_at: datetime | None = None,
) -> RunnerOperationEnvelope:
    return RunnerOperationEnvelope(
        request_id="request-1",
        runtime_id="runtime-1",
        runner_generation=1,
        operation_type=operation_type,
        owner_session_id=(
            value
            if isinstance((value := payload.get("owner_session_id")), str)
            else None
        ),
        payload=payload,
        reply_stream_id="reply:request-1",
        body_stream_id=None,
        body_chunks=body_chunks,
        deadline_at=deadline_at,
    )


def _init_git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "--initial-branch", "main")
    _git(path, "config", "user.name", "Azents Test")
    _git(path, "config", "user.email", "azents-test@example.com")
    (path / "README.md").write_text("hello\n")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "Initial commit")
    return path


def _git(path: Path, *args: str) -> None:
    subprocess.run(
        ("git", "-C", str(path), *args),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
