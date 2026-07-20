"""Exchange file service."""

import dataclasses
import datetime
import hashlib
import logging
import re
import unicodedata
from io import BytesIO
from typing import Annotated, assert_never

from azcommon.infra.s3.service import S3Service
from azcommon.result import Failure, Result, Success
from azcommon.uuid import uuid7
from fastapi import Depends
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import ExchangeFileOrigin, ExchangeFileStatus
from azents.core.s3.deps import get_s3_service
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file import ExchangeFileRepository, exchange_file_object_key
from azents.repos.exchange_file.data import (
    ExchangeFile,
    ExchangeFileClaimExpired,
    ExchangeFileClaimNotFound,
    ExchangeFileClaimOwnerConflict,
    ExchangeFileClaimUnavailable,
    ExchangeFileClaimWrongScope,
    ExchangeFileCreate,
)
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.file_lifecycle_policy import exchange_file_expires_at

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class SessionNotFound:
    """Session not found."""


@dataclasses.dataclass(frozen=True)
class FileNotFound:
    """Exchange file not found."""


@dataclasses.dataclass(frozen=True)
class FileAccessDenied:
    """No Exchange file access permission."""


@dataclasses.dataclass(frozen=True)
class FileExpired:
    """Exchange file expired."""


@dataclasses.dataclass(frozen=True)
class FileUnavailable:
    """Cannot access original file in object storage."""


@dataclasses.dataclass(frozen=True)
class FileRetentionOwnerConflict:
    """Exchange file is already bound to another root session."""


ExchangeFileInputClaimError = (
    FileNotFound
    | FileAccessDenied
    | FileExpired
    | FileUnavailable
    | FileRetentionOwnerConflict
)


@dataclasses.dataclass(frozen=True)
class ExchangeFileDownload:
    """Exchange file download result."""

    file: ExchangeFile
    body: bytes


@dataclasses.dataclass(frozen=True)
class ExchangeFileWithPreview:
    """Preview thumbnail linked to Exchange file to delete."""

    file: ExchangeFile
    preview_thumbnail: ExchangeFile | None


ExchangeFileError = (
    SessionNotFound | FileNotFound | FileAccessDenied | FileExpired | FileUnavailable
)
_PREVIEW_THUMBNAIL_MAX_SIZE = 512
_PREVIEW_THUMBNAIL_MEDIA_TYPE = "image/jpeg"
_MAX_TEXT_PREVIEW_CHARS = 2000
_TEXT_PREVIEW_MEDIA_TYPES = {
    "application/graphql",
    "application/javascript",
    "application/json",
    "application/rtf",
    "application/sql",
    "application/toml",
    "application/x-httpd-php",
    "application/x-javascript",
    "application/x-latex",
    "application/x-sh",
    "application/x-tex",
    "application/xml",
    "application/yaml",
}
_TEXT_PREVIEW_MEDIA_TYPE_SUFFIXES = ("+json", "+xml", "+yaml")
_UNKNOWN_MEDIA_TYPE = "application/octet-stream"


@dataclasses.dataclass(frozen=True)
class ExchangePreviewThumbnail:
    """Created preview thumbnail bytes and metadata."""

    body: bytes
    width: int
    height: int
    generated_at: datetime.datetime


@dataclasses.dataclass(frozen=True)
class _PreparedExchangeFile:
    """Exchange file metadata and blob prepared before persistence."""

    create: ExchangeFileCreate
    object_key: str
    body: bytes
    preview_width: int | None = None
    preview_height: int | None = None
    preview_generated_at: datetime.datetime | None = None


def exchange_object_key_from_uri(uri: str) -> str | None:
    """Return object key from Exchange file-location URI."""
    prefix = "exchange://"
    if not uri.startswith(prefix):
        return None
    object_key = uri.removeprefix(prefix)
    if not object_key:
        return None
    return object_key


def sanitize_exchange_filename(filename: str | None) -> str:
    """Normalize as display filename safe for download header."""
    raw = filename if filename is not None else "upload"
    sanitized = re.sub(r"[\\/\x00-\x1f\x7f]+", "_", raw).strip().strip(".")
    if sanitized:
        return sanitized[:255]
    return "upload"


