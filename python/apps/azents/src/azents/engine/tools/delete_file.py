"""delete_file tool.

Delete file from session data storage.
Used to clean up session files no longer needed by LLM.
"""

import asyncio
import logging

from azcommon.logging import bind_extra
from pydantic import BaseModel, Field

from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.path_policy import RUNTIME_ACCESSIBLE_PATHS_MSG
from azents.services.file_storage import FileStorage
from azents.services.runtime_storage_error import RuntimeStorageError

logger = logging.getLogger(__name__)


class DeleteFileInput(BaseModel):
    """delete_file tool input."""

    path: str = Field(
        description="Absolute runtime path to delete",
    )


def make_delete_file_tool(
    *,
    session_storage: FileStorage,
    agent_id: str,
) -> FunctionTool:
    """Create delete_file tool.

    :param session_storage: File storage client
    :param agent_id: Agent ID
    :return: delete_file Tool instance
    """

    async def handler(input: DeleteFileInput) -> str:
        """Delete session data file."""
        abs_path = input.path

        # Check whether file exists
        L = bind_extra(logger, {"path": abs_path})
        try:
            file_exists = await session_storage.exists(
                abs_path,
                agent_id=agent_id,
            )
        except asyncio.CancelledError:
            raise
        except RuntimeStorageError as exc:
            raise FunctionToolError(f"Failed to access file: {exc.detail}") from None
        except ValueError, OSError:
            L.exception(
                "Failed to check file existence",
                extra={},
            )
            raise FunctionToolError(
                f"Failed to access file: {abs_path}. {RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None

        if not file_exists:
            raise FunctionToolError(
                f"File not found: {abs_path}. {RUNTIME_ACCESSIBLE_PATHS_MSG}"
            )

        # Delete file
        try:
            await session_storage.delete(
                abs_path,
                agent_id=agent_id,
            )
        except asyncio.CancelledError:
            raise
        except FileNotFoundError:
            # Deleted after exists check (race condition)
            raise FunctionToolError(
                f"File not found: {abs_path}. "
                "The file may not have been uploaded or was already deleted."
            ) from None
        except RuntimeStorageError as exc:
            raise FunctionToolError(f"Failed to delete file: {exc.detail}") from None
        except ValueError, OSError:
            L.exception(
                "Failed to delete file from storage",
                extra={},
            )
            raise FunctionToolError(
                f"Failed to delete file: {abs_path}. {RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None

        L.info(
            "File deleted from storage",
            extra={},
        )

        return f"File deleted: {abs_path}"

    return make_tool(
        handler,
        name="delete",
        description=(
            "Delete a file from storage. "
            "Provide an absolute runtime path. "
            f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
        ),
    )
