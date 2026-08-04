"""present_file tool.

Export runtime file as Exchange artifact and share with user.
"""

import logging
import posixpath
import uuid
from pathlib import PurePosixPath

from pydantic import BaseModel, Field

from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolError,
    FunctionToolResult,
)
from azents.engine.tooling.execution_context import (
    get_client_tool_execution_context,
)
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.path_policy import RUNTIME_ACCESSIBLE_PATHS_MSG
from azents.engine.tools.runtime_instruction_context import (
    PresentFilePublicationExecutor,
    RuntimeTargetResolver,
)
from azents.runtime.transfer.present_file_publication import (
    PresentFilePublicationAccessDenied,
    PresentFilePublicationError,
    PresentFilePublicationRequest,
)
from azents.runtime.transfer.runtime_to_server import RuntimeToServerTransferError
from azents.services.file_storage import FileStorage
from azents.services.runtime_storage_error import RuntimeStorageError
from azents.services.session_resource_authority import SessionResourceAuthority
from azents.services.session_storage import guess_media_type

logger = logging.getLogger(__name__)

_PUBLICATION_ID_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "https://azents.ai/runtime-transfer/present-file-publication",
)


def _is_presentable_path(path: str, workspace_root: str | None) -> bool:
    """Check whether path is durable runtime path shareable with user."""
    if workspace_root is None:
        return False
    normalized = PurePosixPath(posixpath.normpath(path))
    root = PurePosixPath(posixpath.normpath(workspace_root))
    return normalized.is_relative_to(root)


def _publication_id(*, run_id: str, call_id: str, runtime_path: str) -> str:
    """Derive a stable verified-object publication ID for one Runtime path."""
    return uuid.uuid5(
        _PUBLICATION_ID_NAMESPACE,
        f"{run_id}:{call_id}:{runtime_path}",
    ).hex


class PresentFileInput(BaseModel):
    """present_file tool input."""

    paths: list[str] = Field(
        description="List of absolute paths to present to the user",
    )


def make_present_file_tool(
    *,
    session_storage: FileStorage,
    publication_service: PresentFilePublicationExecutor,
    resolve_runtime_target: RuntimeTargetResolver,
    authority: SessionResourceAuthority,
    workspace_root: str | None,
) -> FunctionTool:
    """Create present_file tool.

    :param session_storage: runtime runner file storage
    :param publication_service: Runtime-to-server managed publication service
    :param resolve_runtime_target: Resolve a ready Runtime when the tool executes
    :param authority: Validated Session/Run resource authority
    :return: present_file Tool instance
    """

    async def handler(input: PresentFileInput) -> FunctionToolResult:
        """Export runtime file as Exchange artifact."""
        if not input.paths:
            raise FunctionToolError("No paths provided.")
        if workspace_root is None:
            raise FunctionToolError("Runtime file transfer is unavailable.")
        execution = get_client_tool_execution_context()

        attachments: list[RuntimeAttachment] = []
        errors: list[str] = []
        runtime_target = None

        for abs_path in input.paths:
            if not _is_presentable_path(abs_path, workspace_root):
                errors.append(
                    f"Only files under the Agent Workspace can be presented: {abs_path}"
                )
                continue

            # Metadata lookup (does not read entire file)
            try:
                metadata = await session_storage.stat(
                    abs_path,
                    agent_id=authority.agent_id,
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

            expected_size = metadata.get("size")
            if (
                metadata.get("is_file") is not True
                or not isinstance(expected_size, int)
                or isinstance(expected_size, bool)
                or expected_size < 0
            ):
                errors.append(
                    f"File not found or inaccessible: {abs_path}. "
                    f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
                )
                continue

            media_type = guess_media_type(abs_path)
            file_name = abs_path.rsplit("/", 1)[-1]
            publication_id = _publication_id(
                run_id=authority.run_id,
                call_id=execution.call_id,
                runtime_path=abs_path,
            )
            target = runtime_target
            try:
                if target is None:
                    target = await resolve_runtime_target()
                    runtime_target = target
                created = await publication_service.publish(
                    PresentFilePublicationRequest(
                        runtime_path=abs_path,
                        filename=file_name,
                        media_type=media_type,
                        expected_size=expected_size,
                        authority=authority,
                        target=target,
                        publication_id=publication_id,
                    )
                )
            except PresentFilePublicationAccessDenied:
                errors.append("Session resource access denied while presenting file.")
                continue
            except (
                PresentFilePublicationError,
                RuntimeToServerTransferError,
            ) as exc:
                assert target is not None
                logger.warning(
                    "Present file publication failed",
                    exc_info=True,
                    extra={
                        "agent_id": authority.agent_id,
                        "session_id": authority.session_id,
                        "run_id": authority.run_id,
                        "call_id": execution.call_id,
                        "runtime_id": target.runtime_id,
                        "runtime_generation": target.desired_generation,
                        "publication_id": publication_id,
                        "failure_stage": (
                            "exchange_publication"
                            if isinstance(exc, PresentFilePublicationError)
                            else "runtime_transfer"
                        ),
                        "failure_type": type(exc).__name__,
                    },
                )
                errors.append(f"Failed to present file: {abs_path}")
                continue
            except RuntimeStorageError as exc:
                raise FunctionToolError(
                    f"Failed to present file: {exc.detail}"
                ) from None
            except FileNotFoundError, ValueError, OSError:
                logger.warning(
                    "Failed to publish file for present_file",
                    extra={"path": abs_path},
                    exc_info=True,
                )
                errors.append(
                    f"File not found or inaccessible: {abs_path}. "
                    f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
                )
                continue

            attachments.append(
                RuntimeAttachment(
                    attachment_id=created.id,
                    uri=created.uri,
                    media_type=created.media_type,
                    size=created.size_bytes,
                    name=created.filename,
                    text_preview=created.preview_summary,
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
            "Provide a list of absolute paths under the Agent Workspace. "
            f"{RUNTIME_ACCESSIBLE_PATHS_MSG} "
            "The files will be exported as exchange:// file-location attachments that "
            "the user can preview and download."
        ),
    )