def _make_text_preview(body: bytes, media_type: str) -> str | None:
    """Create a bounded preview when attachment bytes are safe UTF-8 text."""
    normalized_media_type = media_type.partition(";")[0].strip().lower()
    supported = (
        normalized_media_type.startswith("text/")
        or normalized_media_type in _TEXT_PREVIEW_MEDIA_TYPES
        or normalized_media_type.endswith(_TEXT_PREVIEW_MEDIA_TYPE_SUFFIXES)
        or normalized_media_type == _UNKNOWN_MEDIA_TYPE
    )
    if not supported:
        return None

    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if any(
        unicodedata.category(character) == "Cc" and character not in "\t\n\r"
        for character in text
    ):
        return None
    if len(text) <= _MAX_TEXT_PREVIEW_CHARS:
        return text
    return text[:_MAX_TEXT_PREVIEW_CHARS] + "\n... (truncated)"


def make_exchange_preview_thumbnail(
    body: bytes,
    media_type: str,
) -> ExchangePreviewThumbnail | None:
    """Convert image bytes to JPEG thumbnail for attachment preview."""
    if not media_type.startswith("image/"):
        return None
    try:
        img = Image.open(BytesIO(body))
        img.load()
    except (OSError, UnidentifiedImageError, ValueError) as err:
        logger.warning(
            "Exchange image upload did not produce preview thumbnail",
            extra={"media_type": media_type, "reason": type(err).__name__},
        )
        return None

    img = ImageOps.exif_transpose(img)
    img.thumbnail(
        (_PREVIEW_THUMBNAIL_MAX_SIZE, _PREVIEW_THUMBNAIL_MAX_SIZE),
        Image.Resampling.LANCZOS,
    )
    if img.mode in {"RGBA", "LA"} or (img.mode == "P" and "transparency" in img.info):
        background = Image.new("RGB", img.size, (255, 255, 255))
        alpha = img.convert("RGBA").getchannel("A")
        background.paste(img.convert("RGBA"), mask=alpha)
        img = background
    else:
        img = img.convert("RGB")

    thumbnail = BytesIO()
    img.save(thumbnail, format="JPEG", quality=85, optimize=True)
    return ExchangePreviewThumbnail(
        body=thumbnail.getvalue(),
        width=img.width,
        height=img.height,
        generated_at=datetime.datetime.now(datetime.UTC),
    )


