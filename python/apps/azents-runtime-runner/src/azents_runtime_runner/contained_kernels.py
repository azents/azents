"""Contained native filesystem kernels."""

import contextlib
import fnmatch
import os
import re
import shutil
import stat as stat_module
import tempfile
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import TypeAlias

from azents_runtime_runner.workspace import Workspace

JsonValue: TypeAlias = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)

_MAX_BRACE_EXPANSIONS = 256


@dataclass
class _GrepScanState:
    """Track scan budget consumed while iterating grep targets."""

    searched_file_count: int = 0
    scanned_bytes: int = 0
    stopped_reason: str | None = None


class _FileOperationSemanticError(Exception):
    """Typed filesystem failure rendered as a Runner final error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _delete_path(
    path: Path,
    *,
    workspace: Workspace,
    recursive: bool,
    cancellation: threading.Event,
) -> dict[str, JsonValue]:
    """Delete one path in a filesystem worker."""
    if cancellation.is_set():
        return {"deleted_path": workspace.display_path(path)}
    try:
        stat_result = path.lstat()
    except FileNotFoundError as exc:
        raise _FileOperationSemanticError("NOT_FOUND", f"No such file: {path}") from exc
    except OSError as exc:
        raise _FileOperationSemanticError("DELETE_FAILED", str(exc)) from exc
    if (
        stat_module.S_ISDIR(stat_result.st_mode)
        and not stat_module.S_ISLNK(stat_result.st_mode)
        and not recursive
    ):
        raise _FileOperationSemanticError(
            "DIRECTORY_RECURSIVE_REQUIRED",
            f"Directory delete requires recursive=true: {path}",
        )
    try:
        if stat_module.S_ISDIR(stat_result.st_mode) and not stat_module.S_ISLNK(
            stat_result.st_mode
        ):
            shutil.rmtree(path)
        else:
            path.unlink()
    except FileNotFoundError as exc:
        raise _FileOperationSemanticError("NOT_FOUND", f"No such file: {path}") from exc
    except OSError as exc:
        raise _FileOperationSemanticError("DELETE_FAILED", str(exc)) from exc
    return {"deleted_path": workspace.display_path(path)}


def _make_directory(
    path: Path,
    *,
    workspace: Workspace,
    parents: bool,
    cancellation: threading.Event,
) -> dict[str, JsonValue]:
    """Create one directory in a filesystem worker."""
    if cancellation.is_set():
        return {"created_path": workspace.display_path(path)}
    try:
        path.mkdir(parents=parents, exist_ok=False)
    except FileExistsError as exc:
        raise _FileOperationSemanticError(
            "ALREADY_EXISTS", f"Path exists: {path}"
        ) from exc
    except FileNotFoundError as exc:
        raise _FileOperationSemanticError(
            "PARENT_NOT_FOUND",
            f"Parent directory does not exist: {path.parent}",
        ) from exc
    except OSError as exc:
        raise _FileOperationSemanticError("MKDIR_FAILED", str(exc)) from exc
    return {"created_path": workspace.display_path(path)}


def _move_path(
    source_path: Path,
    destination_path: Path,
    *,
    workspace: Workspace,
    overwrite: bool,
    cancellation: threading.Event,
) -> dict[str, JsonValue]:
    """Move one path in a filesystem worker."""
    if cancellation.is_set():
        return {
            "moved_source_path": workspace.display_path(source_path),
            "moved_destination_path": workspace.display_path(destination_path),
        }
    if not source_path.exists() and not source_path.is_symlink():
        raise _FileOperationSemanticError("NOT_FOUND", f"No such file: {source_path}")
    if destination_path.exists() or destination_path.is_symlink():
        if not overwrite:
            raise _FileOperationSemanticError(
                "DESTINATION_EXISTS",
                f"Destination already exists: {destination_path}",
            )
        try:
            if destination_path.is_dir() and not destination_path.is_symlink():
                shutil.rmtree(destination_path)
            else:
                destination_path.unlink()
        except OSError as exc:
            raise _FileOperationSemanticError("MOVE_FAILED", str(exc)) from exc
    if not destination_path.parent.exists():
        raise _FileOperationSemanticError(
            "PARENT_NOT_FOUND",
            f"Parent directory does not exist: {destination_path.parent}",
        )
    if not destination_path.parent.is_dir():
        raise _FileOperationSemanticError(
            "PARENT_NOT_DIRECTORY",
            f"Parent path is not a directory: {destination_path.parent}",
        )
    try:
        shutil.move(str(source_path), str(destination_path))
    except OSError as exc:
        raise _FileOperationSemanticError("MOVE_FAILED", str(exc)) from exc
    return {
        "moved_source_path": workspace.display_path(source_path),
        "moved_destination_path": workspace.display_path(destination_path),
    }


def _delete_paths(
    paths: list[Path],
    *,
    workspace: Workspace,
    recursive: bool,
    cancellation: threading.Event,
) -> dict[str, JsonValue]:
    """Delete multiple paths in a filesystem worker."""
    stats: list[tuple[Path, os.stat_result]] = []
    try:
        for path in paths:
            if cancellation.is_set():
                return {"deleted_paths": []}
            stats.append((path, path.lstat()))
    except FileNotFoundError as exc:
        raise _FileOperationSemanticError("NOT_FOUND", str(exc)) from exc
    except OSError as exc:
        raise _FileOperationSemanticError("DELETE_FAILED", str(exc)) from exc
    for path, stat_result in stats:
        if (
            stat_module.S_ISDIR(stat_result.st_mode)
            and not stat_module.S_ISLNK(stat_result.st_mode)
            and not recursive
        ):
            raise _FileOperationSemanticError(
                "DIRECTORY_RECURSIVE_REQUIRED",
                f"Directory delete requires recursive=true: {path}",
            )
    deleted_paths: list[JsonValue] = []
    try:
        for path, stat_result in stats:
            if stat_module.S_ISDIR(stat_result.st_mode) and not stat_module.S_ISLNK(
                stat_result.st_mode
            ):
                shutil.rmtree(path)
            else:
                path.unlink()
            deleted_paths.append(workspace.display_path(path))
    except FileNotFoundError as exc:
        raise _FileOperationSemanticError("NOT_FOUND", str(exc)) from exc
    except OSError as exc:
        raise _FileOperationSemanticError("DELETE_FAILED", str(exc)) from exc
    return {"deleted_paths": deleted_paths}


def _move_paths(
    source_paths: list[Path],
    destination_directory: Path,
    *,
    workspace: Workspace,
    overwrite: bool,
    cancellation: threading.Event,
) -> dict[str, JsonValue]:
    """Move multiple paths into one directory in a filesystem worker."""
    if cancellation.is_set():
        return {"moved_entries": []}
    if not destination_directory.exists():
        raise _FileOperationSemanticError(
            "PARENT_NOT_FOUND",
            f"Destination directory does not exist: {destination_directory}",
        )
    if not destination_directory.is_dir():
        raise _FileOperationSemanticError(
            "PARENT_NOT_DIRECTORY",
            f"Destination path is not a directory: {destination_directory}",
        )
    seen_destinations: set[Path] = set()
    moves: list[tuple[Path, Path]] = []
    for source_path in source_paths:
        if not source_path.exists() and not source_path.is_symlink():
            raise _FileOperationSemanticError(
                "NOT_FOUND", f"No such file: {source_path}"
            )
        destination_path = destination_directory / source_path.name
        if destination_path in seen_destinations:
            raise _FileOperationSemanticError(
                "DESTINATION_EXISTS",
                f"Duplicate destination: {destination_path}",
            )
        seen_destinations.add(destination_path)
        if (
            destination_path.exists() or destination_path.is_symlink()
        ) and not overwrite:
            raise _FileOperationSemanticError(
                "DESTINATION_EXISTS",
                f"Destination already exists: {destination_path}",
            )
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
                    "source_path": workspace.display_path(source_path),
                    "destination_path": workspace.display_path(destination_path),
                }
            )
    except OSError as exc:
        raise _FileOperationSemanticError("MOVE_FAILED", str(exc)) from exc
    return {"moved_entries": moved_entries}


def _read_file_bytes(
    path: Path,
    *,
    offset: int,
    max_bytes: int,
    cancellation: threading.Event,
) -> bytes:
    """Read bounded file bytes in a filesystem worker."""
    if cancellation.is_set():
        return b""
    return path.read_bytes()[offset : offset + max_bytes]


def _read_file_range_bytes(
    path: Path,
    *,
    offset: int,
    max_bytes: int,
    cancellation: threading.Event,
) -> bytes:
    """Read one bounded byte range without reading the complete file."""
    if cancellation.is_set():
        return b""
    with path.open("rb") as source:
        source.seek(offset)
        return source.read(max_bytes)


def _write_file_bytes(
    path: Path,
    *,
    chunks: tuple[bytes, ...],
    cancellation: threading.Event,
) -> int:
    """Write file bytes in a filesystem worker."""
    if cancellation.is_set():
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    data = b"".join(chunks)
    if cancellation.is_set():
        return 0
    path.write_bytes(data)
    return len(data)


def _edit_file_text(
    path: Path,
    *,
    old_string: str,
    new_string: str,
    replace_all: bool,
    cancellation: threading.Event,
) -> int:
    """Replace exact UTF-8 text in one regular file with an atomic write."""
    if cancellation.is_set():
        raise _FileOperationSemanticError(
            "FILE_EDIT_CANCELLED",
            "File edit was cancelled before replacement",
        )
    _assert_edit_path_has_no_symlinks(path)
    try:
        source_stat = path.lstat()
    except FileNotFoundError as exc:
        raise _FileOperationSemanticError(
            "FILE_EDIT_NOT_FOUND",
            "File does not exist",
        ) from exc
    except OSError as exc:
        raise _FileOperationSemanticError("FILE_EDIT_READ_FAILED", str(exc)) from exc
    if not stat_module.S_ISREG(source_stat.st_mode):
        raise _FileOperationSemanticError(
            "FILE_EDIT_UNSUPPORTED_FILE_TYPE",
            "File is not a regular file",
        )
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise _FileOperationSemanticError(
            "FILE_EDIT_NOT_FOUND",
            "File does not exist",
        ) from exc
    except OSError as exc:
        raise _FileOperationSemanticError("FILE_EDIT_READ_FAILED", str(exc)) from exc
    if cancellation.is_set():
        raise _FileOperationSemanticError(
            "FILE_EDIT_CANCELLED",
            "File edit was cancelled before replacement",
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _FileOperationSemanticError(
            "FILE_EDIT_INVALID_UTF8",
            "File is not valid UTF-8 text",
        ) from exc
    matches = text.count(old_string)
    if matches == 0:
        raise _FileOperationSemanticError(
            "FILE_EDIT_OLD_STRING_NOT_FOUND",
            "old_string was not found",
        )
    if not replace_all and matches > 1:
        raise _FileOperationSemanticError(
            "FILE_EDIT_MULTIPLE_MATCHES",
            str(matches),
        )
    edited_text = text.replace(
        old_string,
        new_string,
        -1 if replace_all else 1,
    )
    temp_path: Path | None = None
    try:
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            dir=path.parent,
        )
        temp_path = Path(temp_name)
        with os.fdopen(descriptor, "wb") as file:
            os.fchmod(file.fileno(), stat_module.S_IMODE(source_stat.st_mode))
            file.write(edited_text.encode("utf-8"))
            file.flush()
            os.fsync(file.fileno())
        if cancellation.is_set():
            raise _FileOperationSemanticError(
                "FILE_EDIT_CANCELLED",
                "File edit was cancelled before replacement",
            )
        _assert_edit_path_has_no_symlinks(path)
        current_stat = path.lstat()
        if not _same_file_identity(source_stat, current_stat):
            raise _FileOperationSemanticError(
                "FILE_EDIT_FILE_CHANGED",
                "File changed while edit was in progress",
            )
        os.replace(temp_path, path)
        temp_path = None
    except PermissionError as exc:
        raise _FileOperationSemanticError(
            "FILE_EDIT_PERMISSION_DENIED",
            "Permission denied while saving file",
        ) from exc
    except _FileOperationSemanticError:
        raise
    except OSError as exc:
        raise _FileOperationSemanticError("FILE_EDIT_WRITE_FAILED", str(exc)) from exc
    finally:
        if temp_path is not None:
            with contextlib.suppress(OSError):
                temp_path.unlink()
    return matches if replace_all else 1


def _assert_edit_path_has_no_symlinks(path: Path) -> None:
    """Reject edit paths whose final target or parent chain contains a symlink."""
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as exc:
            raise _FileOperationSemanticError(
                "FILE_EDIT_NOT_FOUND",
                "File does not exist",
            ) from exc
        except OSError as exc:
            raise _FileOperationSemanticError(
                "FILE_EDIT_READ_FAILED",
                str(exc),
            ) from exc
        if stat_module.S_ISLNK(mode):
            raise _FileOperationSemanticError(
                "FILE_EDIT_UNSAFE_PATH",
                "Editing symlink paths is not supported",
            )


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    """Return whether two lstat results refer to the same regular file."""
    return (
        stat_module.S_ISREG(right.st_mode)
        and left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
    )


def _read_stat_payload(
    path: Path,
    *,
    workspace: Workspace,
    cancellation: threading.Event,
) -> dict[str, JsonValue]:
    """Read file metadata in a filesystem worker."""
    if cancellation.is_set():
        return {}
    return _stat_payload(path, workspace)


def _list_file_entries(
    path: Path,
    *,
    workspace: Workspace,
    recursive: bool,
    exclude_patterns: list[str],
    cancellation: threading.Event,
) -> list[JsonValue]:
    """Build a file.list response in a filesystem worker."""
    entries: list[JsonValue] = []
    for child in _iter_list_entries(
        path,
        workspace=workspace,
        recursive=recursive,
        exclude_patterns=exclude_patterns,
        cancellation=cancellation,
    ):
        if cancellation.is_set():
            break
        entries.append(
            {
                "path": workspace.display_path(child),
                "type": _entry_type(child),
                "size_bytes": _file_size(child),
                "modified_at": _modified_at(child),
            }
        )
    return entries


def _glob_file_entries(
    pattern: str,
    *,
    workspace: Workspace,
    exclude_patterns: list[str],
    cancellation: threading.Event,
) -> list[JsonValue]:
    """Build a file.glob response in a filesystem worker."""
    if pattern.startswith("~"):
        raise _FileOperationSemanticError(
            "INVALID_PATTERN",
            "Tilde expansion is not supported. Use an absolute runtime path.",
        )
    expanded_patterns = _expand_braces(pattern)
    prefix = workspace.resolve(_extract_glob_dir_prefix(pattern))
    entries: list[JsonValue] = []
    for child in _iter_list_entries(
        prefix,
        workspace=workspace,
        recursive=_requires_recursive_glob_list(pattern),
        exclude_patterns=exclude_patterns,
        cancellation=cancellation,
    ):
        if cancellation.is_set():
            break
        display_path = workspace.display_path(child)
        if not _match_glob_path(display_path, expanded_patterns):
            continue
        entries.append(
            {
                "path": display_path,
                "type": _entry_type(child),
                "size_bytes": _file_size(child),
                "modified_at": _modified_at(child),
            }
        )
    return entries


def _extract_glob_dir_prefix(pattern: str) -> str:
    """Extract the directory prefix before the first glob segment."""
    parts: list[str] = []
    for segment in pattern.split("/"):
        if _has_glob_meta(segment):
            break
        parts.append(segment)
    prefix = "/".join(parts)
    if prefix:
        return prefix
    return "/" if pattern.startswith("/") else "."


def _requires_recursive_glob_list(pattern: str) -> bool:
    """Return whether a glob needs nested paths below its fixed prefix."""
    prefix = _extract_glob_dir_prefix(pattern)
    if prefix == "/":
        suffix = pattern.lstrip("/")
    elif prefix == ".":
        suffix = pattern
    else:
        suffix = pattern[len(prefix) :].strip("/")
    return "/" in suffix or "**" in suffix


def _match_glob_path(path: str, expanded_patterns: tuple[str, ...]) -> bool:
    """Match expanded glob patterns while preserving path segment boundaries."""
    path_segments = path.strip("/").split("/") if path != "/" else []
    for expanded_pattern in expanded_patterns:
        pattern_segments = (
            expanded_pattern.strip("/").split("/") if expanded_pattern != "/" else []
        )
        if _match_glob_segments(path_segments, pattern_segments):
            return True
    return False


def _match_glob_segments(
    path_segments: list[str],
    pattern_segments: list[str],
) -> bool:
    """Match path segments with support for the recursive `**` segment."""

    @lru_cache(maxsize=None)
    def match(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_segments):
            return path_index == len(path_segments)
        pattern_segment = pattern_segments[pattern_index]
        if pattern_segment == "**":
            if match(path_index, pattern_index + 1):
                return True
            return path_index < len(path_segments) and match(
                path_index + 1, pattern_index
            )
        if path_index == len(path_segments):
            return False
        return fnmatch.fnmatchcase(
            path_segments[path_index], pattern_segment
        ) and match(path_index + 1, pattern_index + 1)

    return match(0, 0)


def _expand_braces(pattern: str) -> tuple[str, ...]:
    """Expand a bounded number of comma-separated brace alternatives."""
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
            raise _FileOperationSemanticError(
                "INVALID_PATTERN",
                f"Brace expansion exceeds the maximum of {_MAX_BRACE_EXPANSIONS} "
                "alternatives.",
            )
    return tuple(expansions)


def _find_expandable_brace(
    pattern: str,
) -> tuple[int, int, tuple[str, ...]] | None:
    """Find the first balanced brace containing top-level alternatives."""
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
    """Split brace contents on commas outside nested braces."""
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


def _has_glob_meta(segment: str) -> bool:
    """Return whether a path segment contains glob metacharacters."""
    return any(char in segment for char in ("*", "?", "[", "{"))


def _grep_files(
    path: Path,
    *,
    workspace: Workspace,
    regex: re.Pattern[str],
    recursive: bool,
    exclude_patterns: list[str],
    max_matching_files: int,
    max_lines_per_file: int,
    max_searched_files: int,
    max_scanned_bytes: int,
    cancellation: threading.Event,
) -> dict[str, JsonValue]:
    """Build a file.grep response in a filesystem worker."""
    state = _GrepScanState()
    matches: list[JsonValue] = []
    for file_path in _iter_grep_files(
        path,
        workspace=workspace,
        recursive=recursive,
        exclude_patterns=exclude_patterns,
        cancellation=cancellation,
    ):
        if cancellation.is_set():
            break
        if len(matches) >= max_matching_files:
            state.stopped_reason = "matching_file_limit"
            break
        if state.searched_file_count >= max_searched_files:
            state.stopped_reason = "searched_file_limit"
            break
        match = _grep_file(
            file_path,
            workspace=workspace,
            regex=regex,
            max_lines_per_file=max_lines_per_file,
            max_scanned_bytes=max_scanned_bytes,
            state=state,
            cancellation=cancellation,
        )
        if match is not None:
            matches.append(match)
        if state.stopped_reason is not None:
            break
    return {
        "files": matches,
        "searched_file_count": state.searched_file_count,
        "matched_file_count": len(matches),
        "truncated": state.stopped_reason is not None,
        "stopped_reason": state.stopped_reason,
    }


def _iter_grep_files(
    path: Path,
    *,
    workspace: Workspace,
    recursive: bool,
    exclude_patterns: list[str],
    cancellation: threading.Event,
) -> Iterator[Path]:
    """Yield regular file paths searched by file.grep in sorted order."""
    for entry in _iter_list_entries(
        path,
        workspace=workspace,
        recursive=recursive,
        exclude_patterns=exclude_patterns,
        cancellation=cancellation,
    ):
        if cancellation.is_set():
            return
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
    cancellation: threading.Event,
) -> dict[str, JsonValue] | None:
    """Find regex-matching lines in one file."""
    state.searched_file_count += 1
    lines: list[JsonValue] = []
    truncated = False
    try:
        with path.open("rb") as file:
            for line_number, raw_line in enumerate(file, start=1):
                if cancellation.is_set():
                    return None
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
    cancellation: threading.Event,
) -> Iterator[Path]:
    """Yield paths included in file.list responses in sorted order."""
    if cancellation.is_set():
        return
    if path.is_file() or path.is_symlink():
        yield path
        return
    try:
        children = sorted(path.iterdir(), key=lambda item: item.name)
    except OSError:
        return
    for child in children:
        if cancellation.is_set():
            return
        if _excluded(child, base=path, workspace=workspace, patterns=exclude_patterns):
            continue
        yield child
        if recursive and child.is_dir() and not child.is_symlink():
            yield from _iter_list_entries(
                child,
                workspace=workspace,
                recursive=True,
                exclude_patterns=exclude_patterns,
                cancellation=cancellation,
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
