"""Shared bounded native VFS text search without Runtime or filesystem projection."""

import dataclasses
import json
import re
from collections.abc import Sequence

from azents.core.vfs import VfsLocation
from azents.services.file_storage import GrepFileMatch, GrepLineMatch, GrepResult
from azents.services.vfs_read import (
    _expand_braces,
    _glob_matches,
    _location_contains,
    _run_regex_grep_process,
)


@dataclasses.dataclass(frozen=True)
class VfsTextFile:
    """Authorized in-memory text ready for bounded isolated regex execution."""

    uri: str
    text: str


def vfs_pattern_matches(pattern: str, path: str) -> bool:
    """Use the existing native segment/brace matcher for canonical mount paths."""
    return _glob_matches(path, _expand_braces(pattern.removeprefix("/") or "**"))


def vfs_location_contains(location: VfsLocation, uri: str, *, recursive: bool) -> bool:
    return _location_contains(location, uri, recursive=recursive)


async def bounded_vfs_regex_search(
    *,
    files: Sequence[VfsTextFile],
    pattern: re.Pattern[str],
    max_matching_files: int,
    max_lines_per_file: int,
    max_searched_files: int,
    max_scanned_bytes: int,
) -> GrepResult:
    """Apply input limits and an 8k encoded-result budget below the 12k tool bound."""
    if (
        min(
            max_matching_files,
            max_lines_per_file,
            max_searched_files,
            max_scanned_bytes,
        )
        < 1
    ):
        raise ValueError("VFS search bounds must be positive.")
    selected: list[dict[str, str]] = []
    scanned = 0
    stopped: str | None = None
    for file in files:
        if len(selected) >= max_searched_files:
            stopped = "searched_file_limit"
            break
        size = len(file.text.encode("utf-8"))
        if scanned + size > max_scanned_bytes:
            stopped = "scanned_byte_limit"
            break
        selected.append({"path": file.uri, "text": file.text})
        scanned += size
    process = await _run_regex_grep_process(
        pattern=pattern.pattern,
        files=selected,
        max_matching_files=max_matching_files,
        max_lines_per_file=max_lines_per_file,
        timeout_seconds=2.0,
    )
    if process is None:
        return GrepResult((), len(selected), 0, True, "deadline")
    matches: list[GrepFileMatch] = []
    result_size = 0
    for file in process.files:
        payload_size = len(
            json.dumps(file.model_dump(), ensure_ascii=False).encode("utf-8")
        )
        if result_size + payload_size > 8000:
            stopped = "result_byte_limit"
            break
        matches.append(
            GrepFileMatch(
                file.path,
                tuple(
                    GrepLineMatch(line.line_number, line.text) for line in file.lines
                ),
                file.truncated,
            )
        )
        result_size += payload_size
    stopped = stopped or process.stopped_reason
    return GrepResult(
        tuple(matches), len(selected), len(matches), stopped is not None, stopped
    )