@dataclasses.dataclass
class ExchangeFileService:
    """Coordinate Exchange file metadata and object storage."""

    exchange_file_repository: Annotated[
        ExchangeFileRepository, Depends(ExchangeFileRepository)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    s3_service: Annotated[S3Service, Depends(get_s3_service)]
    config: Annotated[Config, Depends(get_config)]

    async def create_agent_upload(
        self,
        *,
        agent_id: str,
        user_id: str,
        filename: str | None,
        media_type: str,
        body: bytes,
    ) -> Result[ExchangeFile, SessionNotFound | FileAccessDenied]:
        """Store Web upload as Exchange upload file by Agent.

        Web upload API receives only agent_id so clients need not know AgentSession ID.
        Upload origin files are stored by workspace + agent, not session/runtime.
        """
        return await self._create_agent_file(
            agent_id=agent_id,
            user_id=user_id,
            filename=filename,
            media_type=media_type,
            body=body,
            origin_type=ExchangeFileOrigin.UPLOAD,
        )

    async def create_session_upload(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        filename: str | None,
        media_type: str,
        body: bytes,
    ) -> Result[ExchangeFile, SessionNotFound | FileAccessDenied]:
        """Store Web upload as Exchange upload file by AgentSession."""
        return await self._create_agent_session_file(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            filename=filename,
            media_type=media_type,
            body=body,
            origin_type=ExchangeFileOrigin.UPLOAD,
        )

    async def create_artifact(
        self,
        *,
        session_id: str,
        user_id: str,
        filename: str | None,
        media_type: str,
        body: bytes,
    ) -> Result[ExchangeFile, SessionNotFound | FileAccessDenied]:
        """Store Runtime artifact as Exchange artifact file."""
        return await self._create_file(
            session_id=session_id,
            user_id=user_id,
            filename=filename,
            media_type=media_type,
            body=body,
            origin_type=ExchangeFileOrigin.ARTIFACT,
        )

    async def claim_input_attachments(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        attachment_uris: list[str],
    ) -> Result[None, ExchangeFileInputClaimError]:
        """Claim input ExchangeFiles inside the caller's acceptance transaction."""
        if not attachment_uris:
            return Success(None)
        object_keys: list[str] = []
        for uri in attachment_uris:
            object_key = exchange_object_key_from_uri(uri)
            if object_key is None:
                return Failure(FileNotFound())
            object_keys.append(object_key)

        agent_session = await self.agent_session_repository.get_by_id(
            session,
            session_id,
        )
        if agent_session is None or agent_session.agent_id != agent_id:
            return Failure(FileAccessDenied())
        if not await self._has_workspace_access(
            session,
            workspace_id=agent_session.workspace_id,
            user_id=user_id,
        ):
            return Failure(FileAccessDenied())
        root = await self.agent_session_repository.get_root_session_agent_by_session_id(
            session,
            session_id,
        )
        if root is None:
            return Failure(FileAccessDenied())

        claim = await self.exchange_file_repository.claim_for_retention_root(
            session,
            object_keys=object_keys,
            workspace_id=agent_session.workspace_id,
            agent_id=agent_id,
            retention_root_session_id=root.agent_session_id,
            bound_at=datetime.datetime.now(datetime.UTC),
        )
        match claim:
            case Success():
                return Success(None)
            case Failure(error):
                match error:
                    case ExchangeFileClaimNotFound():
                        return Failure(FileNotFound())
                    case ExchangeFileClaimWrongScope():
                        return Failure(FileAccessDenied())
                    case ExchangeFileClaimExpired():
                        return Failure(FileExpired())
                    case ExchangeFileClaimUnavailable():
                        return Failure(FileUnavailable())
                    case ExchangeFileClaimOwnerConflict():
                        return Failure(FileRetentionOwnerConflict())
                    case _:
                        assert_never(error)
            case _:
                assert_never(claim)

    async def _create_agent_file(
        self,
        *,
        agent_id: str,
        user_id: str,
        filename: str | None,
        media_type: str,
        body: bytes,
        origin_type: ExchangeFileOrigin,
    ) -> Result[ExchangeFile, SessionNotFound | FileAccessDenied]:
        """Create Exchange upload file without session by Agent."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(SessionNotFound())
            if not await self._has_workspace_access(
                session, workspace_id=agent.workspace_id, user_id=user_id
            ):
                return Failure(FileAccessDenied())
            workspace_id = agent.workspace_id

        prepared = self._prepare_files(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            filename=filename,
            media_type=media_type,
            body=body,
            origin_type=origin_type,
            retention_root_session_id=None,
        )
        succeeded = False
        try:
            await self._upload_prepared_files(prepared)
            async with self.session_manager() as session:
                agent = await self.agent_repository.get_by_id(session, agent_id)
                if agent is None or agent.workspace_id != workspace_id:
                    return Failure(SessionNotFound())
                if not await self._has_workspace_access(
                    session,
                    workspace_id=workspace_id,
                    user_id=user_id,
                ):
                    return Failure(FileAccessDenied())
                created = await self._persist_prepared_files(session, prepared)
            succeeded = True
            return Success(created)
        finally:
            if not succeeded:
                await self._cleanup_uploaded_objects(
                    [file.object_key for file in prepared]
                )

    async def _create_agent_session_file(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        filename: str | None,
        media_type: str,
        body: bytes,
        origin_type: ExchangeFileOrigin,
    ) -> Result[ExchangeFile, SessionNotFound | FileAccessDenied]:
        """Create Exchange file by AgentSession."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            if agent_session is None or agent_session.agent_id != agent_id:
                return Failure(SessionNotFound())
            if not await self._has_workspace_access(
                session, workspace_id=agent_session.workspace_id, user_id=user_id
            ):
                return Failure(FileAccessDenied())
            get_root = (
                self.agent_session_repository.get_root_session_agent_by_session_id
            )
            root = await get_root(session, session_id)
            if root is None:
                return Failure(SessionNotFound())
            workspace_id = agent_session.workspace_id
            retention_root_session_id = root.agent_session_id

        prepared = self._prepare_files(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            filename=filename,
            media_type=media_type,
            body=body,
            origin_type=origin_type,
            retention_root_session_id=retention_root_session_id,
        )
        succeeded = False
        try:
            await self._upload_prepared_files(prepared)
            async with self.session_manager() as session:
                agent_session = await self.agent_session_repository.get_by_id(
                    session, session_id
                )
                if (
                    agent_session is None
                    or agent_session.agent_id != agent_id
                    or agent_session.workspace_id != workspace_id
                ):
                    return Failure(SessionNotFound())
                if not await self._has_workspace_access(
                    session,
                    workspace_id=workspace_id,
                    user_id=user_id,
                ):
                    return Failure(FileAccessDenied())
                root = await (
                    self.agent_session_repository.get_root_session_agent_by_session_id
                )(
                    session,
                    session_id,
                )
                if root is None or root.agent_session_id != retention_root_session_id:
                    return Failure(SessionNotFound())
                created = await self._persist_prepared_files(session, prepared)
            succeeded = True
            return Success(created)
        finally:
            if not succeeded:
                await self._cleanup_uploaded_objects(
                    [file.object_key for file in prepared]
                )

    async def _create_file(
        self,
        *,
        session_id: str,
        user_id: str,
        filename: str | None,
        media_type: str,
        body: bytes,
        origin_type: ExchangeFileOrigin,
    ) -> Result[ExchangeFile, SessionNotFound | FileAccessDenied]:
        """Create Exchange file metadata and object."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            if agent_session is None:
                return Failure(SessionNotFound())
            if not await self._has_workspace_access(
                session, workspace_id=agent_session.workspace_id, user_id=user_id
            ):
                return Failure(FileAccessDenied())
            get_root = (
                self.agent_session_repository.get_root_session_agent_by_session_id
            )
            root = await get_root(session, session_id)
            if root is None:
                return Failure(SessionNotFound())
            workspace_id = agent_session.workspace_id
            agent_id = agent_session.agent_id
            retention_root_session_id = root.agent_session_id

        prepared = self._prepare_files(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=user_id,
            filename=filename,
            media_type=media_type,
            body=body,
            origin_type=origin_type,
            retention_root_session_id=retention_root_session_id,
        )
        succeeded = False
        try:
            await self._upload_prepared_files(prepared)
            async with self.session_manager() as session:
                agent_session = await self.agent_session_repository.get_by_id(
                    session, session_id
                )
                if (
                    agent_session is None
                    or agent_session.agent_id != agent_id
                    or agent_session.workspace_id != workspace_id
                ):
                    return Failure(SessionNotFound())
                if not await self._has_workspace_access(
                    session,
                    workspace_id=workspace_id,
                    user_id=user_id,
                ):
                    return Failure(FileAccessDenied())
                root = await (
                    self.agent_session_repository.get_root_session_agent_by_session_id
                )(
                    session,
                    session_id,
                )
                if root is None or root.agent_session_id != retention_root_session_id:
                    return Failure(SessionNotFound())
                created = await self._persist_prepared_files(session, prepared)
            succeeded = True
            return Success(created)
        finally:
            if not succeeded:
                await self._cleanup_uploaded_objects(
                    [file.object_key for file in prepared]
                )

    def _prepare_files(
        self,
        *,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        filename: str | None,
        media_type: str,
        body: bytes,
        origin_type: ExchangeFileOrigin,
        retention_root_session_id: str | None,
    ) -> list[_PreparedExchangeFile]:
        """Prepare stable metadata and object keys before external upload."""
        safe_filename = sanitize_exchange_filename(filename)
        sha256 = hashlib.sha256(body).hexdigest()
        now = datetime.datetime.now(datetime.UTC)
        expires_at = exchange_file_expires_at(now=now, config=self.config)
        file_id = uuid7().hex
        prepared = [
            _PreparedExchangeFile(
                create=ExchangeFileCreate(
                    id=file_id,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    origin_type=origin_type,
                    filename=safe_filename,
                    media_type=media_type,
                    size_bytes=len(body),
                    sha256=sha256,
                    created_by_user_id=user_id,
                    retention_root_session_id=retention_root_session_id,
                    retention_bound_at=(
                        now if retention_root_session_id is not None else None
                    ),
                    expires_at=expires_at,
                    preview_title=safe_filename,
                    preview_summary=_make_text_preview(body, media_type),
                    preview_generated_at=now,
                ),
                object_key=exchange_file_object_key(
                    workspace_id=workspace_id,
                    file_id=file_id,
                ),
                body=body,
            )
        ]

        thumbnail_body = make_exchange_preview_thumbnail(body, media_type)
        if thumbnail_body is None:
            return prepared

        thumbnail_id = uuid7().hex
        prepared.append(
            _PreparedExchangeFile(
                create=ExchangeFileCreate(
                    id=thumbnail_id,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    origin_type=origin_type,
                    filename=f"{safe_filename}.preview.jpg",
                    media_type=_PREVIEW_THUMBNAIL_MEDIA_TYPE,
                    size_bytes=len(thumbnail_body.body),
                    sha256=hashlib.sha256(thumbnail_body.body).hexdigest(),
                    created_by_user_id=user_id,
                    retention_root_session_id=retention_root_session_id,
                    retention_bound_at=(
                        now if retention_root_session_id is not None else None
                    ),
                    expires_at=expires_at,
                    preview_title=f"{safe_filename} preview",
                    preview_generated_at=thumbnail_body.generated_at,
                ),
                object_key=exchange_file_object_key(
                    workspace_id=workspace_id,
                    file_id=thumbnail_id,
                ),
                body=thumbnail_body.body,
                preview_width=thumbnail_body.width,
                preview_height=thumbnail_body.height,
                preview_generated_at=thumbnail_body.generated_at,
            )
        )
        return prepared

    async def _upload_prepared_files(
        self,
        prepared: list[_PreparedExchangeFile],
    ) -> None:
        """Upload prepared blobs without an open DB session."""
        for file in prepared:
            await self.s3_service.upload(
                bucket=self.config.workspace_s3.bucket,
                key=file.object_key,
                body=file.body,
                content_type=file.create.media_type,
            )

    async def _persist_prepared_files(
        self,
        session: AsyncSession,
        prepared: list[_PreparedExchangeFile],
    ) -> ExchangeFile:
        """Persist uploaded file metadata atomically in the verified scope."""
        source = await self.exchange_file_repository.create(
            session,
            prepared[0].create,
        )
        if len(prepared) == 1:
            return source

        thumbnail_prepared = prepared[1]
        thumbnail = await self.exchange_file_repository.create(
            session,
            thumbnail_prepared.create,
        )
        if (
            thumbnail_prepared.preview_width is None
            or thumbnail_prepared.preview_height is None
            or thumbnail_prepared.preview_generated_at is None
        ):
            raise ValueError("Prepared thumbnail metadata is incomplete")
        return await self.exchange_file_repository.set_preview_thumbnail_file_id(
            session,
            file_id=source.id,
            preview_thumbnail_file_id=thumbnail.id,
            preview_thumbnail_media_type=_PREVIEW_THUMBNAIL_MEDIA_TYPE,
            preview_thumbnail_width=thumbnail_prepared.preview_width,
            preview_thumbnail_height=thumbnail_prepared.preview_height,
            preview_generated_at=thumbnail_prepared.preview_generated_at,
        )

    async def download(
        self,
        *,
        file_id: str,
        user_id: str,
    ) -> Result[ExchangeFileDownload, ExchangeFileError]:
        """Fetch original Exchange file bytes."""
        file = await self._get_accessible_file(file_id=file_id, user_id=user_id)
        if isinstance(file, Failure):
            return Failure(file.error)
        if file.value.status == ExchangeFileStatus.EXPIRED:
            return Failure(FileExpired())
        body = await self.s3_service.download_bytes(
            bucket=self.config.workspace_s3.bucket,
            key=file.value.object_key,
        )
        if body is None:
            return Failure(FileUnavailable())
        return Success(ExchangeFileDownload(file=file.value, body=body))

    async def delete(
        self,
        *,
        file_id: str,
        user_id: str,
    ) -> Result[None, ExchangeFileError]:
        """Delete Exchange file object and metadata."""
        target = await self._get_accessible_file_with_preview(
            file_id=file_id,
            user_id=user_id,
        )
        if isinstance(target, Failure):
            return Failure(target.error)
        files_to_delete = [
            file
            for file in (target.value.preview_thumbnail, target.value.file)
            if file is not None
        ]
        for file in files_to_delete:
            await self.s3_service.delete(
                bucket=self.config.workspace_s3.bucket,
                key=file.object_key,
            )
        async with self.session_manager() as session:
            for file in files_to_delete:
                await self.exchange_file_repository.delete_by_id(session, file.id)
        return Success(None)

    async def resolve_attachment(
        self,
        *,
        uri: str,
        user_id: str,
    ) -> Result[ExchangeFileDownload, ExchangeFileError]:
        """Resolve Runtime attachment URI to downloadable Exchange file."""
        object_key = exchange_object_key_from_uri(uri)
        if object_key is None:
            return Failure(FileNotFound())
        result = await self._download_by_object_key(
            object_key=object_key,
            user_id=user_id,
        )
        return result

    async def resolve_attachment_for_agent(
        self,
        *,
        uri: str,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[ExchangeFileDownload, ExchangeFileError]:
        """Download attachment URI inside the current root retention unit."""
        object_key = exchange_object_key_from_uri(uri)
        if object_key is None:
            return Failure(FileNotFound())
        return await self._download_by_object_key_for_agent(
            object_key=object_key,
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
        )

    async def resolve_attachment_metadata(
        self,
        *,
        uri: str,
        user_id: str,
    ) -> Result[ExchangeFile, SessionNotFound | FileNotFound | FileAccessDenied]:
        """Resolve Runtime attachment URI to metadata-only Exchange file."""
        object_key = exchange_object_key_from_uri(uri)
        if object_key is None:
            return Failure(FileNotFound())
        file = await self._get_accessible_file_by_object_key(
            object_key=object_key,
            user_id=user_id,
        )
        if isinstance(file, Failure):
            return Failure(file.error)
        return Success(file.value)

    async def resolve_attachment_metadata_for_agent(
        self,
        *,
        uri: str,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[ExchangeFile, SessionNotFound | FileNotFound | FileAccessDenied]:
        """Resolve metadata inside the current root retention unit."""
        object_key = exchange_object_key_from_uri(uri)
        if object_key is None:
            return Failure(FileNotFound())
        file = await self._get_accessible_file_by_object_key_for_agent(
            object_key=object_key,
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
        )
        if isinstance(file, Failure):
            return Failure(file.error)
        return Success(file.value)

    async def _download_by_object_key(
        self,
        *,
        object_key: str,
        user_id: str,
    ) -> Result[ExchangeFileDownload, ExchangeFileError]:
        """Fetch original bytes by Exchange object key."""
        file = await self._get_accessible_file_by_object_key(
            object_key=object_key,
            user_id=user_id,
        )
        return await self._download_resolved_file(file)

    async def _download_by_object_key_for_agent(
        self,
        *,
        object_key: str,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[ExchangeFileDownload, ExchangeFileError]:
        """Download Exchange object key inside the current retention root."""
        file = await self._get_accessible_file_by_object_key_for_agent(
            object_key=object_key,
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
        )
        return await self._download_resolved_file(file)

    async def _download_resolved_file(
        self,
        file: Result[ExchangeFile, FileNotFound | FileAccessDenied],
    ) -> Result[ExchangeFileDownload, ExchangeFileError]:
        """Download ExchangeFile already verified for namespace/permission."""
        if isinstance(file, Failure):
            return Failure(file.error)
        if file.value.status == ExchangeFileStatus.EXPIRED:
            return Failure(FileExpired())
        body = await self.s3_service.download_bytes(
            bucket=self.config.workspace_s3.bucket,
            key=file.value.object_key,
        )
        if body is None:
            return Failure(FileUnavailable())
        return Success(ExchangeFileDownload(file=file.value, body=body))

    async def _get_accessible_file(
        self,
        *,
        file_id: str,
        user_id: str,
    ) -> Result[ExchangeFile, FileNotFound | FileAccessDenied]:
        """Check file metadata together with workspace access permission."""
        async with self.session_manager() as session:
            file = await self.exchange_file_repository.get_by_id(session, file_id)
            if file is None:
                return Failure(FileNotFound())
            if not await self._has_workspace_access(
                session, workspace_id=file.workspace_id, user_id=user_id
            ):
                return Failure(FileAccessDenied())
            file = await self._expire_if_due(session, file)
            return Success(file)

    async def _get_accessible_file_by_object_key(
        self,
        *,
        object_key: str,
        user_id: str,
    ) -> Result[ExchangeFile, FileNotFound | FileAccessDenied]:
        """Check file location together with workspace access permission."""
        async with self.session_manager() as session:
            file = await self.exchange_file_repository.get_by_object_key(
                session,
                object_key,
            )
            return await self._authorize_and_expire_file(
                session,
                file=file,
                user_id=user_id,
            )

    async def _get_accessible_file_by_object_key_for_agent(
        self,
        *,
        object_key: str,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[ExchangeFile, FileNotFound | FileAccessDenied]:
        """Check file location inside the current root retention unit."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if agent_session is None or agent_session.agent_id != agent_id:
                return Failure(FileAccessDenied())
            get_root = (
                self.agent_session_repository.get_root_session_agent_by_session_id
            )
            root = await get_root(session, session_id)
            if root is None:
                return Failure(FileAccessDenied())
            file = await self.exchange_file_repository.get_by_object_key_for_agent(
                session,
                object_key=object_key,
                agent_id=agent_id,
            )
            if (
                file is not None
                and file.retention_root_session_id != root.agent_session_id
            ):
                return Failure(FileAccessDenied())
            return await self._authorize_and_expire_file(
                session,
                file=file,
                user_id=user_id,
            )

    async def _authorize_and_expire_file(
        self,
        session: AsyncSession,
        *,
        file: ExchangeFile | None,
        user_id: str,
    ) -> Result[ExchangeFile, FileNotFound | FileAccessDenied]:
        """Check workspace permission and expiration status of fetched ExchangeFile."""
        if file is None:
            return Failure(FileNotFound())
        if not await self._has_workspace_access(
            session, workspace_id=file.workspace_id, user_id=user_id
        ):
            return Failure(FileAccessDenied())
        file = await self._expire_if_due(session, file)
        return Success(file)

    async def _get_accessible_file_with_preview(
        self,
        *,
        file_id: str,
        user_id: str,
    ) -> Result[
        ExchangeFileWithPreview,
        FileNotFound | FileAccessDenied,
    ]:
        """Fetch file metadata together with linked preview thumbnail metadata."""
        async with self.session_manager() as session:
            file = await self.exchange_file_repository.get_by_id(session, file_id)
            if file is None:
                return Failure(FileNotFound())
            if not await self._has_workspace_access(
                session, workspace_id=file.workspace_id, user_id=user_id
            ):
                return Failure(FileAccessDenied())

            file = await self._expire_if_due(session, file)
            preview_thumbnail: ExchangeFile | None = None
            if file.preview_thumbnail_file_id is not None:
                preview_thumbnail = await self.exchange_file_repository.get_by_id(
                    session,
                    file.preview_thumbnail_file_id,
                )
                if preview_thumbnail is None:
                    logger.warning(
                        "Exchange file preview thumbnail metadata is missing",
                        extra={
                            "file_id": file.id,
                            "preview_thumbnail_file_id": (
                                file.preview_thumbnail_file_id
                            ),
                        },
                    )
            return Success(
                ExchangeFileWithPreview(
                    file=file,
                    preview_thumbnail=preview_thumbnail,
                )
            )

    async def _expire_if_due(
        self,
        session: AsyncSession,
        file: ExchangeFile,
    ) -> ExchangeFile:
        """Transition expired file to expired and return latest metadata."""
        if file.status == ExchangeFileStatus.EXPIRED:
            return file
        now = datetime.datetime.now(datetime.UTC)
        if file.expires_at > now:
            return file
        expired = await self.exchange_file_repository.expire_file_family(
            session,
            file_id=file.id,
            expired_at=now,
        )
        for item in expired:
            if item.id == file.id:
                return item
        return file.model_copy(
            update={"status": ExchangeFileStatus.EXPIRED, "expired_at": now}
        )

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

    async def _cleanup_uploaded_objects(self, object_keys: list[str]) -> None:
        """Delete already uploaded object when metadata commit fails."""
        for object_key in reversed(object_keys):
            await self.s3_service.delete(
                bucket=self.config.workspace_s3.bucket,
                key=object_key,
            )
