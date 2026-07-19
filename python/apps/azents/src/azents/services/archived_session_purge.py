"""Durable archived-session purge workflow."""

import asyncio
import dataclasses
import datetime
from typing import Annotated

from azcommon.infra.s3.service import S3Service
from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.deps import get_broker
from azents.broker.types import SessionBroker, SessionStopSignal
from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.enums import (
    AgentSessionStatus,
    ArtifactStatus,
    ExchangeFileStatus,
    ModelFileStatus,
)
from azents.core.s3.deps import get_s3_service
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.archived_session_retention.data import ArchivedSessionPurgeJob
from azents.repos.artifact import ArtifactRepository
from azents.repos.artifact.data import Artifact
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.model_file import ModelFileRepository
from azents.repos.model_file.data import ModelFile
from azents.services.session_git_worktree import SessionGitWorktreeService

_LEASE_DURATION = datetime.timedelta(minutes=15)
_MAX_RETRY_DELAY = datetime.timedelta(minutes=30)


@dataclasses.dataclass(frozen=True)
class ArchivedSessionPurgeSummary:
    """Result of one scheduler purge pass."""

    claimed: bool
    completed: bool
    retry_scheduled: bool
    root_session_id: str | None
    model_file_count: int
    artifact_count: int
    exchange_file_count: int
    worktree_count: int


