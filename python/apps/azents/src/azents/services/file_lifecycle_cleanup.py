"""Scheduler-owned file lifecycle cleanup service."""

import asyncio
import dataclasses
import datetime
import logging
from typing import Annotated
from uuid import uuid4

from azcommon.infra.s3.service import S3Service
from fastapi import Depends

from azents.core.config import Config, require_workspace_s3_bucket
from azents.core.deps import get_config
from azents.core.file_lifecycle_cleanup_data import (
    FileLifecycleBlobDeletionSummary,
    ModelFileCleanupResult,
    PendingBlobDeletionIds,
)
from azents.core.s3.deps import get_s3_service
from azents.repos.agent_avatar_cleanup.data import AgentAvatarCleanupJob
from azents.repos.file_lifecycle_cleanup_operations import (
    FileLifecycleCleanupOperations,
)
from azents.services.uploads.handlers.avatar import AvatarUploadHandler
from azents.utils.logging import sanitized_exception_info

logger = logging.getLogger(__name__)

_AVATAR_CLEANUP_LIMIT = 100
_AVATAR_CLEANUP_LEASE_DURATION = datetime.timedelta(minutes=5)
_AVATAR_CLEANUP_LEASE_TOKEN_MAX_LENGTH = 120
_AVATAR_CLEANUP_LEASE_TOKEN_SEPARATOR = ":"


def _new_avatar_cleanup_lease_token(scheduler_lease_owner: str) -> str:
    """Build one bounded unique token for an avatar cleanup pass."""
    suffix = uuid4().hex
    owner_max_length = (
        _AVATAR_CLEANUP_LEASE_TOKEN_MAX_LENGTH
        - len(_AVATAR_CLEANUP_LEASE_TOKEN_SEPARATOR)
        - len(suffix)
    )
    return (
        f"{scheduler_lease_owner[:owner_max_length]}"
        f"{_AVATAR_CLEANUP_LEASE_TOKEN_SEPARATOR}{suffix}"
    )


@dataclasses.dataclass(frozen=True)
class AvatarCleanupResult:
    """Result of one bounded superseded-avatar deletion pass."""

    attempted: int
    completed: int
    failed: int


@dataclasses.dataclass(frozen=True)
class FileLifecycleCleanupSummary:
    """Summary of one file lifecycle cleanup pass."""

    artifacts_expired: int
    exchange_files_expired: int
    model_files_deleted: int
    stale_pins_released: int
    sessions_advanced: int
    artifact_blobs_deleted: int
    exchange_file_blobs_deleted: int
    model_file_blobs_deleted: int
    pending_blob_deletion_attempts: int
    blob_delete_failed: int
    avatar_cleanup_attempted: int
    avatar_cleanup_completed: int
    avatar_cleanup_failed: int

    def to_dict(self) -> dict[str, int]:
        """Return scheduler-result-compatible summary."""
        return dataclasses.asdict(self)


