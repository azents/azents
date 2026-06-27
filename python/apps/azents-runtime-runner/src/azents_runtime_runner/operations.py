"""Runtime Runner operation handlers."""

import asyncio
import base64
import contextlib
import fnmatch
import os
import re
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
_DEFAULT_MAX_PROCESS_COUNT = 16
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
    process: asyncio.subprocess.Process
    stdout: _ProcessOutputBuffer
    stderr: _ProcessOutputBuffer
    created_at: float
    last_accessed_at: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    wait_task: asyncio.Task[int] | None = None
    drain_tasks: tuple[asyncio.Task[None], ...] = ()
    stdout_chunk_id: int = 0
    stderr_chunk_id: int = 0


@dataclass(frozen=True)
class _MissingProcessRecord:
    """Recently removed process state returned as an observation."""

    status: Literal["missing", "terminated", "expired"]
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
        max_process_count: int = _DEFAULT_MAX_PROCESS_COUNT,
    ) -> None:
        """Initialize operation handlers."""
        self._client = client
        self._workspace = workspace
        self._processes: dict[str, _ManagedProcess] = {}
        self._missing_processes: dict[str, _MissingProcessRecord] = {}
        self._process_max_unread_bytes = max(process_max_unread_bytes, 1)
        self._process_idle_timeout_seconds = max(process_idle_timeout_seconds, 1.0)
        self._process_max_lifetime_seconds = max(process_max_lifetime_seconds, 1.0)
        self._max_process_count = max(max_process_count, 1)

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
            await self._final_error(
                operation,
                "UNSUPPORTED_OPERATION",
                f"Unsupported Runner operation: {operation.operation_type}",
            )
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

    async def _process_start(self, operation: RunnerOperationEnvelope) -> None:
        command = _str_payload(operation.payload, "command")
        if not command:
            await self._final_error(operation, "INVALID_PAYLOAD", "command is required")
            return
        await self._cleanup_expired_processes()
        await self._enforce_process_quota()
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
        record = self._register_process(operation, process)
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

    async def _process_write(self, operation: RunnerOperationEnvelope) -> None:
        process_id = _str_payload(operation.payload, "process_id")
        if not process_id:
            await self._final_error(
                operation,
                "INVALID_PAYLOAD",
                "process_id is required",
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
    ) -> _ManagedProcess:
        process_id = f"proc-{uuid.uuid4().hex}"
        now = time.monotonic()
        record = _ManagedProcess(
            process_id=process_id,
            generation=operation.runner_generation,
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
        status: Literal["running", "exited"] = (
            "exited" if _process_exited(record) else "running"
        )
        payload: dict[str, JsonValue] = {
            "process_id": record.process_id,
            "status": status,
            "exit_code": record.process.returncode if status == "exited" else None,
            "stdout": stdout.text,
            "stderr": stderr.text,
            "stdout_truncated": stdout.truncated,
            "stderr_truncated": stderr.truncated,
            "stdout_omitted_bytes": stdout.omitted_bytes,
            "stderr_omitted_bytes": stderr.omitted_bytes,
            "missing_reason": None,
        }
        await self._final_success(operation, payload)
        if status == "exited":
            await self._consume_exited_process(record)

    async def _consume_exited_process(self, record: _ManagedProcess) -> None:
        self._processes.pop(record.process_id, None)
        await self._wait_for_process_drains(record)
        self._record_missing(
            record.process_id,
            status="missing",
            reason="consumed",
        )

    async def _cleanup_expired_processes(self) -> None:
        now = time.monotonic()
        for record in tuple(self._processes.values()):
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

    async def _enforce_process_quota(self) -> None:
        while len(self._processes) >= self._max_process_count:
            oldest = min(
                self._processes.values(),
                key=lambda item: item.last_accessed_at,
            )
            await self._terminate_process(
                oldest,
                status="terminated",
                reason="quota_pruned",
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
        status: Literal["missing", "terminated", "expired"],
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
        return {
            "process_id": process_id,
            "status": missing.status if missing is not None else "missing",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "stdout_omitted_bytes": 0,
            "stderr_omitted_bytes": 0,
            "missing_reason": missing.reason if missing is not None else "not_found",
        }

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
    del workspace
    size_bytes: int | None = None
    if stat_module.S_ISREG(stat_result.st_mode):
        size_bytes = stat_result.st_size
    payload: dict[str, JsonValue] = {
        "path": str(path),
        "kind": _mode_kind(stat_result.st_mode),
        "size_bytes": size_bytes,
        "symlink": stat_module.S_ISLNK(stat_result.st_mode),
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


def _entry_type(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if path.is_dir():
        return "directory"
    if path.is_file():
        return "file"
    return "other"
