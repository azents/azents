"""Artifact service."""

import asyncio
import dataclasses
import datetime
import hashlib
import re
from typing import Annotated

from azcommon.infra.s3.service import S3Service
from azcommon.result import Failure, Result, Success
from azcommon.types import JSONValue
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import ArtifactStatus
from azents.core.s3.deps import get_s3_service
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.artifact import ArtifactRepository
from azents.repos.artifact.data import Artifact, ArtifactCreate
from azents.repos.workspace_user import WorkspaceUserRepository

_ARTIFACT_RETENTION_COMPLETED_RUNS = 2


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
        uploaded_object_key: str | None = None
        try:
            async with self.session_manager() as session:
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
                ):
                    return Failure(ArtifactAccessDenied())

                safe_filename = _sanitize_display_filename(filename)
                sha256 = hashlib.sha256(body).hexdigest()
                created = await self.artifact_repository.create(
                    session,
                    ArtifactCreate(
                        workspace_id=agent_session.workspace_id,
                        session_id=session_id,
                        agent_id=agent_session.agent_id,
                        created_run_id=created_run_id,
                        created_run_index=created_run_index,
                        expires_after_run_index=(
                            created_run_index + _ARTIFACT_RETENTION_COMPLETED_RUNS
                        ),
                        name=safe_filename,
                        media_type=media_type,
                        size_bytes=len(body),
                        sha256=sha256,
                        source_tool_name=source_tool_name,
                        source_call_id=source_call_id,
                        source_part_index=source_part_index,
                        description=description,
                        metadata=_json_metadata(metadata),
                    ),
                )
                await self.s3_service.upload(
                    bucket=self.config.workspace_s3.bucket,
                    key=created.storage_key,
                    body=body,
                    content_type=media_type,
                )
                uploaded_object_key = created.storage_key
                return Success(created)
        except asyncio.CancelledError:
            await self._cleanup_uploaded_object(uploaded_object_key)
            raise
        except Exception:
            await self._cleanup_uploaded_object(uploaded_object_key)
            raise

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

    async def expire_for_run_boundary(
        self,
        *,
        session_id: str,
        current_run_index: int,
    ) -> list[Artifact]:
        """Expire Artifact metadata at run boundary without deleting blobs."""
        now = datetime.datetime.now(datetime.timezone.utc)
        async with self.session_manager() as session:
            return await self.artifact_repository.expire_for_run_boundary(
                session,
                session_id=session_id,
                current_run_index=current_run_index,
                expired_at=now,
            )

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
