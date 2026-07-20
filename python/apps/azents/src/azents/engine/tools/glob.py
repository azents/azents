"""glob tool.

Search Runtime file entries using an absolute path pattern.
"""

import fnmatch
import logging

import httpx
from pydantic import BaseModel, Field

from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.path_policy import RUNTIME_ACCESSIBLE_PATHS_MSG
from azents.services.file_storage import FileStorage
from azents.services.runtime_storage_error import RuntimeStorageError

logger = logging.getLogger(__name__)

_MAX_BRACE_EXPANSIONS = 256
_DEFAULT_EXCLUDE_PATTERNS = (
    ".git",
    "node_modules",
    ".next",
    "dist",
    "build",
    ".turbo",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "coverage",
)


class GlobInput(BaseModel):
    """glob tool input."""

    pattern: str = Field(
        description=(
            "Glob pattern with absolute path prefix. Supports shell-style *, ?, [], "
            "recursive **, and comma-separated brace alternatives such as "
            "/workspace/agent/**/*.{jpg,png}. Shell quoting and backslash escaping "
            "are not interpreted."
        ),
    )
    exclude: list[str] | None = Field(
        default=None,
        description=(
            "Additional directory or glob patterns to exclude during search. "
            "Default excludes such as .git and node_modules still apply unless "
            "disable_default_excludes is true."
        ),
    )
    disable_default_excludes: bool = Field(
        default=False,
        description="Disable built-in heavy-directory excludes for this search.",
    )


def make_glob_tool(
    *,
    session_storage: FileStorage,
    agent_id: str,
    user_id: str,
) -> FunctionTool:
    """Create glob tool.

    :param session_storage: File storage client
    :param agent_id: Agent ID
    :param user_id: User ID
    :return: glob Tool instance
    """

    async def handler(input: GlobInput) -> str:
        """Return absolute path list of files matching pattern."""
        raw_pattern = input.pattern
        if raw_pattern.startswith("~"):
            raise FunctionToolError(
                "Tilde expansion is not supported. Use an absolute runtime path such "
                "as /workspace/agent or /tmp."
            )
        try:
            expanded_patterns = _expand_braces(raw_pattern)
        except ValueError as exc:
            raise FunctionToolError(str(exc)) from None

        # Extract directory prefix before glob character from absolute path pattern
        dir_prefix = _extract_dir_prefix(raw_pattern)

        # Fetch file list
        try:
            attachments = await session_storage.list(
                dir_prefix,
                agent_id=agent_id,
                recursive=_requires_recursive_list(raw_pattern),
                exclude_patterns=_glob_exclude_patterns(input),
                include_directories=True,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400:
                raise FunctionToolError(
                    f"Invalid path prefix: {dir_prefix}. {RUNTIME_ACCESSIBLE_PATHS_MSG}"
                ) from None
            raise
        except ValueError as exc:
            raise FunctionToolError(str(exc)) from None
        except RuntimeStorageError as exc:
            raise FunctionToolError(f"Failed to list files: {exc.detail}") from None
        except FileNotFoundError:
            # Directory does not exist; treat as no matching files (normal situation)
            return f"No files matched pattern: {raw_pattern}"
        except OSError:
            logger.exception(
                "Failed to list files for glob",
                extra={"pattern": raw_pattern},
            )
            raise FunctionToolError(
                f"Failed to list files for pattern: {raw_pattern}. "
                f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None

        matched_paths: list[str] = []
        for att in attachments:
            if _match_path(att.uri, expanded_patterns):
                matched_paths.append(att.uri)

        if not matched_paths:
            return f"No files matched pattern: {raw_pattern}"

        lines = [f"Found {len(matched_paths)} file(s):"]
        lines.extend(matched_paths)
        return "\n".join(lines)

    return make_tool(
        handler,
        name="glob",
        description=(
            "Search for files matching a shell-style glob pattern in storage. "
            "Provide an absolute runtime path pattern. Supports *, ?, [], recursive "
            "** matching zero or more directories, and comma-separated brace "
            "alternatives such as *.{jpg,png}. Shell quoting and backslash escaping "
            "are not interpreted. Default heavy-directory excludes such as .git and "
            "node_modules apply; pass "
            "disable_default_excludes=true to scan those paths. "
            f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
        ),
    )


def _glob_exclude_patterns(input: GlobInput) -> list[str]:
    """Build the final exclude pattern list from glob input."""
    patterns: list[str] = []
    if not input.disable_default_excludes:
        patterns.extend(_DEFAULT_EXCLUDE_PATTERNS)
    if input.exclude:
        patterns.extend(input.exclude)
    return patterns


def _extract_dir_prefix(pattern: str) -> str:
    """Extract the directory prefix before the first glob segment.

    :param pattern: Absolute path glob pattern
    :return: Directory prefix without glob characters
    """
    parts: list[str] = []
    for segment in pattern.split("/"):
        if _has_glob_meta(segment):
            break
        parts.append(segment)
    return "/".join(parts)


def _requires_recursive_list(pattern: str) -> bool:
    """Return whether the pattern needs nested paths below the prefix."""
    prefix = _extract_dir_prefix(pattern).rstrip("/")
    suffix = pattern[len(prefix) :].strip("/")
    return "/" in suffix or "**" in suffix


def _match_path(path: str, expanded_patterns: tuple[str, ...]) -> bool:
    """Match expanded glob patterns while preserving path segment boundaries."""
    path_segments = path.strip("/").split("/") if path != "/" else []
    for expanded_pattern in expanded_patterns:
        pattern_segments = (
            expanded_pattern.strip("/").split("/") if expanded_pattern != "/" else []
        )
        if _match_segments(path_segments, pattern_segments):
            return True
    return False


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
            raise ValueError(
                f"Brace expansion exceeds the maximum of {_MAX_BRACE_EXPANSIONS} "
                "alternatives."
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


def _match_segments(path_segments: list[str], pattern_segments: list[str]) -> bool:
    """Match path segments with support for the recursive `**` segment."""
    if not pattern_segments:
        return not path_segments
    pattern_head = pattern_segments[0]
    pattern_tail = pattern_segments[1:]
    if pattern_head == "**":
        if _match_segments(path_segments, pattern_tail):
            return True
        return bool(path_segments) and _match_segments(
            path_segments[1:], pattern_segments
        )
    if not path_segments:
        return False
    if not fnmatch.fnmatchcase(path_segments[0], pattern_head):
        return False
    return _match_segments(path_segments[1:], pattern_tail)


def _has_glob_meta(segment: str) -> bool:
    """Return whether a path segment contains glob metacharacters."""
    return any(char in segment for char in ("*", "?", "[", "{"))
