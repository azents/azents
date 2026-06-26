"""I/O protocol used by Runtime-backed builtin tools."""

import dataclasses
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal, Protocol

type RuntimeOperationCancelCheck = Callable[[], Awaitable[bool]]


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


class RuntimeRunnerOperationClient(Protocol):
    """Runtime Runner operation client used by Builtin tools."""

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
        """Run bash operation and return result."""
        ...

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
        """Run file read operation and return result."""
        ...

    async def write_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        path: str,
        data: bytes,
        deadline_at: datetime,
    ) -> RuntimeFileWriteResult:
        """Run file write operation and return result."""
        ...

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
        """Run file list operation and return result."""
        ...

    async def stat_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
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
