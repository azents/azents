"""Artifact service."""

import asyncio
import dataclasses
import datetime
import hashlib
import logging
import re
from typing import Annotated

from azcommon.infra.s3.service import S3Service
from azcommon.result import Failure, Result, Success
from azcommon.types import JSONValue
from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import ArtifactStatus
from azents.core.s3.deps import get_s3_service
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.artifact import ArtifactRepository, artifact_storage_key
from azents.repos.artifact.data import Artifact, ArtifactCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.file_lifecycle_policy import artifact_expires_at
from azents.services.upload_commit import reconcile_uploaded_metadata
from azents.utils.task_recovery import (
    compensate_then_reraise,
    current_task_is_cancelling,
    run_bounded_cancellation_safe,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class ArtifactSessionNotFound:
    """Session not found."""


@dataclasses.dataclass(frozen=True)
class ArtifactNotFound:
    """Artifact not found."""


@dataclasses.dataclass(frozen=True)
class ArtifactAccessDenied:
    """No Artifact access permission."""


@dataclasses.dataclass(frozen=True)
class ArtifactExpired:
    """Artifact expired."""


@dataclasses.dataclass(frozen=True)
class ArtifactUnavailable:
    """Cannot access original Artifact in object storage."""


@dataclasses.dataclass(frozen=True)
class ArtifactDownload:
    """Artifact download result."""

    artifact: Artifact
    body: bytes


@dataclasses.dataclass(frozen=True)
class _ArtifactCreationScope:
    """Authorized immutable namespace for one Artifact creation."""

    workspace_id: str
    session_id: str
    agent_id: str


ArtifactError = (
    ArtifactSessionNotFound
    | ArtifactNotFound
    | ArtifactAccessDenied
    | ArtifactExpired
    | ArtifactUnavailable
)


def artifact_storage_key_from_uri(uri: str) -> str | None:
    """Return storage key from Artifact file-location URI."""
    prefix = "artifact://"
    if not uri.startswith(prefix):
        return None
    storage_key = uri.removeprefix(prefix)
    if not storage_key:
        return None
    return storage_key


def _sanitize_display_filename(filename: str | None) -> str:
    """Normalize as Artifact filename for display."""
    raw = filename if filename is not None else "artifact"
    sanitized = re.sub(r"[\\/\x00-\x1f\x7f]+", "_", raw).strip().strip(".")
    if sanitized:
        return sanitized[:255]
    return "artifact"


@dataclasses.dataclass
class ArtifactService:
    """Coordinate Artifact metadata and object storage."""

    artifact_repository: Annotated[ArtifactRepository, Depends(ArtifactRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository,
        Depends(AgentSessionRepository),
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
        created_run_id: str,
        created_run_index: int,
        filename: str | None,
        media_type: str,
        body: bytes,
        source_tool_name: str | None = None,
        source_call_id: str | None = None,
        source_part_index: int | None = None,
        description: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Result[Artifact, ArtifactSessionNotFound | ArtifactAccessDenied]:
        """Create Artifact metadata and object."""
        scope_result = await self._resolve_creation_scope(
            session_id=session_id,
            user_id=user_id,
        )
        if isinstance(scope_result, Failure):
            return Failure(scope_result.error)

        scope = scope_result.value
        artifact_id = uuid7().hex
        object_key = artifact_storage_key(
            workspace_id=scope.workspace_id,
            session_id=scope.session_id,
            created_run_index=created_run_index,
            artifact_id=artifact_id,
        )
        try:
            await self.s3_service.upload(
                bucket=self.config.workspace_s3.bucket,
                key=object_key,
                body=body,
                content_type=media_type,
            )
        except (asyncio.CancelledError, Exception) as upload_error:
            await compensate_then_reraise(
                lambda: self._compensate_uploaded_object(object_key),
                primary_error=upload_error,
            )

        now = datetime.datetime.now(datetime.UTC)
        create = ArtifactCreate(
            id=artifact_id,
            workspace_id=scope.workspace_id,
            session_id=scope.session_id,
            agent_id=scope.agent_id,
            created_run_id=created_run_id,
            created_run_index=created_run_index,
            expires_at=artifact_expires_at(now=now, config=self.config),
            name=_sanitize_display_filename(filename),
            media_type=media_type,
            size_bytes=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            source_tool_name=source_tool_name,
            source_call_id=source_call_id,
            source_part_index=source_part_index,
            description=description,
            metadata=_json_metadata(metadata),
        )
        metadata_result: Result[
            Artifact,
            ArtifactSessionNotFound | ArtifactAccessDenied,
        ]
        try:
            async with self.session_manager() as session:
                refreshed_scope_result = await self._resolve_creation_scope_in_session(
                    session,
                    session_id=scope.session_id,
                    user_id=user_id,
                    lock_authority=True,
                )
                if isinstance(refreshed_scope_result, Failure):
                    metadata_result = Failure(refreshed_scope_result.error)
                elif refreshed_scope_result.value != scope:
                    metadata_result = Failure(ArtifactSessionNotFound())
                else:
                    created = await self.artifact_repository.create(session, create)
                    if not _artifact_matches_creation(
                        created,
                        create=create,
                        object_key=object_key,
                    ):
                        raise RuntimeError(
                            "Artifact repository returned a mismatched storage identity"
                        )
                    metadata_result = Success(created)
        except (asyncio.CancelledError, Exception) as commit_error:
            try:
                reconciled = await reconcile_uploaded_metadata(
                    lookup=lambda: self._get_artifact_by_id(artifact_id),
                    matches_expected_identity=lambda artifact: (
                        _artifact_matches_creation(
                            artifact,
                            create=create,
                            object_key=object_key,
                        )
                    ),
                    resource_kind="Artifact",
                    resource_id=artifact_id,
                    compensate_if_absent=lambda: self._compensate_uploaded_object(
                        object_key
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
                    "Could not establish Artifact metadata commit outcome; "
                    "preserving uploaded object",
                    extra={"artifact_id": artifact_id, "storage_key": object_key},
                )
                raise commit_error from reconciliation_error
            if reconciled is None:
                raise commit_error
            if isinstance(commit_error, asyncio.CancelledError):
                raise
            logger.warning(
                "Recovered Artifact metadata after ambiguous commit response",
                extra={"artifact_id": artifact_id, "storage_key": object_key},
            )
            return Success(reconciled)

        if isinstance(metadata_result, Failure):
            await self._compensate_uploaded_object(object_key)
        return metadata_result

    async def _get_artifact_by_id(self, artifact_id: str) -> Artifact | None:
        """Fetch one Artifact in an independent short reconciliation scope."""
        async with self.session_manager() as session:
            return await self.artifact_repository.get_by_id(session, artifact_id)

    async def _compensate_uploaded_object(self, object_key: str) -> None:
        """Run bounded object compensation to completion across cancellation."""
        try:
            await run_bounded_cancellation_safe(
                lambda: self._cleanup_uploaded_object(object_key)
            )
        except TimeoutError:
            logger.error(
                "Timed out cleaning up Artifact object after create failure",
                extra={"storage_key": object_key},
            )

    async def _resolve_creation_scope(
        self,
        *,
        session_id: str,
        user_id: str,
    ) -> Result[_ArtifactCreationScope, ArtifactSessionNotFound | ArtifactAccessDenied]:
        """Authorize one creation scope in a short DB session."""
        async with self.session_manager() as session:
            return await self._resolve_creation_scope_in_session(
                session,
                session_id=session_id,
                user_id=user_id,
            )

    async def _resolve_creation_scope_in_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        user_id: str,
        lock_authority: bool = False,
    ) -> Result[_ArtifactCreationScope, ArtifactSessionNotFound | ArtifactAccessDenied]:
        """Authorize one creation scope using the caller's short DB session."""
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
            return Failure(ArtifactSessionNotFound())
        if not await self._has_workspace_access(
            session,
            workspace_id=agent_session.workspace_id,
            user_id=user_id,
            lock_authority=lock_authority,
        ):
            return Failure(ArtifactAccessDenied())
        return Success(
            _ArtifactCreationScope(
                workspace_id=agent_session.workspace_id,
                session_id=agent_session.id,
                agent_id=agent_session.agent_id,
            )
        )

    async def resolve(
        self,
        *,
        uri: str,
        user_id: str,
    ) -> Result[ArtifactDownload, ArtifactError]:
        """Resolve artifact:// URI to downloadable Artifact."""
        storage_key = artifact_storage_key_from_uri(uri)
        if storage_key is None:
            return Failure(ArtifactNotFound())
        return await self._download_by_storage_key(
            storage_key=storage_key,
            user_id=user_id,
        )

    async def _download_by_storage_key(
        self,
        *,
        storage_key: str,
        user_id: str,
    ) -> Result[ArtifactDownload, ArtifactError]:
        """Fetch original bytes by Artifact storage key."""
        artifact_result = await self._get_accessible_artifact_by_storage_key(
            storage_key=storage_key,
            user_id=user_id,
        )
        if isinstance(artifact_result, Failure):
            return Failure(artifact_result.error)
        artifact = artifact_result.value
        if artifact.status == ArtifactStatus.EXPIRED:
            return Failure(ArtifactExpired())
        body = await self.s3_service.download_bytes(
            bucket=self.config.workspace_s3.bucket,
            key=artifact.storage_key,
        )
        if body is None:
            return Failure(ArtifactUnavailable())
        return Success(ArtifactDownload(artifact=artifact, body=body))

    async def download(
        self,
        *,
        artifact_id: str,
        user_id: str,
    ) -> Result[ArtifactDownload, ArtifactError]:
        """Fetch original Artifact bytes."""
        artifact_result = await self._get_accessible_artifact(
            artifact_id=artifact_id,
            user_id=user_id,
        )
        if isinstance(artifact_result, Failure):
            return Failure(artifact_result.error)
        artifact = artifact_result.value
        if artifact.status == ArtifactStatus.EXPIRED:
            return Failure(ArtifactExpired())
        body = await self.s3_service.download_bytes(
            bucket=self.config.workspace_s3.bucket,
            key=artifact.storage_key,
        )
        if body is None:
            return Failure(ArtifactUnavailable())
        return Success(ArtifactDownload(artifact=artifact, body=body))

    async def _get_accessible_artifact(
        self,
        *,
        artifact_id: str,
        user_id: str,
    ) -> Result[Artifact, ArtifactNotFound | ArtifactAccessDenied]:
        """Check Artifact metadata together with workspace access permission."""
        async with self.session_manager() as session:
            artifact = await self.artifact_repository.get_by_id(session, artifact_id)
            if artifact is None:
                return Failure(ArtifactNotFound())
            if not await self._has_workspace_access(
                session,
                workspace_id=artifact.workspace_id,
                user_id=user_id,
            ):
                return Failure(ArtifactAccessDenied())
            return Success(artifact)

    async def _get_accessible_artifact_by_storage_key(
        self,
        *,
        storage_key: str,
        user_id: str,
    ) -> Result[Artifact, ArtifactNotFound | ArtifactAccessDenied]:
        """Check Artifact file location together with workspace access permission."""
        async with self.session_manager() as session:
            artifact = await self.artifact_repository.get_by_storage_key(
                session,
                storage_key,
            )
            if artifact is None:
                return Failure(ArtifactNotFound())
            if not await self._has_workspace_access(
                session,
                workspace_id=artifact.workspace_id,
                user_id=user_id,
            ):
                return Failure(ArtifactAccessDenied())
            return Success(artifact)

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

    async def _cleanup_uploaded_object(self, object_key: str | None) -> None:
        """Delete already uploaded object when metadata commit fails."""
        if object_key is None:
            return
        try:
            await self.s3_service.delete(
                bucket=self.config.workspace_s3.bucket,
                key=object_key,
            )
        except Exception:
            logger.exception(
                "Failed to clean up Artifact object after create failure",
                extra={"storage_key": object_key},
            )


def _artifact_matches_creation(
    artifact: Artifact,
    *,
    create: ArtifactCreate,
    object_key: str,
) -> bool:
    """Check immutable metadata that proves a preallocated Artifact identity."""
    return (
        create.id is not None
        and artifact.id == create.id
        and artifact.storage_key == object_key
        and artifact.workspace_id == create.workspace_id
        and artifact.session_id == create.session_id
        and artifact.agent_id == create.agent_id
        and artifact.created_run_id == create.created_run_id
        and artifact.created_run_index == create.created_run_index
        and artifact.expires_at == create.expires_at
        and artifact.name == create.name
        and artifact.media_type == create.media_type
        and artifact.size_bytes == create.size_bytes
        and artifact.sha256 == create.sha256
        and artifact.source_tool_name == create.source_tool_name
        and artifact.source_call_id == create.source_call_id
        and artifact.source_part_index == create.source_part_index
        and artifact.description == create.description
        and artifact.metadata == create.metadata
    )


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
