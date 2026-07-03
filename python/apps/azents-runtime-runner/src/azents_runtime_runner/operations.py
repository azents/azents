"""Runtime Runner operation handlers."""

import asyncio
import base64
import contextlib
import fnmatch
import os
import re
import shutil
import stat as stat_module
import time
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol

from azents_runtime_control.runner import (
    JsonValue,
    RunnerOperationEnvelope,
    RunnerOperationEvent,
    RuntimeRunnerEventType,
)

from azents_runtime_runner.workspace import Workspace

_DEFAULT_BASH_TIMEOUT_SECONDS = 120
_MAX_FILE_READ_BYTES = 8 * 1024 * 1024
_DEFAULT_MAX_GREP_SEARCHED_FILES = 10_000
_DEFAULT_MAX_GREP_SCANNED_BYTES = 128 * 1024 * 1024
_DEFAULT_PROCESS_YIELD_TIME_MS = 1_000
_DEFAULT_PROCESS_MAX_OUTPUT_BYTES = 64 * 1024
_DEFAULT_PROCESS_MAX_UNREAD_BYTES = 256 * 1024
_DEFAULT_PROCESS_IDLE_TIMEOUT_SECONDS = 30 * 60
_DEFAULT_PROCESS_MAX_LIFETIME_SECONDS = 2 * 60 * 60
_DEFAULT_PROCESS_EXITED_UNREAD_TTL_SECONDS = 10 * 60
_DEFAULT_MAX_RUNTIME_PROCESS_COUNT = 16
_DEFAULT_MAX_SESSION_PROCESS_COUNT = 16
_PROCESS_READ_CHUNK_BYTES = 4096
_PROCESS_DRAIN_AFTER_EXIT_TIMEOUT_SECONDS = 1.0
_PROCESS_TERMINATE_TIMEOUT_SECONDS = 2.0
_MAX_MISSING_PROCESS_RECORDS = 128


@dataclass
class _GrepScanState:
    """Track scan budget consumed while iterating grep targets."""

    searched_file_count: int = 0
    scanned_bytes: int = 0
    stopped_reason: str | None = None


@dataclass(frozen=True)
class _StreamSnapshot:
    """Drained process stream snapshot."""

    text: str
    truncated: bool
    omitted_bytes: int


@dataclass(frozen=True)
class _GitCommandResult:
    """Completed Git command output."""

    exit_code: int
    stdout: str
    stderr: str


class _ProcessOutputBuffer:
    """Bounded unread byte buffer for one process stream."""

    def __init__(self, *, max_unread_bytes: int) -> None:
        """Initialize a bounded unread output buffer."""
        self._max_unread_bytes = max(max_unread_bytes, 1)
        self._data = bytearray()
        self._omitted_bytes = 0

    def append(self, data: bytes) -> None:
        """Append output bytes, dropping oldest unread bytes when bounded."""
        if not data:
            return
        self._data.extend(data)
        overflow = len(self._data) - self._max_unread_bytes
        if overflow <= 0:
            return
        del self._data[:overflow]
        self._omitted_bytes += overflow

    def drain(self, *, max_bytes: int) -> _StreamSnapshot:
        """Drain unread output into a bounded text snapshot."""
        data = bytes(self._data)
        omitted_bytes = self._omitted_bytes
        if max_bytes <= 0:
            omitted_bytes += len(data)
            data = b""
        elif len(data) > max_bytes:
            omitted_bytes += len(data) - max_bytes
            data = data[-max_bytes:]
        self._data.clear()
        self._omitted_bytes = 0
        return _StreamSnapshot(
            text=data.decode(errors="replace"),
            truncated=omitted_bytes > 0,
            omitted_bytes=omitted_bytes,
        )


@dataclass
class _ManagedProcess:
    """Runner-owned pipe process state."""

    process_id: str
    generation: int
    owner_session_id: str
    process: asyncio.subprocess.Process
    stdout: _ProcessOutputBuffer
    stderr: _ProcessOutputBuffer
    created_at: float
    last_accessed_at: float
    exited_at: float | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    wait_task: asyncio.Task[int] | None = None
    drain_tasks: tuple[asyncio.Task[None], ...] = ()
    stdout_chunk_id: int = 0
    stderr_chunk_id: int = 0


@dataclass(frozen=True)
class _MissingProcessRecord:
    """Recently removed process state returned as an observation."""

    status: Literal["consumed", "missing", "terminated", "expired"]
    reason: str
    recorded_at: float


class RunnerEventSink(Protocol):
    """Subset of the Control client used by operation handlers."""

    async def append_runner_event(self, event: RunnerOperationEvent) -> None:
        """Append one Runner operation event."""
        ...


