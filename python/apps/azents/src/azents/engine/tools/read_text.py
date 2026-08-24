"""read_text tool.

Read and return text file from session data storage.
Used to inspect full content of truncated tool output or read text files
uploaded by user.
"""

import codecs
import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field

from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.path_policy import RUNTIME_ACCESSIBLE_PATHS_MSG
from azents.services.file_storage import RangedFileStorage
from azents.services.runtime_storage_error import RuntimeStorageError

logger = logging.getLogger(__name__)
_TEXT_READ_CHUNK_BYTES = 64 * 1024
_MAX_TEXT_READ_CHARACTERS = 64 * 1024


@dataclass(frozen=True)
class _CharacterReadResult:
    """One bounded character range and whether more text follows."""

    text: str
    truncated: bool


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
    session_storage: RangedFileStorage,
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
            result = await _read_character_range(
                session_storage,
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

        end = input.offset + len(result.text)
        parts = [
            f"Content of {abs_path} (characters {input.offset}-{end}):",
            "",
            result.text,
        ]

        if result.truncated:
            parts.append("")
            parts.append(f"... (Use offset={end} to read more.)")

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


async def _read_character_range(
    storage: RangedFileStorage,
    path: str,
    *,
    agent_id: str,
    offset: int,
    limit: int,
    encoding: str,
) -> _CharacterReadResult:
    """Read a character range with bounded byte chunks and strict decoding."""
    if offset < 0 or limit <= 0:
        raise ValueError("Character read range must be positive and non-negative")
    decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
    byte_offset = 0
    character_position = 0
    collected_count = 0
    target_count = limit + 1
    parts: list[str] = []

    def append_decoded(decoded: str) -> None:
        """Collect only the decoded characters inside the requested range."""
        nonlocal character_position, collected_count
        decoded_end = character_position + len(decoded)
        if decoded_end > offset:
            start = max(offset - character_position, 0)
            remaining = target_count - collected_count
            part = decoded[start : start + remaining]
            parts.append(part)
            collected_count += len(part)
        character_position = decoded_end

    while collected_count < target_count:
        data = await storage.read_range(
            path,
            agent_id=agent_id,
            offset=byte_offset,
            max_bytes=_TEXT_READ_CHUNK_BYTES,
        )
        eof = len(data) < _TEXT_READ_CHUNK_BYTES
        decoder_state = decoder.getstate()
        try:
            decoded = decoder.decode(data, final=eof)
        except UnicodeDecodeError as exc:
            decoder.setstate(decoder_state)
            append_decoded(decoder.decode(data[: exc.start], final=False))
            if collected_count >= target_count:
                break
            raise
        append_decoded(decoded)
        byte_offset += len(data)
        if eof:
            break

    text = "".join(parts)
    return _CharacterReadResult(
        text=text[:limit],
        truncated=len(text) > limit,
    )
