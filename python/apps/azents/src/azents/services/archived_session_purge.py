"""Durable archived-session purge workflow."""

import asyncio
import dataclasses
import datetime
import logging
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
    ArchivedSessionPurgeParticipantPhase,
    ArtifactStatus,
    ExchangeFileStatus,
    ModelFileStatus,
)
from azents.core.s3.deps import get_s3_service
from azents.core.session_lifecycle import (
    SessionLifecycleParticipantDefinition,
    SessionLifecyclePurgeContext,
)
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
from azents.repos.session_lifecycle_finalizer import (
    SessionLifecycleFinalizerRepository,
)
from azents.services.session_git_worktree import SessionGitWorktreeService
from azents.services.session_lifecycle.orchestrator import (
    SessionLifecycleOrchestrator,
    SessionLifecyclePurgeParticipantFailure,
)
from azents.services.session_lifecycle.registry import (
    get_session_lifecycle_orchestrator,
)

_LEASE_DURATION = datetime.timedelta(minutes=15)
_MAX_RETRY_DELAY = datetime.timedelta(minutes=30)
_STALE_JOB_RECONCILIATION_LIMIT = 100
_PURGE_JOB_LIMIT = 100
_DEADLINE_SAFETY_MARGIN = datetime.timedelta(seconds=30)

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class ArchivedSessionPurgeSummary:
    """Result of one scheduler purge pass."""

    claimed_count: int
    completed_count: int
    retry_scheduled_count: int
    failed_count: int
    model_file_count: int
    artifact_count: int
    exchange_file_count: int
    worktree_count: int
    stale_job_count: int
    limit_reached: bool
    deadline_reached: bool


@dataclasses.dataclass(frozen=True)
class _ArchivedSessionPurgeJobSummary:
    """Result of advancing one claimed archived-session purge job."""

    completed: bool
    retry_scheduled: bool
    model_file_count: int
    artifact_count: int
    exchange_file_count: int
    worktree_count: int


@dataclasses.dataclass(frozen=True)
class _PurgeFileCleanupState:
    """Durable file cleanup scope selected before external object deletion."""

    model_files: list[ModelFile]
    artifacts: list[Artifact]
    exchange_files: list[ExchangeFile]
    model_file_count: int
    artifact_count: int
    exchange_file_count: int


