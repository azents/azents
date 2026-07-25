"""write tool.

Write text file to session data storage using scope/path format.
"""

import logging

from pydantic import BaseModel, Field

from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.path_policy import RUNTIME_ACCESSIBLE_PATHS_MSG
from azents.services.file_storage import FileStorage
from azents.services.runtime_storage_error import RuntimeStorageError
from azents.services.session_storage import guess_media_type

logger = logging.getLogger(__name__)


class WriteInput(BaseModel):
    """write tool input."""

    path: str = Field(
        description=(
            "Absolute path to write (e.g. /workspace/agent/output.csv, /tmp/notes.txt)"
        ),
    )
    content: str = Field(
        description="Text content to write",
    )
    overwrite: bool = Field(
        default=False,
        description=(
            "Set to true to overwrite an existing file."
            " Fails if the file already exists and this is false."
        ),
    )


def make_write_tool(
    *,
    session_storage: FileStorage,
    agent_id: str,
) -> FunctionTool:
    """Create write tool.

    :param session_storage: File storage client
    :param agent_id: Agent ID
    :return: write Tool instance
    """

    async def handler(input: WriteInput) -> str:
        """Store text file."""
        abs_path = input.path

        # Prevent overwrite: fail when existing file exists and overwrite=False
        if not input.overwrite:
            try:
                exists = await session_storage.exists(
                    abs_path,
                    agent_id=agent_id,
                )
            except PermissionError, ValueError:
                exists = False
            except RuntimeStorageError as exc:
                raise FunctionToolError(
                    f"Failed to check destination file: {exc.detail}"
                ) from None
            if exists:
                raise FunctionToolError(
                    f"File already exists: {abs_path}. "
                    "Set overwrite=true to replace it."
                )

        # Store file
        data = input.content.encode("utf-8")
        media_type = guess_media_type(abs_path)

        try:
            attachment = await session_storage.put(
                abs_path,
                data,
                media_type,
                agent_id=agent_id,
            )
        except PermissionError:
            raise FunctionToolError(
                f"Cannot write to read-only scope: {abs_path}. "
                f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None
        except RuntimeStorageError as exc:
            raise FunctionToolError(f"Failed to write file: {exc.detail}") from None
        except ValueError as exc:
            raise FunctionToolError(str(exc)) from None
        except OSError:
            logger.exception(
                "Failed to write file to storage",
                extra={"path": abs_path},
            )
            raise FunctionToolError(
                f"Failed to write file: {abs_path}. {RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None

        return f"File written: {abs_path} ({attachment.size} bytes)"

    return make_tool(
        handler,
        name="write",
        description=(
            "Write a text file to storage. "
            "Provide an absolute path like /workspace/agent/output.csv. "
            f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
        ),
    )
