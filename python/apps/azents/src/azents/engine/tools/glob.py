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
            "Glob pattern with absolute path prefix "
            "(e.g. /workspace/agent/*.txt, /tmp/data/*.csv)"
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
            if _match_path(att.uri, raw_pattern):
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
            "Search for files matching a glob pattern in storage. "
            "Provide an absolute runtime path pattern. "
            "Default heavy-directory excludes such as .git and node_modules apply; "
            "pass disable_default_excludes=true to scan those paths. "
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


def _match_path(path: str, pattern: str) -> bool:
    """Match a glob pattern while preserving path separators as boundaries."""
    path_segments = path.strip("/").split("/") if path != "/" else []
    pattern_segments = pattern.strip("/").split("/") if pattern != "/" else []
    return _match_segments(path_segments, pattern_segments)


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
    return any(char in segment for char in ("*", "?", "["))
