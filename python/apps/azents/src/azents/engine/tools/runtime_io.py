"""I/O protocol used by Runtime-backed builtin tools."""

import dataclasses
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal, Protocol

type RuntimeOperationCancelCheck = Callable[[], Awaitable[bool]]
type RuntimeProcessOutputCallback = Callable[
    ["RuntimeProcessOutputDelta"], Awaitable[None]
]


class RuntimeRunnerOperationUnavailable(RuntimeError):
    """Operation cannot be routed to current Runtime Runner."""


class RuntimeRunnerOperationGenerationError(RuntimeError):
    """Runtime Runner generation is stale."""


class RuntimeRunnerOperationFailedError(RuntimeError):
    """Runtime Runner returned operation final error."""


@dataclasses.dataclass(frozen=True)
class RuntimeBashResult:
    """Completed bash operation result."""

    stdout: str
    stderr: str
    exit_code: int
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeProcessOutputDelta:
    """Live process output delta emitted by Runtime Runner."""

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
class RuntimeFileReadResult:
    """Completed file read operation result."""

    data: bytes
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeFileListEntry:
    """Runtime file list entry."""

    path: str
    type: Literal["file", "directory", "symlink", "other"]
    size_bytes: int | None


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
    final_cursor: str


@dataclasses.dataclass(frozen=True)
class RuntimeGrepLineMatch:
    """Runtime grep line match."""

    line_number: int
    text: str


@dataclasses.dataclass(frozen=True)
class RuntimeGrepFileMatch:
    """Runtime grep file match."""

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
    """One file operation referenced by a Runtime patch result."""

    path: str
    action: RuntimeFilePatchAction


@dataclasses.dataclass(frozen=True)
class RuntimeFilePatchChange:
    """One file change committed by a Runtime patch operation."""

    path: str
    action: RuntimeFilePatchAction
    added_lines: int
    removed_lines: int
    content_sha256: str | None


@dataclasses.dataclass(frozen=True)
class RuntimeFileApplyPatchFailure:
    """Typed Runtime patch failure with committed-delta detail."""

    phase: RuntimeFilePatchPhase
    reason: str
    applied: tuple[RuntimeFilePatchChange, ...]
    failed: RuntimeFilePatchOperation | None
    not_attempted: tuple[RuntimeFilePatchOperation, ...]
    exact: bool


@dataclasses.dataclass(frozen=True)
class RuntimeFileApplyPatchResult:
    """Completed Runtime patch operation result."""

    changes: tuple[RuntimeFilePatchChange, ...]
    final_cursor: str


class RuntimeFileApplyPatchFailedError(RuntimeRunnerOperationFailedError):
    """Runtime Runner returned a typed file patch failure."""

    def __init__(self, message: str, *, failure: RuntimeFileApplyPatchFailure) -> None:
        """Initialize the failure with committed-delta detail."""
        super().__init__(message)
        self.failure = failure


class RuntimeRunnerOperationClient(Protocol):
    """Runtime Runner operation client used by Builtin tools."""

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
        """Run bash operation and return result."""
        ...

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
        """Start process operation and return process snapshot."""
        ...

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
        """Write process stdin or poll with empty stdin."""
        ...

    async def terminate_session_processes(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str,
        deadline_at: datetime,
    ) -> None:
        """Terminate all live processes owned by an AgentSession."""
        ...

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
        """Run file read operation and return result."""
        ...

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
        """Run file write operation and return result."""
        ...

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
        """Run one strict Runtime patch operation and return committed changes."""
        ...

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
        """Run one atomic Runtime text replacement."""
        ...

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
        """Run file list operation and return result."""
        ...

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
        """Run file glob operation and return result."""
        ...

    async def stat_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        deadline_at: datetime,
    ) -> RuntimeFileStatResult:
        """Run file stat operation and return result."""
        ...

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
        """Run file grep operation and return result."""
        ...
