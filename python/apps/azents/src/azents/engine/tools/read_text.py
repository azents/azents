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
_MAX_TEXT_READ_CHARACTERS = 64 * 1024


class ReadTextInput(BaseModel):
    """read_text tool input."""

    path: str = Field(
        description="Absolute runtime text path to read",
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

        try:
            result = await session_storage.get_text(
                abs_path,
                agent_id=agent_id,
                offset=input.offset,
                limit=min(input.limit, _MAX_TEXT_READ_CHARACTERS),
                encoding=input.encoding,
            )
        except FileNotFoundError:
            raise FunctionToolError(
                f"File not found: {abs_path}. {RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None
        except LookupError:
            raise FunctionToolError(
                f"Unsupported text encoding: {input.encoding}"
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

        parts = [
            (
                f"Content of {abs_path} "
                f"(characters {result.start_character}-{result.end_character}):"
            ),
            "",
            result.text,
        ]

        if result.truncated:
            parts.append("")
            parts.append(f"... (Use offset={result.end_character} to read more.)")

        return "\n".join(parts)

    return make_tool(
        handler,
        name="read",
        description=(
            "Read a text file from storage. "
            "Provide an absolute runtime path. "
            f"{RUNTIME_ACCESSIBLE_PATHS_MSG} "
            "Supports character offset and limit, plus explicit text encoding "
            "(default utf-8) for reading large files in chunks."
        ),
    )
