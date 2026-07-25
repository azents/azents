"""glob tool.

Search Runtime file entries using an absolute path pattern.
"""

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
) -> FunctionTool:
    """Create glob tool.

    :param session_storage: File storage client
    :param agent_id: Agent ID
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
            attachments = await session_storage.glob(
                raw_pattern,
                agent_id=agent_id,
                exclude_patterns=_glob_exclude_patterns(input),
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400:
                raise FunctionToolError(
                    f"Invalid glob pattern: {raw_pattern}. "
                    f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
                ) from None
            raise
        except ValueError as exc:
            raise FunctionToolError(str(exc)) from None
        except RuntimeStorageError as exc:
            raise FunctionToolError(f"Failed to glob files: {exc.detail}") from None
        except FileNotFoundError:
            return f"No files matched pattern: {raw_pattern}"
        except OSError:
            logger.exception(
                "Failed to glob Runtime files",
                extra={"pattern": raw_pattern},
            )
            raise FunctionToolError(
                f"Failed to glob files for pattern: {raw_pattern}. "
                f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None

        matched_paths = [attachment.uri for attachment in attachments]

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
