"""Registered bounded read routing for Azents virtual filesystem mounts."""

from __future__ import annotations

import asyncio
import dataclasses
import fnmatch
import json
import logging
import re
import sys
import time
from collections.abc import Sequence
from functools import lru_cache
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.vfs import (
    AZENTS_VFS_SKILLS_MOUNT,
    VfsFileEntry,
    VfsLocation,
    VfsProjection,
    parse_vfs_exact_uri,
    parse_vfs_glob_pattern,
    parse_vfs_search_uri,
)
from azents.rdb.session import SessionManager
from azents.repos.session_execution.ownership import OwnerBoundSessionManager
from azents.services.file_storage import (
    GrepFileMatch,
    GrepLineMatch,
    GrepResult,
    TextReadResult,
)
from azents.services.session_resource_authority import SessionExecutionOwner

_SKILLS_GLOB_MAX_RESULTS = 1_000
_SKILLS_OPERATION_MAX_SECONDS = 2.0
_SKILLS_GREP_LINE_MAX_CHARACTERS = 10_000
_MAX_BRACE_EXPANSIONS = 256
logger = logging.getLogger(__name__)

_REGEX_GREP_WORKER = r"""
import json
import re
import sys

request = json.load(sys.stdin)
pattern = re.compile(request["pattern"])
max_matching_files = request["max_matching_files"]
max_lines_per_file = request["max_lines_per_file"]
max_line_characters = request["max_line_characters"]
matches = []
stopped_reason = None
for file in request["files"]:
    lines = []
    file_truncated = False
    for line_number, line in enumerate(file["text"].splitlines(), start=1):
        if pattern.search(line) is None:
            continue
        if len(lines) >= max_lines_per_file:
            file_truncated = True
            break
        if len(line) > max_line_characters:
            line = line[:max_line_characters] + "... [truncated]"
            file_truncated = True
        lines.append({"line_number": line_number, "text": line})
    if not lines:
        continue
    if len(matches) >= max_matching_files:
        stopped_reason = "matching_file_limit"
        break
    matches.append(
        {
            "path": file["path"],
            "lines": lines,
            "truncated": file_truncated,
        }
    )
json.dump(
    {"files": matches, "stopped_reason": stopped_reason},
    sys.stdout,
    ensure_ascii=False,
    separators=(",", ":"),
)
"""


class _RegexGrepLineResult(BaseModel):
    """One bounded line match returned by the isolated regex worker."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    line_number: int
    text: str


class _RegexGrepFileResult(BaseModel):
    """One bounded file match returned by the isolated regex worker."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    lines: list[_RegexGrepLineResult]
    truncated: bool


class _RegexGrepProcessResult(BaseModel):
    """Typed isolated regex worker output."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    files: list[_RegexGrepFileResult]
    stopped_reason: str | None


class VfsReadError(Exception):
    """Stable VFS read failure safe for tool-facing normalization."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclasses.dataclass(frozen=True)
class VfsReadContext:
    """Server-created identity and policy context for one VFS operation."""

    run_id: str
    session_id: str
    root_session_id: str
    agent_id: str
    workspace_id: str
    associated_user_id: str | None
    owner_generation: int
    memory_enabled: bool

    @property
    def execution_owner(self) -> SessionExecutionOwner:
        """Return the durable concrete-Session execution fence."""
        return SessionExecutionOwner(
            session_id=self.session_id,
            owner_generation=self.owner_generation,
        )


@dataclasses.dataclass(frozen=True)
class VfsReadBackendCapabilities:
    """Operations implemented natively by one VFS mount backend."""

    read_text: bool
    grep: bool
    glob: bool
    transfer_read: bool


@dataclasses.dataclass(frozen=True)
class VfsGlobResult:
    """Sorted canonical URI matches returned by one VFS backend."""

    uris: tuple[str, ...]
    truncated: bool
    stopped_reason: str | None = None


class VfsReadAuthorityValidator[ReadContextT = VfsReadContext](Protocol):
    """Execution-owner admission check used before backend I/O."""

    async def validate(self, context: ReadContextT) -> None:
        """Raise when the concrete Session owner generation is stale."""
        ...


@dataclasses.dataclass(frozen=True)
class OwnerBoundVfsReadAuthorityValidator:
    """Validate one VFS operation against current durable Session ownership."""

    session_manager: SessionManager[AsyncSession]

    async def validate(self, context: VfsReadContext) -> None:
        """Check owner generation without retaining a transaction over backend I/O."""
        manager = OwnerBoundSessionManager(
            session_manager=self.session_manager,
            session_id=context.session_id,
            owner_generation=context.owner_generation,
        )
        await manager.assert_current()


