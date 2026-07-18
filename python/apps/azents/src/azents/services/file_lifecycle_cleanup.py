"""Scheduler-owned file lifecycle cleanup service."""

import asyncio
import dataclasses
import datetime
import logging
from typing import Annotated

from azcommon.infra.s3.service import S3Service
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import ModelFileStatus
from azents.core.s3.deps import get_s3_service
from azents.engine.events.model_file_refs import unique_model_file_ids
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.artifact import ArtifactRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.model_file import ModelFileRepository
from azents.repos.model_file_pin import ModelFilePinRepository

logger = logging.getLogger(__name__)

_ARTIFACT_EXPIRATION_LIMIT = 100
_EXCHANGE_FILE_EXPIRATION_LIMIT = 100
_MODEL_FILE_SESSION_LIMIT = 20
_MODEL_FILE_EVENT_LIMIT = 200
_STALE_PIN_LIMIT = 200


@dataclasses.dataclass(frozen=True)
class PendingBlobDeletionIds:
    """IDs eligible for blob deletion before the current cleanup pass."""

    artifact_ids: frozenset[str]
    exchange_file_ids: frozenset[str]
    model_file_ids: frozenset[str]


@dataclasses.dataclass(frozen=True)
class FileLifecycleBlobDeletionSummary:
    """Result of the bounded terminal-blob deletion stage."""

    attempted: int
    artifact_blobs_deleted: int
    exchange_file_blobs_deleted: int
    model_file_blobs_deleted: int
    pending_attempts: int
    failures: int


@dataclasses.dataclass(frozen=True)
class ModelFileCleanupResult:
    """Result of one ModelFile metadata cleanup pass."""

    deleted_count: int
    sessions_advanced: int


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

    def to_dict(self) -> dict[str, int]:
        """Return scheduler-result-compatible summary."""
        return dataclasses.asdict(self)


