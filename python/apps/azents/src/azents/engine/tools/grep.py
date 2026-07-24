"""grep tool.

Search regex patterns in text files under an absolute path.
"""

import logging
import re
from typing import ClassVar

import httpx
from pydantic import BaseModel, Field

from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.services.file_storage import FileStorage
from azents.services.runtime_storage_error import RuntimeStorageError

logger = logging.getLogger(__name__)

# Maximum matching file count included in search results.
_MAX_MATCHING_FILES = 50

# Maximum matching line count included for one file.
_MAX_LINES_PER_FILE = 10

# Maximum file count grep can visit in one operation.
_MAX_SEARCHED_FILES = 10_000

# Maximum byte count grep can read in one operation.
_MAX_SCANNED_BYTES = 128 * 1024 * 1024

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


class GrepInput(BaseModel):
    """grep tool input."""

    default_exclude_patterns: ClassVar[tuple[str, ...]] = _DEFAULT_EXCLUDE_PATTERNS

    pattern: str = Field(
        description="Regular expression pattern to search for",
    )
    path: str = Field(
        description=(
            "Absolute file or directory path to search in "
            "(e.g. /workspace/agent/, /tmp/file.txt, /workspace/agent/src/)"
        ),
    )
    recursive: bool = Field(
        default=True,
        description="Search directories recursively. Ignored when path is a file.",
    )
    exclude: list[str] | None = Field(
        default=None,
        description=(
            "Additional directory or glob patterns to exclude during recursive search. "
            "Default excludes such as .git and node_modules still apply unless "
            "disable_default_excludes is true."
        ),
    )
    disable_default_excludes: bool = Field(
        default=False,
        description="Disable built-in heavy-directory excludes for this search.",
    )


def make_grep_tool(
    *,
    session_storage: FileStorage,
    agent_id: str,
) -> FunctionTool:
    """Create grep tool.

    :param session_storage: File storage client
    :param agent_id: Agent ID
    :return: grep Tool instance
    """

    async def handler(input: GrepInput) -> str:
        """Search regex pattern in files under directory."""
        abs_path = input.path

        # Compile regex
        try:
            re.compile(input.pattern)
        except re.error as exc:
            raise FunctionToolError(f"Invalid regex pattern: {exc}") from None

        try:
            grep_result = await session_storage.grep(
                abs_path,
                agent_id=agent_id,
                pattern=input.pattern,
                recursive=input.recursive,
                exclude_patterns=_grep_exclude_patterns(input),
                max_searched_files=_MAX_SEARCHED_FILES,
                max_scanned_bytes=_MAX_SCANNED_BYTES,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400:
                raise FunctionToolError(f"Invalid path: {abs_path}.") from None
            raise
        except ValueError as exc:
            raise FunctionToolError(str(exc)) from None
        except RuntimeStorageError as exc:
            raise FunctionToolError(f"Failed to grep files: {exc.detail}") from None
        except FileNotFoundError:
            # Directory does not exist; treat as no files (normal situation)
            return f"No files found in: {abs_path}"
        except OSError:
            logger.exception(
                "Failed to grep files",
                extra={"path": abs_path},
            )
            raise FunctionToolError(f"Failed to grep files in: {abs_path}.") from None

        if grep_result.searched_file_count == 0:
            return f"No files found in: {abs_path}"

        results: list[str] = []
        for file_match in grep_result.files:
            results.append(file_match.path)
            for line in file_match.lines:
                results.append(f"  {line.line_number}: {line.text}")
            if file_match.truncated:
                results.append("  ... (more matches truncated)")
        if grep_result.truncated:
            results.append(_truncation_message(grep_result.stopped_reason))

        if not results:
            return f"No matches found for pattern '{input.pattern}' in {abs_path}"

        header = f"Found matches in {grep_result.matched_file_count} file(s):"
        return "\n".join([header, *results])

    return make_tool(
        handler,
        name="grep",
        description=(
            "Search for a regex pattern in text files "
            "under a storage file or directory. "
            "Directories are searched recursively by default and common heavy "
            "directories such as .git and node_modules are excluded by default. "
            "Use exclude to add patterns, or disable_default_excludes "
            "to scan them. "
            "Provide a regex pattern and an absolute runtime file or directory path. "
        ),
    )


def _grep_exclude_patterns(input: GrepInput) -> list[str]:
    """Build the final exclude pattern list from grep input."""
    patterns: list[str] = []
    if not input.disable_default_excludes:
        patterns.extend(input.default_exclude_patterns)
    if input.exclude:
        patterns.extend(input.exclude)
    return patterns


def _truncation_message(stopped_reason: str | None) -> str:
    """Convert a truncation reason into a user-facing message."""
    if stopped_reason == "searched_file_limit":
        detail = f"{_MAX_SEARCHED_FILES} searched-file limit reached"
    elif stopped_reason == "scanned_byte_limit":
        detail = f"{_MAX_SCANNED_BYTES // (1024 * 1024)} MiB scanned-byte limit reached"
    else:
        detail = f"{_MAX_MATCHING_FILES} matching-file limit reached"
    return f"\n... (truncated, {detail})"