@dataclasses.dataclass
class ArchivedSessionPurgeService:
    """Fence and purge one archived SessionAgent tree per scheduler pass."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    retention_repository: Annotated[
        ArchivedSessionRetentionRepository,
        Depends(ArchivedSessionRetentionRepository),
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    model_file_repository: Annotated[ModelFileRepository, Depends(ModelFileRepository)]
    artifact_repository: Annotated[ArtifactRepository, Depends(ArtifactRepository)]
    exchange_file_repository: Annotated[
        ExchangeFileRepository, Depends(ExchangeFileRepository)
    ]
    session_git_worktree_service: Annotated[
        SessionGitWorktreeService, Depends(SessionGitWorktreeService)
    ]
    broker: Annotated[SessionBroker, Depends(get_broker)]
    s3_service: Annotated[S3Service, Depends(get_s3_service)]
    config: Annotated[Config, Depends(get_config)]

    async def purge_once(self, *, lease_owner: str) -> ArchivedSessionPurgeSummary:
        """Claim and advance one durable purge job."""
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            job = await self.retention_repository.claim_due_purge_job(
                session,
                now=now,
                lease_owner=lease_owner,
                lease_until=now + _LEASE_DURATION,
            )
        if job is None:
            return ArchivedSessionPurgeSummary(False, False, False, None, 0, 0, 0, 0)

        try:
            return await self._purge_claimed(job=job, lease_owner=lease_owner)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._retry(
                job_id=job.id,
                lease_owner=lease_owner,
                attempt_count=job.attempt_count,
                error_kind=type(exc).__name__,
                error_summary=str(exc) or type(exc).__name__,
            )
            raise

    async def _purge_claimed(
        self,
        *,
        job: ArchivedSessionPurgeJob,
        lease_owner: str,
    ) -> ArchivedSessionPurgeSummary:
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            sessions = await self.agent_session_repository.lock_root_tree_sessions(
                session,
                root_session_id=job.root_session_id,
            )
            if not sessions:
                completed = await self.retention_repository.complete_purge_job(
                    session,
                    job_id=job.id,
                    lease_owner=lease_owner,
                    now=now,
                )
                return ArchivedSessionPurgeSummary(
                    True, completed, False, job.root_session_id, 0, 0, 0, 0
                )
            if any(item.status is not AgentSessionStatus.ARCHIVED for item in sessions):
                raise RuntimeError("Purge root tree is no longer archived")
            session_ids = [item.id for item in sessions]
            fenced_count = (
                await self.agent_session_repository.fence_archived_owner_generations(
                    session,
                    session_ids=session_ids,
                )
            )
            if fenced_count != len(session_ids):
                raise RuntimeError("Purge root tree ownership fence is incomplete")
            for session_id in session_ids:
                await self.agent_session_repository.request_stop(
                    session,
                    session_id=session_id,
                    stop_request_id=uuid7().hex,
                    user_id=None,
                )
            active = await self.agent_run_repository.has_active_for_session_ids(
                session,
                session_ids=session_ids,
            )

        for session_id in session_ids:
            await self.broker.send_message(SessionStopSignal(session_id=session_id))
        if active:
            await self._retry(
                job_id=job.id,
                lease_owner=lease_owner,
                attempt_count=job.attempt_count,
                error_kind="ActiveAgentRun",
                error_summary="Subtree AgentRun is still active after purge fencing.",
            )
            return ArchivedSessionPurgeSummary(
                True, False, True, job.root_session_id, 0, 0, 0, 0
            )

        for session_id in session_ids:
            await self.broker.purge_session_state(session_id)

        root_session = next(item for item in sessions if item.id == job.root_session_id)
        worktree_count = (
            await self.session_git_worktree_service.run_cleanup_for_root_tree(
                agent_id=root_session.agent_id,
                root_session_id=job.root_session_id,
                subtree_session_ids=session_ids,
            )
        )
        async with self.session_manager() as session:
            model_files = await self.model_file_repository.list_for_session_ids(
                session,
                session_ids=session_ids,
            )
            artifacts = await self.artifact_repository.list_for_session_ids(
                session,
                session_ids=session_ids,
            )
            exchange_files = (
                await self.exchange_file_repository.list_for_retention_root(
                    session,
                    retention_root_session_id=job.root_session_id,
                )
            )
            model_file_count = len(model_files)
            artifact_count = len(artifacts)
            exchange_file_count = len(exchange_files)
            await self.model_file_repository.mark_deleted_for_session_ids(
                session,
                session_ids=session_ids,
                deleted_at=now,
            )
            await self.artifact_repository.expire_for_session_ids(
                session,
                session_ids=session_ids,
                expired_at=now,
            )
            await self.exchange_file_repository.expire_for_retention_root(
                session,
                retention_root_session_id=job.root_session_id,
                expired_at=now,
            )
            model_files = await self.model_file_repository.list_for_session_ids(
                session,
                session_ids=session_ids,
            )
            artifacts = await self.artifact_repository.list_for_session_ids(
                session,
                session_ids=session_ids,
            )
            exchange_files = (
                await self.exchange_file_repository.list_for_retention_root(
                    session,
                    retention_root_session_id=job.root_session_id,
                )
            )
            marked = await self.retention_repository.mark_purge_cleaning(
                session,
                job_id=job.id,
                lease_owner=lease_owner,
                model_file_count=model_file_count,
                artifact_count=artifact_count,
                exchange_file_count=exchange_file_count,
                worktree_count=worktree_count,
                now=now,
            )
            if not marked:
                raise RuntimeError("Archived-session purge lease was lost")

        await self._delete_file_blobs(
            model_files=model_files,
            artifacts=artifacts,
            exchange_files=exchange_files,
        )

        async with self.session_manager() as session:
            final_sessions = (
                await self.agent_session_repository.lock_root_tree_sessions(
                    session,
                    root_session_id=job.root_session_id,
                )
            )
            if {item.id for item in final_sessions} != set(session_ids):
                raise RuntimeError("Purge root tree boundary changed during cleanup")
            if any(
                item.status is not AgentSessionStatus.ARCHIVED
                for item in final_sessions
            ):
                raise RuntimeError("Purge root tree is no longer archived")
            model_files = await self.model_file_repository.list_for_session_ids(
                session,
                session_ids=session_ids,
            )
            artifacts = await self.artifact_repository.list_for_session_ids(
                session,
                session_ids=session_ids,
            )
            exchange_files = (
                await self.exchange_file_repository.list_for_retention_root(
                    session,
                    retention_root_session_id=job.root_session_id,
                )
            )
            if any(
                file.status is not ModelFileStatus.DELETED
                or file.blob_deleted_at is None
                for file in model_files
            ):
                raise RuntimeError("ModelFile purge cleanup is incomplete")
            if any(
                artifact.status is not ArtifactStatus.EXPIRED
                or artifact.blob_deleted_at is None
                for artifact in artifacts
            ):
                raise RuntimeError("Artifact purge cleanup is incomplete")
            if any(
                file.status is not ExchangeFileStatus.EXPIRED
                or file.blob_deleted_at is None
                for file in exchange_files
            ):
                raise RuntimeError("ExchangeFile purge cleanup is incomplete")
            if await self.agent_run_repository.has_active_for_session_ids(
                session,
                session_ids=session_ids,
            ):
                raise RuntimeError("AgentRun became active during purge cleanup")
            await self.model_file_repository.delete_purged_for_session_ids(
                session,
                session_ids=session_ids,
            )
            await self.artifact_repository.delete_purged_for_session_ids(
                session,
                session_ids=session_ids,
            )
            await self.exchange_file_repository.delete_purged_for_retention_root(
                session,
                retention_root_session_id=job.root_session_id,
            )
            await self.agent_session_repository.delete_by_id(
                session,
                job.root_session_id,
            )
            completed = await self.retention_repository.complete_purge_job(
                session,
                job_id=job.id,
                lease_owner=lease_owner,
                now=datetime.datetime.now(datetime.UTC),
            )
            if not completed:
                raise RuntimeError("Archived-session purge lease was lost")

        return ArchivedSessionPurgeSummary(
            True,
            True,
            False,
            job.root_session_id,
            len(model_files),
            len(artifacts),
            len(exchange_files),
            worktree_count,
        )

    async def _delete_file_blobs(
        self,
        *,
        model_files: list[ModelFile],
        artifacts: list[Artifact],
        exchange_files: list[ExchangeFile],
    ) -> None:
        for item in model_files:
            if (
                item.status is not ModelFileStatus.DELETED
                or item.blob_deleted_at is not None
            ):
                continue
            await self.s3_service.delete(
                bucket=self.config.workspace_s3.bucket,
                key=item.storage_key,
            )
            async with self.session_manager() as session:
                await self.model_file_repository.mark_blob_deleted(
                    session,
                    model_file_id=item.id,
                    blob_deleted_at=datetime.datetime.now(datetime.UTC),
                )
        for item in artifacts:
            if (
                item.status is not ArtifactStatus.EXPIRED
                or item.blob_deleted_at is not None
            ):
                continue
            await self.s3_service.delete(
                bucket=self.config.workspace_s3.bucket,
                key=item.storage_key,
            )
            async with self.session_manager() as session:
                await self.artifact_repository.mark_blob_deleted(
                    session,
                    artifact_id=item.id,
                    blob_deleted_at=datetime.datetime.now(datetime.UTC),
                )
        for item in exchange_files:
            if (
                item.status is not ExchangeFileStatus.EXPIRED
                or item.blob_deleted_at is not None
            ):
                continue
            await self.s3_service.delete(
                bucket=self.config.workspace_s3.bucket,
                key=item.object_key,
            )
            async with self.session_manager() as session:
                await self.exchange_file_repository.mark_blob_deleted(
                    session,
                    file_id=item.id,
                    blob_deleted_at=datetime.datetime.now(datetime.UTC),
                )

    async def _retry(
        self,
        *,
        job_id: str,
        lease_owner: str,
        attempt_count: int,
        error_kind: str,
        error_summary: str,
    ) -> None:
        now = datetime.datetime.now(datetime.UTC)
        delay_minutes = min(2 ** max(0, attempt_count - 1), 30)
        delay = min(datetime.timedelta(minutes=delay_minutes), _MAX_RETRY_DELAY)
        async with self.session_manager() as session:
            await self.retention_repository.mark_purge_retry(
                session,
                job_id=job_id,
                lease_owner=lease_owner,
                next_attempt_at=now + delay,
                error_kind=error_kind,
                error_summary=error_summary,
                now=now,
            )