@runtime_checkable
class VfsReadBackend[ReadContextT = VfsReadContext](Protocol):
    """Native bounded read operations owned by one canonical VFS mount."""

    @property
    def mount(self) -> str:
        """Return the canonical mount name."""
        ...

    @property
    def capabilities(self) -> VfsReadBackendCapabilities:
        """Return the backend operation capability declaration."""
        ...

    async def read_text(
        self,
        context: ReadContextT,
        location: VfsLocation,
        *,
        offset: int,
        limit: int,
        encoding: str,
    ) -> TextReadResult:
        """Read one bounded decoded character range."""
        ...

    async def grep(
        self,
        context: ReadContextT,
        location: VfsLocation,
        *,
        pattern: re.Pattern[str],
        recursive: bool,
        exclude_patterns: Sequence[str],
        max_matching_files: int,
        max_lines_per_file: int,
        max_searched_files: int,
        max_scanned_bytes: int,
    ) -> GrepResult:
        """Search bounded backend-native text content."""
        ...

    async def glob(
        self,
        context: ReadContextT,
        location: VfsLocation,
        *,
        exclude_patterns: Sequence[str],
    ) -> VfsGlobResult:
        """Return bounded sorted canonical URI matches."""
        ...


@runtime_checkable
class VfsTransferReadBackend[ReadContextT = VfsReadContext](Protocol):
    """Optional backend capability for server-to-Runtime transfer."""

    async def transfer_read(
        self,
        context: ReadContextT,
        location: VfsLocation,
    ) -> VfsFileEntry:
        """Resolve one immutable transfer entry without materializing a tree."""
        ...


class VfsReadBackendRegistry[ReadContextT = VfsReadContext]:
    """Immutable canonical-mount registry with fatal duplicate detection."""

    def __init__(self, backends: Sequence[VfsReadBackend[ReadContextT]]) -> None:
        registered: dict[str, VfsReadBackend[ReadContextT]] = {}
        for backend in backends:
            canonical_mount = parse_vfs_search_uri(f"azents://{backend.mount}").mount
            if canonical_mount != backend.mount:
                raise ValueError(
                    f"Non-canonical VFS read backend mount: {backend.mount}"
                )
            if backend.mount in registered:
                raise ValueError(f"Duplicate VFS read backend mount: {backend.mount}")
            registered[backend.mount] = backend
        self._backends = registered

    def get(self, mount: str) -> VfsReadBackend[ReadContextT]:
        """Return one registered mount backend or fail explicitly."""
        backend = self._backends.get(mount)
        if backend is None:
            raise VfsReadError(
                "unsupported_mount",
                f"Unsupported azents:// mount: {mount}",
            )
        return backend

    @property
    def mounts(self) -> tuple[str, ...]:
        """Return registered mount names in deterministic order."""
        return tuple(sorted(self._backends))