@dataclasses.dataclass
class ArchivedSessionPurgeService:
    """Fence and purge a bounded batch of archived SessionAgent trees."""

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
    lifecycle_finalizer_repository: Annotated[
        SessionLifecycleFinalizerRepository,
        Depends(SessionLifecycleFinalizerRepository),
    ]
    session_git_worktree_service: Annotated[
        SessionGitWorktreeService, Depends(SessionGitWorktreeService)
    ]
    broker: Annotated[SessionBroker, Depends(get_broker)]
    s3_service: Annotated[S3Service, Depends(get_s3_service)]
    config: Annotated[Config, Depends(get_config)]
    lifecycle_orchestrator: Annotated[
        SessionLifecycleOrchestrator,
        Depends(get_session_lifecycle_orchestrator),
    ]

    async def purge_once(
        self,
        *,
        lease_owner: str,
        deadline: datetime.datetime,
    ) -> ArchivedSessionPurgeSummary:
        """Claim and advance a bounded batch of durable purge jobs."""
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            stale_job_count = (
                await self.retention_repository.cancel_invalid_unstarted_purge_jobs(
                    session,
                    now=now,
                    limit=_STALE_JOB_RECONCILIATION_LIMIT,
                )
            )

        claimed_count = 0
        completed_count = 0
        retry_scheduled_count = 0
        failed_count = 0
        model_file_count = 0
        artifact_count = 0
        exchange_file_count = 0
        worktree_count = 0
        deadline_reached = False

        for _ in range(_PURGE_JOB_LIMIT):
            now = datetime.datetime.now(datetime.UTC)
            if now + _DEADLINE_SAFETY_MARGIN >= deadline:
                deadline_reached = True
                break
            async with self.session_manager() as session:
                job = await self.retention_repository.claim_due_purge_job(
                    session,
                    now=now,
                    lease_owner=lease_owner,
                    lease_until=now + _LEASE_DURATION,
                )
                if job is not None:
                    lifecycle_orchestrator = self.lifecycle_orchestrator
                    await lifecycle_orchestrator.materialize_claimed_purge_participants(
                        session,
                        retention_repository=self.retention_repository,
                        purge_job_id=job.id,
                        lease_owner=lease_owner,
                    )
            if job is None:
                break
            claimed_count += 1

            try:
                job_summary = await self._purge_claimed(
                    job=job,
                    lease_owner=lease_owner,
                )
            except asyncio.CancelledError:
                raise
            except SessionLifecyclePurgeParticipantFailure as exc:
                await self._retry(
                    job_id=job.id,
                    lease_owner=lease_owner,
                    attempt_count=job.attempt_count,
                    error_kind=exc.error_kind,
                    error_summary=exc.error_summary,
                    error_participant_key=exc.participant_key,
                    error_phase=exc.phase,
                )
                failed_count += 1
                retry_scheduled_count += 1
                logger.exception(
                    "Archived-session purge job failed; retry scheduled",
                    extra={
                        "purge_job_id": job.id,
                        "root_session_id": job.root_session_id,
                        "participant_key": exc.participant_key,
                        "phase": exc.phase,
                        "attempt_count": job.attempt_count,
                    },
                )
                continue
            except Exception as exc:
                await self._retry(
                    job_id=job.id,
                    lease_owner=lease_owner,
                    attempt_count=job.attempt_count,
                    error_kind=type(exc).__name__,
                    error_summary=str(exc) or type(exc).__name__,
                    error_participant_key=None,
                    error_phase=None,
                )
                failed_count += 1
                retry_scheduled_count += 1
                logger.exception(
                    "Archived-session purge job failed; retry scheduled",
                    extra={
                        "purge_job_id": job.id,
                        "root_session_id": job.root_session_id,
                        "attempt_count": job.attempt_count,
                    },
                )
                continue

            completed_count += int(job_summary.completed)
            retry_scheduled_count += int(job_summary.retry_scheduled)
            model_file_count += job_summary.model_file_count
            artifact_count += job_summary.artifact_count
            exchange_file_count += job_summary.exchange_file_count
            worktree_count += job_summary.worktree_count

        return ArchivedSessionPurgeSummary(
            claimed_count=claimed_count,
            completed_count=completed_count,
            retry_scheduled_count=retry_scheduled_count,
            failed_count=failed_count,
            model_file_count=model_file_count,
            artifact_count=artifact_count,
            exchange_file_count=exchange_file_count,
            worktree_count=worktree_count,
            stale_job_count=stale_job_count,
            limit_reached=claimed_count == _PURGE_JOB_LIMIT,
            deadline_reached=deadline_reached,
        )

    async def _purge_claimed(
        self,
        *,
        job: ArchivedSessionPurgeJob,
        lease_owner: str,
    ) -> _ArchivedSessionPurgeJobSummary:
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
                return _ArchivedSessionPurgeJobSummary(
                    completed=completed,
                    retry_scheduled=False,
                    model_file_count=0,
                    artifact_count=0,
                    exchange_file_count=0,
                    worktree_count=0,
                )
            root_session = next(
                (item for item in sessions if item.id == job.root_session_id),
                None,
            )
            if (
                root_session is None
                or root_session.status is not AgentSessionStatus.ARCHIVED
            ):
                raise RuntimeError("Purge root session is no longer archived")
            session_ids = [item.id for item in sessions]
            fenced_count = (
                await self.agent_session_repository.fence_purge_owner_generations(
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
                error_participant_key=None,
                error_phase=ArchivedSessionPurgeParticipantPhase.PENDING,
            )
            return _ArchivedSessionPurgeJobSummary(
                completed=False,
                retry_scheduled=True,
                model_file_count=0,
                artifact_count=0,
                exchange_file_count=0,
                worktree_count=0,
            )

        context = SessionLifecyclePurgeContext(
            purge_job_id=job.id,
            lease_owner=lease_owner,
            root_session_id=job.root_session_id,
            subtree_session_ids=tuple(session_ids),
        )
        await self.lifecycle_orchestrator.run_purge_phase(
            session_manager=self.session_manager,
            retention_repository=self.retention_repository,
            context=context,
            phase=ArchivedSessionPurgeParticipantPhase.PREPARED,
            operation=self._prepare_purge_participant,
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
        cleanup_state = _PurgeFileCleanupState(
            model_files=model_files,
            artifacts=artifacts,
            exchange_files=exchange_files,
            model_file_count=model_file_count,
            artifact_count=artifact_count,
            exchange_file_count=exchange_file_count,
        )
        worktree_count = 0

        async def cleanup_participant(
            participant: SessionLifecycleParticipantDefinition,
        ) -> dict[str, object] | None:
            nonlocal worktree_count
            match participant.key:
                case "session.broker-state":
                    for session_id in session_ids:
                        await self.broker.purge_session_state(session_id)
                    return {"purged_session_count": len(session_ids)}
                case "session.model-files":
                    await self._delete_file_blobs(
                        model_files=cleanup_state.model_files,
                        artifacts=[],
                        exchange_files=[],
                    )
                    return {"model_file_count": cleanup_state.model_file_count}
                case "session.artifacts":
                    await self._delete_file_blobs(
                        model_files=[],
                        artifacts=cleanup_state.artifacts,
                        exchange_files=[],
                    )
                    return {"artifact_count": cleanup_state.artifact_count}
                case "session.exchange-files":
                    await self._delete_file_blobs(
                        model_files=[],
                        artifacts=[],
                        exchange_files=cleanup_state.exchange_files,
                    )
                    return {"exchange_file_count": cleanup_state.exchange_file_count}
                case "session.git-worktrees":
                    run_worktree_cleanup = (
                        self.session_git_worktree_service.run_cleanup_for_root_tree
                    )
                    worktree_count = await run_worktree_cleanup(
                        agent_id=root_session.agent_id,
                        root_session_id=job.root_session_id,
                        subtree_session_ids=session_ids,
                    )
                    return {"worktree_count": worktree_count}
                case _:
                    return None

        await self.lifecycle_orchestrator.run_purge_phase(
            session_manager=self.session_manager,
            retention_repository=self.retention_repository,
            context=context,
            phase=ArchivedSessionPurgeParticipantPhase.CLEANUP_COMPLETED,
            operation=cleanup_participant,
        )
        async with self.session_manager() as session:
            marked = await self.retention_repository.mark_purge_cleaning(
                session,
                job_id=job.id,
                lease_owner=lease_owner,
                model_file_count=model_file_count,
                artifact_count=artifact_count,
                exchange_file_count=exchange_file_count,
                worktree_count=worktree_count,
                now=datetime.datetime.now(datetime.UTC),
            )
        if not marked:
            raise RuntimeError("Archived-session purge lease was lost")

        async def verify_participant(
            participant: SessionLifecycleParticipantDefinition,
        ) -> dict[str, object] | None:
            match participant.key:
                case "session.model-files":
                    async with self.session_manager() as session:
                        files = await self.model_file_repository.list_for_session_ids(
                            session,
                            session_ids=session_ids,
                        )
                    if any(
                        file.status is not ModelFileStatus.DELETED
                        or file.blob_deleted_at is None
                        for file in files
                    ):
                        raise RuntimeError("ModelFile purge cleanup is incomplete")
                    return {"model_file_count": len(files)}
                case "session.artifacts":
                    async with self.session_manager() as session:
                        artifacts = await self.artifact_repository.list_for_session_ids(
                            session,
                            session_ids=session_ids,
                        )
                    if any(
                        artifact.status is not ArtifactStatus.EXPIRED
                        or artifact.blob_deleted_at is None
                        for artifact in artifacts
                    ):
                        raise RuntimeError("Artifact purge cleanup is incomplete")
                    return {"artifact_count": len(artifacts)}
                case "session.exchange-files":
                    async with self.session_manager() as session:
                        files = (
                            await self.exchange_file_repository.list_for_retention_root(
                                session,
                                retention_root_session_id=job.root_session_id,
                            )
                        )
                    if any(
                        file.status is not ExchangeFileStatus.EXPIRED
                        or file.blob_deleted_at is None
                        for file in files
                    ):
                        raise RuntimeError("ExchangeFile purge cleanup is incomplete")
                    return {"exchange_file_count": len(files)}
                case _:
                    return None

        await self.lifecycle_orchestrator.run_purge_phase(
            session_manager=self.session_manager,
            retention_repository=self.retention_repository,
            context=context,
            phase=ArchivedSessionPurgeParticipantPhase.VERIFIED,
            operation=verify_participant,
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
            final_root_session = next(
                (item for item in final_sessions if item.id == job.root_session_id),
                None,
            )
            if (
                final_root_session is None
                or final_root_session.status is not AgentSessionStatus.ARCHIVED
            ):
                raise RuntimeError("Purge root session is no longer archived")
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
            await self.lifecycle_finalizer_repository.finalize_purged_root_tree(
                session,
                root_session_id=job.root_session_id,
                session_ids=session_ids,
            )
            completed = await self.retention_repository.complete_purge_job(
                session,
                job_id=job.id,
                lease_owner=lease_owner,
                now=datetime.datetime.now(datetime.UTC),
            )
            if not completed:
                raise RuntimeError("Archived-session purge lease was lost")

        return _ArchivedSessionPurgeJobSummary(
            completed=True,
            retry_scheduled=False,
            model_file_count=len(model_files),
            artifact_count=len(artifacts),
            exchange_file_count=len(exchange_files),
            worktree_count=worktree_count,
        )

    async def _prepare_purge_participant(
        self,
        participant: SessionLifecycleParticipantDefinition,
    ) -> dict[str, object] | None:
        """Record that a fenced participant is ready for cleanup."""
        del participant
        return None

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
        error_participant_key: str | None,
        error_phase: ArchivedSessionPurgeParticipantPhase | None,
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
                error_participant_key=error_participant_key,
                error_phase=error_phase,
                now=now,
            )
