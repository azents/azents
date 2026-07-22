"""Runner operation client built on the Agent Runtime control protocol."""

import asyncio
import base64
import dataclasses
import time
from collections.abc import Awaitable, Callable, Sequence
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
    RuntimeReplyEvent,
    RuntimeReplyEventType,
    RuntimeReplyRecord,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore

_DEFAULT_POLL_INTERVAL_SECONDS = 0.01
_DEFAULT_CANCEL_CHECK_INTERVAL_SECONDS = 1.0
_DEFAULT_BODY_CHUNK_SIZE_BYTES = 1024 * 1024

type RuntimeOperationCancelCheck = Callable[[], Awaitable[bool]]
type RuntimeOperationTextCallback = Callable[
    ["RuntimeOperationTextDelta"], Awaitable[None]
]
type RuntimeProcessOutputCallback = Callable[
    ["RuntimeProcessOutputDelta"], Awaitable[None]
]


class RuntimeRunnerOperationUnavailable(RuntimeError):
    """Runner operation cannot be routed to a current Runner."""


class RuntimeRunnerOperationGenerationError(RuntimeError):
    """Runner operation used a stale Runner generation."""


class RuntimeRunnerOperationFailedError(RuntimeError):
    """Runner reported a final operation error."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        """Initialize the failure with its stable semantic code."""
        super().__init__(message)
        self.code = code


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
class RuntimeFileEditResult:
    """Completed file edit operation result."""

    replacements: int
    final_cursor: str


type RuntimeFilePatchAction = Literal["add", "update", "delete"]
type RuntimeFilePatchPhase = Literal[
    "parse",
    "preflight",
    "stage",
    "revalidate",
    "commit",
]


@dataclasses.dataclass(frozen=True)
class RuntimeFilePatchOperation:
    """One file operation referenced by a patch result."""

    path: str
    action: RuntimeFilePatchAction


@dataclasses.dataclass(frozen=True)
class RuntimeFilePatchChange:
    """One file change committed by a patch operation."""

    path: str
    action: RuntimeFilePatchAction
    added_lines: int
    removed_lines: int
    content_sha256: str | None


@dataclasses.dataclass(frozen=True)
class RuntimeFileApplyPatchFailure:
    """Typed patch failure detail returned by Runtime Runner."""

    phase: RuntimeFilePatchPhase
    reason: str
    applied: tuple[RuntimeFilePatchChange, ...]
    failed: RuntimeFilePatchOperation | None
    not_attempted: tuple[RuntimeFilePatchOperation, ...]
    exact: bool


@dataclasses.dataclass(frozen=True)
class RuntimeFileApplyPatchResult:
    """Completed file patch operation result."""

    changes: tuple[RuntimeFilePatchChange, ...]
    final_cursor: str


class RuntimeFileApplyPatchFailedError(RuntimeRunnerOperationFailedError):
    """Runtime Runner returned a typed file patch failure."""

    def __init__(self, message: str, *, failure: RuntimeFileApplyPatchFailure) -> None:
        """Initialize the patch failure with its committed-delta detail."""
        super().__init__(message)
        self.failure = failure


@dataclasses.dataclass(frozen=True)
class RuntimeOperationTextDelta:
    """Live stdout or stderr text delta returned by Runner protocol."""

    stream: Literal["stdout", "stderr"]
    text: str


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
class RuntimeFileMoveEntry:
    """Runner file move entry."""

    source_path: str
    destination_path: str


@dataclasses.dataclass(frozen=True)
class RuntimeFileBulkDeleteResult:
    """Completed file bulk delete operation result."""

    paths: tuple[str, ...]
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeFileBulkMoveResult:
    """Completed file bulk move operation result."""

    entries: tuple[RuntimeFileMoveEntry, ...]
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeGitRefEntry:
    """Git ref entry discovered by the Runtime Runner."""

    name: str
    ref: str
    type: Literal["branch", "remote_branch", "tag", "other"]
    target: str
    default: bool


@dataclasses.dataclass(frozen=True)
class RuntimeGitRefsResult:
    """Completed Git ref discovery operation result."""

    refs: tuple[RuntimeGitRefEntry, ...]
    default_branch: str | None
    head_commit: str | None
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeGitCreateWorktreeResult:
    """Completed Git worktree creation operation result."""

    base_commit: str
    worktree_path: str
    branch_name: str
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeGitInspectWorktreeResult:
    """Completed Git worktree inspection result."""

    worktree_path: str
    registered: bool
    registered_branch_name: str | None
    target_kind: Literal["directory", "missing", "other"]
    dirty: bool | None
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeGitRemoveWorktreeResult:
    """Completed Git worktree removal operation result."""

    worktree_path: str
    outcome: Literal["removed", "already_absent"]
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeGitDeleteBranchResult:
    """Completed Git branch deletion operation result."""

    branch_name: str
    outcome: Literal["deleted", "already_absent"]
    final_cursor: str


type RuntimeForegroundResult = (
    RuntimeBashResult
    | RuntimeFileReadResult
    | RuntimeFileListResult
    | RuntimeFileStatResult
    | RuntimeGrepResult
    | RuntimeFileWriteResult
    | RuntimeFileEditResult
    | RuntimeFileApplyPatchResult
    | RuntimeProcessResult
    | RuntimeFileDeleteResult
    | RuntimeFileMkdirResult
    | RuntimeFileMoveResult
    | RuntimeFileBulkDeleteResult
    | RuntimeFileBulkMoveResult
    | RuntimeGitRefsResult
    | RuntimeGitCreateWorktreeResult
    | RuntimeGitInspectWorktreeResult
    | RuntimeGitRemoveWorktreeResult
    | RuntimeGitDeleteBranchResult
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
        owner_session_id: str | None,
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
                owner_session_id=owner_session_id,
                payload={
                    "command": command,
                    "timeout_seconds": timeout_seconds,
                    "env": env_payload,
                },
                deadline_at=deadline_at,
                body_stream_id=None,
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
        owner_session_id: str | None,
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
                owner_session_id=owner_session_id,
                payload={
                    "path": path,
                    "offset": offset,
                    "max_bytes": max_bytes,
                },
                deadline_at=deadline_at,
                body_stream_id=None,
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
        owner_session_id: str | None,
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
                owner_session_id=owner_session_id,
                payload={
                    "path": path,
                    "total_bytes": len(data),
                },
                deadline_at=deadline_at,
                body_stream_id=body_stream_id,
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

    async def apply_patch(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        base_path: str,
        patch: bytes,
        schema_version: int,
        deadline_at: datetime,
    ) -> RuntimeFileApplyPatchResult:
        """Run a file patch operation through a request body stream."""
        body_stream_id = f"body:{runtime_id}:{datetime.now(timezone.utc).timestamp()}"
        await self._append_body_chunks(
            body_stream_id=body_stream_id,
            request_id=body_stream_id,
            data=patch,
        )
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="file.apply_patch",
                owner_session_id=owner_session_id,
                payload={
                    "base_path": base_path,
                    "total_bytes": len(patch),
                    "schema_version": schema_version,
                },
                deadline_at=deadline_at,
                body_stream_id=body_stream_id,
            )
        )
        resume_task = asyncio.create_task(
            self.resume_file_apply_patch(
                reply_stream_id=dispatch.reply_stream_id,
                after_cursor=None,
                request_id=dispatch.request_id,
                operation_id=dispatch.operation_id,
                runtime_id=runtime_id,
                generation=runner_generation,
                deadline_at=deadline_at,
            )
        )
        cancel_requested = False
        while True:
            try:
                return await asyncio.shield(resume_task)
            except asyncio.CancelledError:
                current_task = asyncio.current_task()
                if current_task is not None:
                    current_task.uncancel()
                if cancel_requested:
                    continue
                cancel_requested = True
                await self._control_protocol.request_runner_operation_cancel(
                    runtime_id=runtime_id,
                    runner_generation=runner_generation,
                    operation_id=dispatch.operation_id,
                    created_at=datetime.now(timezone.utc),
                )

    async def edit_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool,
        deadline_at: datetime,
    ) -> RuntimeFileEditResult:
        """Run one atomic text replacement in the Runtime Runner."""
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="file.edit",
                owner_session_id=owner_session_id,
                payload={
                    "path": path,
                    "old_string": old_string,
                    "new_string": new_string,
                    "replace_all": replace_all,
                },
                deadline_at=deadline_at,
                body_stream_id=None,
            )
        )
        return await self.resume_file_edit(
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
        owner_session_id: str | None,
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
                owner_session_id=owner_session_id,
                payload={"path": path, "recursive": recursive},
                deadline_at=deadline_at,
                body_stream_id=None,
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

    async def bulk_delete_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        paths: list[str],
        recursive: bool,
        deadline_at: datetime,
    ) -> RuntimeFileBulkDeleteResult:
        """Run a foreground file bulk delete operation and wait for final result."""
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="file.bulk_delete",
                owner_session_id=owner_session_id,
                payload={"paths": list(paths), "recursive": recursive},
                deadline_at=deadline_at,
                body_stream_id=None,
            )
        )
        return await self.resume_file_bulk_delete(
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
        owner_session_id: str | None,
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
                owner_session_id=owner_session_id,
                payload={"path": path, "parents": parents},
                deadline_at=deadline_at,
                body_stream_id=None,
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
        owner_session_id: str | None,
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
                owner_session_id=owner_session_id,
                payload={
                    "source_path": source_path,
                    "destination_path": destination_path,
                    "overwrite": overwrite,
                },
                deadline_at=deadline_at,
                body_stream_id=None,
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

    async def bulk_move_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        source_paths: list[str],
        destination_directory: str,
        overwrite: bool,
        deadline_at: datetime,
    ) -> RuntimeFileBulkMoveResult:
        """Run a foreground file bulk move operation and wait for final result."""
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="file.bulk_move",
                owner_session_id=owner_session_id,
                payload={
                    "source_paths": list(source_paths),
                    "destination_directory": destination_directory,
                    "overwrite": overwrite,
                },
                deadline_at=deadline_at,
                body_stream_id=None,
            )
        )
        return await self.resume_file_bulk_move(
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
        owner_session_id: str | None,
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
                owner_session_id=owner_session_id,
                payload=payload,
                deadline_at=deadline_at,
                body_stream_id=None,
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

    async def glob_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        pattern: str,
        exclude_patterns: list[str] | None,
        deadline_at: datetime,
    ) -> RuntimeFileListResult:
        """Run a foreground file glob operation and wait for final result."""
        payload: dict[str, JsonValue] = {"pattern": pattern}
        if exclude_patterns is not None:
            payload["exclude_patterns"] = list(exclude_patterns)
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="file.glob",
                owner_session_id=owner_session_id,
                payload=payload,
                deadline_at=deadline_at,
                body_stream_id=None,
            )
        )
        return await self.resume_file_glob(
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
        owner_session_id: str | None,
        path: str,
        deadline_at: datetime,
    ) -> RuntimeFileStatResult:
        """Run foreground file stat operation and wait for final result."""
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="file.stat",
                owner_session_id=owner_session_id,
                payload={"path": path},
                deadline_at=deadline_at,
                body_stream_id=None,
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
        owner_session_id: str | None,
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
                owner_session_id=owner_session_id,
                payload=payload,
                deadline_at=deadline_at,
                body_stream_id=None,
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

    async def list_git_refs(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        source_project_path: str,
        deadline_at: datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitRefsResult:
        """Run a foreground Git ref discovery operation and wait for final result."""
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="list_git_refs",
                owner_session_id=owner_session_id,
                payload={"source_project_path": source_project_path},
                deadline_at=deadline_at,
                body_stream_id=None,
            )
        )
        return await self.resume_git_refs(
            reply_stream_id=dispatch.reply_stream_id,
            after_cursor=None,
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
            text_output_callback=text_output_callback,
        )

    async def create_git_worktree(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        source_project_path: str,
        worktree_path: str,
        branch_name: str,
        starting_ref: str,
        deadline_at: datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitCreateWorktreeResult:
        """Run a foreground Git worktree creation operation."""
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="create_git_worktree",
                owner_session_id=owner_session_id,
                payload={
                    "source_project_path": source_project_path,
                    "worktree_path": worktree_path,
                    "branch_name": branch_name,
                    "starting_ref": starting_ref,
                },
                deadline_at=deadline_at,
                body_stream_id=None,
            )
        )
        return await self.resume_git_create_worktree(
            reply_stream_id=dispatch.reply_stream_id,
            after_cursor=None,
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
            text_output_callback=text_output_callback,
        )

    async def remove_git_worktree(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        source_project_path: str,
        worktree_path: str,
        branch_name: str,
        force: bool,
        deadline_at: datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitRemoveWorktreeResult:
        """Run a foreground Git worktree removal operation."""
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="remove_git_worktree",
                owner_session_id=owner_session_id,
                payload={
                    "source_project_path": source_project_path,
                    "worktree_path": worktree_path,
                    "branch_name": branch_name,
                    "force": force,
                },
                deadline_at=deadline_at,
                body_stream_id=None,
            )
        )
        return await self.resume_git_remove_worktree(
            reply_stream_id=dispatch.reply_stream_id,
            after_cursor=None,
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
            text_output_callback=text_output_callback,
        )

    async def inspect_git_worktree(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        source_project_path: str,
        worktree_path: str,
        branch_name: str,
        deadline_at: datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitInspectWorktreeResult:
        """Run a foreground non-mutating Git worktree inspection operation."""
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="inspect_git_worktree",
                owner_session_id=owner_session_id,
                payload={
                    "source_project_path": source_project_path,
                    "worktree_path": worktree_path,
                    "branch_name": branch_name,
                },
                deadline_at=deadline_at,
                body_stream_id=None,
            )
        )
        return await self.resume_git_inspect_worktree(
            reply_stream_id=dispatch.reply_stream_id,
            after_cursor=None,
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
            text_output_callback=text_output_callback,
        )

    async def delete_git_branch(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        source_project_path: str,
        branch_name: str,
        deadline_at: datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitDeleteBranchResult:
        """Run a foreground Git branch deletion operation."""
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="delete_git_branch",
                owner_session_id=owner_session_id,
                payload={
                    "source_project_path": source_project_path,
                    "branch_name": branch_name,
                },
                deadline_at=deadline_at,
                body_stream_id=None,
            )
        )
        return await self.resume_git_delete_branch(
            reply_stream_id=dispatch.reply_stream_id,
            after_cursor=None,
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
            text_output_callback=text_output_callback,
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
                owner_session_id=owner_session_id,
                payload=payload,
                deadline_at=deadline_at,
                body_stream_id=None,
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
                owner_session_id=owner_session_id,
                payload={
                    "process_id": process_id,
                    "stdin": stdin,
                    "yield_time_ms": yield_time_ms,
                    "max_output_bytes": max_output_bytes,
                },
                deadline_at=deadline_at,
                body_stream_id=None,
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

    async def terminate_session_processes(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str,
        deadline_at: datetime,
    ) -> None:
        """Terminate all Runner-owned processes for one AgentSession."""
        dispatch = await self._dispatch_runner_operation(
            RuntimeRunnerOperation(
                runtime_id=runtime_id,
                runner_generation=runner_generation,
                operation_type="process.terminate_session",
                owner_session_id=None,
                payload={"owner_session_id": owner_session_id},
                deadline_at=deadline_at,
                body_stream_id=None,
            )
        )
        await self._read_until_final(
            dispatch.reply_stream_id,
            _ReplyFolder(after_cursor=None),
            request_id=dispatch.request_id,
            operation_id=dispatch.operation_id,
            runtime_id=runtime_id,
            generation=runner_generation,
            deadline_at=deadline_at,
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

    async def resume_file_glob(
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
        """Resume reading a file glob reply stream until final result."""
        return await self.resume_file_list(
            reply_stream_id=reply_stream_id,
            after_cursor=after_cursor,
            request_id=request_id,
            operation_id=operation_id,
            runtime_id=runtime_id,
            generation=generation,
            deadline_at=deadline_at,
        )

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

    async def resume_file_apply_patch(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
    ) -> RuntimeFileApplyPatchResult:
        """Resume reading a file patch reply stream until final result."""
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
        return RuntimeFileApplyPatchResult(
            changes=tuple(_file_patch_changes(final.event.payload, "changes")),
            final_cursor=final.cursor,
        )

    async def resume_file_edit(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
    ) -> RuntimeFileEditResult:
        """Resume reading a file edit reply stream until final result."""
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
        return RuntimeFileEditResult(
            replacements=_int_payload(
                final.event.payload,
                "replacements",
                default=0,
            ),
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

    async def resume_file_bulk_delete(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
    ) -> RuntimeFileBulkDeleteResult:
        """Resume reading a file bulk delete reply stream until final result."""
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
        paths = final.event.payload.get("deleted_paths")
        return RuntimeFileBulkDeleteResult(
            paths=tuple(value for value in paths if isinstance(value, str))
            if isinstance(paths, list)
            else (),
            final_cursor=final.cursor,
        )

    async def resume_file_bulk_move(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
    ) -> RuntimeFileBulkMoveResult:
        """Resume reading a file bulk move reply stream until final result."""
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
        entries = final.event.payload.get("moved_entries")
        return RuntimeFileBulkMoveResult(
            entries=tuple(_file_move_entries(entries))
            if isinstance(entries, list)
            else (),
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

    async def resume_git_refs(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitRefsResult:
        """Resume reading a Git ref discovery reply stream until final result."""
        folder = _ReplyFolder(
            after_cursor=after_cursor,
            text_output_callback=text_output_callback,
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
        return RuntimeGitRefsResult(
            refs=tuple(_git_ref_entries(final.event.payload)),
            default_branch=_optional_str_payload(final.event.payload, "default_branch"),
            head_commit=_optional_str_payload(final.event.payload, "head_commit"),
            final_cursor=final.cursor,
        )

    async def resume_git_create_worktree(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitCreateWorktreeResult:
        """Resume reading a Git worktree creation reply stream."""
        folder = _ReplyFolder(
            after_cursor=after_cursor,
            text_output_callback=text_output_callback,
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
        return RuntimeGitCreateWorktreeResult(
            base_commit=_str_payload(final.event.payload, "base_commit"),
            worktree_path=_str_payload(final.event.payload, "worktree_path"),
            branch_name=_str_payload(final.event.payload, "branch_name"),
            final_cursor=final.cursor,
        )

    async def resume_git_remove_worktree(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitRemoveWorktreeResult:
        """Resume reading a Git worktree removal reply stream."""
        folder = _ReplyFolder(
            after_cursor=after_cursor,
            text_output_callback=text_output_callback,
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
        return RuntimeGitRemoveWorktreeResult(
            worktree_path=_str_payload(final.event.payload, "removed_worktree_path"),
            outcome=_git_remove_outcome(final.event.payload.get("outcome")),
            final_cursor=final.cursor,
        )

    async def resume_git_inspect_worktree(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitInspectWorktreeResult:
        """Resume reading a Git worktree inspection reply stream."""
        folder = _ReplyFolder(
            after_cursor=after_cursor,
            text_output_callback=text_output_callback,
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
        return RuntimeGitInspectWorktreeResult(
            worktree_path=_str_payload(final.event.payload, "worktree_path"),
            registered=_bool_payload(
                final.event.payload,
                "worktree_registered",
                default=False,
            ),
            registered_branch_name=_optional_str_payload(
                final.event.payload,
                "registered_branch_name",
            ),
            target_kind=_git_worktree_target_kind(
                final.event.payload.get("target_kind")
            ),
            dirty=_optional_bool_payload(final.event.payload, "dirty"),
            final_cursor=final.cursor,
        )

    async def resume_git_delete_branch(
        self,
        *,
        reply_stream_id: str,
        after_cursor: str | None,
        request_id: str | None = None,
        operation_id: str | None = None,
        runtime_id: str | None = None,
        generation: int | None = None,
        deadline_at: datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitDeleteBranchResult:
        """Resume reading a Git branch deletion reply stream."""
        folder = _ReplyFolder(
            after_cursor=after_cursor,
            text_output_callback=text_output_callback,
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
        return RuntimeGitDeleteBranchResult(
            branch_name=_str_payload(final.event.payload, "deleted_branch_name"),
            outcome=_git_branch_delete_outcome(final.event.payload.get("outcome")),
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
                        "Runtime operation timed out",
                        code="operation_timeout",
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
                            patch_failure = _file_apply_patch_failure(
                                record.event.payload
                            )
                            if patch_failure is not None:
                                raise RuntimeFileApplyPatchFailedError(
                                    _error_message(record.event.payload),
                                    failure=patch_failure,
                                )
                            raise RuntimeRunnerOperationFailedError(
                                _error_message(record.event.payload),
                                code=(
                                    _str_payload(
                                        record.event.payload,
                                        "error_code",
                                    )
                                    or None
                                ),
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
        await self._coordination_store.append_reply_for_operation(
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
            operation_id=operation_id,
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
    text_output_callback: RuntimeOperationTextCallback | None = None
    process_output_callback: RuntimeProcessOutputCallback | None = None

    async def apply(self, record: RuntimeReplyRecord) -> None:
        """Fold one reply record into accumulated output state."""
        event = record.event
        if event.event_type == RuntimeReplyEventType.STDOUT:
            text = _str_payload(event.payload, "text")
            self.stdout.append(text)
            if self.text_output_callback is not None:
                await self.text_output_callback(
                    RuntimeOperationTextDelta(stream="stdout", text=text)
                )
            return
        if event.event_type == RuntimeReplyEventType.STDERR:
            text = _str_payload(event.payload, "text")
            self.stderr.append(text)
            if self.text_output_callback is not None:
                await self.text_output_callback(
                    RuntimeOperationTextDelta(stream="stderr", text=text)
                )
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


def _optional_bool_payload(
    payload: dict[str, JsonValue],
    key: str,
) -> bool | None:
    value = payload.get(key)
    return value if isinstance(value, bool) else None


def _git_worktree_target_kind(
    value: object,
) -> Literal["directory", "missing", "other"]:
    if value == "directory":
        return "directory"
    if value == "missing":
        return "missing"
    if value == "other":
        return "other"
    raise ValueError("Runner returned an invalid Git worktree target kind")


def _git_remove_outcome(value: object) -> Literal["removed", "already_absent"]:
    if value == "removed":
        return "removed"
    if value == "already_absent":
        return "already_absent"
    raise ValueError("Runner returned an invalid Git worktree removal outcome")


def _git_branch_delete_outcome(
    value: object,
) -> Literal["deleted", "already_absent"]:
    if value == "deleted":
        return "deleted"
    if value == "already_absent":
        return "already_absent"
    raise ValueError("Runner returned an invalid Git branch deletion outcome")


def _error_message(payload: dict[str, JsonValue]) -> str:
    code = _str_payload(payload, "error_code")
    message = _str_payload(payload, "error_message")
    if code and message:
        return f"{code}: {message}"
    return message or code or "Runner operation failed"


def _file_apply_patch_failure(
    payload: dict[str, JsonValue],
) -> RuntimeFileApplyPatchFailure | None:
    value = payload.get("file_apply_patch")
    if not isinstance(value, dict):
        return None
    phase = _file_patch_phase(value.get("phase"))
    if phase is None:
        return None
    return RuntimeFileApplyPatchFailure(
        phase=phase,
        reason=_str_payload(value, "reason"),
        applied=tuple(_file_patch_changes(value, "applied")),
        failed=_optional_file_patch_operation(value.get("failed")),
        not_attempted=tuple(_file_patch_operations(value, "not_attempted")),
        exact=_bool_payload(value, "exact", default=False),
    )


def _file_patch_changes(
    payload: dict[str, JsonValue],
    key: str,
) -> list[RuntimeFilePatchChange]:
    raw_changes = payload.get(key)
    if not isinstance(raw_changes, list):
        return []
    changes: list[RuntimeFilePatchChange] = []
    for raw_change in raw_changes:
        if not isinstance(raw_change, dict):
            continue
        operation = _optional_file_patch_operation(raw_change)
        if operation is None:
            continue
        changes.append(
            RuntimeFilePatchChange(
                path=operation.path,
                action=operation.action,
                added_lines=_int_payload(raw_change, "added_lines", default=0),
                removed_lines=_int_payload(raw_change, "removed_lines", default=0),
                content_sha256=_optional_str_payload(raw_change, "content_sha256"),
            )
        )
    return changes


def _file_patch_operations(
    payload: dict[str, JsonValue],
    key: str,
) -> list[RuntimeFilePatchOperation]:
    raw_operations = payload.get(key)
    if not isinstance(raw_operations, list):
        return []
    operations: list[RuntimeFilePatchOperation] = []
    for raw_operation in raw_operations:
        operation = _optional_file_patch_operation(raw_operation)
        if operation is not None:
            operations.append(operation)
    return operations


def _optional_file_patch_operation(
    value: object,
) -> RuntimeFilePatchOperation | None:
    if not isinstance(value, dict):
        return None
    path = value.get("path")
    action = _file_patch_action(value.get("action"))
    if not isinstance(path, str) or action is None:
        return None
    return RuntimeFilePatchOperation(path=path, action=action)


def _file_patch_action(value: object) -> RuntimeFilePatchAction | None:
    if value == "add":
        return "add"
    if value == "update":
        return "update"
    if value == "delete":
        return "delete"
    return None


def _file_patch_phase(value: object) -> RuntimeFilePatchPhase | None:
    if value == "parse":
        return "parse"
    if value == "preflight":
        return "preflight"
    if value == "stage":
        return "stage"
    if value == "revalidate":
        return "revalidate"
    if value == "commit":
        return "commit"
    return None


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


def _file_move_entries(values: Sequence[object]) -> list[RuntimeFileMoveEntry]:
    entries: list[RuntimeFileMoveEntry] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        source_path = value.get("source_path")
        destination_path = value.get("destination_path")
        if isinstance(source_path, str) and isinstance(destination_path, str):
            entries.append(
                RuntimeFileMoveEntry(
                    source_path=source_path,
                    destination_path=destination_path,
                )
            )
    return entries


def _git_ref_entries(payload: dict[str, JsonValue]) -> list[RuntimeGitRefEntry]:
    raw_entries = payload.get("git_refs")
    if not isinstance(raw_entries, list):
        return []
    entries: list[RuntimeGitRefEntry] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        name = raw_entry.get("name")
        ref = raw_entry.get("ref")
        target = raw_entry.get("target")
        ref_type = _git_ref_type(raw_entry.get("type"))
        if (
            isinstance(name, str)
            and isinstance(ref, str)
            and isinstance(target, str)
            and ref_type is not None
        ):
            entries.append(
                RuntimeGitRefEntry(
                    name=name,
                    ref=ref,
                    type=ref_type,
                    target=target,
                    default=_bool_payload(raw_entry, "default", default=False),
                )
            )
    return entries


def _git_ref_type(
    value: object,
) -> Literal["branch", "remote_branch", "tag", "other"] | None:
    if value == "branch":
        return "branch"
    if value == "remote_branch":
        return "remote_branch"
    if value == "tag":
        return "tag"
    if value == "other":
        return "other"
    return None


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
