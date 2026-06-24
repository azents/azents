"""glob tool.

Search file list using absolute path pattern.
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


class GlobInput(BaseModel):
    """glob tool input."""

    pattern: str = Field(
        description=(
            "Glob pattern with absolute path prefix "
            "(e.g. /workspace/agent/*.txt, /tmp/data/*.csv)"
        ),
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

        # Match pattern with fnmatch (attachment.uri is absolute path)
        matched_paths: list[str] = []
        for att in attachments:
            if fnmatch.fnmatch(att.uri, raw_pattern):
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
            f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
        ),
    )


def _extract_dir_prefix(pattern: str) -> str:
    """Extract directory prefix before glob character from absolute path pattern.

    :param pattern: Absolute path glob pattern
    :return: Directory prefix without glob characters
    """
    parts: list[str] = []
    for segment in pattern.split("/"):
        if any(c in segment for c in ("*", "?", "[")):
            break
        parts.append(segment)
    return "/".join(parts)
