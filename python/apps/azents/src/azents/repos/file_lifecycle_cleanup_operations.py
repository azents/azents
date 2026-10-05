"""Completed bounded file lifecycle metadata and cursor operations."""

import dataclasses
import datetime
from typing import Annotated

from fastapi import Depends

from azents.core.enums import ModelFileStatus
from azents.core.file_lifecycle_cleanup_data import (
    ModelFileCleanupResult,
    PendingBlobDeletionBatch,
    PendingBlobDeletionIds,
)
from azents.engine.events.model_file_refs import unique_model_file_ids
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_avatar_cleanup import AgentAvatarCleanupRepository
from azents.repos.agent_avatar_cleanup.data import AgentAvatarCleanupJob
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.artifact import ArtifactRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.model_file import ModelFileRepository
from azents.repos.model_file_pin import ModelFilePinRepository

_ARTIFACT_EXPIRATION_LIMIT = 100
_EXCHANGE_FILE_EXPIRATION_LIMIT = 100
_MODEL_FILE_SESSION_LIMIT = 20
_MODEL_FILE_EVENT_LIMIT = 200
_STALE_PIN_LIMIT = 200
_AVATAR_CLEANUP_MAX_RETRY_DELAY = datetime.timedelta(minutes=30)


@dataclasses.dataclass
class FileLifecycleCleanupOperations:
    """Own metadata transactions without external object-store operations."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
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
    avatar_cleanup_repository: Annotated[
        AgentAvatarCleanupRepository, Depends(AgentAvatarCleanupRepository)
    ]
    read_only_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def _mark_avatar_cleanup_retry(
        self,
        *,
        job: AgentAvatarCleanupJob,
        lease_token: str,
        failure_kind: str,
        now: datetime.datetime,
    ) -> None:
        """Record a bounded retry delay for one failed avatar deletion."""
        delay_minutes = min(2 ** max(0, job.attempt_count - 1), 30)
        delay = min(
            datetime.timedelta(minutes=delay_minutes),
            _AVATAR_CLEANUP_MAX_RETRY_DELAY,
        )
        async with self.session_manager() as session:
            await self.avatar_cleanup_repository.mark_retry(
                session,
                job_id=job.id,
                lease_token=lease_token,
                next_attempt_at=now + delay,
                failure_kind=failure_kind,
                now=now,
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
        async with self.read_only_session_manager() as session:
            lagging = await self.agent_session_repository.list_model_file_gc_lagging(
                session,
                limit=_MODEL_FILE_SESSION_LIMIT,
            )
        deleted_count = 0
        advanced_count = 0
        for state in lagging:
            async with self.read_only_session_manager() as session:
                events = await self.transcript_repository.list_model_file_gc_range(
                    session,
                    state.session_id,
                    after_event_id=state.cursor_event_id,
                    to_event_id=state.head_event_id,
                    limit=_MODEL_FILE_EVENT_LIMIT,
                )
            if not events:
                async with self.session_manager() as session:
                    await self.agent_session_repository.advance_model_file_gc_cursor(
                        session,
                        session_id=state.session_id,
                        cursor_event_id=state.head_event_id,
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
            cursor_event_id = (
                state.head_event_id
                if last_event.id >= state.head_event_id
                else last_event.id
            )
            async with self.session_manager() as session:
                await self.agent_session_repository.advance_model_file_gc_cursor(
                    session,
                    session_id=state.session_id,
                    cursor_event_id=cursor_event_id,
                    updated_at=datetime.datetime.now(datetime.UTC),
                )
            advanced_count += 1
        return ModelFileCleanupResult(
            deleted_count=deleted_count,
            sessions_advanced=advanced_count,
        )

    async def _list_pending_blob_deletion_ids(self) -> PendingBlobDeletionIds:
        """Snapshot terminal rows selected before the current cleanup mutations."""
        async with self.read_only_session_manager() as session:
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

    async def claim_avatars(
        self,
        *,
        now: datetime.datetime,
        lease_token: str,
        lease_until: datetime.datetime,
        limit: int,
    ) -> list[AgentAvatarCleanupJob]:
        """Complete claim avatars before further external cleanup."""
        async with self.session_manager() as session:
            return await self.avatar_cleanup_repository.claim_due(
                session,
                now=now,
                lease_token=lease_token,
                lease_until=lease_until,
                limit=limit,
            )

    async def settle_avatar(self, *, job_id: str, lease_token: str) -> bool:
        """Complete settle avatar before further external cleanup."""
        async with self.session_manager() as session:
            return await self.avatar_cleanup_repository.delete_completed(
                session, job_id=job_id, lease_token=lease_token
            )

    async def settle_artifact(
        self, *, artifact_id: str, blob_deleted_at: datetime.datetime
    ) -> None:
        """Complete settle artifact before further external cleanup."""
        async with self.session_manager() as session:
            return await self.artifact_repository.mark_blob_deleted(
                session, artifact_id=artifact_id, blob_deleted_at=blob_deleted_at
            )

    async def settle_exchange_file(
        self, *, file_id: str, blob_deleted_at: datetime.datetime
    ) -> None:
        """Complete settle exchange file before further external cleanup."""
        async with self.session_manager() as session:
            return await self.exchange_file_repository.mark_blob_deleted(
                session, file_id=file_id, blob_deleted_at=blob_deleted_at
            )

    async def settle_model_file(
        self, *, model_file_id: str, blob_deleted_at: datetime.datetime
    ) -> None:
        """Complete settle model file before further external cleanup."""
        async with self.session_manager() as session:
            return await self.model_file_repository.mark_blob_deleted(
                session, model_file_id=model_file_id, blob_deleted_at=blob_deleted_at
            )

    async def list_pending_blob_batch(self) -> PendingBlobDeletionBatch:
        """Complete one native read-only pending metadata snapshot."""
        async with self.read_only_session_manager() as session:
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
        return PendingBlobDeletionBatch(
            artifacts=artifacts, exchange_files=exchange_files, model_files=model_files
        )
