"""read_text tool.

Read and return text file from session data storage.
Used to inspect full content of truncated tool output or read text files
uploaded by user.
"""

import logging

from pydantic import BaseModel, Field

from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.path_policy import RUNTIME_ACCESSIBLE_PATHS_MSG
from azents.services.file_storage import FileStorage
from azents.services.runtime_storage_error import RuntimeStorageError

logger = logging.getLogger(__name__)


class ReadTextInput(BaseModel):
    """read_text tool input."""

    path: str = Field(
        description="Absolute path to read (e.g. /workspace/agent/notes.txt)",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Character offset to start reading from",
    )
    limit: int = Field(
        default=10_000,
        gt=0,
        description="Maximum number of characters to read (default 10000)",
    )


def make_read_text_tool(
    *,
    session_storage: FileStorage,
    agent_id: str,
    user_id: str,
) -> FunctionTool:
    """Create read_text tool.

    :param session_storage: File storage client
    :param agent_id: Agent ID
    :param user_id: User ID
    :return: read_text Tool instance
    """

    async def handler(input: ReadTextInput) -> str:
        """Read text file and return content in specified range."""
        abs_path = input.path

        # Read file
        try:
            data = await session_storage.get(
                abs_path,
                agent_id=agent_id,
            )
        except FileNotFoundError:
            raise FunctionToolError(
                f"File not found: {abs_path}. {RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None
        except RuntimeStorageError as exc:
            raise FunctionToolError(f"Failed to read file: {exc.detail}") from None
        except ValueError, OSError:
            logger.exception(
                "Failed to read text file from storage",
                extra={"path": abs_path},
            )
            raise FunctionToolError(
                f"Failed to read file: {abs_path}. {RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None

        # UTF-8 decode
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise FunctionToolError(
                f"File is not valid UTF-8 text: {abs_path}"
            ) from None

        total_chars = len(text)
        start = min(input.offset, total_chars)
        end = min(start + input.limit, total_chars)
        chunk = text[start:end]

        # Format result
        parts = [
            f"Content of {abs_path} (chars {start}-{end} of {total_chars}):",
            "",
            chunk,
        ]

        if end < total_chars:
            parts.append("")
            parts.append(
                f"... ({end} of {total_chars} chars shown."
                f" Use offset={end} to read more.)"
            )

        return "\n".join(parts)

    return make_tool(
        handler,
        name="read",
        description=(
            "Read a text file from storage. "
            "Provide an absolute path like /workspace/agent/notes.txt. "
            f"{RUNTIME_ACCESSIBLE_PATHS_MSG} "
            "Supports offset and limit for reading large files in chunks."
        ),
    )