@dataclasses.dataclass
class FileLifecycleCleanupService:
    """Run bounded cleanup for file lifecycle resources."""

    operations: Annotated[
        FileLifecycleCleanupOperations, Depends(FileLifecycleCleanupOperations)
    ]
    avatar_handler: Annotated[AvatarUploadHandler, Depends(AvatarUploadHandler)]
    s3_service: Annotated[S3Service, Depends(get_s3_service)]
    config: Annotated[Config, Depends(get_config)]

    async def cleanup_once(self, *, lease_owner: str) -> FileLifecycleCleanupSummary:
        """Run one bounded scheduler cleanup pass."""
        pending_blob_deletion_ids = await self._list_pending_blob_deletion_ids()
        artifacts_expired = await self._expire_artifacts()
        exchange_expired = await self._expire_exchange_files()
        stale_pins_released = await self._release_stale_pins()
        model_file_cleanup = await self._cleanup_model_files()
        blob_deletions = await self._retry_blob_deletions(pending_blob_deletion_ids)
        avatar_cleanup = await self._cleanup_superseded_avatars(
            lease_token=_new_avatar_cleanup_lease_token(lease_owner),
        )
        return FileLifecycleCleanupSummary(
            artifacts_expired=artifacts_expired,
            exchange_files_expired=exchange_expired,
            model_files_deleted=model_file_cleanup.deleted_count,
            stale_pins_released=stale_pins_released,
            sessions_advanced=model_file_cleanup.sessions_advanced,
            artifact_blobs_deleted=blob_deletions.artifact_blobs_deleted,
            exchange_file_blobs_deleted=blob_deletions.exchange_file_blobs_deleted,
            model_file_blobs_deleted=blob_deletions.model_file_blobs_deleted,
            pending_blob_deletion_attempts=blob_deletions.pending_attempts,
            blob_delete_failed=blob_deletions.failures,
            avatar_cleanup_attempted=avatar_cleanup.attempted,
            avatar_cleanup_completed=avatar_cleanup.completed,
            avatar_cleanup_failed=avatar_cleanup.failed,
        )

    async def _cleanup_superseded_avatars(
        self,
        *,
        lease_token: str,
    ) -> AvatarCleanupResult:
        """Delete a bounded page of durably tracked superseded avatars."""
        now = datetime.datetime.now(datetime.UTC)
        jobs = await self.operations.claim_avatars(
            now=now,
            lease_token=lease_token,
            lease_until=now + _AVATAR_CLEANUP_LEASE_DURATION,
            limit=_AVATAR_CLEANUP_LIMIT,
        )
        completed = 0
        failed = 0
        for job in jobs:
            try:
                await self.avatar_handler.delete_files(
                    job.avatar,
                    self.s3_service,
                    require_workspace_s3_bucket(self.config.workspace_s3),
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                failed += 1
                failed_at = datetime.datetime.now(datetime.UTC)
                logger.error(
                    "Failed to delete superseded Agent avatar",
                    exc_info=sanitized_exception_info(
                        error,
                        message="Superseded Agent avatar cleanup failed",
                    ),
                    extra={
                        "agent_avatar_cleanup_job_id": job.id,
                        "agent_id": job.agent_id,
                        "attempt_count": job.attempt_count,
                        "failure_kind": type(error).__name__,
                    },
                )
                await self._mark_avatar_cleanup_retry(
                    job=job,
                    lease_token=lease_token,
                    failure_kind=type(error).__name__,
                    now=failed_at,
                )
                continue
            deleted = await self.operations.settle_avatar(
                job_id=job.id,
                lease_token=lease_token,
            )
            completed += int(deleted)
        return AvatarCleanupResult(
            attempted=len(jobs),
            completed=completed,
            failed=failed,
        )

    async def _mark_avatar_cleanup_retry(
        self,
        *,
        job: AgentAvatarCleanupJob,
        lease_token: str,
        failure_kind: str,
        now: datetime.datetime,
    ) -> None:
        """Sequence the completed mark avatar cleanup retry operation."""
        return await self.operations._mark_avatar_cleanup_retry(
            job=job, lease_token=lease_token, failure_kind=failure_kind, now=now
        )

    async def _expire_artifacts(self) -> int:
        """Sequence the completed expire artifacts operation."""
        return await self.operations._expire_artifacts()

    async def _expire_exchange_files(self) -> int:
        """Sequence the completed expire exchange files operation."""
        return await self.operations._expire_exchange_files()

    async def _release_stale_pins(self) -> int:
        """Sequence the completed release stale pins operation."""
        return await self.operations._release_stale_pins()

    async def _cleanup_model_files(self) -> ModelFileCleanupResult:
        """Sequence the completed cleanup model files operation."""
        return await self.operations._cleanup_model_files()

    async def _list_pending_blob_deletion_ids(self) -> PendingBlobDeletionIds:
        """Sequence the completed list pending blob deletion ids operation."""
        return await self.operations._list_pending_blob_deletion_ids()

    async def _retry_blob_deletions(
        self,
        pending_blob_deletion_ids: PendingBlobDeletionIds,
    ) -> FileLifecycleBlobDeletionSummary:
        """Delete a bounded terminal-blob batch and record result counters."""
        artifact_blobs_deleted = 0
        exchange_file_blobs_deleted = 0
        model_file_blobs_deleted = 0
        failures = 0
        pending_attempts = 0
        batch = await self.operations.list_pending_blob_batch()
        artifacts = batch.artifacts
        exchange_files = batch.exchange_files
        model_files = batch.model_files
        for artifact in artifacts:
            if artifact.id in pending_blob_deletion_ids.artifact_ids:
                pending_attempts += 1
            try:
                await self.s3_service.delete(
                    bucket=require_workspace_s3_bucket(self.config.workspace_s3),
                    key=artifact.storage_key,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                failures += 1
                logger.exception(
                    "Failed to delete expired artifact blob",
                    extra={
                        "artifact_id": artifact.id,
                        "storage_key": artifact.storage_key,
                    },
                )
                continue
            await self.operations.settle_artifact(
                artifact_id=artifact.id,
                blob_deleted_at=datetime.datetime.now(datetime.UTC),
            )
            artifact_blobs_deleted += 1
        for file in exchange_files:
            if file.id in pending_blob_deletion_ids.exchange_file_ids:
                pending_attempts += 1
            try:
                await self.s3_service.delete(
                    bucket=require_workspace_s3_bucket(self.config.workspace_s3),
                    key=file.object_key,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                failures += 1
                logger.exception(
                    "Failed to delete expired exchange file blob",
                    extra={"file_id": file.id, "object_key": file.object_key},
                )
                continue
            await self.operations.settle_exchange_file(
                file_id=file.id,
                blob_deleted_at=datetime.datetime.now(datetime.UTC),
            )
            exchange_file_blobs_deleted += 1
        for model_file in model_files:
            if model_file.id in pending_blob_deletion_ids.model_file_ids:
                pending_attempts += 1
            try:
                await self.s3_service.delete(
                    bucket=require_workspace_s3_bucket(self.config.workspace_s3),
                    key=model_file.storage_key,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                failures += 1
                logger.exception(
                    "Failed to delete deleted model file blob",
                    extra={
                        "model_file_id": model_file.id,
                        "storage_key": model_file.storage_key,
                    },
                )
                continue
            await self.operations.settle_model_file(
                model_file_id=model_file.id,
                blob_deleted_at=datetime.datetime.now(datetime.UTC),
            )
            model_file_blobs_deleted += 1
        return FileLifecycleBlobDeletionSummary(
            attempted=len(artifacts) + len(exchange_files) + len(model_files),
            artifact_blobs_deleted=artifact_blobs_deleted,
            exchange_file_blobs_deleted=exchange_file_blobs_deleted,
            model_file_blobs_deleted=model_file_blobs_deleted,
            pending_attempts=pending_attempts,
            failures=failures,
        )
