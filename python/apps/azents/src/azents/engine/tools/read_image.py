"""read_image tool.

Return image file in session data storage as ModelFile-backed FilePart.
"""

import logging

from azcommon.result import Failure
from pydantic import BaseModel, Field

from azents.engine.events.model_file_parts import file_output_part_from_model_file
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolError,
    FunctionToolResult,
)
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.path_policy import RUNTIME_ACCESSIBLE_PATHS_MSG
from azents.services.file_storage import FileStorage
from azents.services.model_file import (
    ModelFileAccessDenied,
    ModelFileInvalidImage,
    ModelFileOversized,
    ModelFileService,
    ModelFileSessionNotFound,
    model_file_size_limit_message,
)
from azents.services.runtime_storage_error import RuntimeStorageError

logger = logging.getLogger(__name__)

# Maximum image size (20MB)
_MAX_IMAGE_SIZE = 20 * 1024 * 1024

# File extension to MIME type mapping
_EXTENSION_TO_MEDIA_TYPE: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class ReadImageInput(BaseModel):
    """read_image tool input."""

    path: str = Field(
        description=(
            "Absolute path to read (e.g. /workspace/agent/photo.png, /tmp/chart.png)"
        ),
    )


def make_read_image_tool(
    *,
    session_storage: FileStorage,
    model_file_service: ModelFileService,
    session_id: str,
    agent_id: str,
    user_id: str,
    run_index: int,
) -> FunctionTool:
    """Create read_image tool.

    :param session_storage: runtime runner file storage
    :param model_file_service: ModelFile creation service
    :param session_id: AgentSession ID
    :param agent_id: Agent ID
    :param user_id: User ID
    :param run_index: Current run index
    :return: read_image Tool instance
    """

    async def handler(input: ReadImageInput) -> FunctionToolResult:
        """Read image file and return as FilePart output."""
        abs_path = input.path

        # Infer MIME type from extension
        dot_idx = abs_path.rfind(".")
        ext = abs_path[dot_idx:].lower() if dot_idx >= 0 else ""
        media_type = _EXTENSION_TO_MEDIA_TYPE.get(ext)
        if media_type is None:
            supported = ", ".join(
                sorted(_EXTENSION_TO_MEDIA_TYPE.keys()),
            )
            raise FunctionToolError(
                f"Unsupported image format: "
                f"'{ext or '(no extension)'}'. "
                f"Supported formats: {supported}"
            )

        # Read file (prefer file_storage)
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
            raise FunctionToolError(f"Failed to read image: {exc.detail}") from None
        except ValueError, OSError:
            logger.exception(
                "Failed to read image from storage",
                extra={"path": abs_path},
            )
            raise FunctionToolError(
                f"Failed to read file: {abs_path}. {RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None

        # Size validation
        if len(data) > _MAX_IMAGE_SIZE:
            size_mb = len(data) / (1024 * 1024)
            raise FunctionToolError(
                f"Image too large: {size_mb:.1f}MB. "
                f"Maximum allowed size is {_MAX_IMAGE_SIZE // (1024 * 1024)}MB."
            )

        model_file_result = await model_file_service.create(
            session_id=session_id,
            user_id=user_id,
            created_run_index=run_index,
            filename=_filename_from_path(abs_path),
            media_type=media_type,
            body=data,
            metadata={
                "source_kind": "runtime_path",
                "source_path": abs_path,
                "tool": "read_image",
            },
        )
        if isinstance(model_file_result, Failure):
            return _model_file_create_failure(model_file_result.error)

        model_file = model_file_result.value
        file_part = file_output_part_from_model_file(
            model_file,
            metadata={
                "source_kind": "runtime_path",
                "source_path": abs_path,
                "tool": "read_image",
            },
        )
        logger.info(
            "Image loaded as model file",
            extra={
                "path": abs_path,
                "size": len(data),
                "media_type": media_type,
                "model_file_id": model_file.id,
            },
        )
        return FunctionToolResult(
            output=[
                {
                    "type": "text",
                    "text": (
                        f"Image loaded: {abs_path} "
                        f"({model_file.media_type}, {model_file.size_bytes} bytes)."
                    ),
                },
                file_part.model_dump(mode="json", exclude_none=True),
            ]
        )

    return make_tool(
        handler,
        name="read_image",
        description=(
            "Read an image file from storage. "
            "Provide an absolute path like /workspace/agent/photo.png. "
            f"{RUNTIME_ACCESSIBLE_PATHS_MSG} "
            "Supported formats: PNG, JPEG, GIF, WebP."
        ),
    )


def _filename_from_path(path: str) -> str:
    """Return display file name from path."""
    name = path.rsplit("/", maxsplit=1)[-1]
    return name or "image"


def _model_file_create_failure(
    error: (
        ModelFileSessionNotFound
        | ModelFileAccessDenied
        | ModelFileOversized
        | ModelFileInvalidImage
    ),
) -> FunctionToolResult:
    """Convert ModelFile creation failure to tool result or tool error."""
    if isinstance(error, ModelFileOversized):
        return FunctionToolResult(
            output=[
                {
                    "type": "text",
                    "text": model_file_size_limit_message(error),
                }
            ]
        )
    if isinstance(error, ModelFileInvalidImage):
        raise FunctionToolError("Invalid image file") from None
    if isinstance(error, ModelFileSessionNotFound):
        raise FunctionToolError("Session was not found") from None
    raise FunctionToolError("Access denied for model file input") from None
