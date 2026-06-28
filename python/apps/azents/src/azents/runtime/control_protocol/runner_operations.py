"""Runner operation client built on the Agent Runtime control protocol."""

import asyncio
import base64
import dataclasses
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Literal

from azents.runtime.control_protocol.data import (
    RuntimeDispatchResult,
    RuntimeProtocolRouteUnavailable,
    RuntimeProtocolStaleGeneration,
    RuntimeRunnerOperation,
)
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.data import (
    JsonValue,
    RuntimeBodyChunk,
    RuntimeCoordinationTarget,
    RuntimeOperationStatus,
    RuntimeReplyEvent,
    RuntimeReplyEventType,
    RuntimeReplyRecord,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore

_DEFAULT_POLL_INTERVAL_SECONDS = 0.01
_DEFAULT_CANCEL_CHECK_INTERVAL_SECONDS = 1.0
_DEFAULT_BODY_CHUNK_SIZE_BYTES = 1024 * 1024

type RuntimeOperationCancelCheck = Callable[[], Awaitable[bool]]
type RuntimeProcessOutputCallback = Callable[
    ["RuntimeProcessOutputDelta"], Awaitable[None]
]


class RuntimeRunnerOperationUnavailable(RuntimeError):
    """Runner operation cannot be routed to a current Runner."""


class RuntimeRunnerOperationGenerationError(RuntimeError):
    """Runner operation used a stale Runner generation."""


class RuntimeRunnerOperationFailedError(RuntimeError):
    """Runner reported a final operation error."""


class RuntimeRunnerOperationCanceledError(RuntimeError):
    """Foreground Runner operation was cancelled by Control/User intent."""


@dataclasses.dataclass(frozen=True)
class RuntimeBashResult:
    """Completed bash operation result."""

    stdout: str
    stderr: str
    exit_code: int
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeFileReadResult:
    """Completed file read operation result."""

    data: bytes
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeFileListEntry:
    """Runner file list entry."""

    path: str
    type: Literal["file", "directory", "symlink", "other"]
    size_bytes: int | None
    modified_at: str | None = None


@dataclasses.dataclass(frozen=True)
class RuntimeFileListResult:
    """Completed file list operation result."""

    entries: tuple[RuntimeFileListEntry, ...]
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeFileStatResult:
    """Completed file stat operation result."""

    path: str
    kind: Literal["file", "directory", "symlink", "other", "missing"]
    size_bytes: int | None
    symlink: bool
    real_path: str | None
    resolved_kind: Literal["file", "directory", "symlink", "other", "missing"] | None
    modified_at: str | None
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeGrepLineMatch:
    """Runner grep line match."""

    line_number: int
    text: str


@dataclasses.dataclass(frozen=True)
class RuntimeGrepFileMatch:
    """Runner grep file match."""

    path: str
    lines: tuple[RuntimeGrepLineMatch, ...]
    truncated: bool


@dataclasses.dataclass(frozen=True)
class RuntimeGrepResult:
    """Completed grep operation result."""

    files: tuple[RuntimeGrepFileMatch, ...]
    searched_file_count: int
    matched_file_count: int
    truncated: bool
    stopped_reason: str | None
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeFileWriteResult:
    """Completed file write operation result."""

    bytes_written: int
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeProcessOutputDelta:
    """Live process output delta returned by Runner protocol."""

    process_id: str
    stream: Literal["stdout", "stderr"]
    chunk_id: int
    text: str
    truncated: bool
    omitted_bytes: int


@dataclasses.dataclass(frozen=True)
class RuntimeProcessResult:
    """Completed process operation snapshot result."""

    process_id: str
    status: Literal[
        "running",
        "exited_unread",
        "consumed",
        "missing",
        "terminated",
        "expired",
    ]
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    stdout_omitted_bytes: int
    stderr_omitted_bytes: int
    missing_reason: str | None
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeFileDeleteResult:
    """Completed file delete operation result."""

    path: str
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeFileMkdirResult:
    """Completed file mkdir operation result."""

    path: str
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeFileMoveResult:
    """Completed file move operation result."""

    source_path: str
    destination_path: str
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeOperationReceipt:
    """Background Runner operation receipt."""

    operation_id: str
    request_id: str
    reply_stream_id: str


type RuntimeForegroundResult = (
    RuntimeBashResult
    | RuntimeFileReadResult
    | RuntimeFileListResult
    | RuntimeFileStatResult
    | RuntimeGrepResult
    | RuntimeFileWriteResult
    | RuntimeProcessResult
    | RuntimeFileDeleteResult
    | RuntimeFileMkdirResult
    | RuntimeFileMoveResult
)


class RuntimeRunnerOperationClient:
    """High-level Runner operation client for Worker/API call sites."""

    def __init__(
        self,
        *,
        control_protocol: RuntimeControlProtocolService,
        coordination_store: RuntimeCoordinationStore,
        poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
        body_chunk_size_bytes: int = _DEFAULT_BODY_CHUNK_SIZE_BYTES,
    ) -> None:
        """Initialize the Runner operation client."""
        if body_chunk_size_bytes <= 0:
            raise ValueError("body_chunk_size_bytes must be positive")
        self._control_protocol = control_protocol
        self._coordination_store = coordination_store
        self._poll_interval_seconds = poll_interval_seconds
        self._body_chunk_size_bytes = body_chunk_size_bytes

    async def run_bash(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        command: str,
        timeout_seconds: int,
        env: dict[str, str] | None,
        deadline_at: datetime,
        cancel_check: RuntimeOperationCancelCheck | None = None,
    ) -> RuntimeBashResult:
        """Run a foreground bash operation and wait for final result."""
        env_payload: dict[str, JsonValue] | None = (
            dict(env) if env is not None else None
        )
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="bash",
                payload={
                    "command": command,
                    "timeout_seconds": timeout_seconds,
                    "env": env_payload,
                },
                deadline_at=deadline_at,
                body_stream_id=None,
                background=False,
            )
        )
        return await self.resume_bash(
            reply_stream_id=dispatch.reply_stream_id,
            after_cursor=None,
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
            cancel_check=cancel_check,
        )

    async def read_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        path: str,
        offset: int,
        max_bytes: int | None,
        deadline_at: datetime,
    ) -> RuntimeFileReadResult:
        """Run a foreground file read operation and wait for final result."""
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="file.read",
                payload={
                    "path": path,
                    "offset": offset,
                    "max_bytes": max_bytes,
                },
                deadline_at=deadline_at,
                body_stream_id=None,
                background=False,
            )
        )
        return await self.resume_file_read(
            reply_stream_id=dispatch.reply_stream_id,
            after_cursor=None,
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
        )

    async def write_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        path: str,
        data: bytes,
        deadline_at: datetime,
    ) -> RuntimeFileWriteResult:
        """Run a foreground file write operation through a request body stream."""
        body_stream_id = f"body:{runtime_id}:{datetime.now(timezone.utc).timestamp()}"
        await self._append_body_chunks(
            body_stream_id=body_stream_id,
            request_id=body_stream_id,
            data=data,
        )
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="file.write",
                payload={
                    "path": path,
                    "total_bytes": len(data),
                },
                deadline_at=deadline_at,
                body_stream_id=body_stream_id,
                background=False,
            )
        )
        return await self.resume_file_write(
            reply_stream_id=dispatch.reply_stream_id,
            after_cursor=None,
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
        )

    async def delete_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        path: str,
        recursive: bool,
        deadline_at: datetime,
    ) -> RuntimeFileDeleteResult:
        """Run a foreground file delete operation and wait for final result."""
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="file.delete",
                payload={"path": path, "recursive": recursive},
                deadline_at=deadline_at,
                body_stream_id=None,
                background=False,
            )
        )
        return await self.resume_file_delete(
            reply_stream_id=dispatch.reply_stream_id,
            after_cursor=None,
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
        )

    async def mkdir_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        path: str,
        parents: bool,
        deadline_at: datetime,
    ) -> RuntimeFileMkdirResult:
        """Run a foreground file mkdir operation and wait for final result."""
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="file.mkdir",
                payload={"path": path, "parents": parents},
                deadline_at=deadline_at,
                body_stream_id=None,
                background=False,
            )
        )
        return await self.resume_file_mkdir(
            reply_stream_id=dispatch.reply_stream_id,
            after_cursor=None,
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
        )

    async def move_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        source_path: str,
        destination_path: str,
        overwrite: bool,
        deadline_at: datetime,
    ) -> RuntimeFileMoveResult:
        """Run a foreground file move operation and wait for final result."""
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="file.move",
                payload={
                    "source_path": source_path,
                    "destination_path": destination_path,
                    "overwrite": overwrite,
                },
                deadline_at=deadline_at,
                body_stream_id=None,
                background=False,
            )
        )
        return await self.resume_file_move(
            reply_stream_id=dispatch.reply_stream_id,
            after_cursor=None,
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
        )

    async def list_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        path: str,
        recursive: bool = False,
        exclude_patterns: list[str] | None = None,
        deadline_at: datetime,
    ) -> RuntimeFileListResult:
        """Run a foreground file list operation and wait for final result."""
        payload: dict[str, JsonValue] = {"path": path, "recursive": recursive}
        if exclude_patterns is not None:
            payload["exclude_patterns"] = list(exclude_patterns)
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="file.list",
                payload=payload,
                deadline_at=deadline_at,
                body_stream_id=None,
                background=False,
            )
        )
        return await self.resume_file_list(
            reply_stream_id=dispatch.reply_stream_id,
            after_cursor=None,
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
        )

    async def stat_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        path: str,
        deadline_at: datetime,
    ) -> RuntimeFileStatResult:
        """Run foreground file stat operation and wait for final result."""
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="file.stat",
                payload={"path": path},
                deadline_at=deadline_at,
                body_stream_id=None,
                background=False,
            )
        )
        return await self.resume_file_stat(
            reply_stream_id=dispatch.reply_stream_id,
            after_cursor=None,
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
        )

    async def grep_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        path: str,
        pattern: str,
        recursive: bool = True,
        exclude_patterns: list[str] | None = None,
        max_matching_files: int = 50,
        max_lines_per_file: int = 10,
        max_searched_files: int | None = None,
        max_scanned_bytes: int | None = None,
        deadline_at: datetime,
    ) -> RuntimeGrepResult:
        """Run a foreground file grep operation and wait for final result."""
        payload: dict[str, JsonValue] = {
            "path": path,
            "pattern": pattern,
            "recursive": recursive,
            "max_matching_files": max_matching_files,
            "max_lines_per_file": max_lines_per_file,
        }
        if exclude_patterns is not None:
            payload["exclude_patterns"] = list(exclude_patterns)
        if max_searched_files is not None:
            payload["max_searched_files"] = max_searched_files
        if max_scanned_bytes is not None:
            payload["max_scanned_bytes"] = max_scanned_bytes
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="file.grep",
                payload=payload,
                deadline_at=deadline_at,
                body_stream_id=None,
                background=False,
            )
        )
        return await self.resume_grep_files(
            reply_stream_id=dispatch.reply_stream_id,
            after_cursor=None,
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
        )

    async def start_process(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        command: str,
        workdir: str | None,
        yield_time_ms: int,
        max_output_bytes: int,
        env: dict[str, str] | None,
        owner_session_id: str,
        deadline_at: datetime,
        process_output_callback: RuntimeProcessOutputCallback | None = None,
    ) -> RuntimeProcessResult:
        """Start a pipe-based process and wait for the operation snapshot."""
        payload: dict[str, JsonValue] = {
            "command": command,
            "yield_time_ms": yield_time_ms,
            "max_output_bytes": max_output_bytes,
            "owner_session_id": owner_session_id,
        }
        if workdir is not None:
            payload["workdir"] = workdir
        if env is not None:
            payload["env"] = dict(env)
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="process.start",
                payload=payload,
                deadline_at=deadline_at,
                body_stream_id=None,
                background=False,
            )
        )
        return await self.resume_process(
            reply_stream_id=dispatch.reply_stream_id,
            after_cursor=None,
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
            process_output_callback=process_output_callback,
        )

    async def write_process_stdin(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        process_id: str,
        stdin: str,
        yield_time_ms: int,
        max_output_bytes: int,
        owner_session_id: str,
        deadline_at: datetime,
        process_output_callback: RuntimeProcessOutputCallback | None = None,
    ) -> RuntimeProcessResult:
        """Write stdin to a pipe-based process or poll with empty stdin."""
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="process.write",
                payload={
                    "process_id": process_id,
                    "stdin": stdin,
                    "yield_time_ms": yield_time_ms,
                    "max_output_bytes": max_output_bytes,
                    "owner_session_id": owner_session_id,
                },
                deadline_at=deadline_at,
                body_stream_id=None,
                background=False,
            )
        )
        return await self.resume_process(
            reply_stream_id=dispatch.reply_stream_id,
            after_cursor=None,
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
            process_output_callback=process_output_callback,
        )

    async def start_background_operation(
        self,
        operation: RuntimeRunnerOperation,
    ) -> RuntimeOperationReceipt:
        """Dispatch a background Runner operation without waiting for final reply."""
        dispatch = await self._dispatch_runner_operation(
            dataclasses.replace(operation, background=True)
        )
        return RuntimeOperationReceipt(
            operation_id=dispatch.operation_id,
            request_id=dispatch.request_id,
            reply_stream_id=dispatch.reply_stream_id,
        )

    async def resume_bash(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
        cancel_check: RuntimeOperationCancelCheck | None = None,
    ) -> RuntimeBashResult:
        """Resume reading a bash operation reply stream until final result."""
        folder = _ReplyFolder(after_cursor=after_cursor)
        final = await self._read_until_final(
            reply_stream_id,
            folder,
            request_id=request_id,
            operation_id=operation_id,
            runtime_id=runtime_id,
            generation=generation,
            deadline_at=deadline_at,
            cancel_check=cancel_check,
        )
        exit_code = _int_payload(final.event.payload, "exit_code", default=0)
        return RuntimeBashResult(
            stdout="".join(folder.stdout),
            stderr="".join(folder.stderr),
            exit_code=exit_code,
            final_cursor=final.cursor,
        )

    async def resume_file_read(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
    ) -> RuntimeFileReadResult:
        """Resume reading a file read reply stream until final result."""
        folder = _ReplyFolder(after_cursor=after_cursor)
        final = await self._read_until_final(
            reply_stream_id,
            folder,
            request_id=request_id,
            operation_id=operation_id,
            runtime_id=runtime_id,
            generation=generation,
            deadline_at=deadline_at,
        )
        return RuntimeFileReadResult(
            data=b"".join(folder.file_chunks),
            final_cursor=final.cursor,
        )

    async def resume_file_list(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
    ) -> RuntimeFileListResult:
        """Resume reading a file list reply stream until final result."""
        folder = _ReplyFolder(after_cursor=after_cursor)
        final = await self._read_until_final(
            reply_stream_id,
            folder,
            request_id=request_id,
            operation_id=operation_id,
            runtime_id=runtime_id,
            generation=generation,
            deadline_at=deadline_at,
        )
        entries = tuple(_file_list_entries(final.event.payload))
        return RuntimeFileListResult(entries=entries, final_cursor=final.cursor)

    async def resume_file_stat(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
    ) -> RuntimeFileStatResult:
        """Read file stat reply stream until final result."""
        folder = _ReplyFolder(after_cursor=after_cursor)
        final = await self._read_until_final(
            reply_stream_id,
            folder,
            request_id=request_id,
            operation_id=operation_id,
            runtime_id=runtime_id,
            generation=generation,
            deadline_at=deadline_at,
        )
        return _file_stat_result(final.event.payload, final_cursor=final.cursor)

    async def resume_file_write(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
    ) -> RuntimeFileWriteResult:
        """Resume reading a file write reply stream until final result."""
        folder = _ReplyFolder(after_cursor=after_cursor)
        final = await self._read_until_final(
            reply_stream_id,
            folder,
            request_id=request_id,
            operation_id=operation_id,
            runtime_id=runtime_id,
            generation=generation,
            deadline_at=deadline_at,
        )
        return RuntimeFileWriteResult(
            bytes_written=_int_payload(final.event.payload, "bytes_written", default=0),
            final_cursor=final.cursor,
        )

    async def resume_file_delete(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
    ) -> RuntimeFileDeleteResult:
        """Resume reading a file delete reply stream until final result."""
        folder = _ReplyFolder(after_cursor=after_cursor)
        final = await self._read_until_final(
            reply_stream_id,
            folder,
            request_id=request_id,
            operation_id=operation_id,
            runtime_id=runtime_id,
            generation=generation,
            deadline_at=deadline_at,
        )
        return RuntimeFileDeleteResult(
            path=_str_payload(final.event.payload, "deleted_path"),
            final_cursor=final.cursor,
        )

    async def resume_file_mkdir(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
    ) -> RuntimeFileMkdirResult:
        """Resume reading a file mkdir reply stream until final result."""
        folder = _ReplyFolder(after_cursor=after_cursor)
        final = await self._read_until_final(
            reply_stream_id,
            folder,
            request_id=request_id,
            operation_id=operation_id,
            runtime_id=runtime_id,
            generation=generation,
            deadline_at=deadline_at,
        )
        return RuntimeFileMkdirResult(
            path=_str_payload(final.event.payload, "created_path"),
            final_cursor=final.cursor,
        )

    async def resume_file_move(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
    ) -> RuntimeFileMoveResult:
        """Resume reading a file move reply stream until final result."""
        folder = _ReplyFolder(after_cursor=after_cursor)
        final = await self._read_until_final(
            reply_stream_id,
            folder,
            request_id=request_id,
            operation_id=operation_id,
            runtime_id=runtime_id,
            generation=generation,
            deadline_at=deadline_at,
        )
        return RuntimeFileMoveResult(
            source_path=_str_payload(final.event.payload, "moved_source_path"),
            destination_path=_str_payload(
                final.event.payload, "moved_destination_path"
            ),
            final_cursor=final.cursor,
        )

    async def resume_grep_files(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
    ) -> RuntimeGrepResult:
        """Resume reading a grep reply stream until final result."""
        folder = _ReplyFolder(after_cursor=after_cursor)
        final = await self._read_until_final(
            reply_stream_id,
            folder,
            request_id=request_id,
            operation_id=operation_id,
            runtime_id=runtime_id,
            generation=generation,
            deadline_at=deadline_at,
        )
        return RuntimeGrepResult(
            files=tuple(_grep_file_matches(final.event.payload)),
            searched_file_count=_int_payload(
                final.event.payload,
                "searched_file_count",
                default=0,
            ),
            matched_file_count=_int_payload(
                final.event.payload,
                "matched_file_count",
                default=0,
            ),
            truncated=_bool_payload(final.event.payload, "truncated", default=False),
            stopped_reason=_optional_str_payload(final.event.payload, "stopped_reason"),
            final_cursor=final.cursor,
        )

    async def resume_process(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
        process_output_callback: RuntimeProcessOutputCallback | None = None,
    ) -> RuntimeProcessResult:
        """Resume reading a process operation reply stream until final snapshot."""
        folder = _ReplyFolder(
            after_cursor=after_cursor,
            process_output_callback=process_output_callback,
        )
        final = await self._read_until_final(
            reply_stream_id,
            folder,
            request_id=request_id,
            operation_id=operation_id,
            runtime_id=runtime_id,
            generation=generation,
            deadline_at=deadline_at,
        )
        result = _process_result(final.event.payload, final_cursor=final.cursor)
        stdout = result.stdout or "".join(folder.process_stdout)
        stderr = result.stderr or "".join(folder.process_stderr)
        return dataclasses.replace(result, stdout=stdout, stderr=stderr)

    async def _dispatch_runner_operation(
        self,
        operation: RuntimeRunnerOperation,
    ) -> RuntimeDispatchResult:
        result = await self._control_protocol.dispatch_runner_operation(
            operation,
            created_at=datetime.now(timezone.utc),
        )
        if isinstance(result, RuntimeProtocolRouteUnavailable):
            raise RuntimeRunnerOperationUnavailable(
                f"Runner operation route unavailable: {result.subject_id}"
            )
        if isinstance(result, RuntimeProtocolStaleGeneration):
            raise RuntimeRunnerOperationGenerationError(
                f"Runner generation is stale: {result.subject_id}:{result.generation}"
            )
        return result

    async def _append_body_chunks(
        self,
        *,
        body_stream_id: str,
        request_id: str,
        data: bytes,
    ) -> None:
        if not data:
            await self._coordination_store.append_body_chunk(
                body_stream_id,
                RuntimeBodyChunk(
                    request_id=request_id,
                    chunk_id=1,
                    data=b"",
                    created_at=datetime.now(timezone.utc),
                    final=True,
                ),
            )
            return
        chunk_id = 1
        for offset in range(0, len(data), self._body_chunk_size_bytes):
            end = offset + self._body_chunk_size_bytes
            await self._coordination_store.append_body_chunk(
                body_stream_id,
                RuntimeBodyChunk(
                    request_id=request_id,
                    chunk_id=chunk_id,
                    data=data[offset:end],
                    created_at=datetime.now(timezone.utc),
                    final=end >= len(data),
                ),
            )
            chunk_id += 1

    async def _read_until_final(
        self,
        reply_stream_id: str,
        folder: "_ReplyFolder",
        *,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
        cancel_check: RuntimeOperationCancelCheck | None = None,
    ) -> RuntimeReplyRecord:
        cursor = folder.after_cursor
        next_cancel_check_at = 0.0
        try:
            while True:
                now = datetime.now(timezone.utc)
                if now >= deadline_at:
                    await self._append_local_final_error(
                        reply_stream_id=reply_stream_id,
                        request_id=request_id,
                        operation_id=operation_id,
                        runtime_id=runtime_id,
                        generation=generation,
                        code="operation_timeout",
                        message="Runtime operation timed out",
                        created_at=now,
                    )
                    raise RuntimeRunnerOperationFailedError(
                        "Runtime operation timed out"
                    )
                if (
                    cancel_check is not None
                    and time.monotonic() >= next_cancel_check_at
                    and await cancel_check()
                ):
                    await self._append_local_final_error(
                        reply_stream_id=reply_stream_id,
                        request_id=request_id,
                        operation_id=operation_id,
                        runtime_id=runtime_id,
                        generation=generation,
                        code="canceled",
                        message="Runtime operation cancelled",
                        created_at=now,
                    )
                    raise RuntimeRunnerOperationCanceledError(
                        "Runtime operation cancelled"
                    )
                next_cancel_check_at = (
                    time.monotonic() + _DEFAULT_CANCEL_CHECK_INTERVAL_SECONDS
                )
                records = await self._control_protocol.read_replies(
                    reply_stream_id=reply_stream_id,
                    after_cursor=cursor,
                    limit=100,
                )
                if not records:
                    await asyncio.sleep(self._poll_interval_seconds)
                    continue
                for record in records:
                    cursor = record.cursor
                    if request_id is not None and record.event.request_id != request_id:
                        continue
                    await folder.apply(record)
                    if record.event.final:
                        if record.event.event_type == RuntimeReplyEventType.FINAL_ERROR:
                            raise RuntimeRunnerOperationFailedError(
                                _error_message(record.event.payload)
                            )
                        return record
        except asyncio.CancelledError:
            await self._append_local_final_error(
                reply_stream_id=reply_stream_id,
                request_id=request_id,
                operation_id=operation_id,
                runtime_id=runtime_id,
                generation=generation,
                code="canceled",
                message="Runtime operation cancelled",
                created_at=datetime.now(timezone.utc),
            )
            raise

    async def _append_local_final_error(
        self,
        *,
        reply_stream_id: str,
        request_id: str | None,
        operation_id: str | None,
        runtime_id: str | None,
        generation: int | None,
        code: str,
        message: str,
        created_at: datetime,
    ) -> None:
        if (
            request_id is None
            or operation_id is None
            or runtime_id is None
            or generation is None
        ):
            return
        cursor = await self._coordination_store.append_reply(
            reply_stream_id,
            RuntimeReplyEvent(
                request_id=request_id,
                runtime_id=runtime_id,
                generation=generation,
                event_type=RuntimeReplyEventType.FINAL_ERROR,
                payload={"error_code": code, "error_message": message},
                created_at=created_at,
                final=True,
            ),
        )
        await self._coordination_store.update_operation_status(
            operation_id,
            status=RuntimeOperationStatus.FINAL,
            updated_at=created_at,
            final_event_cursor=cursor,
        )