@dataclasses.dataclass(frozen=True)
class VfsReadRouter[ReadContextT = VfsReadContext]:
    """Validate one VFS location and dispatch to its native backend."""

    registry: VfsReadBackendRegistry[ReadContextT]
    authority_validator: VfsReadAuthorityValidator[ReadContextT]

    async def read_text(
        self,
        context: ReadContextT,
        uri: str,
        *,
        offset: int,
        limit: int,
        encoding: str,
    ) -> TextReadResult:
        """Route one exact text read."""
        location = parse_vfs_exact_uri(uri)
        backend = self.registry.get(location.mount)
        self._require_capability(backend, "read_text")
        await self.authority_validator.validate(context)
        started_at = time.monotonic()
        result = await backend.read_text(
            context,
            location,
            offset=offset,
            limit=limit,
            encoding=encoding,
        )
        self._log_operation(
            backend=backend,
            operation="read_text",
            started_at=started_at,
            visited_files=1,
            visited_bytes=len(result.text.encode(encoding, errors="ignore")),
            matches=None,
            truncated=result.truncated,
            stopped_reason="character_limit" if result.truncated else None,
        )
        return result

    async def grep(
        self,
        context: ReadContextT,
        uri: str,
        *,
        pattern: re.Pattern[str],
        recursive: bool,
        exclude_patterns: Sequence[str],
        max_matching_files: int,
        max_lines_per_file: int,
        max_searched_files: int,
        max_scanned_bytes: int,
    ) -> GrepResult:
        """Route one file-or-directory regex search."""
        location = parse_vfs_search_uri(uri)
        backend = self.registry.get(location.mount)
        self._require_capability(backend, "grep")
        await self.authority_validator.validate(context)
        started_at = time.monotonic()
        result = await backend.grep(
            context,
            location,
            pattern=pattern,
            recursive=recursive,
            exclude_patterns=exclude_patterns,
            max_matching_files=max_matching_files,
            max_lines_per_file=max_lines_per_file,
            max_searched_files=max_searched_files,
            max_scanned_bytes=max_scanned_bytes,
        )
        self._log_operation(
            backend=backend,
            operation="grep",
            started_at=started_at,
            visited_files=result.searched_file_count,
            visited_bytes=None,
            matches=result.matched_file_count,
            truncated=result.truncated,
            stopped_reason=result.stopped_reason,
        )
        return result

    async def glob(
        self,
        context: ReadContextT,
        pattern: str,
        *,
        exclude_patterns: Sequence[str],
    ) -> VfsGlobResult:
        """Route one canonical VFS glob pattern."""
        location = parse_vfs_glob_pattern(pattern)
        backend = self.registry.get(location.mount)
        self._require_capability(backend, "glob")
        await self.authority_validator.validate(context)
        started_at = time.monotonic()
        result = await backend.glob(
            context,
            location,
            exclude_patterns=exclude_patterns,
        )
        self._log_operation(
            backend=backend,
            operation="glob",
            started_at=started_at,
            visited_files=None,
            visited_bytes=0,
            matches=len(result.uris),
            truncated=result.truncated,
            stopped_reason=result.stopped_reason,
        )
        return result

    @staticmethod
    def _require_capability(
        backend: VfsReadBackend[ReadContextT],
        operation: Literal["read_text", "grep", "glob"],
    ) -> None:
        match operation:
            case "read_text":
                supported = backend.capabilities.read_text
            case "grep":
                supported = backend.capabilities.grep
            case "glob":
                supported = backend.capabilities.glob
        if not supported:
            raise VfsReadError(
                "unsupported_operation",
                f"VFS mount {backend.mount} does not support {operation}",
            )

    @staticmethod
    def _log_operation(
        *,
        backend: VfsReadBackend[ReadContextT],
        operation: Literal["read_text", "grep", "glob"],
        started_at: float,
        visited_files: int | None,
        visited_bytes: int | None,
        matches: int | None,
        truncated: bool,
        stopped_reason: str | None,
    ) -> None:
        """Record content-free VFS operation observability."""
        logger.info(
            "VFS read operation completed",
            extra={
                "vfs_mount": backend.mount,
                "vfs_backend": type(backend).__name__,
                "vfs_operation": operation,
                "duration_ms": (time.monotonic() - started_at) * 1000,
                "visited_files": visited_files,
                "visited_bytes": visited_bytes,
                "matches": matches,
                "truncated": truncated,
                "stopped_reason": stopped_reason,
                "outcome": "completed",
            },
        )


class VfsProjectionReader(Protocol):
    """Persisted immutable projection operations required by Skills reads."""

    def for_execution(
        self,
        owner: SessionExecutionOwner,
    ) -> VfsProjectionReader:
        """Return an execution-owner-fenced projection reader."""
        ...

    async def load_run_projection(
        self,
        *,
        run_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str,
    ) -> VfsProjection:
        """Load one authorized persisted run projection."""
        ...


