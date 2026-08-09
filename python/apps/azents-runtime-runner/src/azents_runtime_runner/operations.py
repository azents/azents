"""Runtime Runner operation handlers."""

import asyncio
import base64
import contextlib
import logging
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

from azents_runtime_control.grpc_runner_client import (
    RuntimeRunnerControlStreamClosed,
)
from azents_runtime_control.runner import (
    JsonValue,
    RunnerOperationEnvelope,
    RunnerOperationEvent,
    RuntimeRunnerEventType,
)

from azents_runtime_runner.contained_client import (
    ContainedOperationClient,
    ContainedOperationEvent,
)
from azents_runtime_runner.containment import (
    ExecutionBackend,
    ExecutionProcess,
    ProcessTerminationResult,
    shell_execution_spec,
)
from azents_runtime_runner.workspace import Workspace

logger = logging.getLogger(__name__)

_DEFAULT_BASH_TIMEOUT_SECONDS = 120
_MAX_FILE_READ_BYTES = 8 * 1024 * 1024
_MAX_TEXT_READ_BYTES = 64 * 1024
_DEFAULT_MAX_FILE_OPERATION_WORKERS = 8
_DEFAULT_MAX_GREP_SEARCHED_FILES = 10_000
_DEFAULT_MAX_GREP_SCANNED_BYTES = 128 * 1024 * 1024
_MAX_BRACE_EXPANSIONS = 256
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
_PROCESS_KILL_TIMEOUT_SECONDS = 2.0
_PROCESS_CLOSE_TIMEOUT_SECONDS = 5.0
_MAX_MISSING_PROCESS_RECORDS = 128
_MANAGED_WORKTREE_ROOT = ".azents/worktrees"
_MAX_MANAGED_WORKTREE_DISCOVERY_ENTRIES = 512
_CONTAINED_NATIVE_OPERATION_TYPES = frozenset(
    {
        "file.read",
        "file.download",
        "file.read_text",
        "file.write",
        "file.upload",
        "file.apply_patch",
        "file.edit",
        "file.list",
        "file.glob",
        "file.grep",
        "file.stat",
        "file.delete",
        "file.mkdir",
        "file.move",
        "file.bulk_delete",
        "file.bulk_move",
        "list_git_refs",
        "create_git_worktree",
        "inspect_git_worktree",
        "discover_managed_git_worktrees",
        "remove_discovered_git_worktree",
        "remove_git_worktree",
        "delete_git_branch",
    }
)


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
    owner_session_id: str
    process: ExecutionProcess
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
        execution_backend: ExecutionBackend,
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
        self._apply_patch_lock = asyncio.Lock()
        self._execution_backend = execution_backend
        self._contained_operations = ContainedOperationClient(
            backend=execution_backend,
            workspace_path=workspace.root,
        )

    async def handle(self, operation: RunnerOperationEnvelope) -> None:
        """Run one operation and publish progress/final events."""
        try:
            await self._event(
                operation,
                RuntimeRunnerEventType.ACCEPTED,
                {"operation_type": operation.operation_type},
            )
            if operation.operation_type in _CONTAINED_NATIVE_OPERATION_TYPES:
                await self._contained_native_operation(operation)
                return
            if operation.operation_type == "bash":
                await self._bash(operation)
                return
            if operation.operation_type == "process.start":
                await self._process_start(operation)
                return
            if operation.operation_type == "process.write":
                await self._process_write(operation)
                return
            if operation.operation_type == "process.terminate_session":
                await self._process_terminate_session(operation)
                return
            await self._final_error(
                operation,
                "UNSUPPORTED_OPERATION",
                f"Unsupported Runner operation: {operation.operation_type}",
            )
        except asyncio.CancelledError:
            raise
        except RuntimeRunnerControlStreamClosed:
            raise
        except Exception as exc:
            await self._final_error(operation, "RUNNER_OPERATION_ERROR", str(exc))

    async def _contained_native_operation(
        self,
        operation: RunnerOperationEnvelope,
    ) -> None:
        async def emit(event: ContainedOperationEvent) -> None:
            payload = dict(event.payload)
            if event.binary is not None:
                if event.event_type != RuntimeRunnerEventType.FILE_CHUNK:
                    raise RuntimeError(
                        "contained helper sent binary data for an unsupported event"
                    )
                payload["data_base64"] = base64.b64encode(event.binary).decode()
            await self._event(
                operation,
                RuntimeRunnerEventType(event.event_type),
                payload,
                final=event.final,
            )

        async def run() -> None:
            await self._contained_operations.run(
                operation=operation.operation_type,
                payload=operation.payload,
                body_chunks=tuple(chunk.data for chunk in operation.body_chunks),
                deadline_at=operation.deadline_at,
                event_handler=emit,
            )

        if operation.operation_type == "file.apply_patch":
            async with self._apply_patch_lock:
                await run()
            return
        await run()

    async def cancel(self, operation: RunnerOperationEnvelope) -> None:
        """Publish terminal cancellation for work that has not started."""
        if operation.operation_type == "file.apply_patch":
            await self._event(
                operation,
                RuntimeRunnerEventType.FINAL_ERROR,
                {
                    "error_code": "FILE_APPLY_PATCH_FAILED",
                    "error_message": "Patch was cancelled before commit",
                    "file_apply_patch": {
                        "phase": "preflight",
                        "reason": "cancelled",
                        "message": "Patch was cancelled before commit",
                        "applied": [],
                        "failed": None,
                        "not_attempted": [],
                        "exact": True,
                    },
                },
                final=True,
            )
            return
        await self._final_error(
            operation,
            "RUNNER_OPERATION_CANCELLED",
            "Runner operation was cancelled before execution",
        )

    async def close(self) -> None:
        """Terminate managed processes before reconnecting."""
        records = tuple(self._processes.values())
        if not records:
            return
        started_at = time.monotonic()
        logger.info(
            "Runtime Runner process cleanup started",
            extra={"process_count": len(records)},
        )
        tasks = tuple(
            asyncio.create_task(
                self._terminate_process(
                    record,
                    status="terminated",
                    reason="runner_shutdown",
                )
            )
            for record in records
        )
        timed_out = False
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks),
                timeout=_PROCESS_CLOSE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            timed_out = True
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._force_terminate_processes(records)
            logger.warning(
                "Runtime Runner process cleanup timed out",
                extra={
                    "process_count": len(records),
                    "timeout_seconds": _PROCESS_CLOSE_TIMEOUT_SECONDS,
                },
            )
        except asyncio.CancelledError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._force_terminate_processes(records)
            raise
        finally:
            logger.info(
                "Runtime Runner process cleanup finished",
                extra={
                    "process_count": len(records),
                    "duration_ms": round(
                        (time.monotonic() - started_at) * 1000,
                        3,
                    ),
                    "timed_out": timed_out,
                },
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
        try:
            process = await self._execution_backend.start(
                shell_execution_spec(
                    backend=self._execution_backend,
                    command=command,
                    cwd=self._workspace.root,
                    workspace_path=str(self._workspace.root),
                    operation_environment=_str_mapping_payload(
                        operation.payload,
                        "env",
                    ),
                    managed=False,
                )
            )
        except ValueError as exc:
            await self._final_error(operation, "INVALID_ENVIRONMENT", str(exc))
            return
        except (OSError, RuntimeError) as exc:
            await self._final_error(operation, "COMMAND_START_FAILED", str(exc))
            return
        try:
            stdout, stderr = await self._communicate_process(
                process,
                timeout_seconds=timeout_seconds,
            )
        except TimeoutError:
            termination = await process.terminate_descendants(
                terminate_timeout_seconds=_PROCESS_TERMINATE_TIMEOUT_SECONDS,
                kill_timeout_seconds=_PROCESS_KILL_TIMEOUT_SECONDS,
            )
            self._log_backend_process_termination(
                operation,
                reason="command_timeout",
                termination=termination,
            )
            await self._final_error(operation, "COMMAND_TIMEOUT", "Command timed out")
            return
        except asyncio.CancelledError:
            termination = await process.terminate_descendants(
                terminate_timeout_seconds=_PROCESS_TERMINATE_TIMEOUT_SECONDS,
                kill_timeout_seconds=_PROCESS_KILL_TIMEOUT_SECONDS,
            )
            self._log_backend_process_termination(
                operation,
                reason="operation_cancelled",
                termination=termination,
            )
            raise
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

    async def _process_start(self, operation: RunnerOperationEnvelope) -> None:
        command = _str_payload(operation.payload, "command")
        if not command:
            await self._final_error(operation, "INVALID_PAYLOAD", "command is required")
            return
        owner_session_id = operation.owner_session_id
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
        try:
            process = await self._execution_backend.start(
                shell_execution_spec(
                    backend=self._execution_backend,
                    command=command,
                    cwd=cwd,
                    workspace_path=str(self._workspace.root),
                    operation_environment=_str_mapping_payload(
                        operation.payload,
                        "env",
                    ),
                    managed=True,
                )
            )
        except ValueError as exc:
            await self._final_error(operation, "INVALID_ENVIRONMENT", str(exc))
            return
        except OSError as exc:
            await self._final_error(operation, "PROCESS_START_FAILED", str(exc))
            return
        except RuntimeError as exc:
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
        owner_session_id = operation.owner_session_id
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
        process: ExecutionProcess,
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
        await record.process.write_stdin(stdin.encode())

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
        started_at = time.monotonic()
        self._processes.pop(record.process_id, None)
        already_exited = _process_exited(record)
        termination = None
        if not already_exited:
            termination = await record.process.terminate_descendants(
                terminate_timeout_seconds=_PROCESS_TERMINATE_TIMEOUT_SECONDS,
                kill_timeout_seconds=_PROCESS_KILL_TIMEOUT_SECONDS,
            )
            await self._wait_for_process_tasks(
                record,
                timeout_seconds=(
                    _PROCESS_TERMINATE_TIMEOUT_SECONDS + _PROCESS_KILL_TIMEOUT_SECONDS
                ),
            )
        tasks = tuple(
            task
            for task in (record.wait_task, *record.drain_tasks)
            if task is not None and not task.done()
        )
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._record_missing(record.process_id, status=status, reason=reason)
        logger.info(
            "Runtime Runner managed process cleanup finished",
            extra={
                "process_id": record.process_id,
                "status": status,
                "reason": reason,
                "already_exited": already_exited,
                "escalated": (False if termination is None else termination.escalated),
                "timed_out": (False if termination is None else termination.timed_out),
                "duration_ms": round(
                    (time.monotonic() - started_at) * 1000,
                    3,
                ),
            },
        )

    async def _wait_for_process_tasks(
        self,
        record: _ManagedProcess,
        *,
        timeout_seconds: float,
    ) -> bool:
        del self
        tasks = tuple(
            task
            for task in (record.wait_task, *record.drain_tasks)
            if task is not None and not task.done()
        )
        if not tasks:
            return True
        _done, pending = await asyncio.wait(tasks, timeout=timeout_seconds)
        return not pending

    async def _force_terminate_processes(
        self,
        records: tuple[_ManagedProcess, ...],
    ) -> None:
        del self
        await asyncio.gather(
            *(
                record.process.terminate_descendants(
                    terminate_timeout_seconds=0,
                    kill_timeout_seconds=_PROCESS_KILL_TIMEOUT_SECONDS,
                )
                for record in records
            ),
            return_exceptions=True,
        )

    async def _communicate_process(
        self,
        process: ExecutionProcess,
        *,
        timeout_seconds: int,
    ) -> tuple[bytes, bytes]:
        del self
        stdout_task = asyncio.create_task(process.stdout.read())
        stderr_task = asyncio.create_task(process.stderr.read())
        wait_task = asyncio.create_task(process.wait())
        tasks = (stdout_task, stderr_task, wait_task)
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks),
                timeout=timeout_seconds,
            )
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return stdout_task.result(), stderr_task.result()

    def _log_backend_process_termination(
        self,
        operation: RunnerOperationEnvelope,
        *,
        reason: str,
        termination: ProcessTerminationResult,
    ) -> None:
        del self
        logger.info(
            "Runtime Runner backend process cleanup finished",
            extra={
                "request_id": operation.request_id,
                "runtime_id": operation.runtime_id,
                "runner_generation": operation.runner_generation,
                "operation_type": operation.operation_type,
                "owner_session_id": operation.owner_session_id,
                "reason": reason,
                "escalated": termination.escalated,
                "timed_out": termination.timed_out,
            },
        )

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