@dataclasses.dataclass
class _ReplyFolder:
    """Mutable accumulator for a foreground operation reply stream."""

    after_cursor: str | None
    stdout: list[str] = dataclasses.field(default_factory=list)
    stderr: list[str] = dataclasses.field(default_factory=list)
    file_chunks: list[bytes] = dataclasses.field(default_factory=list)
    process_stdout: list[str] = dataclasses.field(default_factory=list)
    process_stderr: list[str] = dataclasses.field(default_factory=list)
    process_output_callback: RuntimeProcessOutputCallback | None = None

    async def apply(self, record: RuntimeReplyRecord) -> None:
        """Fold one reply record into accumulated output state."""
        event = record.event
        if event.event_type == RuntimeReplyEventType.STDOUT:
            self.stdout.append(_str_payload(event.payload, "text"))
            return
        if event.event_type == RuntimeReplyEventType.STDERR:
            self.stderr.append(_str_payload(event.payload, "text"))
            return
        if event.event_type == RuntimeReplyEventType.FILE_CHUNK:
            self.file_chunks.append(
                base64.b64decode(_str_payload(event.payload, "data_base64"))
            )
            return
        if event.event_type == RuntimeReplyEventType.PROCESS_OUTPUT:
            stream = _str_payload(event.payload, "stream")
            text = _str_payload(event.payload, "text")
            if stream == "stdout":
                self.process_stdout.append(text)
            elif stream == "stderr":
                self.process_stderr.append(text)
            else:
                return
            if self.process_output_callback is not None:
                await self.process_output_callback(
                    RuntimeProcessOutputDelta(
                        process_id=_str_payload(event.payload, "process_id"),
                        stream=stream,
                        chunk_id=_int_payload(event.payload, "chunk_id", default=0),
                        text=text,
                        truncated=_bool_payload(
                            event.payload, "truncated", default=False
                        ),
                        omitted_bytes=_int_payload(
                            event.payload, "omitted_bytes", default=0
                        ),
                    )
                )


