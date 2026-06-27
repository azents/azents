"""ModelFile service."""

import dataclasses
import hashlib
import re
from io import BytesIO
from typing import Annotated, Literal

from azcommon.infra.s3.service import S3Service
from azcommon.result import Failure, Result, Success
from azcommon.types import JSONValue
from fastapi import Depends
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import ModelFileStatus
from azents.core.s3.deps import get_s3_service
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.model_file import ModelFileRepository
from azents.repos.model_file.data import ModelFile, ModelFileCreate
from azents.repos.workspace_user import WorkspaceUserRepository

_IMAGE_MEDIA_PREFIX = "image/"
_TEXT_MEDIA_PREFIX = "text/"
_MODEL_IMAGE_MEDIA_TYPE = "image/jpeg"
_MODEL_IMAGE_NORMALIZED_FORMAT = "jpeg"
_ORIGINAL_NORMALIZED_FORMAT = "original"
_IMAGE_JPEG_QUALITY = 85
_NON_IMAGE_MAX_BYTES = 1_000_000


@dataclasses.dataclass(frozen=True)
class ModelFileSessionNotFound:
    """Session not found."""


@dataclasses.dataclass(frozen=True)
class ModelFileNotFound:
    """ModelFile not found."""


@dataclasses.dataclass(frozen=True)
class ModelFileAccessDenied:
    """No ModelFile access permission."""


@dataclasses.dataclass(frozen=True)
class ModelFileUnavailable:
    """Cannot access ModelFile blob in object storage."""


@dataclasses.dataclass(frozen=True)
class ModelFileOversized:
    """ModelFile creation size cap exceeded."""

    max_bytes: int
    actual_bytes: int


@dataclasses.dataclass(frozen=True)
class ModelFileInvalidImage:
    """Image ModelFile normalization failed."""


@dataclasses.dataclass(frozen=True)
class ModelFileDownload:
    """ModelFile download result."""

    model_file: ModelFile
    body: bytes


@dataclasses.dataclass(frozen=True)
class NormalizedModelFileBody:
    """Normalized blob to store in ModelFileStore."""

    body: bytes
    media_type: str
    kind: Literal["image", "document", "text", "binary"]
    normalized_format: str


ModelFileCreateError = (
    ModelFileSessionNotFound
    | ModelFileAccessDenied
    | ModelFileOversized
    | ModelFileInvalidImage
)
ModelFileResolveError = ModelFileNotFound | ModelFileAccessDenied | ModelFileUnavailable


def model_file_size_limit_message(error: ModelFileOversized) -> str:
    """Return size cap exceeded message shown to user."""
    return (
        "File size exceeds the allowed limit: "
        f"{error.actual_bytes} bytes > {error.max_bytes} bytes. "
        "This file was not stored as model input."
    )