@dataclasses.dataclass
class FileLifecycleCleanupService:
    """Run bounded cleanup for file lifecycle resources."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    artifact_repository: Annotated[ArtifactRepository, Depends(ArtifactRepository)]
    exchange_file_repository: Annotated[
        ExchangeFileRepository, Depends(ExchangeFileRepository)
    ]
    model_file_repository: Annotated[ModelFileRepository, Depends(ModelFileRepository)]
    model_file_pin_repository: Annotated[
        ModelFilePinRepository, Depends(ModelFilePinRepository)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    s3_service: Annotated[S3Service, Depends(get_s3_service)]
    config: Annotated[Config, Depends(get_config)]

    async def cleanup_once(self) -> FileLifecycleCleanupSummary:
        """Run one bounded scheduler cleanup pass."""
        pending_blob_deletion_ids = await self._list_pending_blob_deletion_ids()
        artifacts_expired = await self._expire_artifacts()
        exchange_expired = await self._expire_exchange_files()
        stale_pins_released = await self._release_stale_pins()
        model_file_cleanup = await self._cleanup_model_files()
        blob_deletions = await self._retry_blob_deletions(pending_blob_deletion_ids)
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
        )

    async def _expire_artifacts(self) -> int:
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            expired = await self.artifact_repository.expire_due(
                session,
                now=now,
                limit=_ARTIFACT_EXPIRATION_LIMIT,
            )
        return len(expired)

    async def _expire_exchange_files(self) -> int:
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            expired = await self.exchange_file_repository.expire_due(
                session,
                now=now,
                limit=_EXCHANGE_FILE_EXPIRATION_LIMIT,
            )
        return len(expired)

    async def _release_stale_pins(self) -> int:
        async with self.session_manager() as session:
            return await self.model_file_pin_repository.release_terminal_run_pins(
                session,
                limit=_STALE_PIN_LIMIT,
            )

    async def _cleanup_model_files(self) -> ModelFileCleanupResult:
        async with self.session_manager() as session:
            lagging = await self.agent_session_repository.list_model_file_gc_lagging(
                session,
                limit=_MODEL_FILE_SESSION_LIMIT,
            )
        deleted_count = 0
        advanced_count = 0
        for state in lagging:
            async with self.session_manager() as session:
                events = await self.transcript_repository.list_model_file_gc_range(
                    session,
                    state.session_id,
                    after_order=state.cursor_model_order,
                    to_order=state.head_model_order,
                    limit=_MODEL_FILE_EVENT_LIMIT,
                )
            if not events:
                async with self.session_manager() as session:
                    await self.agent_session_repository.advance_model_file_gc_cursor(
                        session,
                        session_id=state.session_id,
                        cursor_event_id=state.head_event_id,
                        cursor_model_order=state.head_model_order,
                        updated_at=datetime.datetime.now(datetime.UTC),
                    )
                advanced_count += 1
                continue
            model_file_ids = unique_model_file_ids(events)
            now = datetime.datetime.now(datetime.UTC)
            async with self.session_manager() as session:
                deleted = await self.model_file_repository.mark_deleted_if_unpinned(
                    session,
                    model_file_ids=model_file_ids,
                    deleted_at=now,
                )
                statuses = await self.model_file_repository.list_statuses_for_session(
                    session,
                    session_id=state.session_id,
                    model_file_ids=model_file_ids,
                )
            deleted_count += len(deleted)
            if any(status == ModelFileStatus.AVAILABLE for status in statuses.values()):
                continue
            last_event = events[-1]
            cursor_order = min(last_event.model_order, state.head_model_order)
            cursor_event_id = (
                state.head_event_id
                if cursor_order >= state.head_model_order
                else last_event.id
            )
            async with self.session_manager() as session:
                await self.agent_session_repository.advance_model_file_gc_cursor(
                    session,
                    session_id=state.session_id,
                    cursor_event_id=cursor_event_id,
                    cursor_model_order=cursor_order,
                    updated_at=datetime.datetime.now(datetime.UTC),
                )
            advanced_count += 1
        return ModelFileCleanupResult(
            deleted_count=deleted_count,
            sessions_advanced=advanced_count,
        )

    async def _list_pending_blob_deletion_ids(self) -> PendingBlobDeletionIds:
        """Snapshot terminal rows selected before the current cleanup mutations."""
        async with self.session_manager() as session:
            artifacts = (
                await self.artifact_repository.list_expired_pending_blob_deletion(
                    session,
                    limit=_ARTIFACT_EXPIRATION_LIMIT,
                )
            )
            exchange_files = (
                await self.exchange_file_repository.list_expired_pending_blob_deletion(
                    session,
                    limit=_EXCHANGE_FILE_EXPIRATION_LIMIT,
                )
            )
            model_files = (
                await self.model_file_repository.list_deleted_pending_blob_deletion(
                    session,
                    limit=_MODEL_FILE_EVENT_LIMIT,
                )
            )
        return PendingBlobDeletionIds(
            artifact_ids=frozenset(artifact.id for artifact in artifacts),
            exchange_file_ids=frozenset(file.id for file in exchange_files),
            model_file_ids=frozenset(model_file.id for model_file in model_files),
        )

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
        async with self.session_manager() as session:
            artifacts = (
                await self.artifact_repository.list_expired_pending_blob_deletion(
                    session,
                    limit=_ARTIFACT_EXPIRATION_LIMIT,
                )
            )
            exchange_files = (
                await self.exchange_file_repository.list_expired_pending_blob_deletion(
                    session,
                    limit=_EXCHANGE_FILE_EXPIRATION_LIMIT,
                )
            )
            model_files = (
                await self.model_file_repository.list_deleted_pending_blob_deletion(
                    session,
                    limit=_MODEL_FILE_EVENT_LIMIT,
                )
            )
        for artifact in artifacts:
            if artifact.id in pending_blob_deletion_ids.artifact_ids:
                pending_attempts += 1
            try:
                await self.s3_service.delete(
                    bucket=self.config.workspace_s3.bucket,
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
            async with self.session_manager() as session:
                await self.artifact_repository.mark_blob_deleted(
                    session,
                    artifact_id=artifact.id,
                    blob_deleted_at=datetime.datetime.now(datetime.UTC),
                )
            artifact_blobs_deleted += 1
        for file in exchange_files:
            if file.id in pending_blob_deletion_ids.exchange_file_ids:
                pending_attempts += 1
            try:
                await self.s3_service.delete(
                    bucket=self.config.workspace_s3.bucket,
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
            async with self.session_manager() as session:
                await self.exchange_file_repository.mark_blob_deleted(
                    session,
                    file_id=file.id,
                    blob_deleted_at=datetime.datetime.now(datetime.UTC),
                )
            exchange_file_blobs_deleted += 1
        for model_file in model_files:
            if model_file.id in pending_blob_deletion_ids.model_file_ids:
                pending_attempts += 1
            try:
                await self.s3_service.delete(
                    bucket=self.config.workspace_s3.bucket,
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
            async with self.session_manager() as session:
                await self.model_file_repository.mark_blob_deleted(
                    session,
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
