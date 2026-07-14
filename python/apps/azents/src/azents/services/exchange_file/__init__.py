"""Exchange file service."""

import asyncio
import dataclasses
import datetime
import hashlib
import logging
import re
from io import BytesIO
from typing import Annotated

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
from azents.repos.exchange_file import (
    ExchangeFileRepository,
    exchange_file_object_key,
)
from azents.repos.exchange_file.data import ExchangeFile, ExchangeFileCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.file_lifecycle_policy import exchange_file_expires_at
from azents.services.upload_commit import reconcile_uploaded_metadata
from azents.utils.task_recovery import (
    compensate_then_reraise,
    current_task_is_cancelling,
    run_bounded_cancellation_safe,
)

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
    "application/javascript",
    "application/json",
    "application/xml",
}


@dataclasses.dataclass(frozen=True)
class _PreviewThumbnail:
    """Created preview thumbnail bytes and metadata."""

    body: bytes
    width: int
    height: int
    generated_at: datetime.datetime


@dataclasses.dataclass(frozen=True)
class _ExchangeFileCreationScope:
    """Authorized immutable namespace for one ExchangeFile creation."""

    workspace_id: str
    agent_id: str
    session_id: str | None


@dataclasses.dataclass(frozen=True)
class _ExchangeFileCreationExpectation:
    """Immutable metadata identities written by one upload transaction."""

    file: ExchangeFileCreate
    object_key: str
    thumbnail: ExchangeFileCreate | None
    thumbnail_object_key: str | None
    preview_thumbnail_width: int | None
    preview_thumbnail_height: int | None
    preview_generated_at: datetime.datetime


@dataclasses.dataclass(frozen=True)
class _ExchangeFileCommitRows:
    """Rows observed for a preallocated ExchangeFile family."""

    file: ExchangeFile | None
    thumbnail: ExchangeFile | None


def exchange_object_key_from_uri(uri: str) -> str | None:
    """Return object key from Exchange file-location URI."""
    prefix = "exchange://"
    if not uri.startswith(prefix):
        return None
    object_key = uri.removeprefix(prefix)
    if not object_key:
        return None
    return object_key


def _sanitize_display_filename(filename: str | None) -> str:
    """Normalize as display filename safe for download header."""
    raw = filename if filename is not None else "upload"
    sanitized = re.sub(r"[\\/\x00-\x1f\x7f]+", "_", raw).strip().strip(".")
    if sanitized:
        return sanitized[:255]
    return "upload"


def _make_text_preview(body: bytes, media_type: str) -> str | None:
    """Create a bounded UTF-8 preview for supported text attachments."""
    supported = (
        media_type.startswith("text/") or media_type in _TEXT_PREVIEW_MEDIA_TYPES
    )
    if not supported:
        return None
    text = body.decode("utf-8", errors="replace")
    if len(text) <= _MAX_TEXT_PREVIEW_CHARS:
        return text
    return text[:_MAX_TEXT_PREVIEW_CHARS] + "\n... (truncated)"