@dataclasses.dataclass
class ModelFileService:
    """Coordinate ModelFile metadata and object storage."""

    model_file_repository: Annotated[ModelFileRepository, Depends(ModelFileRepository)]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
    ]
    agent_run_repository: Annotated[
        AgentRunRepository,
        Depends(AgentRunRepository),
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository,
        Depends(WorkspaceUserRepository),
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]
    s3_service: Annotated[S3Service, Depends(get_s3_service)]
    config: Annotated[Config, Depends(get_config)]

    async def create(
        self,
        *,
        session_id: str,
        user_id: str,
        created_run_index: int,
        filename: str | None,
        media_type: str,
        body: bytes,
        metadata: dict[str, object] | None = None,
    ) -> Result[ModelFile, ModelFileCreateError]:
        """Create ModelFile metadata and normalized object."""
        normalized = normalize_model_file_body(media_type=media_type, body=body)
        if isinstance(normalized, Failure):
            return Failure(normalized.error)

        uploaded_object_key: str | None = None
        succeeded = False
        try:
            created_result: Success[ModelFile] | None = None
            async with self.session_manager() as session:
                agent_session = await self.agent_session_repository.get_by_id(
                    session,
                    session_id,
                )
                if agent_session is None:
                    return Failure(ModelFileSessionNotFound())
                if not await self._has_workspace_access(
                    session,
                    workspace_id=agent_session.workspace_id,
                    user_id=user_id,
                ):
                    return Failure(ModelFileAccessDenied())

                normalized_body = normalized.value
                created = await self.model_file_repository.create(
                    session,
                    ModelFileCreate(
                        workspace_id=agent_session.workspace_id,
                        session_id=session_id,
                        agent_id=agent_session.agent_id,
                        name=_sanitize_display_filename(filename),
                        media_type=normalized_body.media_type,
                        kind=normalized_body.kind,
                        size_bytes=len(normalized_body.body),
                        created_run_index=created_run_index,
                        normalized_format=normalized_body.normalized_format,
                        sha256=hashlib.sha256(normalized_body.body).hexdigest(),
                        metadata=_json_metadata(metadata),
                    ),
                )
                await self.s3_service.upload(
                    bucket=self.config.workspace_s3.bucket,
                    key=created.storage_key,
                    body=normalized_body.body,
                    content_type=normalized_body.media_type,
                )
                uploaded_object_key = created.storage_key
                created_result = Success(created)
            succeeded = True
            return created_result
        finally:
            if not succeeded:
                await self._cleanup_uploaded_object(uploaded_object_key)

    async def create_for_pending_input(
        self,
        *,
        session_id: str,
        user_id: str,
        filename: str | None,
        media_type: str,
        body: bytes,
        metadata: dict[str, object] | None = None,
    ) -> Result[ModelFile, ModelFileCreateError]:
        """Create ModelFile for user input that has not started yet."""
        async with self.session_manager() as session:
            next_run_index = await self.agent_run_repository.next_run_index(
                session,
                session_id=session_id,
            )
        return await self.create(
            session_id=session_id,
            user_id=user_id,
            created_run_index=next_run_index,
            filename=filename,
            media_type=media_type,
            body=body,
            metadata=metadata,
        )

    async def create_for_agent_pending_input(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        filename: str | None,
        media_type: str,
        body: bytes,
        metadata: dict[str, object] | None = None,
    ) -> Result[ModelFile, ModelFileCreateError]:
        """Create ModelFile for user input in current Agent namespace."""
        normalized = normalize_model_file_body(media_type=media_type, body=body)
        if isinstance(normalized, Failure):
            return Failure(normalized.error)

        uploaded_object_key: str | None = None
        succeeded = False
        try:
            created_result: Success[ModelFile] | None = None
            async with self.session_manager() as session:
                agent = await self.agent_repository.get_by_id(session, agent_id)
                if agent is None:
                    return Failure(ModelFileSessionNotFound())
                if not await self._has_workspace_access(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                ):
                    return Failure(ModelFileAccessDenied())
                next_run_index = await self.agent_run_repository.next_run_index(
                    session,
                    session_id=session_id,
                )

                normalized_body = normalized.value
                created = await self.model_file_repository.create(
                    session,
                    ModelFileCreate(
                        workspace_id=agent.workspace_id,
                        session_id=session_id,
                        agent_id=agent.id,
                        name=_sanitize_display_filename(filename),
                        media_type=normalized_body.media_type,
                        kind=normalized_body.kind,
                        size_bytes=len(normalized_body.body),
                        created_run_index=next_run_index,
                        normalized_format=normalized_body.normalized_format,
                        sha256=hashlib.sha256(normalized_body.body).hexdigest(),
                        metadata=_json_metadata(metadata),
                    ),
                )
                await self.s3_service.upload(
                    bucket=self.config.workspace_s3.bucket,
                    key=created.storage_key,
                    body=normalized_body.body,
                    content_type=normalized_body.media_type,
                )
                uploaded_object_key = created.storage_key
                created_result = Success(created)
            succeeded = True
            return created_result
        finally:
            if not succeeded:
                await self._cleanup_uploaded_object(uploaded_object_key)

    async def download(
        self,
        *,
        model_file_id: str,
        user_id: str,
    ) -> Result[ModelFileDownload, ModelFileResolveError]:
        """Fetch ModelFile normalized blob."""
        model_file_result = await self._get_accessible_model_file(
            model_file_id=model_file_id,
            user_id=user_id,
        )
        return await self._download_resolved_model_file(model_file_result)

    async def download_for_agent(
        self,
        *,
        model_file_id: str,
        agent_id: str,
        user_id: str,
    ) -> Result[ModelFileDownload, ModelFileResolveError]:
        """Fetch ModelFile normalized blob inside current Agent namespace."""
        model_file_result = await self._get_accessible_model_file_for_agent(
            model_file_id=model_file_id,
            agent_id=agent_id,
            user_id=user_id,
        )
        return await self._download_resolved_model_file(model_file_result)

    async def _download_resolved_model_file(
        self,
        model_file_result: Result[
            ModelFile,
            ModelFileNotFound | ModelFileAccessDenied,
        ],
    ) -> Result[ModelFileDownload, ModelFileResolveError]:
        """Download ModelFile blob already verified for namespace/permission."""
        if isinstance(model_file_result, Failure):
            return Failure(model_file_result.error)
        model_file = model_file_result.value
        if model_file.status != ModelFileStatus.AVAILABLE:
            return Failure(ModelFileUnavailable())
        body = await self.s3_service.download_bytes(
            bucket=self.config.workspace_s3.bucket,
            key=model_file.storage_key,
        )
        if body is None:
            return Failure(ModelFileUnavailable())
        return Success(ModelFileDownload(model_file=model_file, body=body))

    async def _get_accessible_model_file(
        self,
        *,
        model_file_id: str,
        user_id: str,
    ) -> Result[ModelFile, ModelFileNotFound | ModelFileAccessDenied]:
        """Check ModelFile metadata together with workspace access permission."""
        async with self.session_manager() as session:
            model_file = await self.model_file_repository.get_by_id(
                session,
                model_file_id,
            )
            return await self._authorize_model_file(
                session,
                model_file=model_file,
                user_id=user_id,
            )

    async def _get_accessible_model_file_for_agent(
        self,
        *,
        model_file_id: str,
        agent_id: str,
        user_id: str,
    ) -> Result[ModelFile, ModelFileNotFound | ModelFileAccessDenied]:
        """Check ModelFile metadata only inside current Agent namespace."""
        async with self.session_manager() as session:
            model_file = await self.model_file_repository.get_by_id_for_agent(
                session,
                model_file_id=model_file_id,
                agent_id=agent_id,
            )
            return await self._authorize_model_file(
                session,
                model_file=model_file,
                user_id=user_id,
            )

    async def _authorize_model_file(
        self,
        session: AsyncSession,
        *,
        model_file: ModelFile | None,
        user_id: str,
    ) -> Result[ModelFile, ModelFileNotFound | ModelFileAccessDenied]:
        """Check workspace access permission of fetched ModelFile."""
        if model_file is None:
            return Failure(ModelFileNotFound())
        if not await self._has_workspace_access(
            session,
            workspace_id=model_file.workspace_id,
            user_id=user_id,
        ):
            return Failure(ModelFileAccessDenied())
        return Success(model_file)

    async def _has_workspace_access(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        user_id: str,
    ) -> bool:
        """Check whether user is workspace member."""
        workspace_user = await self.workspace_user_repository.get_by_workspace_and_user(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        return workspace_user is not None

    async def _cleanup_uploaded_object(self, object_key: str | None) -> None:
        """Delete already uploaded object when metadata commit fails."""
        if object_key is None:
            return
        await self.s3_service.delete(
            bucket=self.config.workspace_s3.bucket,
            key=object_key,
        )


def normalize_model_file_body(
    *,
    media_type: str,
    body: bytes,
) -> Result[NormalizedModelFileBody, ModelFileOversized | ModelFileInvalidImage]:
    """Normalize to provider-neutral blob for ModelFileStore storage."""
    if media_type.startswith(_IMAGE_MEDIA_PREFIX):
        return _normalize_image_model_file(body)
    if len(body) > _NON_IMAGE_MAX_BYTES:
        return Failure(
            ModelFileOversized(
                max_bytes=_NON_IMAGE_MAX_BYTES,
                actual_bytes=len(body),
            )
        )
    return Success(
        NormalizedModelFileBody(
            body=body,
            media_type=media_type,
            kind=_kind_for_media_type(media_type),
            normalized_format=_ORIGINAL_NORMALIZED_FORMAT,
        )
    )


def _normalize_image_model_file(
    body: bytes,
) -> Result[NormalizedModelFileBody, ModelFileOversized | ModelFileInvalidImage]:
    """Normalize Image ModelFile to JPEG blob."""
    normalized = _jpeg_model_file_body(
        body=body,
        max_edge=None,
        normalized_format=_MODEL_IMAGE_NORMALIZED_FORMAT,
    )
    if isinstance(normalized, Failure):
        return Failure(normalized.error)
    return Success(normalized.value)


def _jpeg_model_file_body(
    *,
    body: bytes,
    max_edge: int | None,
    normalized_format: str,
) -> Result[NormalizedModelFileBody, ModelFileInvalidImage]:
    """Convert image bytes to JPEG blob for ModelFile."""
    try:
        image = Image.open(BytesIO(body))
        image.load()
    except OSError, UnidentifiedImageError, ValueError:
        return Failure(ModelFileInvalidImage())

    image = ImageOps.exif_transpose(image)
    has_alpha = image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    )
    if has_alpha:
        background = Image.new("RGB", image.size, (255, 255, 255))
        alpha = image.convert("RGBA").getchannel("A")
        background.paste(image.convert("RGBA"), mask=alpha)
        image = background
    else:
        image = image.convert("RGB")

    if max_edge is not None:
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)

    output = BytesIO()
    image.save(output, format="JPEG", quality=_IMAGE_JPEG_QUALITY, optimize=True)
    return Success(
        NormalizedModelFileBody(
            body=output.getvalue(),
            media_type=_MODEL_IMAGE_MEDIA_TYPE,
            kind="image",
            normalized_format=normalized_format,
        )
    )


def _kind_for_media_type(
    media_type: str,
) -> Literal["image", "document", "text", "binary"]:
    """Classify MIME type as FilePart kind."""
    if media_type.startswith(_IMAGE_MEDIA_PREFIX):
        return "image"
    if media_type.startswith(_TEXT_MEDIA_PREFIX):
        return "text"
    if media_type in {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }:
        return "document"
    return "binary"


def _sanitize_display_filename(filename: str | None) -> str | None:
    """Normalize as ModelFile filename for display."""
    if filename is None:
        return None
    sanitized = re.sub(r"[\\/\x00-\x1f\x7f]+", "_", filename).strip().strip(".")
    if sanitized:
        return sanitized[:255]
    return None


def _json_metadata(metadata: dict[str, object] | None) -> dict[str, JSONValue]:
    """Return dict metadata storable in JSONB."""
    if metadata is None:
        return {}
    return {key: _json_value(value) for key, value in metadata.items()}


def _json_value(value: object) -> JSONValue:
    """Normalize arbitrary value to JSONValue."""
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)
