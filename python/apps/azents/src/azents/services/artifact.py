"""Artifact service."""

import asyncio
import dataclasses
import datetime
import hashlib
import logging
import re
from typing import Annotated

from azcommon.infra.s3.service import (
    S3ObjectIdentity,
    S3ProductPublicationMetadata,
    S3Service,
)
from azcommon.result import Failure, Result, Success
from azcommon.types import JSONValue
from azcommon.uuid import uuid7
from fastapi import Depends

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import ArtifactStatus
from azents.core.s3.deps import get_s3_service
from azents.repos.artifact import artifact_storage_key
from azents.repos.artifact.data import Artifact, ArtifactCreate
from azents.repos.artifact.operations import (
    ArtifactMetadataFailure,
    ArtifactOperationRepository,
)
from azents.repos.file_metadata_authority import FileResourceAuthority
from azents.services.file_lifecycle_policy import artifact_expires_at
from azents.services.session_resource_authority import SessionResourceAuthority

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
class ArtifactTransferSource:
    """Authorized Artifact metadata for a trusted Runtime transfer."""

    artifact: Artifact


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

    operation_repository: Annotated[
        ArtifactOperationRepository,
        Depends(ArtifactOperationRepository),
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
        scope_result = await self.operation_repository.authorize_user_create(
            session_id=session_id,
            user_id=user_id,
        )
        if isinstance(scope_result, Failure):
            return Failure(_map_create_failure(scope_result.error))
        scope = scope_result.value
        artifact_id = uuid7().hex
        uploaded_object_key = artifact_storage_key(
            workspace_id=scope.workspace_id,
            session_id=session_id,
            created_run_index=created_run_index,
            artifact_id=artifact_id,
        )
        succeeded = False
        try:
            await self.s3_service.upload(
                bucket=self.config.workspace_s3.bucket,
                key=uploaded_object_key,
                body=body,
                content_type=media_type,
            )
            created = await self.operation_repository.create_for_user(
                session_id=session_id,
                user_id=user_id,
                expected_scope=scope,
                create=ArtifactCreate(
                    id=artifact_id,
                    workspace_id=scope.workspace_id,
                    session_id=session_id,
                    agent_id=scope.agent_id,
                    created_run_id=created_run_id,
                    created_run_index=created_run_index,
                    expires_at=artifact_expires_at(
                        now=datetime.datetime.now(datetime.UTC),
                        config=self.config,
                    ),
                    name=_sanitize_display_filename(filename),
                    media_type=media_type,
                    size_bytes=len(body),
                    sha256=hashlib.sha256(body).hexdigest(),
                    source_tool_name=source_tool_name,
                    source_call_id=source_call_id,
                    source_part_index=source_part_index,
                    description=description,
                    metadata=_json_metadata(metadata),
                ),
            )
            if isinstance(created, Failure):
                return Failure(_map_create_failure(created.error))
            succeeded = True
            return Success(created.value)
        finally:
            if not succeeded:
                await self._cleanup_uploaded_object(uploaded_object_key)

    async def create_for_authority(
        self,
        *,
        authority: SessionResourceAuthority,
        filename: str | None,
        media_type: str,
        body: bytes,
        source_tool_name: str | None = None,
        source_call_id: str | None = None,
        source_part_index: int | None = None,
        description: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Result[Artifact, ArtifactAccessDenied]:
        """Create an Artifact under validated canonical Session/Run authority."""
        repository_authority = _repository_authority(authority)
        if not await self.operation_repository.validate_authority(repository_authority):
            return Failure(ArtifactAccessDenied())
        artifact_id = uuid7().hex
        object_key = artifact_storage_key(
            workspace_id=authority.workspace_id,
            session_id=authority.session_id,
            created_run_index=authority.run_index,
            artifact_id=artifact_id,
        )
        succeeded = False
        try:
            await self.s3_service.upload(
                bucket=self.config.workspace_s3.bucket,
                key=object_key,
                body=body,
                content_type=media_type,
            )
            created = await self.operation_repository.create_for_authority(
                authority=repository_authority,
                create=_authority_artifact_create(
                    authority=authority,
                    artifact_id=artifact_id,
                    filename=filename,
                    media_type=media_type,
                    size_bytes=len(body),
                    sha256=hashlib.sha256(body).hexdigest(),
                    source_tool_name=source_tool_name,
                    source_call_id=source_call_id,
                    source_part_index=source_part_index,
                    description=description,
                    metadata=metadata,
                    config=self.config,
                ),
            )
            if isinstance(created, Failure):
                return Failure(ArtifactAccessDenied())
            succeeded = True
            return Success(created.value)
        finally:
            if not succeeded:
                await self._cleanup_uploaded_object(object_key)

    async def create_from_verified_object_for_authority(
        self,
        *,
        authority: SessionResourceAuthority,
        source: S3ObjectIdentity,
        size_bytes: int,
        sha256: str,
        publication_id: str,
        filename: str | None,
        media_type: str,
        source_tool_name: str | None = None,
        source_call_id: str | None = None,
        source_part_index: int | None = None,
        description: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Result[Artifact, ArtifactAccessDenied]:
        """Publish a verified transfer object as an authority-owned Artifact."""
        repository_authority = _repository_authority(authority)
        existing_result = await self.operation_repository.load_verified_publication(
            authority=repository_authority,
            artifact_id=publication_id,
        )
        if isinstance(existing_result, Failure):
            return Failure(ArtifactAccessDenied())
        if existing_result.value is not None:
            return Success(
                self._validated_existing_verified_publication(
                    existing=existing_result.value,
                    authority=authority,
                    size_bytes=size_bytes,
                    sha256=sha256,
                    media_type=media_type,
                    publication_id=publication_id,
                )
            )
        object_key = artifact_storage_key(
            workspace_id=authority.workspace_id,
            session_id=authority.session_id,
            created_run_index=authority.run_index,
            artifact_id=publication_id,
        )
        publication_metadata = S3ProductPublicationMetadata(
            sha256=sha256,
            content_type=media_type,
            publication_id=publication_id,
        )
        created_by_invocation = False
        committed = False
        try:
            publication = (
                await self.s3_service.copy_verified_transfer_object_to_product(
                    source=source,
                    destination=S3ObjectIdentity(
                        bucket=self.config.workspace_s3.bucket,
                        key=object_key,
                    ),
                    expected_size=size_bytes,
                    publication_metadata=publication_metadata,
                )
            )
            created_by_invocation = publication.created
            finalized = await self.operation_repository.finalize_verified_publication(
                authority=repository_authority,
                create=_authority_artifact_create(
                    authority=authority,
                    artifact_id=publication_id,
                    filename=filename,
                    media_type=media_type,
                    size_bytes=size_bytes,
                    sha256=sha256,
                    source_tool_name=source_tool_name,
                    source_call_id=source_call_id,
                    source_part_index=source_part_index,
                    description=description,
                    metadata=metadata,
                    config=self.config,
                ),
            )
            if isinstance(finalized, Failure):
                return Failure(ArtifactAccessDenied())
            created = self._validated_existing_verified_publication(
                existing=finalized.value,
                authority=authority,
                size_bytes=size_bytes,
                sha256=sha256,
                media_type=media_type,
                publication_id=publication_id,
            )
            committed = True
            return Success(created)
        finally:
            if created_by_invocation and not committed:
                logger.warning(
                    "Retaining uncommitted Artifact object for stable "
                    "publication recovery",
                    extra={"publication_id": publication_id},
                )

    def _validated_existing_verified_publication(
        self,
        *,
        existing: Artifact,
        authority: SessionResourceAuthority,
        size_bytes: int,
        sha256: str,
        media_type: str,
        publication_id: str,
    ) -> Artifact:
        """Return a committed stable publication only when its identity matches."""
        if (
            existing.id == publication_id
            and existing.workspace_id == authority.workspace_id
            and existing.session_id == authority.session_id
            and existing.agent_id == authority.agent_id
            and existing.created_run_id == authority.run_id
            and existing.created_run_index == authority.run_index
            and existing.storage_key
            == artifact_storage_key(
                workspace_id=authority.workspace_id,
                session_id=authority.session_id,
                created_run_index=authority.run_index,
                artifact_id=publication_id,
            )
            and existing.status is ArtifactStatus.AVAILABLE
            and existing.size_bytes == size_bytes
            and existing.sha256 == sha256
            and existing.media_type == media_type
        ):
            return existing
        raise RuntimeError(
            "publication ID is already committed with different metadata"
        )

    async def _has_committed_verified_publication(
        self,
        *,
        authority: SessionResourceAuthority,
        size_bytes: int,
        sha256: str,
        media_type: str,
        publication_id: str,
    ) -> bool:
        """Preserve the final object when commit outcome cannot be disproven."""
        try:
            existing = await self.operation_repository.load_verified_publication(
                authority=_repository_authority(authority),
                artifact_id=publication_id,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return True
        if isinstance(existing, Failure) or existing.value is None:
            return isinstance(existing, Failure)
        try:
            self._validated_existing_verified_publication(
                existing=existing.value,
                authority=authority,
                size_bytes=size_bytes,
                sha256=sha256,
                media_type=media_type,
                publication_id=publication_id,
            )
        except RuntimeError:
            return True
        return True

    async def resolve_for_authority(
        self,
        *,
        uri: str,
        authority: SessionResourceAuthority,
    ) -> Result[ArtifactDownload, ArtifactError]:
        """Resolve an Artifact under validated canonical Session/Run authority."""
        storage_key = artifact_storage_key_from_uri(uri)
        if storage_key is None:
            return Failure(ArtifactNotFound())
        repository_authority = _repository_authority(authority)
        artifact_result = await self.operation_repository.load_for_authority(
            authority=repository_authority,
            storage_key=storage_key,
        )
        artifact = _map_artifact_metadata_result(artifact_result)
        if isinstance(artifact, Failure):
            return Failure(artifact.error)
        if artifact.value.status == ArtifactStatus.EXPIRED:
            return Failure(ArtifactExpired())
        body = await self.s3_service.download_bytes(
            bucket=self.config.workspace_s3.bucket,
            key=artifact.value.storage_key,
        )
        if body is None:
            return Failure(ArtifactUnavailable())
        if not await self.operation_repository.validate_authority(repository_authority):
            return Failure(ArtifactAccessDenied())
        return Success(ArtifactDownload(artifact=artifact.value, body=body))

    async def resolve_transfer_source_for_authority(
        self,
        *,
        uri: str,
        authority: SessionResourceAuthority,
    ) -> Result[ArtifactTransferSource, ArtifactError]:
        """Resolve authorized Artifact metadata without reading object bytes."""
        storage_key = artifact_storage_key_from_uri(uri)
        if storage_key is None:
            return Failure(ArtifactNotFound())
        artifact = _map_artifact_metadata_result(
            await self.operation_repository.load_for_authority(
                authority=_repository_authority(authority),
                storage_key=storage_key,
            )
        )
        if isinstance(artifact, Failure):
            return Failure(artifact.error)
        if artifact.value.status == ArtifactStatus.EXPIRED:
            return Failure(ArtifactExpired())
        return Success(ArtifactTransferSource(artifact=artifact.value))

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
        artifact = _map_artifact_metadata_result(
            await self.operation_repository.load_for_user_by_storage_key(
                storage_key=storage_key,
                user_id=user_id,
            )
        )
        return await self._download_resolved_artifact(artifact)

    async def download(
        self,
        *,
        artifact_id: str,
        user_id: str,
    ) -> Result[ArtifactDownload, ArtifactError]:
        """Fetch original Artifact bytes."""
        artifact = _map_artifact_metadata_result(
            await self.operation_repository.load_for_user_by_id(
                artifact_id=artifact_id,
                user_id=user_id,
            )
        )
        return await self._download_resolved_artifact(artifact)

    async def _download_resolved_artifact(
        self,
        artifact: Result[Artifact, ArtifactNotFound | ArtifactAccessDenied],
    ) -> Result[ArtifactDownload, ArtifactError]:
        """Download one completed, authorized Artifact metadata snapshot."""
        if isinstance(artifact, Failure):
            return Failure(artifact.error)
        if artifact.value.status == ArtifactStatus.EXPIRED:
            return Failure(ArtifactExpired())
        body = await self.s3_service.download_bytes(
            bucket=self.config.workspace_s3.bucket,
            key=artifact.value.storage_key,
        )
        if body is None:
            return Failure(ArtifactUnavailable())
        return Success(ArtifactDownload(artifact=artifact.value, body=body))

    async def _cleanup_uploaded_object(self, object_key: str | None) -> None:
        """Delete already uploaded object when metadata commit fails."""
        if object_key is None:
            return
        await self.s3_service.delete(
            bucket=self.config.workspace_s3.bucket,
            key=object_key,
        )


def _repository_authority(
    authority: SessionResourceAuthority,
) -> FileResourceAuthority:
    """Convert service authority to a repository operation input."""
    return FileResourceAuthority(
        workspace_id=authority.workspace_id,
        agent_id=authority.agent_id,
        session_id=authority.session_id,
        root_session_id=authority.root_session_id,
        run_id=authority.run_id,
        run_index=authority.run_index,
        owner_generation=authority.owner_generation,
    )


def _authority_artifact_create(
    *,
    authority: SessionResourceAuthority,
    artifact_id: str,
    filename: str | None,
    media_type: str,
    size_bytes: int,
    sha256: str,
    source_tool_name: str | None,
    source_call_id: str | None,
    source_part_index: int | None,
    description: str | None,
    metadata: dict[str, object] | None,
    config: Config,
) -> ArtifactCreate:
    """Build stable authority-owned Artifact metadata."""
    return ArtifactCreate(
        id=artifact_id,
        workspace_id=authority.workspace_id,
        session_id=authority.session_id,
        agent_id=authority.agent_id,
        created_run_id=authority.run_id,
        created_run_index=authority.run_index,
        expires_at=artifact_expires_at(
            now=datetime.datetime.now(datetime.UTC),
            config=config,
        ),
        name=_sanitize_display_filename(filename),
        media_type=media_type,
        size_bytes=size_bytes,
        sha256=sha256,
        source_tool_name=source_tool_name,
        source_call_id=source_call_id,
        source_part_index=source_part_index,
        description=description,
        metadata=_json_metadata(metadata),
    )


def _map_create_failure(
    failure: ArtifactMetadataFailure,
) -> ArtifactSessionNotFound | ArtifactAccessDenied:
    """Map repository create failure to the stable service contract."""
    if failure is ArtifactMetadataFailure.SESSION_NOT_FOUND:
        return ArtifactSessionNotFound()
    return ArtifactAccessDenied()


def _map_artifact_metadata_result(
    result: Result[Artifact, ArtifactMetadataFailure],
) -> Result[Artifact, ArtifactNotFound | ArtifactAccessDenied]:
    """Map repository metadata failures to the stable service contract."""
    if isinstance(result, Success):
        return result
    if result.error is ArtifactMetadataFailure.NOT_FOUND:
        return Failure(ArtifactNotFound())
    return Failure(ArtifactAccessDenied())


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
