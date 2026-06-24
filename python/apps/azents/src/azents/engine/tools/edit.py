"""edit tool.

Replace string in text file using scope/path format.
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


class EditInput(BaseModel):
    """edit tool input."""

    path: str = Field(
        description="Absolute path to edit (e.g. /workspace/agent/config.json)",
    )
    old_string: str = Field(
        description="The exact text to find and replace",
    )
    new_string: str = Field(
        description="The replacement text",
    )
    replace_all: bool = Field(
        default=False,
        description=(
            "Replace all occurrences (default: false, requires exactly one match)"
        ),
    )


def make_edit_tool(
    *,
    session_storage: FileStorage,
    agent_id: str,
    user_id: str,
) -> FunctionTool:
    """Create edit tool.

    :param session_storage: File storage client
    :param agent_id: Agent ID
    :param user_id: User ID
    :return: edit Tool instance
    """

    async def handler(input: EditInput) -> str:
        """Replace string in text file."""
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
        except ValueError as exc:
            raise FunctionToolError(str(exc)) from None
        except OSError:
            logger.exception(
                "Failed to read file for editing",
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

        # Search and replace old_string
        old_string = input.old_string
        new_string = input.new_string
        count = text.count(old_string)

        if count == 0:
            raise FunctionToolError(
                f"old_string not found in {abs_path}. "
                "Make sure the text matches exactly, including whitespace."
            )

        if not input.replace_all and count > 1:
            raise FunctionToolError(
                f"old_string found {count} times in {abs_path}. "
                "Use replace_all=true to replace all occurrences, "
                "or provide a more specific old_string."
            )

        if input.replace_all:
            new_text = text.replace(old_string, new_string)
        else:
            new_text = text.replace(old_string, new_string, 1)

        # Store
        new_data = new_text.encode("utf-8")
        media_type = guess_media_type(abs_path)

        try:
            await session_storage.put(
                abs_path,
                new_data,
                media_type,
                agent_id=agent_id,
            )
        except PermissionError:
            raise FunctionToolError(
                f"Cannot write to read-only scope: {abs_path}. "
                f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None
        except RuntimeStorageError as exc:
            raise FunctionToolError(f"Failed to save file: {exc.detail}") from None
        except ValueError as exc:
            raise FunctionToolError(str(exc)) from None
        except OSError:
            logger.exception(
                "Failed to save edited file",
                extra={"path": abs_path},
            )
            raise FunctionToolError(
                f"Failed to save file: {abs_path}. {RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None

        replacements = count if input.replace_all else 1
        return (
            f"Edited {abs_path}: replaced {replacements} occurrence(s) "
            f"of old_string with new_string."
        )

    return make_tool(
        handler,
        name="edit",
        description=(
            "Edit a text file by replacing exact string matches. "
            "Provide an absolute path like /workspace/agent/config.json, "
            "the old_string to find, and new_string to replace it with. "
            f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
        ),
    )
