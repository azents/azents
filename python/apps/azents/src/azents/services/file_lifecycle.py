"""Scheduler-owned file lifecycle cleanup service."""

import dataclasses
import datetime
import hashlib
import logging
from typing import Annotated

from azcommon.infra.s3.service import S3Service
from azcommon.result import Failure
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import ModelFileStatus
from azents.core.s3.deps import get_s3_service
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.artifact import ArtifactRepository
from azents.repos.artifact.data import Artifact
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.model_file import ModelFileRepository
from azents.repos.model_file.data import ModelFile
from azents.services.model_file import (
    degrade_image_model_file_body,
    model_file_retention_age_for_kind,
)

logger = logging.getLogger(__name__)

_EXCHANGE_FILE_EXPIRATION_CLEANUP_LIMIT = 100
_ARTIFACT_EXPIRATION_CLEANUP_LIMIT = 100
_MODEL_FILE_LIFECYCLE_CLEANUP_LIMIT = 100
_MODEL_FILE_UNREACHABLE_GRACE_RUNS = 1


@dataclasses.dataclass(frozen=True)
class FileLifecycleCleanupSummary:
    """Summary of one scheduler lifecycle cleanup pass."""

    exchange_files_expired: int
    artifacts_expired: int
    model_files_changed: int


@dataclasses.dataclass
class FileLifecycleCleanupService:
    """Run scheduler-owned file lifecycle cleanup in bounded batches."""

    exchange_file_repository: Annotated[
        ExchangeFileRepository, Depends(ExchangeFileRepository)
    ]
    artifact_repository: Annotated[ArtifactRepository, Depends(ArtifactRepository)]
    model_file_repository: Annotated[ModelFileRepository, Depends(ModelFileRepository)]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    s3_service: Annotated[S3Service, Depends(get_s3_service)]
    config: Annotated[Config, Depends(get_config)]

    async def cleanup_once(self) -> FileLifecycleCleanupSummary:
        """Run one lifecycle cleanup pass across all file stores."""
        await self.retry_pending_blob_deletions()
        exchange_files = await self.expire_due_exchange_files()
        artifacts = await self.expire_due_artifacts()
        model_files = await self.process_due_model_files()
        return FileLifecycleCleanupSummary(
            exchange_files_expired=len(exchange_files),
            artifacts_expired=len(artifacts),
            model_files_changed=len(model_files),
        )

    async def expire_due_exchange_files(self) -> list[ExchangeFile]:
        """Mark expired ExchangeFiles and retry pending blob deletion."""
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            expired = await self.exchange_file_repository.expire_due(
                session,
                now=now,
                limit=_EXCHANGE_FILE_EXPIRATION_CLEANUP_LIMIT,
            )
        for file in expired:
            await self._delete_exchange_file_blob(file)
        return expired

    async def expire_due_artifacts(self) -> list[Artifact]:
        """Expire Artifacts whose session latest run passed retention age."""
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            candidate_session_ids = (
                await self.artifact_repository.list_candidate_session_ids(
                    session,
                    limit=_ARTIFACT_EXPIRATION_CLEANUP_LIMIT,
                )
            )
            latest_run_indexes = await self.agent_run_repository.latest_run_indexes(
                session,
                session_ids=candidate_session_ids,
            )
            if not latest_run_indexes:
                return []
            expired = await self.artifact_repository.expire_due_by_latest_run_index(
                session,
                latest_run_indexes=latest_run_indexes,
                expired_at=now,
                limit=_ARTIFACT_EXPIRATION_CLEANUP_LIMIT,
            )
        for artifact in expired:
            await self._delete_artifact_blob(artifact)
        return expired

    async def process_due_model_files(self) -> list[ModelFile]:
        """Apply ADR-0046 ModelFile retention transitions."""
        async with self.session_manager() as session:
            candidate_session_ids = (
                await self.model_file_repository.list_candidate_session_ids(
                    session,
                    limit=_MODEL_FILE_LIFECYCLE_CLEANUP_LIMIT,
                )
            )
            latest_run_indexes = await self.agent_run_repository.latest_run_indexes(
                session,
                session_ids=candidate_session_ids,
            )
            if not latest_run_indexes:
                return []
            candidates = await self.model_file_repository.list_due_by_latest_run_index(
                session,
                latest_run_indexes=latest_run_indexes,
                limit=_MODEL_FILE_LIFECYCLE_CLEANUP_LIMIT,
            )
        return await self._process_model_file_candidates(candidates, latest_run_indexes)

    async def retry_pending_blob_deletions(self) -> None:
        """Retry blob deletion for rows already in terminal blob-delete states."""
        async with self.session_manager() as session:
            exchange_files = await self.exchange_file_repository.list_expired_with_blob(
                session,
                limit=_EXCHANGE_FILE_EXPIRATION_CLEANUP_LIMIT,
            )
            artifacts = await self.artifact_repository.list_expired_with_blob(
                session,
                limit=_ARTIFACT_EXPIRATION_CLEANUP_LIMIT,
            )
            model_files = await self.model_file_repository.list_deleted_with_blob(
                session,
                limit=_MODEL_FILE_LIFECYCLE_CLEANUP_LIMIT,
            )
        for file in exchange_files:
            await self._delete_exchange_file_blob(file)
        for artifact in artifacts:
            await self._delete_artifact_blob(artifact)
        for model_file in model_files:
            await self._delete_model_file_blob(model_file)

    async def _process_model_file_candidates(
        self,
        candidates: list[ModelFile],
        latest_run_indexes: dict[str, int],
    ) -> list[ModelFile]:
        """Process selected ModelFile lifecycle candidates."""
        now = datetime.datetime.now(datetime.UTC)
        changed: list[ModelFile] = []
        for model_file in candidates:
            current_run_index = latest_run_indexes.get(model_file.session_id)
            if current_run_index is None:
                continue
            if model_file.status is ModelFileStatus.UNREACHABLE:
                if _unreachable_grace_expired(
                    model_file,
                    current_run_index=current_run_index,
                ):
                    deleted = await self._mark_deleted(model_file, deleted_at=now)
                    await self._delete_model_file_blob(deleted)
                    changed.append(deleted)
                continue

            age = current_run_index - model_file.created_run_index
            if age >= model_file_retention_age_for_kind(kind=model_file.kind):
                changed.append(
                    await self._mark_unreachable(
                        model_file,
                        unreachable_run_index=current_run_index,
                        unreachable_at=now,
                    )
                )
                continue
            if model_file.kind != "image":
                continue
            target_edge = _target_image_edge(model_file, age=age)
            if target_edge is None:
                continue
            changed.append(
                await self._degrade_or_mark_unreachable(
                    model_file,
                    target_edge=target_edge,
                    current_run_index=current_run_index,
                    changed_at=now,
                )
            )
        return changed

    async def _degrade_or_mark_unreachable(
        self,
        model_file: ModelFile,
        *,
        target_edge: int,
        current_run_index: int,
        changed_at: datetime.datetime,
    ) -> ModelFile:
        """Degrade an image ModelFile or mark it unreachable if degradation fails."""
        body = await self.s3_service.download_bytes(
            bucket=self.config.workspace_s3.bucket,
            key=model_file.storage_key,
        )
        if body is None:
            return await self._mark_unreachable(
                model_file,
                unreachable_run_index=current_run_index,
                unreachable_at=changed_at,
            )
        degraded = degrade_image_model_file_body(
            body=body,
            max_edge=target_edge,
        )
        if isinstance(degraded, Failure):
            return await self._mark_unreachable(
                model_file,
                unreachable_run_index=current_run_index,
                unreachable_at=changed_at,
            )
        normalized = degraded.value
        await self.s3_service.upload(
            bucket=self.config.workspace_s3.bucket,
            key=model_file.storage_key,
            body=normalized.body,
            content_type=normalized.media_type,
        )
        async with self.session_manager() as session:
            return await self.model_file_repository.mark_degraded(
                session,
                model_file_id=model_file.id,
                size_bytes=len(normalized.body),
                normalized_format=normalized.normalized_format,
                sha256=hashlib.sha256(normalized.body).hexdigest(),
                degraded_at=changed_at,
            )

    async def _mark_deleted(
        self,
        model_file: ModelFile,
        *,
        deleted_at: datetime.datetime,
    ) -> ModelFile:
        """Mark a ModelFile deleted before trying blob deletion."""
        async with self.session_manager() as session:
            return await self.model_file_repository.mark_deleted(
                session,
                model_file_id=model_file.id,
                deleted_at=deleted_at,
            )

    async def _mark_unreachable(
        self,
        model_file: ModelFile,
        *,
        unreachable_run_index: int,
        unreachable_at: datetime.datetime,
    ) -> ModelFile:
        """Mark a ModelFile unreachable."""
        async with self.session_manager() as session:
            return await self.model_file_repository.mark_unreachable(
                session,
                model_file_id=model_file.id,
                unreachable_run_index=unreachable_run_index,
                unreachable_at=unreachable_at,
            )

    async def _delete_exchange_file_blob(self, file: ExchangeFile) -> None:
        """Delete ExchangeFile blob and record success for idempotent retries."""
        try:
            await self.s3_service.delete(
                bucket=self.config.workspace_s3.bucket,
                key=file.object_key,
            )
        except Exception:
            logger.exception(
                "Failed to delete expired exchange file blob",
                extra={"file_id": file.id, "object_key": file.object_key},
            )
            return
        async with self.session_manager() as session:
            await self.exchange_file_repository.mark_blob_deleted(
                session,
                file_id=file.id,
            )

    async def _delete_artifact_blob(self, artifact: Artifact) -> None:
        """Delete Artifact blob and record success for idempotent retries."""
        try:
            await self.s3_service.delete(
                bucket=self.config.workspace_s3.bucket,
                key=artifact.storage_key,
            )
        except Exception:
            logger.exception(
                "Failed to delete expired artifact blob",
                extra={
                    "artifact_id": artifact.id,
                    "session_id": artifact.session_id,
                    "storage_key": artifact.storage_key,
                },
            )
            return
        async with self.session_manager() as session:
            await self.artifact_repository.mark_blob_deleted(
                session,
                artifact_id=artifact.id,
            )

    async def _delete_model_file_blob(self, model_file: ModelFile) -> None:
        """Delete ModelFile blob and record success for idempotent retries."""
        try:
            await self.s3_service.delete(
                bucket=self.config.workspace_s3.bucket,
                key=model_file.storage_key,
            )
        except Exception:
            logger.exception(
                "Failed to delete deleted model file blob",
                extra={
                    "model_file_id": model_file.id,
                    "session_id": model_file.session_id,
                    "storage_key": model_file.storage_key,
                },
            )
            return
        async with self.session_manager() as session:
            await self.model_file_repository.mark_blob_deleted(
                session,
                model_file_id=model_file.id,
            )


def _unreachable_grace_expired(
    model_file: ModelFile,
    *,
    current_run_index: int,
) -> bool:
    """Return whether deferred GC grace for unreachable ModelFile ended."""
    if model_file.unreachable_run_index is None:
        return True
    return (
        current_run_index - model_file.unreachable_run_index
        >= _MODEL_FILE_UNREACHABLE_GRACE_RUNS
    )


def _target_image_edge(model_file: ModelFile, *, age: int) -> int | None:
    """Return image degrade edge to apply for current run age."""
    if age >= 3:
        if model_file.normalized_format != "jpeg:300":
            return 300
        return None
    if age >= 1:
        if model_file.normalized_format not in {"jpeg:1024", "jpeg:300"}:
            return 1024
    return None