@dataclasses.dataclass(frozen=True)
class SkillsVfsReadBackend:
    """Bounded native read operations over the immutable run Skills projection."""

    projection_service: VfsProjectionReader

    @property
    def mount(self) -> str:
        return AZENTS_VFS_SKILLS_MOUNT

    @property
    def capabilities(self) -> VfsReadBackendCapabilities:
        return VfsReadBackendCapabilities(
            read_text=True,
            grep=True,
            glob=True,
            transfer_read=True,
        )

    async def read_text(
        self,
        context: VfsReadContext,
        location: VfsLocation,
        *,
        offset: int,
        limit: int,
        encoding: str,
    ) -> TextReadResult:
        if offset < 0 or limit <= 0:
            raise ValueError("VFS text range must be positive and non-negative")
        projection = await self._projection(context)
        entry = projection.find(location.canonical)
        if entry is None:
            raise VfsReadError("not_found", "VFS file is unavailable")
        try:
            text = entry.decode_body().decode(encoding)
        except LookupError:
            raise
        except UnicodeDecodeError:
            raise
        except ValueError as exc:
            raise VfsReadError(
                "storage_unavailable",
                "VFS file content is unavailable",
            ) from exc
        bounded_limit = max(0, limit)
        end = min(len(text), offset + bounded_limit)
        return TextReadResult(
            text=text[offset:end],
            start_character=min(offset, len(text)),
            end_character=end,
            truncated=end < len(text),
        )

    async def grep(
        self,
        context: VfsReadContext,
        location: VfsLocation,
        *,
        pattern: re.Pattern[str],
        recursive: bool,
        exclude_patterns: Sequence[str],
        max_matching_files: int,
        max_lines_per_file: int,
        max_searched_files: int,
        max_scanned_bytes: int,
    ) -> GrepResult:
        if (
            max_matching_files < 1
            or max_lines_per_file < 1
            or max_searched_files < 1
            or max_scanned_bytes < 1
        ):
            raise ValueError("VFS grep limits must be positive")
        projection = await self._projection(context)
        deadline = time.monotonic() + _SKILLS_OPERATION_MAX_SECONDS
        searched = 0
        scanned_bytes = 0
        files: list[dict[str, str]] = []
        stopped_reason: str | None = None
        for entry in projection.entries:
            if not _location_contains(
                location,
                entry.canonical_uri,
                recursive=recursive,
            ):
                continue
            relative = _relative_to_location(location, entry.canonical_uri)
            if _excluded(relative, exclude_patterns):
                continue
            if searched >= max_searched_files:
                stopped_reason = "searched_file_limit"
                break
            if time.monotonic() >= deadline:
                stopped_reason = "deadline"
                break
            try:
                body = entry.decode_body()
            except ValueError as exc:
                raise VfsReadError(
                    "storage_unavailable",
                    "VFS file content is unavailable",
                ) from exc
            if scanned_bytes + len(body) > max_scanned_bytes:
                stopped_reason = "scanned_byte_limit"
                break
            searched += 1
            scanned_bytes += len(body)
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                continue
            files.append(
                {
                    "path": entry.canonical_uri,
                    "text": text,
                }
            )
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            return GrepResult(
                files=(),
                searched_file_count=searched,
                matched_file_count=0,
                truncated=True,
                stopped_reason="deadline",
            )
        process_result = await _run_regex_grep_process(
            pattern=pattern.pattern,
            files=files,
            max_matching_files=max_matching_files,
            max_lines_per_file=max_lines_per_file,
            timeout_seconds=remaining_seconds,
        )
        if process_result is None:
            return GrepResult(
                files=(),
                searched_file_count=searched,
                matched_file_count=0,
                truncated=True,
                stopped_reason="deadline",
            )
        matches = tuple(
            GrepFileMatch(
                path=file.path,
                lines=tuple(
                    GrepLineMatch(
                        line_number=line.line_number,
                        text=line.text,
                    )
                    for line in file.lines
                ),
                truncated=file.truncated,
            )
            for file in process_result.files
        )
        final_stopped_reason = process_result.stopped_reason or stopped_reason
        return GrepResult(
            files=matches,
            searched_file_count=searched,
            matched_file_count=len(matches),
            truncated=final_stopped_reason is not None,
            stopped_reason=final_stopped_reason,
        )

    async def glob(
        self,
        context: VfsReadContext,
        location: VfsLocation,
        *,
        exclude_patterns: Sequence[str],
    ) -> VfsGlobResult:
        projection = await self._projection(context)
        deadline = time.monotonic() + _SKILLS_OPERATION_MAX_SECONDS
        expanded = _expand_braces(location.canonical)
        matches: list[str] = []
        stopped_reason: str | None = None
        for entry in projection.entries:
            if time.monotonic() >= deadline:
                stopped_reason = "deadline"
                break
            relative = entry.canonical_uri.split(f"azents://{self.mount}/", 1)[-1]
            if _excluded(relative, exclude_patterns):
                continue
            if not _glob_matches(entry.canonical_uri, expanded):
                continue
            if len(matches) >= _SKILLS_GLOB_MAX_RESULTS:
                stopped_reason = "matching_file_limit"
                break
            matches.append(entry.canonical_uri)
        return VfsGlobResult(
            uris=tuple(sorted(matches)),
            truncated=stopped_reason is not None,
            stopped_reason=stopped_reason,
        )

    async def transfer_read(
        self,
        context: VfsReadContext,
        location: VfsLocation,
    ) -> VfsFileEntry:
        projection = await self._projection(context)
        entry = projection.find(location.canonical)
        if entry is None:
            raise VfsReadError("not_found", "VFS file is unavailable")
        return entry

    async def _projection(self, context: VfsReadContext) -> VfsProjection:
        service = self.projection_service.for_execution(context.execution_owner)
        return await service.load_run_projection(
            run_id=context.run_id,
            agent_id=context.agent_id,
            session_id=context.session_id,
            workspace_id=context.workspace_id,
        )


