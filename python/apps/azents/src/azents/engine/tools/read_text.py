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
_MAX_TEXT_READ_BYTES = 64 * 1024


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
    encoding: str = Field(
        default="utf-8",
        min_length=1,
        max_length=64,
        description="Text encoding to use for decoding (default utf-8)",
    )


def make_read_text_tool(
    *,
    session_storage: FileStorage,
    agent_id: str,
) -> FunctionTool:
    """Create read_text tool.

    :param session_storage: File storage client
    :param agent_id: Agent ID
    :return: read_text Tool instance
    """

    async def handler(input: ReadTextInput) -> str:
        """Read text file and return content in specified range."""
        abs_path = input.path

        max_bytes = min(input.limit * 4, _MAX_TEXT_READ_BYTES)
        try:
            text = await session_storage.get_text(
                abs_path,
                agent_id=agent_id,
                offset=input.offset,
                max_bytes=max_bytes,
                encoding=input.encoding,
            )
        except FileNotFoundError:
            raise FunctionToolError(
                f"File not found: {abs_path}. {RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None
        except RuntimeStorageError as exc:
            raise FunctionToolError(f"Failed to read file: {exc.detail}") from None
        except UnicodeDecodeError:
            raise FunctionToolError(
                f"File cannot be decoded as {input.encoding}: {abs_path}"
            ) from None
        except ValueError, OSError:
            logger.exception(
                "Failed to read text file from storage",
                extra={"path": abs_path},
            )
            raise FunctionToolError(
                f"Failed to read file: {abs_path}. {RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None

        chunk = text[: input.limit]
        end = input.offset + len(chunk.encode(input.encoding))
        parts = [
            f"Content of {abs_path} (bytes {input.offset}-{end}):",
            "",
            chunk,
        ]

        if len(chunk) < len(text):
            parts.append("")
            parts.append(f"... (Use offset={end} to read more.)")

        return "\n".join(parts)

    return make_tool(
        handler,
        name="read",
        description=(
            "Read a text file from storage. "
            "Provide an absolute path like /workspace/agent/notes.txt. "
            f"{RUNTIME_ACCESSIBLE_PATHS_MSG} "
            "Supports byte offset, character limit, and explicit text encoding "
            "(default utf-8) for reading large files in chunks."
        ),
    )