def _str_payload(payload: dict[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        return ""
    return value


def _optional_str_payload(payload: dict[str, JsonValue], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _int_payload(
    payload: dict[str, JsonValue],
    key: str,
    *,
    default: int,
) -> int:
    value = payload.get(key)
    if isinstance(value, int):
        return value
    return default


def _bool_payload(
    payload: dict[str, JsonValue],
    key: str,
    *,
    default: bool,
) -> bool:
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    return default


def _error_message(payload: dict[str, JsonValue]) -> str:
    code = _str_payload(payload, "error_code")
    message = _str_payload(payload, "error_message")
    if code and message:
        return f"{code}: {message}"
    return message or code or "Runner operation failed"


def _file_list_entries(
    payload: dict[str, JsonValue],
) -> list[RuntimeFileListEntry]:
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        return []
    entries: list[RuntimeFileListEntry] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        path = raw_entry.get("path")
        entry_type = raw_entry.get("type")
        size_bytes = raw_entry.get("size_bytes")
        if not isinstance(path, str):
            continue
        parsed_type = _file_entry_type(entry_type)
        if parsed_type is None:
            continue
        entries.append(
            RuntimeFileListEntry(
                path=path,
                type=parsed_type,
                size_bytes=size_bytes if isinstance(size_bytes, int) else None,
                modified_at=_optional_str_payload(raw_entry, "modified_at"),
            )
        )
    return entries


def _file_stat_result(
    payload: dict[str, JsonValue],
    *,
    final_cursor: str,
) -> RuntimeFileStatResult:
    """Convert file.stat final payload to result object."""
    kind = _file_stat_kind(payload.get("kind"))
    resolved_kind = _file_stat_kind(payload.get("resolved_kind"))
    size_bytes = payload.get("size_bytes")
    return RuntimeFileStatResult(
        path=_str_payload(payload, "path"),
        kind=kind or "other",
        size_bytes=(
            size_bytes
            if isinstance(size_bytes, int) and not isinstance(size_bytes, bool)
            else None
        ),
        symlink=_bool_payload(payload, "symlink", default=False),
        real_path=_optional_str_payload(payload, "real_path"),
        resolved_kind=resolved_kind,
        modified_at=_optional_str_payload(payload, "modified_at"),
        final_cursor=final_cursor,
    )


def _file_stat_kind(
    value: object,
) -> Literal["file", "directory", "symlink", "other", "missing"] | None:
    if value == "file":
        return "file"
    if value == "directory":
        return "directory"
    if value == "symlink":
        return "symlink"
    if value == "other":
        return "other"
    if value == "missing":
        return "missing"
    return None


def _process_result(
    payload: dict[str, JsonValue],
    *,
    final_cursor: str,
) -> RuntimeProcessResult:
    status = _process_status(payload.get("status"))
    exit_code = payload.get("exit_code")
    return RuntimeProcessResult(
        process_id=_str_payload(payload, "process_id"),
        status=status or "missing",
        exit_code=(
            exit_code
            if isinstance(exit_code, int) and not isinstance(exit_code, bool)
            else None
        ),
        stdout=_str_payload(payload, "stdout"),
        stderr=_str_payload(payload, "stderr"),
        stdout_truncated=_bool_payload(payload, "stdout_truncated", default=False),
        stderr_truncated=_bool_payload(payload, "stderr_truncated", default=False),
        stdout_omitted_bytes=_int_payload(payload, "stdout_omitted_bytes", default=0),
        stderr_omitted_bytes=_int_payload(payload, "stderr_omitted_bytes", default=0),
        missing_reason=_optional_str_payload(payload, "missing_reason"),
        final_cursor=final_cursor,
    )


def _process_status(
    value: object,
) -> (
    Literal[
        "running",
        "exited_unread",
        "consumed",
        "missing",
        "terminated",
        "expired",
    ]
    | None
):
    if value == "running":
        return "running"
    if value == "exited_unread":
        return "exited_unread"
    if value == "consumed":
        return "consumed"
    if value == "missing":
        return "missing"
    if value == "terminated":
        return "terminated"
    if value == "expired":
        return "expired"
    return None


def _grep_file_matches(
    payload: dict[str, JsonValue],
) -> list[RuntimeGrepFileMatch]:
    raw_files = payload.get("files")
    if not isinstance(raw_files, list):
        return []
    files: list[RuntimeGrepFileMatch] = []
    for raw_file in raw_files:
        if not isinstance(raw_file, dict):
            continue
        path = raw_file.get("path")
        if not isinstance(path, str):
            continue
        files.append(
            RuntimeGrepFileMatch(
                path=path,
                lines=tuple(_grep_line_matches(raw_file)),
                truncated=_bool_value(raw_file.get("truncated")),
            )
        )
    return files


def _grep_line_matches(payload: dict[str, JsonValue]) -> list[RuntimeGrepLineMatch]:
    raw_lines = payload.get("lines")
    if not isinstance(raw_lines, list):
        return []
    lines: list[RuntimeGrepLineMatch] = []
    for raw_line in raw_lines:
        if not isinstance(raw_line, dict):
            continue
        line_number = raw_line.get("line_number")
        text = raw_line.get("text")
        if not isinstance(line_number, int) or not isinstance(text, str):
            continue
        lines.append(RuntimeGrepLineMatch(line_number=line_number, text=text))
    return lines


def _bool_value(value: JsonValue | None) -> bool:
    return value if isinstance(value, bool) else False


def _file_entry_type(
    value: object,
) -> Literal["file", "directory", "symlink", "other"] | None:
    if value == "file":
        return "file"
    if value == "directory":
        return "directory"
    if value == "symlink":
        return "symlink"
    if value == "other":
        return "other"
    return None


def encode_file_chunk(data: bytes) -> str:
    """Encode binary file chunk data for Runner reply event payloads."""
    return base64.b64encode(data).decode()


def runner_reply_target() -> RuntimeCoordinationTarget:
    """Return the Runner reply target for tests and adapter call sites."""
    return RuntimeCoordinationTarget.RUNNER