async def _run_regex_grep_process(
    *,
    pattern: str,
    files: list[dict[str, str]],
    max_matching_files: int,
    max_lines_per_file: int,
    timeout_seconds: float,
) -> _RegexGrepProcessResult | None:
    """Run user regex in a killable isolated Python process."""
    request = json.dumps(
        {
            "pattern": pattern,
            "files": files,
            "max_matching_files": max_matching_files,
            "max_lines_per_file": max_lines_per_file,
            "max_line_characters": _SKILLS_GREP_LINE_MAX_CHARACTERS,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-c",
            _REGEX_GREP_WORKER,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        raise VfsReadError(
            "storage_unavailable",
            "VFS regex execution is unavailable",
        ) from exc
    try:
        async with asyncio.timeout(timeout_seconds):
            stdout, _ = await process.communicate(request)
    except TimeoutError:
        process.kill()
        await process.wait()
        return None
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    if process.returncode != 0:
        raise VfsReadError(
            "invalid_pattern",
            "VFS regex execution failed",
        )
    try:
        return _RegexGrepProcessResult.model_validate_json(stdout)
    except ValidationError as exc:
        raise VfsReadError(
            "storage_unavailable",
            "VFS regex result is unavailable",
        ) from exc


def _location_contains(
    location: VfsLocation,
    candidate: str,
    *,
    recursive: bool,
) -> bool:
    if candidate == location.canonical:
        return True
    prefix = f"{location.canonical.rstrip('/')}/"
    if not candidate.startswith(prefix):
        return False
    if recursive:
        return True
    return "/" not in candidate[len(prefix) :]


def _relative_to_location(location: VfsLocation, candidate: str) -> str:
    if candidate == location.canonical:
        return candidate.rsplit("/", 1)[-1]
    return candidate[len(location.canonical.rstrip("/")) + 1 :]


def _glob_matches(path: str, expanded_patterns: tuple[str, ...]) -> bool:
    path_segments = path.split("/")
    for expanded_pattern in expanded_patterns:
        pattern_segments = expanded_pattern.split("/")
        if _match_glob_segments(path_segments, pattern_segments):
            return True
    return False


def _match_glob_segments(
    path_segments: list[str],
    pattern_segments: list[str],
) -> bool:
    @lru_cache(maxsize=None)
    def match(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_segments):
            return path_index == len(path_segments)
        pattern_segment = pattern_segments[pattern_index]
        if pattern_segment == "**":
            if match(path_index, pattern_index + 1):
                return True
            return path_index < len(path_segments) and match(
                path_index + 1,
                pattern_index,
            )
        if path_index == len(path_segments):
            return False
        return fnmatch.fnmatchcase(
            path_segments[path_index],
            pattern_segment,
        ) and match(path_index + 1, pattern_index + 1)

    return match(0, 0)


def _expand_braces(pattern: str) -> tuple[str, ...]:
    pending = [pattern]
    expansions: list[str] = []
    while pending:
        candidate = pending.pop()
        expandable = _find_expandable_brace(candidate)
        if expandable is None:
            expansions.append(candidate)
            continue
        opening, closing, alternatives = expandable
        prefix = candidate[:opening]
        suffix = candidate[closing + 1 :]
        pending.extend(
            f"{prefix}{alternative}{suffix}" for alternative in reversed(alternatives)
        )
        if len(expansions) + len(pending) > _MAX_BRACE_EXPANSIONS:
            raise VfsReadError(
                "invalid_pattern",
                f"Brace expansion exceeds {_MAX_BRACE_EXPANSIONS} alternatives",
            )
    return tuple(expansions)


def _find_expandable_brace(
    pattern: str,
) -> tuple[int, int, tuple[str, ...]] | None:
    for opening, opening_char in enumerate(pattern):
        if opening_char != "{":
            continue
        depth = 0
        for closing in range(opening, len(pattern)):
            char = pattern[closing]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    alternatives = _split_brace_alternatives(
                        pattern[opening + 1 : closing]
                    )
                    if len(alternatives) >= 2:
                        return opening, closing, alternatives
                    break
    return None


def _split_brace_alternatives(value: str) -> tuple[str, ...]:
    alternatives: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(value):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        elif char == "," and depth == 0:
            alternatives.append(value[start:index])
            start = index + 1
    alternatives.append(value[start:])
    return tuple(alternatives)


def _excluded(relative_path: str, patterns: Sequence[str]) -> bool:
    parts = relative_path.split("/")
    for pattern in patterns:
        if fnmatch.fnmatch(relative_path, pattern):
            return True
        if any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True
    return False