class RunnerOperations:
    """Handle Control-delivered operations inside one Runtime workspace."""

    def __init__(
        self,
        *,
        client: RunnerEventSink,
        workspace: Workspace,
        process_max_unread_bytes: int = _DEFAULT_PROCESS_MAX_UNREAD_BYTES,
        process_idle_timeout_seconds: float = _DEFAULT_PROCESS_IDLE_TIMEOUT_SECONDS,
        process_max_lifetime_seconds: float = _DEFAULT_PROCESS_MAX_LIFETIME_SECONDS,
        process_exited_unread_ttl_seconds: float = (
            _DEFAULT_PROCESS_EXITED_UNREAD_TTL_SECONDS
        ),
        max_runtime_process_count: int = _DEFAULT_MAX_RUNTIME_PROCESS_COUNT,
        max_session_process_count: int = _DEFAULT_MAX_SESSION_PROCESS_COUNT,
    ) -> None:
        """Initialize operation handlers."""
        self._client = client
        self._workspace = workspace
        self._processes: dict[str, _ManagedProcess] = {}
        self._missing_processes: dict[str, _MissingProcessRecord] = {}
        self._process_max_unread_bytes = max(process_max_unread_bytes, 1)
        self._process_idle_timeout_seconds = max(process_idle_timeout_seconds, 1.0)
        self._process_max_lifetime_seconds = max(process_max_lifetime_seconds, 1.0)
        self._process_exited_unread_ttl_seconds = max(
            process_exited_unread_ttl_seconds, 1.0
        )
        self._max_runtime_process_count = max(max_runtime_process_count, 1)
        self._max_session_process_count = max(max_session_process_count, 1)

    async def handle(self, operation: RunnerOperationEnvelope) -> None:
        """Run one operation and publish progress/final events."""
        try:
            await self._event(
                operation,
                RuntimeRunnerEventType.ACCEPTED,
                {"operation_type": operation.operation_type},
            )
            if operation.operation_type == "bash":
                await self._bash(operation)
                return
            if operation.operation_type in {"file.read", "file.download"}:
                await self._file_read(operation)
                return
            if operation.operation_type in {"file.write", "file.upload"}:
                await self._file_write(operation)
                return
            if operation.operation_type == "file.list":
                await self._file_list(operation)
                return
            if operation.operation_type == "file.grep":
                await self._file_grep(operation)
                return
            if operation.operation_type == "file.stat":
                await self._file_stat(operation)
                return
            if operation.operation_type == "process.start":
                await self._process_start(operation)
                return
            if operation.operation_type == "process.write":
                await self._process_write(operation)
                return
            if operation.operation_type == "file.delete":
                await self._file_delete(operation)
                return
            if operation.operation_type == "file.mkdir":
                await self._file_mkdir(operation)
                return
            if operation.operation_type == "file.move":
                await self._file_move(operation)
                return
            if operation.operation_type == "process.terminate_session":
                await self._process_terminate_session(operation)
                return
            if operation.operation_type == "file.bulk_delete":
                await self._file_bulk_delete(operation)
                return
            if operation.operation_type == "file.bulk_move":
                await self._file_bulk_move(operation)
                return
            if operation.operation_type == "list_git_refs":
                await self._git_list_refs(operation)
                return
            if operation.operation_type == "create_git_worktree":
                await self._git_create_worktree(operation)
                return
            if operation.operation_type == "remove_git_worktree":
                await self._git_remove_worktree(operation)
                return
            if operation.operation_type == "delete_git_branch":
                await self._git_delete_branch(operation)
                return
            await self._final_error(
                operation,
                "UNSUPPORTED_OPERATION",
                f"Unsupported Runner operation: {operation.operation_type}",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._final_error(operation, "RUNNER_OPERATION_ERROR", str(exc))

    async def close(self) -> None:
        """Terminate Runner-owned processes during Runner shutdown."""
        for process_id in tuple(self._processes):
            record = self._processes.get(process_id)
            if record is not None:
                await self._terminate_process(
                    record,
                    status="terminated",
                    reason="runner_shutdown",
                )

    async def _bash(self, operation: RunnerOperationEnvelope) -> None:
        command = _str_payload(operation.payload, "command")
        if not command:
            await self._final_error(operation, "INVALID_PAYLOAD", "command is required")
            return
        timeout_seconds = _int_payload(
            operation.payload,
            "timeout_seconds",
            default=_DEFAULT_BASH_TIMEOUT_SECONDS,
        )
        env = os.environ.copy()
        env.update(_str_mapping_payload(operation.payload, "env"))
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=self._workspace.root,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            await self._final_error(operation, "COMMAND_TIMEOUT", "Command timed out")
            return
        if stdout:
            await self._event(
                operation,
                RuntimeRunnerEventType.STDOUT,
                {"text": stdout.decode(errors="replace")},
            )
        if stderr:
            await self._event(
                operation,
                RuntimeRunnerEventType.STDERR,
                {"text": stderr.decode(errors="replace")},
            )
        await self._final_success(operation, {"exit_code": process.returncode or 0})

    async def _file_read(self, operation: RunnerOperationEnvelope) -> None:
        try:
            path = self._workspace.resolve(operation.payload.get("path"))
        except ValueError as exc:
            await self._final_error(operation, "INVALID_PATH", str(exc))
            return
        offset = _int_payload(operation.payload, "offset", default=0)
        max_bytes = _optional_int_payload(operation.payload, "max_bytes")
        if max_bytes is None:
            max_bytes = _MAX_FILE_READ_BYTES
        data = path.read_bytes()[offset : offset + max_bytes]
        await self._event(
            operation,
            RuntimeRunnerEventType.FILE_CHUNK,
            {"data_base64": base64.b64encode(data).decode()},
        )
        await self._final_success(operation, {"bytes_read": len(data)})

    async def _file_write(self, operation: RunnerOperationEnvelope) -> None:
        try:
            path = self._workspace.resolve(operation.payload.get("path"))
        except ValueError as exc:
            await self._final_error(operation, "INVALID_PATH", str(exc))
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        data = b"".join(chunk.data for chunk in operation.body_chunks)
        path.write_bytes(data)
        await self._final_success(operation, {"bytes_written": len(data)})

    async def _file_list(self, operation: RunnerOperationEnvelope) -> None:
        try:
            path = self._workspace.resolve(operation.payload.get("path"))
        except ValueError as exc:
            await self._final_error(operation, "INVALID_PATH", str(exc))
            return
        recursive = _bool_payload(operation.payload, "recursive", default=False)
        exclude_patterns = _str_list_payload(operation.payload, "exclude_patterns")
        entries = []
        for child in _iter_list_entries(
            path,
            workspace=self._workspace,
            recursive=recursive,
            exclude_patterns=exclude_patterns,
        ):
            entries.append(
                {
                    "path": self._workspace.display_path(child),
                    "type": _entry_type(child),
                    "size_bytes": _file_size(child),
                    "modified_at": _modified_at(child),
                }
            )
        await self._final_success(operation, {"entries": entries})

    async def _file_stat(self, operation: RunnerOperationEnvelope) -> None:
        try:
            path = _resolve_lexical_path(
                operation.payload.get("path"),
                workspace=self._workspace,
            )
        except ValueError as exc:
            await self._final_error(operation, "INVALID_PATH", str(exc))
            return
        try:
            path.lstat()
        except FileNotFoundError:
            await self._final_error(operation, "NOT_FOUND", f"No such file: {path}")
            return
        except OSError as exc:
            await self._final_error(operation, "STAT_FAILED", str(exc))
            return
        await self._final_success(operation, _stat_payload(path, self._workspace))

    async def _file_delete(self, operation: RunnerOperationEnvelope) -> None:
        try:
            path = _resolve_lexical_path(
                operation.payload.get("path"),
                workspace=self._workspace,
            )
        except ValueError as exc:
            await self._final_error(operation, "INVALID_PATH", str(exc))
            return
        recursive = _bool_payload(operation.payload, "recursive", default=False)
        try:
            stat_result = path.lstat()
        except FileNotFoundError:
            await self._final_error(operation, "NOT_FOUND", f"No such file: {path}")
            return
        except OSError as exc:
            await self._final_error(operation, "DELETE_FAILED", str(exc))
            return
        try:
            if stat_module.S_ISDIR(stat_result.st_mode) and not stat_module.S_ISLNK(
                stat_result.st_mode
            ):
                if not recursive:
                    await self._final_error(
                        operation,
                        "DIRECTORY_RECURSIVE_REQUIRED",
                        f"Directory delete requires recursive=true: {path}",
                    )
                    return
                shutil.rmtree(path)
            else:
                path.unlink()
        except FileNotFoundError:
            await self._final_error(operation, "NOT_FOUND", f"No such file: {path}")
            return
        except OSError as exc:
            await self._final_error(operation, "DELETE_FAILED", str(exc))
            return
        await self._final_success(
            operation,
            {"deleted_path": self._workspace.display_path(path)},
        )

    async def _file_mkdir(self, operation: RunnerOperationEnvelope) -> None:
        try:
            path = _resolve_lexical_path(
                operation.payload.get("path"),
                workspace=self._workspace,
            )
        except ValueError as exc:
            await self._final_error(operation, "INVALID_PATH", str(exc))
            return
        parents = _bool_payload(operation.payload, "parents", default=False)
        try:
            path.mkdir(parents=parents, exist_ok=False)
        except FileExistsError:
            await self._final_error(operation, "ALREADY_EXISTS", f"Path exists: {path}")
            return
        except FileNotFoundError:
            await self._final_error(
                operation,
                "PARENT_NOT_FOUND",
                f"Parent directory does not exist: {path.parent}",
            )
            return
        except OSError as exc:
            await self._final_error(operation, "MKDIR_FAILED", str(exc))
            return
        await self._final_success(
            operation,
            {"created_path": self._workspace.display_path(path)},
        )

    async def _file_move(self, operation: RunnerOperationEnvelope) -> None:
        try:
            source_path = _resolve_lexical_path(
                operation.payload.get("source_path"),
                workspace=self._workspace,
            )
            destination_path = _resolve_lexical_path(
                operation.payload.get("destination_path"),
                workspace=self._workspace,
            )
        except ValueError as exc:
            await self._final_error(operation, "INVALID_PATH", str(exc))
            return
        overwrite = _bool_payload(operation.payload, "overwrite", default=False)
        if not source_path.exists() and not source_path.is_symlink():
            await self._final_error(
                operation, "NOT_FOUND", f"No such file: {source_path}"
            )
            return
        if destination_path.exists() or destination_path.is_symlink():
            if not overwrite:
                await self._final_error(
                    operation,
                    "DESTINATION_EXISTS",
                    f"Destination already exists: {destination_path}",
                )
                return
            try:
                if destination_path.is_dir() and not destination_path.is_symlink():
                    shutil.rmtree(destination_path)
                else:
                    destination_path.unlink()
            except OSError as exc:
                await self._final_error(operation, "MOVE_FAILED", str(exc))
                return
        if not destination_path.parent.exists():
            await self._final_error(
                operation,
                "PARENT_NOT_FOUND",
                f"Parent directory does not exist: {destination_path.parent}",
            )
            return
        if not destination_path.parent.is_dir():
            await self._final_error(
                operation,
                "PARENT_NOT_DIRECTORY",
                f"Parent path is not a directory: {destination_path.parent}",
            )
            return
        try:
            shutil.move(str(source_path), str(destination_path))
        except OSError as exc:
            await self._final_error(operation, "MOVE_FAILED", str(exc))
            return
        await self._final_success(
            operation,
            {
                "moved_source_path": self._workspace.display_path(source_path),
                "moved_destination_path": self._workspace.display_path(
                    destination_path
                ),
            },
        )

    async def _file_bulk_delete(self, operation: RunnerOperationEnvelope) -> None:
        paths: list[Path] = []
        for raw_path in _str_list_payload(operation.payload, "paths"):
            try:
                paths.append(_resolve_lexical_path(raw_path, workspace=self._workspace))
            except ValueError as exc:
                await self._final_error(operation, "INVALID_PATH", str(exc))
                return
        if not paths:
            await self._final_error(operation, "INVALID_PAYLOAD", "paths is required")
            return
        recursive = _bool_payload(operation.payload, "recursive", default=False)
        stats: list[tuple[Path, os.stat_result]] = []
        try:
            for path in paths:
                stats.append((path, path.lstat()))
        except FileNotFoundError as exc:
            await self._final_error(operation, "NOT_FOUND", str(exc))
            return
        except OSError as exc:
            await self._final_error(operation, "DELETE_FAILED", str(exc))
            return
        for path, stat_result in stats:
            if (
                stat_module.S_ISDIR(stat_result.st_mode)
                and not stat_module.S_ISLNK(stat_result.st_mode)
                and not recursive
            ):
                await self._final_error(
                    operation,
                    "DIRECTORY_RECURSIVE_REQUIRED",
                    f"Directory delete requires recursive=true: {path}",
                )
                return
        deleted_paths: list[JsonValue] = []
        try:
            for path, stat_result in stats:
                if stat_module.S_ISDIR(stat_result.st_mode) and not stat_module.S_ISLNK(
                    stat_result.st_mode
                ):
                    shutil.rmtree(path)
                else:
                    path.unlink()
                deleted_paths.append(self._workspace.display_path(path))
        except FileNotFoundError as exc:
            await self._final_error(operation, "NOT_FOUND", str(exc))
            return
        except OSError as exc:
            await self._final_error(operation, "DELETE_FAILED", str(exc))
            return
        await self._final_success(operation, {"deleted_paths": deleted_paths})

    async def _file_bulk_move(self, operation: RunnerOperationEnvelope) -> None:
        source_paths: list[Path] = []
        for raw_path in _str_list_payload(operation.payload, "source_paths"):
            try:
                source_paths.append(
                    _resolve_lexical_path(raw_path, workspace=self._workspace)
                )
            except ValueError as exc:
                await self._final_error(operation, "INVALID_PATH", str(exc))
                return
        if not source_paths:
            await self._final_error(
                operation, "INVALID_PAYLOAD", "source_paths is required"
            )
            return
        try:
            destination_directory = _resolve_lexical_path(
                operation.payload.get("destination_directory"),
                workspace=self._workspace,
            )
        except ValueError as exc:
            await self._final_error(operation, "INVALID_PATH", str(exc))
            return
        overwrite = _bool_payload(operation.payload, "overwrite", default=False)
        if not destination_directory.exists():
            await self._final_error(
                operation,
                "PARENT_NOT_FOUND",
                f"Destination directory does not exist: {destination_directory}",
            )
            return
        if not destination_directory.is_dir():
            await self._final_error(
                operation,
                "PARENT_NOT_DIRECTORY",
                f"Destination path is not a directory: {destination_directory}",
            )
            return
        seen_destinations: set[Path] = set()
        moves: list[tuple[Path, Path]] = []
        for source_path in source_paths:
            if not source_path.exists() and not source_path.is_symlink():
                await self._final_error(
                    operation, "NOT_FOUND", f"No such file: {source_path}"
                )
                return
            destination_path = destination_directory / source_path.name
            if destination_path in seen_destinations:
                await self._final_error(
                    operation,
                    "DESTINATION_EXISTS",
                    f"Duplicate destination: {destination_path}",
                )
                return
            seen_destinations.add(destination_path)
            if destination_path.exists() or destination_path.is_symlink():
                if not overwrite:
                    await self._final_error(
                        operation,
                        "DESTINATION_EXISTS",
                        f"Destination already exists: {destination_path}",
                    )
                    return
            moves.append((source_path, destination_path))
        moved_entries: list[JsonValue] = []
        try:
            for source_path, destination_path in moves:
                if destination_path.exists() or destination_path.is_symlink():
                    if destination_path.is_dir() and not destination_path.is_symlink():
                        shutil.rmtree(destination_path)
                    else:
                        destination_path.unlink()
                shutil.move(str(source_path), str(destination_path))
                moved_entries.append(
                    {
                        "source_path": self._workspace.display_path(source_path),
                        "destination_path": self._workspace.display_path(
                            destination_path
                        ),
                    }
                )
        except OSError as exc:
            await self._final_error(operation, "MOVE_FAILED", str(exc))
            return
        await self._final_success(operation, {"moved_entries": moved_entries})

    async def _file_grep(self, operation: RunnerOperationEnvelope) -> None:
        try:
            path = self._workspace.resolve(operation.payload.get("path"))
        except ValueError as exc:
            await self._final_error(operation, "INVALID_PATH", str(exc))
            return
        pattern = _str_payload(operation.payload, "pattern")
        if not pattern:
            await self._final_error(operation, "INVALID_PAYLOAD", "pattern is required")
            return
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            await self._final_error(operation, "INVALID_REGEX", str(exc))
            return
        recursive = _bool_payload(operation.payload, "recursive", default=True)
        exclude_patterns = _str_list_payload(operation.payload, "exclude_patterns")
        max_matching_files = _positive_int_payload(
            operation.payload,
            "max_matching_files",
            default=50,
        )
        max_lines_per_file = _positive_int_payload(
            operation.payload,
            "max_lines_per_file",
            default=10,
        )
        max_searched_files = _positive_int_payload(
            operation.payload,
            "max_searched_files",
            default=_DEFAULT_MAX_GREP_SEARCHED_FILES,
        )
        max_scanned_bytes = _positive_int_payload(
            operation.payload,
            "max_scanned_bytes",
            default=_DEFAULT_MAX_GREP_SCANNED_BYTES,
        )
        state = _GrepScanState()
        matches: list[JsonValue] = []
        for file_path in _iter_grep_files(
            path,
            workspace=self._workspace,
            recursive=recursive,
            exclude_patterns=exclude_patterns,
        ):
            if len(matches) >= max_matching_files:
                state.stopped_reason = "matching_file_limit"
                break
            if state.searched_file_count >= max_searched_files:
                state.stopped_reason = "searched_file_limit"
                break
            match = _grep_file(
                file_path,
                workspace=self._workspace,
                regex=regex,
                max_lines_per_file=max_lines_per_file,
                max_scanned_bytes=max_scanned_bytes,
                state=state,
            )
            if match is not None:
                matches.append(match)
            if state.stopped_reason is not None:
                break
        await self._final_success(
            operation,
            {
                "files": matches,
                "searched_file_count": state.searched_file_count,
                "matched_file_count": len(matches),
                "truncated": state.stopped_reason is not None,
                "stopped_reason": state.stopped_reason,
            },
        )

    async def _git_list_refs(self, operation: RunnerOperationEnvelope) -> None:
        source_path = await self._git_source_path(operation)
        if source_path is None:
            return
        refs_result = await self._run_git_capture(
            operation,
            ("for-each-ref", "--format=%(refname)%09%(objectname)%09%(refname:short)"),
            cwd=source_path,
        )
        if refs_result is None:
            return
        if refs_result.exit_code != 0:
            await self._final_error(
                operation,
                "git_command_failed",
                _git_command_error_message(refs_result),
            )
            return
        default_branch = await self._default_branch(operation, source_path)
        head_commit = await self._head_commit(operation, source_path)
        refs: list[JsonValue] = []
        for line in refs_result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            ref, target, short_name = parts
            refs.append(
                {
                    "name": _git_ref_display_name(ref, short_name),
                    "ref": ref,
                    "type": _git_ref_type(ref),
                    "target": target,
                    "default": _git_ref_is_default(ref, short_name, default_branch),
                }
            )
        await self._final_success(
            operation,
            {
                "git_refs": refs,
                "default_branch": default_branch,
                "head_commit": head_commit,
            },
        )

    async def _git_create_worktree(self, operation: RunnerOperationEnvelope) -> None:
        source_path = await self._git_source_path(operation)
        if source_path is None:
            return
        starting_ref = _str_payload(operation.payload, "starting_ref")
        if not starting_ref:
            await self._final_error(
                operation,
                "invalid_ref",
                "starting_ref is required",
            )
            return
        branch_name = _str_payload(operation.payload, "branch_name")
        if not branch_name:
            await self._final_error(
                operation,
                "invalid_branch",
                "branch_name is required",
            )
            return
        try:
            worktree_path = _resolve_lexical_path(
                operation.payload.get("worktree_path"),
                workspace=self._workspace,
            )
        except ValueError as exc:
            await self._final_error(operation, "invalid_worktree_path", str(exc))
            return
        if worktree_path.exists() or worktree_path.is_symlink():
            await self._final_error(
                operation,
                "worktree_path_exists",
                f"Worktree path already exists: {worktree_path}",
            )
            return
        base_commit = await self._resolve_git_commit(
            operation,
            source_path,
            starting_ref,
        )
        if base_commit is None:
            return
        branch_exists = await self._git_branch_exists(
            operation, source_path, branch_name
        )
        if branch_exists is None:
            return
        if branch_exists:
            await self._final_error(
                operation,
                "branch_exists",
                f"Git branch already exists: {branch_name}",
            )
            return
        result = await self._run_git_streaming(
            operation,
            (
                "worktree",
                "add",
                "-b",
                branch_name,
                str(worktree_path),
                starting_ref,
            ),
            cwd=source_path,
        )
        if result is None:
            return
        if result.exit_code != 0:
            await self._final_error(
                operation,
                "git_command_failed",
                _git_command_error_message(result),
            )
            return
        await self._final_success(
            operation,
            {
                "base_commit": base_commit,
                "worktree_path": str(worktree_path),
                "branch_name": branch_name,
            },
        )

    async def _git_remove_worktree(self, operation: RunnerOperationEnvelope) -> None:
        source_path = await self._git_source_path(operation)
        if source_path is None:
            return
        try:
            worktree_path = _resolve_lexical_path(
                operation.payload.get("worktree_path"),
                workspace=self._workspace,
            )
        except ValueError as exc:
            await self._final_error(operation, "invalid_worktree_path", str(exc))
            return
        argv = ["worktree", "remove"]
        if _bool_payload(operation.payload, "force", default=False):
            argv.append("--force")
        argv.append(str(worktree_path))
        result = await self._run_git_streaming(operation, tuple(argv), cwd=source_path)
        if result is None:
            return
        if result.exit_code != 0:
            await self._final_error(
                operation,
                "git_command_failed",
                _git_command_error_message(result),
            )
            return
        await self._final_success(
            operation,
            {"removed_worktree_path": str(worktree_path)},
        )

    async def _git_delete_branch(self, operation: RunnerOperationEnvelope) -> None:
        source_path = await self._git_source_path(operation)
        if source_path is None:
            return
        branch_name = _str_payload(operation.payload, "branch_name")
        if not branch_name:
            await self._final_error(
                operation,
                "invalid_branch",
                "branch_name is required",
            )
            return
        result = await self._run_git_streaming(
            operation,
            ("branch", "-D", branch_name),
            cwd=source_path,
        )
        if result is None:
            return
        if result.exit_code != 0:
            await self._final_error(
                operation,
                "git_command_failed",
                _git_command_error_message(result),
            )
            return
        await self._final_success(
            operation,
            {"deleted_branch_name": branch_name},
        )

    async def _process_start(self, operation: RunnerOperationEnvelope) -> None:
        command = _str_payload(operation.payload, "command")
        if not command:
            await self._final_error(operation, "INVALID_PAYLOAD", "command is required")
            return
        owner_session_id = _str_payload(operation.payload, "owner_session_id")
        if not owner_session_id:
            await self._final_error(
                operation,
                "INVALID_PAYLOAD",
                "owner_session_id is required",
            )
            return
        await self._cleanup_expired_processes()
        await self._enforce_process_quota(owner_session_id)
        workdir = _optional_str_payload(operation.payload, "workdir")
        try:
            cwd = (
                self._workspace.root
                if workdir is None
                else self._workspace.resolve(workdir)
            )
        except ValueError as exc:
            await self._final_error(operation, "INVALID_WORKDIR", str(exc))
            return
        if not cwd.is_dir():
            await self._final_error(
                operation,
                "INVALID_WORKDIR",
                f"No such directory: {cwd}",
            )
            return
        env = os.environ.copy()
        env.update(_str_mapping_payload(operation.payload, "env"))
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=cwd,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            await self._final_error(operation, "PROCESS_START_FAILED", str(exc))
            return
        record = self._register_process(operation, process, owner_session_id)
        async with record.lock:
            await self._wait_for_exit_or_yield(
                record,
                yield_time_ms=_yield_time_ms(operation.payload),
            )
            await self._emit_process_snapshot(
                operation,
                record,
                max_output_bytes=_max_output_bytes(operation.payload),
            )

    async def _process_terminate_session(
        self,
        operation: RunnerOperationEnvelope,
    ) -> None:
        owner_session_id = _str_payload(operation.payload, "owner_session_id")
        if not owner_session_id:
            await self._final_error(
                operation,
                "INVALID_PAYLOAD",
                "owner_session_id is required",
            )
            return
        records = [
            record
            for record in tuple(self._processes.values())
            if record.owner_session_id == owner_session_id
        ]
        for record in records:
            await self._terminate_process(
                record,
                status="terminated",
                reason="user_stop",
            )
        await self._final_success(
            operation,
            {"terminated_count": len(records)},
        )

    async def _process_write(self, operation: RunnerOperationEnvelope) -> None:
        process_id = _str_payload(operation.payload, "process_id")
        if not process_id:
            await self._final_error(
                operation,
                "INVALID_PAYLOAD",
                "process_id is required",
            )
            return
        owner_session_id = _str_payload(operation.payload, "owner_session_id")
        if not owner_session_id:
            await self._final_error(
                operation,
                "INVALID_PAYLOAD",
                "owner_session_id is required",
            )
            return
        await self._cleanup_expired_processes()
        record = self._processes.get(process_id)
        if record is None:
            await self._final_success(
                operation,
                self._missing_process_payload(process_id),
            )
            return
        if record.owner_session_id != owner_session_id:
            await self._final_success(
                operation,
                _process_observation_payload(
                    process_id,
                    status="missing",
                    missing_reason="owner_session_mismatch",
                ),
            )
            return
        if record.generation != operation.runner_generation:
            await self._terminate_process(
                record,
                status="terminated",
                reason="stale_generation",
            )
            await self._final_success(
                operation,
                self._missing_process_payload(process_id),
            )
            return
        async with record.lock:
            record.last_accessed_at = time.monotonic()
            stdin = _str_payload(operation.payload, "stdin")
            if stdin and not _process_exited(record):
                await self._write_stdin(record, stdin)
            await self._wait_for_exit_or_yield(
                record,
                yield_time_ms=_yield_time_ms(operation.payload),
            )
            await self._emit_process_snapshot(
                operation,
                record,
                max_output_bytes=_max_output_bytes(operation.payload),
            )

    def _register_process(
        self,
        operation: RunnerOperationEnvelope,
        process: asyncio.subprocess.Process,
        owner_session_id: str,
    ) -> _ManagedProcess:
        process_id = f"proc-{uuid.uuid4().hex}"
        now = time.monotonic()
        record = _ManagedProcess(
            process_id=process_id,
            generation=operation.runner_generation,
            owner_session_id=owner_session_id,
            process=process,
            stdout=_ProcessOutputBuffer(
                max_unread_bytes=self._process_max_unread_bytes
            ),
            stderr=_ProcessOutputBuffer(
                max_unread_bytes=self._process_max_unread_bytes
            ),
            created_at=now,
            last_accessed_at=now,
        )
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("process stdout/stderr pipes are required")
        record.wait_task = asyncio.create_task(process.wait())
        record.drain_tasks = (
            asyncio.create_task(
                self._drain_process_stream(record, "stdout", process.stdout)
            ),
            asyncio.create_task(
                self._drain_process_stream(record, "stderr", process.stderr)
            ),
        )
        self._processes[process_id] = record
        return record

    async def _drain_process_stream(
        self,
        record: _ManagedProcess,
        stream: Literal["stdout", "stderr"],
        reader: asyncio.StreamReader,
    ) -> None:
        del self
        while True:
            data = await reader.read(_PROCESS_READ_CHUNK_BYTES)
            if not data:
                return
            if stream == "stdout":
                record.stdout.append(data)
            else:
                record.stderr.append(data)

    async def _write_stdin(self, record: _ManagedProcess, stdin: str) -> None:
        writer = record.process.stdin
        if writer is None or writer.is_closing():
            return
        try:
            writer.write(stdin.encode())
            await writer.drain()
        except BrokenPipeError:
            return
        except ConnectionError:
            return
        except RuntimeError:
            return

    async def _wait_for_exit_or_yield(
        self,
        record: _ManagedProcess,
        *,
        yield_time_ms: int,
    ) -> None:
        wait_task = record.wait_task
        if wait_task is None:
            return
        if wait_task.done():
            record.exited_at = record.exited_at or time.monotonic()
            await self._wait_for_process_drains(record)
            return
        if yield_time_ms <= 0:
            await asyncio.sleep(0)
            return
        try:
            await asyncio.wait_for(
                asyncio.shield(wait_task),
                timeout=yield_time_ms / 1000,
            )
        except TimeoutError:
            return
        record.exited_at = record.exited_at or time.monotonic()
        await self._wait_for_process_drains(record)

    async def _wait_for_process_drains(self, record: _ManagedProcess) -> None:
        if not record.drain_tasks:
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                asyncio.gather(*record.drain_tasks, return_exceptions=True),
                timeout=_PROCESS_DRAIN_AFTER_EXIT_TIMEOUT_SECONDS,
            )

    async def _emit_process_snapshot(
        self,
        operation: RunnerOperationEnvelope,
        record: _ManagedProcess,
        *,
        max_output_bytes: int,
    ) -> None:
        stdout = record.stdout.drain(max_bytes=max_output_bytes)
        stderr = record.stderr.drain(max_bytes=max_output_bytes)
        if stdout.text:
            record.stdout_chunk_id += 1
            await self._event(
                operation,
                RuntimeRunnerEventType.PROCESS_OUTPUT,
                {
                    "process_id": record.process_id,
                    "stream": "stdout",
                    "chunk_id": record.stdout_chunk_id,
                    "text": stdout.text,
                    "truncated": stdout.truncated,
                    "omitted_bytes": stdout.omitted_bytes,
                },
            )
        if stderr.text:
            record.stderr_chunk_id += 1
            await self._event(
                operation,
                RuntimeRunnerEventType.PROCESS_OUTPUT,
                {
                    "process_id": record.process_id,
                    "stream": "stderr",
                    "chunk_id": record.stderr_chunk_id,
                    "text": stderr.text,
                    "truncated": stderr.truncated,
                    "omitted_bytes": stderr.omitted_bytes,
                },
            )
        status: Literal["running", "exited_unread"] = (
            "exited_unread" if _process_exited(record) else "running"
        )
        payload: dict[str, JsonValue] = {
            "process_id": record.process_id,
            "status": status,
            "exit_code": (
                record.process.returncode if status == "exited_unread" else None
            ),
            "stdout": stdout.text,
            "stderr": stderr.text,
            "stdout_truncated": stdout.truncated,
            "stderr_truncated": stderr.truncated,
            "stdout_omitted_bytes": stdout.omitted_bytes,
            "stderr_omitted_bytes": stderr.omitted_bytes,
            "missing_reason": None,
        }
        await self._final_success(operation, payload)
        if status == "exited_unread":
            await self._consume_exited_process(record)

    async def _consume_exited_process(self, record: _ManagedProcess) -> None:
        self._processes.pop(record.process_id, None)
        await self._wait_for_process_drains(record)
        self._record_missing(
            record.process_id,
            status="consumed",
            reason="consumed",
        )

    async def _cleanup_expired_processes(self) -> None:
        now = time.monotonic()
        for record in tuple(self._processes.values()):
            if _process_exited(record):
                record.exited_at = record.exited_at or now
                if now - record.exited_at > self._process_exited_unread_ttl_seconds:
                    await self._expire_exited_unread_process(record)
                continue
            if now - record.created_at > self._process_max_lifetime_seconds:
                await self._terminate_process(
                    record,
                    status="expired",
                    reason="max_lifetime_exceeded",
                )
                continue
            if now - record.last_accessed_at > self._process_idle_timeout_seconds:
                await self._terminate_process(
                    record,
                    status="expired",
                    reason="idle_timeout",
                )

    async def _enforce_process_quota(self, owner_session_id: str) -> None:
        while (
            self._session_process_count(owner_session_id)
            >= self._max_session_process_count
        ):
            oldest = min(
                (
                    item
                    for item in self._processes.values()
                    if item.owner_session_id == owner_session_id
                ),
                key=lambda item: item.last_accessed_at,
            )
            await self._terminate_process(
                oldest,
                status="terminated",
                reason="session_quota_pruned",
            )
        while len(self._processes) >= self._max_runtime_process_count:
            oldest = min(
                self._processes.values(),
                key=lambda item: item.last_accessed_at,
            )
            await self._terminate_process(
                oldest,
                status="terminated",
                reason="runtime_quota_pruned",
            )

    def _session_process_count(self, owner_session_id: str) -> int:
        return sum(
            1
            for record in self._processes.values()
            if record.owner_session_id == owner_session_id
        )

    async def _expire_exited_unread_process(self, record: _ManagedProcess) -> None:
        self._processes.pop(record.process_id, None)
        await self._wait_for_process_drains(record)
        self._record_missing(
            record.process_id,
            status="expired",
            reason="exited_unread_ttl",
        )

    async def _terminate_process(
        self,
        record: _ManagedProcess,
        *,
        status: Literal["terminated", "expired"],
        reason: str,
    ) -> None:
        self._processes.pop(record.process_id, None)
        if not _process_exited(record):
            record.process.terminate()
            wait_task = record.wait_task
            if wait_task is not None:
                try:
                    await asyncio.wait_for(
                        asyncio.shield(wait_task),
                        timeout=_PROCESS_TERMINATE_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    record.process.kill()
                    await asyncio.shield(wait_task)
        for task in record.drain_tasks:
            if not task.done():
                task.cancel()
        if record.drain_tasks:
            await asyncio.gather(*record.drain_tasks, return_exceptions=True)
        self._record_missing(record.process_id, status=status, reason=reason)

    def _record_missing(
        self,
        process_id: str,
        *,
        status: Literal["consumed", "missing", "terminated", "expired"],
        reason: str,
    ) -> None:
        self._missing_processes[process_id] = _MissingProcessRecord(
            status=status,
            reason=reason,
            recorded_at=time.monotonic(),
        )
        if len(self._missing_processes) <= _MAX_MISSING_PROCESS_RECORDS:
            return
        oldest_process_id = min(
            self._missing_processes,
            key=lambda item: self._missing_processes[item].recorded_at,
        )
        self._missing_processes.pop(oldest_process_id, None)

    def _missing_process_payload(self, process_id: str) -> dict[str, JsonValue]:
        missing = self._missing_processes.get(process_id)
        if missing is None:
            return _process_observation_payload(
                process_id,
                status="missing",
                missing_reason="not_found",
            )
        return _process_observation_payload(
            process_id,
            status=missing.status,
            missing_reason=missing.reason,
        )

    async def _git_source_path(self, operation: RunnerOperationEnvelope) -> Path | None:
        try:
            source_path = _resolve_lexical_path(
                operation.payload.get("source_project_path"),
                workspace=self._workspace,
            )
        except ValueError as exc:
            await self._final_error(operation, "invalid_source_path", str(exc))
            return None
        if not source_path.exists():
            await self._final_error(
                operation,
                "not_git_repo",
                f"Source project path does not exist: {source_path}",
            )
            return None
        if not source_path.is_dir():
            await self._final_error(
                operation,
                "not_git_repo",
                f"Source project path is not a directory: {source_path}",
            )
            return None
        result = await self._run_git_capture(
            operation,
            ("rev-parse", "--is-inside-work-tree"),
            cwd=source_path,
        )
        if result is None:
            return None
        if result.exit_code != 0 or result.stdout.strip() != "true":
            await self._final_error(
                operation,
                "not_git_repo",
                f"Source project path is not a Git repository: {source_path}",
            )
            return None
        return source_path

    async def _resolve_git_commit(
        self,
        operation: RunnerOperationEnvelope,
        source_path: Path,
        ref: str,
    ) -> str | None:
        result = await self._run_git_capture(
            operation,
            ("rev-parse", "--verify", f"{ref}^{{commit}}"),
            cwd=source_path,
        )
        if result is None:
            return None
        if result.exit_code != 0:
            await self._final_error(
                operation, "invalid_ref", _git_command_error_message(result)
            )
            return None
        return result.stdout.strip()

    async def _git_branch_exists(
        self,
        operation: RunnerOperationEnvelope,
        source_path: Path,
        branch_name: str,
    ) -> bool | None:
        result = await self._run_git_capture(
            operation,
            ("show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"),
            cwd=source_path,
        )
        if result is None:
            return None
        if result.exit_code == 0:
            return True
        if result.exit_code == 1:
            return False
        await self._final_error(
            operation, "git_command_failed", _git_command_error_message(result)
        )
        return None

    async def _default_branch(
        self,
        operation: RunnerOperationEnvelope,
        source_path: Path,
    ) -> str | None:
        result = await self._run_git_capture(
            operation,
            ("symbolic-ref", "--quiet", "--short", "HEAD"),
            cwd=source_path,
        )
        if result is None or result.exit_code != 0:
            return None
        value = result.stdout.strip()
        return value or None

    async def _head_commit(
        self,
        operation: RunnerOperationEnvelope,
        source_path: Path,
    ) -> str | None:
        result = await self._run_git_capture(
            operation,
            ("rev-parse", "HEAD"),
            cwd=source_path,
        )
        if result is None or result.exit_code != 0:
            return None
        value = result.stdout.strip()
        return value or None

    async def _run_git_capture(
        self,
        operation: RunnerOperationEnvelope,
        argv: tuple[str, ...],
        *,
        cwd: Path,
    ) -> _GitCommandResult | None:
        return await self._run_git_command(
            operation,
            argv,
            cwd=cwd,
            stream_output=False,
        )

    async def _run_git_streaming(
        self,
        operation: RunnerOperationEnvelope,
        argv: tuple[str, ...],
        *,
        cwd: Path,
    ) -> _GitCommandResult | None:
        return await self._run_git_command(
            operation,
            argv,
            cwd=cwd,
            stream_output=True,
        )

    async def _run_git_command(
        self,
        operation: RunnerOperationEnvelope,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        stream_output: bool,
    ) -> _GitCommandResult | None:
        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                *argv,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            await self._final_error(operation, "git_command_failed", str(exc))
            return None
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("git stdout/stderr pipes are required")
        stdout_task = asyncio.create_task(
            self._drain_git_stream(
                operation,
                RuntimeRunnerEventType.STDOUT,
                process.stdout,
                stream_output=stream_output,
            )
        )
        stderr_task = asyncio.create_task(
            self._drain_git_stream(
                operation,
                RuntimeRunnerEventType.STDERR,
                process.stderr,
                stream_output=stream_output,
            )
        )
        timeout = _remaining_timeout_seconds(operation.deadline_at)
        try:
            if timeout is None:
                exit_code = await process.wait()
            else:
                exit_code = await asyncio.wait_for(process.wait(), timeout=timeout)
        except TimeoutError:
            process.kill()
            await process.wait()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            await self._final_error(
                operation,
                "operation_timeout",
                "Git operation timed out",
            )
            return None
        stdout, stderr = await asyncio.gather(stdout_task, stderr_task)
        return _GitCommandResult(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
        )

    async def _drain_git_stream(
        self,
        operation: RunnerOperationEnvelope,
        event_type: RuntimeRunnerEventType,
        reader: asyncio.StreamReader,
        *,
        stream_output: bool,
    ) -> str:
        chunks: list[str] = []
        while True:
            data = await reader.read(_PROCESS_READ_CHUNK_BYTES)
            if not data:
                return "".join(chunks)
            text = data.decode(errors="replace")
            chunks.append(text)
            if stream_output:
                await self._event(operation, event_type, {"text": text})

    async def _final_success(
        self,
        operation: RunnerOperationEnvelope,
        payload: Mapping[str, JsonValue],
    ) -> None:
        await self._event(
            operation,
            RuntimeRunnerEventType.FINAL_SUCCESS,
            dict(payload),
            final=True,
        )

    async def _final_error(
        self,
        operation: RunnerOperationEnvelope,
        code: str,
        message: str,
    ) -> None:
        await self._event(
            operation,
            RuntimeRunnerEventType.FINAL_ERROR,
            {"error_code": code, "error_message": message},
            final=True,
        )

    async def _event(
        self,
        operation: RunnerOperationEnvelope,
        event_type: RuntimeRunnerEventType,
        payload: Mapping[str, JsonValue],
        *,
        final: bool = False,
    ) -> None:
        await self._client.append_runner_event(
            RunnerOperationEvent(
                request_id=operation.request_id,
                runtime_id=operation.runtime_id,
                generation=operation.runner_generation,
                event_type=event_type,
                payload=dict(payload),
                created_at=datetime.now(UTC),
                final=final,
            )
        )


def _process_exited(record: _ManagedProcess) -> bool:
    return record.process.returncode is not None


def _remaining_timeout_seconds(deadline_at: datetime | None) -> float | None:
    if deadline_at is None:
        return None
    return max((deadline_at - datetime.now(UTC)).total_seconds(), 0.001)


def _git_command_error_message(result: _GitCommandResult) -> str:
    text = result.stderr.strip() or result.stdout.strip()
    if text:
        return text
    return f"Git command failed with exit code {result.exit_code}"


def _git_ref_display_name(ref: str, short_name: str) -> str:
    if ref.startswith("refs/heads/"):
        return ref.removeprefix("refs/heads/")
    if ref.startswith("refs/remotes/"):
        return ref.removeprefix("refs/remotes/")
    if ref.startswith("refs/tags/"):
        return ref.removeprefix("refs/tags/")
    return short_name


def _git_ref_type(ref: str) -> str:
    if ref.startswith("refs/heads/"):
        return "branch"
    if ref.startswith("refs/remotes/"):
        return "remote_branch"
    if ref.startswith("refs/tags/"):
        return "tag"
    return "other"


def _git_ref_is_default(ref: str, short_name: str, default_branch: str | None) -> bool:
    if default_branch is None:
        return False
    return short_name == default_branch or ref == f"refs/heads/{default_branch}"


def _yield_time_ms(payload: Mapping[str, JsonValue]) -> int:
    return _non_negative_int_payload(
        payload,
        "yield_time_ms",
        default=_DEFAULT_PROCESS_YIELD_TIME_MS,
    )


def _max_output_bytes(payload: Mapping[str, JsonValue]) -> int:
    return _positive_int_payload(
        payload,
        "max_output_bytes",
        default=_DEFAULT_PROCESS_MAX_OUTPUT_BYTES,
    )


def _str_payload(payload: Mapping[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def _optional_str_payload(payload: Mapping[str, JsonValue], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _int_payload(payload: Mapping[str, JsonValue], key: str, *, default: int) -> int:
    value = payload.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _bool_payload(payload: Mapping[str, JsonValue], key: str, *, default: bool) -> bool:
    value = payload.get(key)
    return value if isinstance(value, bool) else default


def _optional_int_payload(payload: Mapping[str, JsonValue], key: str) -> int | None:
    value = payload.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _non_negative_int_payload(
    payload: Mapping[str, JsonValue],
    key: str,
    *,
    default: int,
) -> int:
    value = payload.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return default


def _positive_int_payload(
    payload: Mapping[str, JsonValue],
    key: str,
    *,
    default: int,
) -> int:
    value = payload.get(key)
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return default


def _str_mapping_payload(
    payload: Mapping[str, JsonValue],
    key: str,
) -> dict[str, str]:
    value = payload.get(key)
    if not isinstance(value, dict):
        return {}
    return {
        str(item_key): item_value
        for item_key, item_value in value.items()
        if isinstance(item_value, str)
    }


def _str_list_payload(payload: Mapping[str, JsonValue], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _iter_grep_files(
    path: Path,
    *,
    workspace: Workspace,
    recursive: bool,
    exclude_patterns: list[str],
) -> Iterator[Path]:
    """Yield regular file paths searched by file.grep in sorted order."""
    for entry in _iter_list_entries(
        path,
        workspace=workspace,
        recursive=recursive,
        exclude_patterns=exclude_patterns,
    ):
        if entry.is_file() and not entry.is_symlink():
            yield entry


def _grep_file(
    path: Path,
    *,
    workspace: Workspace,
    regex: re.Pattern[str],
    max_lines_per_file: int,
    max_scanned_bytes: int,
    state: _GrepScanState,
) -> dict[str, JsonValue] | None:
    """Find regex-matching lines in one file."""
    state.searched_file_count += 1
    lines: list[JsonValue] = []
    truncated = False
    try:
        with path.open("rb") as file:
            for line_number, raw_line in enumerate(file, start=1):
                state.scanned_bytes += len(raw_line)
                if state.scanned_bytes > max_scanned_bytes:
                    state.stopped_reason = "scanned_byte_limit"
                    break
                try:
                    line = raw_line.decode("utf-8").rstrip("\r\n")
                except UnicodeDecodeError:
                    return None
                if not regex.search(line):
                    continue
                if len(lines) >= max_lines_per_file:
                    truncated = True
                    break
                line_match: dict[str, JsonValue] = {
                    "line_number": line_number,
                    "text": line,
                }
                lines.append(line_match)
    except OSError:
        return None
    if not lines:
        return None
    file_match: dict[str, JsonValue] = {
        "path": workspace.display_path(path),
        "lines": lines,
        "truncated": truncated,
    }
    return file_match


def _iter_list_entries(
    path: Path,
    *,
    workspace: Workspace,
    recursive: bool,
    exclude_patterns: list[str],
) -> Iterator[Path]:
    """Yield paths included in file.list responses in sorted order."""
    if path.is_file() or path.is_symlink():
        yield path
        return
    try:
        children = sorted(path.iterdir(), key=lambda item: item.name)
    except OSError:
        return
    for child in children:
        if _excluded(child, base=path, workspace=workspace, patterns=exclude_patterns):
            continue
        yield child
        if recursive and child.is_dir() and not child.is_symlink():
            yield from _iter_list_entries(
                child,
                workspace=workspace,
                recursive=True,
                exclude_patterns=exclude_patterns,
            )


def _excluded(
    path: Path,
    *,
    base: Path,
    workspace: Workspace,
    patterns: list[str],
) -> bool:
    """Return whether the path matches an exclude pattern."""
    del workspace
    relative_path = _lexical_relative_path(path, base)
    parts = relative_path.split("/")
    for pattern in patterns:
        if fnmatch.fnmatch(relative_path, pattern):
            return True
        if any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True
    return False


def _resolve_lexical_path(raw_path: object, *, workspace: Workspace) -> Path:
    """Build an absolute path without following symlink targets."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("path is required")
    path = Path(raw_path)
    if not path.is_absolute():
        path = workspace.root / path
    return Path(os.path.normpath(str(path)))


def _lexical_relative_path(path: Path, base: Path) -> str:
    """Return a lexical path relative to base without following symlink targets."""
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.name


def _stat_payload(path: Path, workspace: Workspace) -> dict[str, JsonValue]:
    """Build a file.stat payload from lstat."""
    stat_result = path.lstat()
    size_bytes: int | None = None
    if stat_module.S_ISREG(stat_result.st_mode):
        size_bytes = stat_result.st_size
    payload: dict[str, JsonValue] = {
        "path": str(path),
        "kind": _mode_kind(stat_result.st_mode),
        "size_bytes": size_bytes,
        "symlink": stat_module.S_ISLNK(stat_result.st_mode),
        "modified_at": datetime.fromtimestamp(stat_result.st_mtime, UTC).isoformat(),
    }
    if stat_module.S_ISLNK(stat_result.st_mode):
        resolved = path.resolve(strict=False)
        payload["real_path"] = str(resolved)
        try:
            payload["resolved_kind"] = _mode_kind(resolved.stat().st_mode)
        except OSError:
            payload["resolved_kind"] = "missing"
    return payload


def _mode_kind(mode: int) -> str:
    """Convert stat mode to a Runtime file kind string."""
    if stat_module.S_ISLNK(mode):
        return "symlink"
    if stat_module.S_ISDIR(mode):
        return "directory"
    if stat_module.S_ISREG(mode):
        return "file"
    return "other"


def _file_size(path: Path) -> int | None:
    """Read file size and return None when stat fails."""
    if not path.is_file() or path.is_symlink():
        return None
    try:
        return path.stat().st_size
    except OSError:
        return None


def _modified_at(path: Path) -> str | None:
    """Return lstat modified time as an ISO-8601 UTC string."""
    try:
        return datetime.fromtimestamp(path.lstat().st_mtime, UTC).isoformat()
    except OSError:
        return None


def _entry_type(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if path.is_dir():
        return "directory"
    if path.is_file():
        return "file"
    return "other"


def _process_observation_payload(
    process_id: str,
    *,
    status: Literal["consumed", "missing", "terminated", "expired"],
    missing_reason: str,
) -> dict[str, JsonValue]:
    return {
        "process_id": process_id,
        "status": status,
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "stdout_truncated": False,
        "stderr_truncated": False,
        "stdout_omitted_bytes": 0,
        "stderr_omitted_bytes": 0,
        "missing_reason": missing_reason,
    }