def _make_preview_thumbnail(body: bytes, media_type: str) -> _PreviewThumbnail | None:
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
    return _PreviewThumbnail(
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
        scope_result = await self._resolve_agent_creation_scope(
            agent_id=agent_id,
            user_id=user_id,
        )
        if isinstance(scope_result, Failure):
            return Failure(scope_result.error)
        return await self._store_file(
            scope=scope_result.value,
            user_id=user_id,
            filename=filename,
            media_type=media_type,
            body=body,
            origin_type=origin_type,
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
        scope_result = await self._resolve_session_creation_scope(
            session_id=session_id,
            user_id=user_id,
            expected_agent_id=agent_id,
        )
        if isinstance(scope_result, Failure):
            return Failure(scope_result.error)
        return await self._store_file(
            scope=scope_result.value,
            user_id=user_id,
            filename=filename,
            media_type=media_type,
            body=body,
            origin_type=origin_type,
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
        scope_result = await self._resolve_session_creation_scope(
            session_id=session_id,
            user_id=user_id,
            expected_agent_id=None,
        )
        if isinstance(scope_result, Failure):
            return Failure(scope_result.error)
        return await self._store_file(
            scope=scope_result.value,
            user_id=user_id,
            filename=filename,
            media_type=media_type,
            body=body,
            origin_type=origin_type,
        )

    async def _resolve_agent_creation_scope(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[_ExchangeFileCreationScope, SessionNotFound | FileAccessDenied]:
        """Authorize one Agent-owned creation scope in a short DB session."""
        async with self.session_manager() as session:
            return await self._resolve_agent_creation_scope_in_session(
                session,
                agent_id=agent_id,
                user_id=user_id,
            )

    async def _resolve_agent_creation_scope_in_session(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        user_id: str,
        lock_membership: bool = False,
    ) -> Result[_ExchangeFileCreationScope, SessionNotFound | FileAccessDenied]:
        """Authorize an Agent-owned scope using the caller's DB session."""
        agent = await self.agent_repository.get_by_id(session, agent_id)
        if agent is None:
            return Failure(SessionNotFound())
        if not await self._has_workspace_access(
            session,
            workspace_id=agent.workspace_id,
            user_id=user_id,
            lock_authority=lock_membership,
        ):
            return Failure(FileAccessDenied())
        return Success(
            _ExchangeFileCreationScope(
                workspace_id=agent.workspace_id,
                agent_id=agent.id,
                session_id=None,
            )
        )

    async def _resolve_session_creation_scope(
        self,
        *,
        session_id: str,
        user_id: str,
        expected_agent_id: str | None,
    ) -> Result[_ExchangeFileCreationScope, SessionNotFound | FileAccessDenied]:
        """Authorize one AgentSession-owned creation scope in a short DB session."""
        async with self.session_manager() as session:
            return await self._resolve_session_creation_scope_in_session(
                session,
                session_id=session_id,
                user_id=user_id,
                expected_agent_id=expected_agent_id,
            )

    async def _resolve_session_creation_scope_in_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        user_id: str,
        expected_agent_id: str | None,
        lock_authority: bool = False,
    ) -> Result[_ExchangeFileCreationScope, SessionNotFound | FileAccessDenied]:
        """Authorize an AgentSession-owned scope using the caller's DB session."""
        if lock_authority:
            agent_session = await self.agent_session_repository.lock_by_id(
                session,
                session_id,
            )
        else:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
        if agent_session is None:
            return Failure(SessionNotFound())
        if (
            expected_agent_id is not None
            and agent_session.agent_id != expected_agent_id
        ):
            return Failure(SessionNotFound())
        if not await self._has_workspace_access(
            session,
            workspace_id=agent_session.workspace_id,
            user_id=user_id,
            lock_authority=lock_authority,
        ):
            return Failure(FileAccessDenied())
        return Success(
            _ExchangeFileCreationScope(
                workspace_id=agent_session.workspace_id,
                agent_id=agent_session.agent_id,
                session_id=agent_session.id,
            )
        )

    async def _revalidate_creation_scope_in_session(
        self,
        session: AsyncSession,
        *,
        scope: _ExchangeFileCreationScope,
        user_id: str,
        lock_authority: bool = False,
    ) -> Result[_ExchangeFileCreationScope, SessionNotFound | FileAccessDenied]:
        """Re-authorize a previously resolved scope before metadata commit."""
        if scope.session_id is None:
            return await self._resolve_agent_creation_scope_in_session(
                session,
                agent_id=scope.agent_id,
                user_id=user_id,
                lock_membership=lock_authority,
            )
        return await self._resolve_session_creation_scope_in_session(
            session,
            session_id=scope.session_id,
            user_id=user_id,
            expected_agent_id=scope.agent_id,
            lock_authority=lock_authority,
        )

    async def _store_file(
        self,
        *,
        scope: _ExchangeFileCreationScope,
        user_id: str,
        filename: str | None,
        media_type: str,
        body: bytes,
        origin_type: ExchangeFileOrigin,
    ) -> Result[ExchangeFile, SessionNotFound | FileAccessDenied]:
        """Upload without a DB session, then commit authorized metadata."""
        safe_filename = _sanitize_display_filename(filename)
        sha256 = hashlib.sha256(body).hexdigest()
        now = datetime.datetime.now(datetime.UTC)
        expires_at = exchange_file_expires_at(now=now, config=self.config)
        thumbnail_body = _make_preview_thumbnail(body, media_type)

        file_id = uuid7().hex
        object_key = exchange_file_object_key(
            workspace_id=scope.workspace_id,
            file_id=file_id,
        )
        thumbnail_id = uuid7().hex if thumbnail_body is not None else None
        thumbnail_object_key = (
            exchange_file_object_key(
                workspace_id=scope.workspace_id,
                file_id=thumbnail_id,
            )
            if thumbnail_id is not None
            else None
        )
        file_create = ExchangeFileCreate(
            id=file_id,
            workspace_id=scope.workspace_id,
            agent_id=scope.agent_id,
            origin_type=origin_type,
            filename=safe_filename,
            media_type=media_type,
            size_bytes=len(body),
            sha256=sha256,
            created_by_user_id=user_id,
            expires_at=expires_at,
            preview_title=safe_filename,
            preview_summary=_make_text_preview(body, media_type),
            preview_generated_at=now,
        )
        thumbnail_create: ExchangeFileCreate | None = None
        if thumbnail_body is not None and thumbnail_id is not None:
            thumbnail_create = ExchangeFileCreate(
                id=thumbnail_id,
                workspace_id=scope.workspace_id,
                agent_id=scope.agent_id,
                origin_type=origin_type,
                filename=f"{safe_filename}.preview.jpg",
                media_type=_PREVIEW_THUMBNAIL_MEDIA_TYPE,
                size_bytes=len(thumbnail_body.body),
                sha256=hashlib.sha256(thumbnail_body.body).hexdigest(),
                created_by_user_id=user_id,
                expires_at=expires_at,
                preview_title=f"{safe_filename} preview",
                preview_generated_at=thumbnail_body.generated_at,
            )
        expectation = _ExchangeFileCreationExpectation(
            file=file_create,
            object_key=object_key,
            thumbnail=thumbnail_create,
            thumbnail_object_key=thumbnail_object_key,
            preview_thumbnail_width=(
                thumbnail_body.width if thumbnail_body is not None else None
            ),
            preview_thumbnail_height=(
                thumbnail_body.height if thumbnail_body is not None else None
            ),
            preview_generated_at=(
                thumbnail_body.generated_at if thumbnail_body is not None else now
            ),
        )
        uploaded_object_keys: list[str] = []
        try:
            uploaded_object_keys.append(object_key)
            await self.s3_service.upload(
                bucket=self.config.workspace_s3.bucket,
                key=object_key,
                body=body,
                content_type=media_type,
            )
            if thumbnail_body is not None and thumbnail_object_key is not None:
                uploaded_object_keys.append(thumbnail_object_key)
                await self.s3_service.upload(
                    bucket=self.config.workspace_s3.bucket,
                    key=thumbnail_object_key,
                    body=thumbnail_body.body,
                    content_type=_PREVIEW_THUMBNAIL_MEDIA_TYPE,
                )
        except (asyncio.CancelledError, Exception) as upload_error:
            await compensate_then_reraise(
                lambda: self._compensate_uploaded_objects(uploaded_object_keys),
                primary_error=upload_error,
            )

        metadata_result: Result[
            ExchangeFile,
            SessionNotFound | FileAccessDenied,
        ]
        try:
            async with self.session_manager() as session:
                refreshed_scope_result = (
                    await self._revalidate_creation_scope_in_session(
                        session,
                        scope=scope,
                        user_id=user_id,
                        lock_authority=True,
                    )
                )
                if isinstance(refreshed_scope_result, Failure):
                    metadata_result = Failure(refreshed_scope_result.error)
                elif refreshed_scope_result.value != scope:
                    metadata_result = Failure(SessionNotFound())
                else:
                    created = await self.exchange_file_repository.create(
                        session,
                        file_create,
                    )
                    thumbnail: ExchangeFile | None = None
                    if thumbnail_create is not None and thumbnail_body is not None:
                        thumbnail = await self.exchange_file_repository.create(
                            session,
                            thumbnail_create,
                        )
                        set_preview_file = (
                            self.exchange_file_repository.set_preview_thumbnail_file_id
                        )
                        created = await set_preview_file(
                            session,
                            file_id=created.id,
                            preview_thumbnail_file_id=thumbnail.id,
                            preview_thumbnail_media_type=(
                                _PREVIEW_THUMBNAIL_MEDIA_TYPE
                            ),
                            preview_thumbnail_width=thumbnail_body.width,
                            preview_thumbnail_height=thumbnail_body.height,
                            preview_generated_at=thumbnail_body.generated_at,
                        )
                    rows = _ExchangeFileCommitRows(
                        file=created,
                        thumbnail=thumbnail,
                    )
                    if not _exchange_file_family_matches_creation(
                        rows,
                        expectation=expectation,
                    ):
                        raise RuntimeError(
                            "ExchangeFile repository returned a mismatched "
                            "storage identity"
                        )
                    metadata_result = Success(created)
        except (asyncio.CancelledError, Exception) as commit_error:
            try:
                reconciled_rows = await reconcile_uploaded_metadata(
                    lookup=lambda: self._get_exchange_file_commit_rows(
                        file_id=file_id,
                        thumbnail_id=thumbnail_id,
                    ),
                    matches_expected_identity=lambda rows: (
                        _exchange_file_family_matches_creation(
                            rows,
                            expectation=expectation,
                        )
                    ),
                    resource_kind="ExchangeFile",
                    resource_id=file_id,
                    compensate_if_absent=lambda: self._compensate_uploaded_objects(
                        uploaded_object_keys
                    ),
                )
            except asyncio.CancelledError as reconciliation_cancellation:
                if (
                    isinstance(commit_error, asyncio.CancelledError)
                    or not current_task_is_cancelling()
                ):
                    raise commit_error from reconciliation_cancellation
                raise
            except Exception as reconciliation_error:
                logger.exception(
                    "Could not establish ExchangeFile metadata commit outcome; "
                    "preserving uploaded objects",
                    extra={
                        "file_id": file_id,
                        "object_keys": uploaded_object_keys,
                    },
                )
                raise commit_error from reconciliation_error
            if reconciled_rows is None:
                raise commit_error
            if isinstance(commit_error, asyncio.CancelledError):
                raise
            if reconciled_rows.file is None:
                raise commit_error from None
            logger.warning(
                "Recovered ExchangeFile metadata after ambiguous commit response",
                extra={"file_id": file_id, "object_keys": uploaded_object_keys},
            )
            return Success(reconciled_rows.file)

        if isinstance(metadata_result, Failure):
            await self._compensate_uploaded_objects(uploaded_object_keys)
        return metadata_result

    async def _get_exchange_file_commit_rows(
        self,
        *,
        file_id: str,
        thumbnail_id: str | None,
    ) -> _ExchangeFileCommitRows | None:
        """Fetch one preallocated file family in a short reconciliation scope."""
        async with self.session_manager() as session:
            file = await self.exchange_file_repository.get_by_id(session, file_id)
            thumbnail = (
                await self.exchange_file_repository.get_by_id(session, thumbnail_id)
                if thumbnail_id is not None
                else None
            )
        if file is None and thumbnail is None:
            return None
        return _ExchangeFileCommitRows(file=file, thumbnail=thumbnail)

    async def _compensate_uploaded_objects(self, object_keys: list[str]) -> None:
        """Run bounded object compensation to completion across cancellation."""
        try:
            await run_bounded_cancellation_safe(
                lambda: self._cleanup_uploaded_objects(object_keys)
            )
        except TimeoutError:
            logger.error(
                "Timed out cleaning up ExchangeFile objects after create failure",
                extra={"object_keys": object_keys},
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
        """Expire, delete, and then remove Exchange file metadata."""
        target = await self._expire_accessible_file_with_preview_for_delete(
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
                await self.exchange_file_repository.mark_blob_deleted(
                    session,
                    file_id=file.id,
                    blob_deleted_at=datetime.datetime.now(datetime.UTC),
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
        user_id: str,
    ) -> Result[ExchangeFileDownload, ExchangeFileError]:
        """Download attachment URI inside current Agent namespace."""
        object_key = exchange_object_key_from_uri(uri)
        if object_key is None:
            return Failure(FileNotFound())
        return await self._download_by_object_key_for_agent(
            object_key=object_key,
            agent_id=agent_id,
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
        user_id: str,
    ) -> Result[ExchangeFile, SessionNotFound | FileNotFound | FileAccessDenied]:
        """Resolve attachment metadata inside current Agent namespace."""
        object_key = exchange_object_key_from_uri(uri)
        if object_key is None:
            return Failure(FileNotFound())
        file = await self._get_accessible_file_by_object_key_for_agent(
            object_key=object_key,
            agent_id=agent_id,
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
        user_id: str,
    ) -> Result[ExchangeFileDownload, ExchangeFileError]:
        """Download Exchange object key inside current Agent namespace."""
        file = await self._get_accessible_file_by_object_key_for_agent(
            object_key=object_key,
            agent_id=agent_id,
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
        user_id: str,
    ) -> Result[ExchangeFile, FileNotFound | FileAccessDenied]:
        """Check file location only inside current Agent namespace."""
        async with self.session_manager() as session:
            file = await self.exchange_file_repository.get_by_object_key_for_agent(
                session,
                object_key=object_key,
                agent_id=agent_id,
            )
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

    async def _expire_accessible_file_with_preview_for_delete(
        self,
        *,
        file_id: str,
        user_id: str,
    ) -> Result[
        ExchangeFileWithPreview,
        FileNotFound | FileAccessDenied,
    ]:
        """Authorize and durably tombstone a file family before object deletion."""
        async with self.session_manager() as session:
            file = await self.exchange_file_repository.get_by_id(session, file_id)
            if file is None:
                return Failure(FileNotFound())
            if not await self._has_workspace_access(
                session, workspace_id=file.workspace_id, user_id=user_id
            ):
                return Failure(FileAccessDenied())

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
            expired_at = datetime.datetime.now(datetime.UTC)
            expired = await self.exchange_file_repository.expire_file_family(
                session,
                file_id=file.id,
                expired_at=expired_at,
            )
            expired_by_id = {item.id: item for item in expired}
            file = expired_by_id.get(
                file.id,
                file.model_copy(
                    update={
                        "status": ExchangeFileStatus.EXPIRED,
                        "expired_at": file.expired_at or expired_at,
                    }
                ),
            )
            if preview_thumbnail is not None:
                preview_thumbnail = expired_by_id.get(
                    preview_thumbnail.id,
                    preview_thumbnail.model_copy(
                        update={
                            "status": ExchangeFileStatus.EXPIRED,
                            "expired_at": preview_thumbnail.expired_at or expired_at,
                        }
                    ),
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
        lock_authority: bool = False,
    ) -> bool:
        """Check whether user is workspace member."""
        if lock_authority:
            workspace_user = (
                await self.workspace_user_repository.lock_by_workspace_and_user(
                    session,
                    workspace_id,
                    user_id,
                )
            )
        else:
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
            )
        return workspace_user is not None

    async def _cleanup_uploaded_objects(self, object_keys: list[str]) -> None:
        """Delete already uploaded object when metadata commit fails."""
        for object_key in reversed(object_keys):
            try:
                await self.s3_service.delete(
                    bucket=self.config.workspace_s3.bucket,
                    key=object_key,
                )
            except Exception:
                logger.exception(
                    "Failed to clean up ExchangeFile object after create failure",
                    extra={"object_key": object_key},
                )


def _exchange_file_family_matches_creation(
    rows: _ExchangeFileCommitRows,
    *,
    expectation: _ExchangeFileCreationExpectation,
) -> bool:
    """Check the complete immutable identity of one preallocated file family."""
    file = rows.file
    if file is None:
        return False
    thumbnail_create = expectation.thumbnail
    thumbnail = rows.thumbnail
    if thumbnail_create is None:
        if thumbnail is not None:
            return False
        expected_thumbnail_id = None
        expected_thumbnail_uri = None
        expected_thumbnail_media_type = None
    else:
        if thumbnail is None or expectation.thumbnail_object_key is None:
            return False
        if not _exchange_file_matches_creation(
            thumbnail,
            create=thumbnail_create,
            object_key=expectation.thumbnail_object_key,
            preview_thumbnail_file_id=None,
            preview_thumbnail_uri=None,
            preview_thumbnail_media_type=None,
            preview_thumbnail_width=None,
            preview_thumbnail_height=None,
            preview_generated_at=thumbnail_create.preview_generated_at,
        ):
            return False
        expected_thumbnail_id = thumbnail_create.id
        expected_thumbnail_uri = f"exchange://{expectation.thumbnail_object_key}"
        expected_thumbnail_media_type = _PREVIEW_THUMBNAIL_MEDIA_TYPE
    return _exchange_file_matches_creation(
        file,
        create=expectation.file,
        object_key=expectation.object_key,
        preview_thumbnail_file_id=expected_thumbnail_id,
        preview_thumbnail_uri=expected_thumbnail_uri,
        preview_thumbnail_media_type=expected_thumbnail_media_type,
        preview_thumbnail_width=expectation.preview_thumbnail_width,
        preview_thumbnail_height=expectation.preview_thumbnail_height,
        preview_generated_at=expectation.preview_generated_at,
    )


def _exchange_file_matches_creation(
    file: ExchangeFile,
    *,
    create: ExchangeFileCreate,
    object_key: str,
    preview_thumbnail_file_id: str | None,
    preview_thumbnail_uri: str | None,
    preview_thumbnail_media_type: str | None,
    preview_thumbnail_width: int | None,
    preview_thumbnail_height: int | None,
    preview_generated_at: datetime.datetime | None,
) -> bool:
    """Check immutable metadata that proves a preallocated ExchangeFile identity."""
    return (
        create.id is not None
        and file.id == create.id
        and file.object_key == object_key
        and file.workspace_id == create.workspace_id
        and file.agent_id == create.agent_id
        and file.origin_type == create.origin_type
        and file.filename == create.filename
        and file.media_type == create.media_type
        and file.size_bytes == create.size_bytes
        and file.sha256 == create.sha256
        and file.created_by_user_id == create.created_by_user_id
        and file.expires_at == create.expires_at
        and file.preview_title == create.preview_title
        and file.preview_summary == create.preview_summary
        and file.preview_thumbnail_file_id == preview_thumbnail_file_id
        and file.preview_thumbnail_uri == preview_thumbnail_uri
        and file.preview_thumbnail_media_type == preview_thumbnail_media_type
        and file.preview_thumbnail_width == preview_thumbnail_width
        and file.preview_thumbnail_height == preview_thumbnail_height
        and file.preview_generated_at == preview_generated_at
    )
