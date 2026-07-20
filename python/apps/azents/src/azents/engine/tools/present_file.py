"""present_file tool.

Export runtime file as Exchange artifact and share with user.
"""

import logging
import posixpath

from azcommon.result import Failure, Success
from pydantic import BaseModel, Field

from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolError,
    FunctionToolResult,
)
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.path_policy import RUNTIME_ACCESSIBLE_PATHS_MSG
from azents.services.exchange_file import (
    ExchangeFileService,
    FileAccessDenied,
    SessionNotFound,
)
from azents.services.file_storage import FileStorage
from azents.services.runtime_storage_error import RuntimeStorageError
from azents.services.session_storage import guess_media_type

logger = logging.getLogger(__name__)

_PRESENTABLE_ROOT = "/workspace/agent"


def _is_presentable_path(path: str) -> bool:
    """Check whether path is durable runtime path shareable with user."""
    normalized = posixpath.normpath(path)
    return normalized == _PRESENTABLE_ROOT or normalized.startswith(
        f"{_PRESENTABLE_ROOT}/"
    )


class PresentFileInput(BaseModel):
    """present_file tool input."""

    paths: list[str] = Field(
        description="List of absolute paths to present to the user",
    )


def make_present_file_tool(
    *,
    session_storage: FileStorage,
    exchange_file_service: ExchangeFileService,
    session_id: str,
    agent_id: str,
    user_id: str,
) -> FunctionTool:
    """Create present_file tool.

    :param session_storage: runtime runner file storage
    :param exchange_file_service: Exchange file service
    :param session_id: Current AgentSession ID
    :param agent_id: Agent ID
    :param user_id: User ID
    :return: present_file Tool instance
    """

    async def handler(input: PresentFileInput) -> FunctionToolResult:
        """Export runtime file as Exchange artifact."""
        if not input.paths:
            raise FunctionToolError("No paths provided.")

        attachments: list[RuntimeAttachment] = []
        errors: list[str] = []

        for abs_path in input.paths:
            if not _is_presentable_path(abs_path):
                errors.append(
                    "Only files under /workspace/agent can be presented to the user: "
                    f"{abs_path}"
                )
                continue

            # Metadata lookup (does not read entire file)
            try:
                await session_storage.stat(
                    abs_path,
                    agent_id=agent_id,
                )
            except RuntimeStorageError as exc:
                raise FunctionToolError(
                    f"Failed to access file: {exc.detail}"
                ) from None
            except FileNotFoundError, ValueError, OSError:
                logger.warning(
                    "Failed to access file for present_file",
                    extra={"path": abs_path},
                    exc_info=True,
                )
                errors.append(
                    f"File not found or inaccessible: {abs_path}. "
                    f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
                )
                continue

            media_type = guess_media_type(abs_path)
            file_name = abs_path.rsplit("/", 1)[-1]
            try:
                body = await session_storage.get(abs_path, agent_id=agent_id)
            except RuntimeStorageError as exc:
                raise FunctionToolError(f"Failed to read file: {exc.detail}") from None
            except FileNotFoundError, ValueError, OSError:
                logger.warning(
                    "Failed to read file for present_file export",
                    extra={"path": abs_path},
                    exc_info=True,
                )
                errors.append(
                    f"File not found or inaccessible: {abs_path}. "
                    f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
                )
                continue

            created = await exchange_file_service.create_artifact(
                session_id=session_id,
                user_id=user_id,
                filename=file_name,
                media_type=media_type,
                body=body,
            )
            if isinstance(created, Failure):
                error = created.error
                if isinstance(error, SessionNotFound):
                    errors.append("Session not found while presenting file.")
                    continue
                if isinstance(error, FileAccessDenied):
                    errors.append("Session access denied while presenting file.")
                    continue
                errors.append(f"Failed to present file: {abs_path}")
                continue

            if not isinstance(created, Success):
                raise FunctionToolError("Unexpected present_file result.")

            attachments.append(
                RuntimeAttachment(
                    attachment_id=created.value.id,
                    uri=created.value.uri,
                    media_type=created.value.media_type,
                    size=created.value.size_bytes,
                    name=created.value.filename,
                    text_preview=created.value.preview_summary,
                )
            )

        content_parts: list[str] = []
        if attachments:
            names = ", ".join(a.name for a in attachments)
            content_parts.append(
                f"Presented {len(attachments)} file(s) to user: {names}"
            )
        if errors:
            content_parts.append("Errors:\n" + "\n".join(f"- {e}" for e in errors))

        content = "\n\n".join(content_parts) if content_parts else "No files presented."
        output: list[dict[str, object]] = [{"type": "text", "text": content}]
        for attachment in attachments:
            output.append(
                {
                    "type": "attachment",
                    "attachment_id": attachment.attachment_id,
                    "uri": attachment.uri,
                    "name": attachment.name,
                    "media_type": attachment.media_type,
                    "size": attachment.size,
                    "preview_summary": attachment.text_preview,
                    "preview_thumbnail_uri": attachment.preview_thumbnail_uri,
                    "availability": attachment.availability,
                    "preview_title": attachment.preview_title,
                    "preview_thumbnail_media_type": (
                        attachment.preview_thumbnail_media_type
                    ),
                    "preview_thumbnail_width": attachment.preview_thumbnail_width,
                    "preview_thumbnail_height": attachment.preview_thumbnail_height,
                    "preview_generated_at": (
                        attachment.preview_generated_at.isoformat()
                        if attachment.preview_generated_at is not None
                        else None
                    ),
                }
            )
        return FunctionToolResult(
            output=output,
        )

    return make_tool(
        handler,
        name="present_file",
        description=(
            "Present files to the user. "
            "Provide a list of absolute paths "
            "under /workspace/agent (e.g. /workspace/agent/result.png). "
            f"{RUNTIME_ACCESSIBLE_PATHS_MSG} "
            "The files will be exported as exchange:// file-location attachments that "
            "the user can preview and download."
        ),
    )
