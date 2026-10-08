"""Durable archived-session purge workflow."""

import asyncio
import dataclasses
import datetime
import logging
from typing import Annotated

from azcommon.infra.s3.service import S3Service
from fastapi import Depends

from azents.broker.deps import get_broker
from azents.broker.types import SessionBroker, SessionStopSignal
from azents.core.archived_session_purge_data import ArchivedSessionPurgeJobSummary
from azents.core.config import Config, require_workspace_s3_bucket
from azents.core.deps import get_config
from azents.core.enums import (
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
from azents.core.session_lifecycle_purge import (
    SessionLifecyclePurgeParticipantFailure,
    SessionLifecyclePurgeSnapshotValidationFailure,
)
from azents.repos.archived_session_purge_operations import (
    ArchivedSessionPurgeOperations,
)
from azents.repos.archived_session_retention.data import ArchivedSessionPurgeJob
from azents.repos.artifact.data import Artifact
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.file_lifecycle_cleanup_operations import (
    FileLifecycleCleanupOperations,
)
from azents.repos.model_file.data import ModelFile
from azents.services.session_lifecycle.orchestrator import SessionLifecycleOrchestrator
from azents.services.session_lifecycle.registry import (
    get_session_lifecycle_orchestrator,
)

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


@dataclasses.dataclass
class ArchivedSessionPurgeService:
    """Fence and purge a bounded batch of archived SessionAgent trees."""

    operations: Annotated[
        ArchivedSessionPurgeOperations, Depends(ArchivedSessionPurgeOperations)
    ]
    file_operations: Annotated[
        FileLifecycleCleanupOperations, Depends(FileLifecycleCleanupOperations)
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
        stale_job_count = await self.operations.cancel_invalid_jobs(now=now)

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
            claim = await self.operations.claim(now=now, lease_owner=lease_owner)
            job = claim.job
            materialization_error = claim.materialization_error
            if job is None:
                break
            claimed_count += 1

            try:
                if materialization_error is not None:
                    raise materialization_error
                job_summary = await self._purge_claimed(
                    job=job,
                    lease_owner=lease_owner,
                )
            except asyncio.CancelledError:
                raise
            except SessionLifecyclePurgeSnapshotValidationFailure as exc:
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
                    "Archived-session purge participant snapshot is invalid; "
                    "retry scheduled",
                    extra={
                        "purge_job_id": job.id,
                        "root_session_id": job.root_session_id,
                        "participant_key": exc.participant_key,
                        "phase": exc.phase,
                        "attempt_count": job.attempt_count,
                    },
                )
                continue
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
    ) -> ArchivedSessionPurgeJobSummary:
        now = datetime.datetime.now(datetime.UTC)
        preparation = await self.operations.prepare_root(
            job=job, lease_owner=lease_owner, now=now
        )
        if preparation.terminal is not None:
            return preparation.terminal
        session_ids = preparation.session_ids
        active = preparation.active
        preserve_scheduled = preparation.preserve_scheduled

        if not preserve_scheduled:
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
            return ArchivedSessionPurgeJobSummary(
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

        async def prepare_participant(
            participant: SessionLifecycleParticipantDefinition,
        ) -> dict[str, object] | None:
            return await self._prepare_purge_participant(
                participant,
                context=context,
            )

        await self.lifecycle_orchestrator.run_purge_phase(
            context=context,
            phase=ArchivedSessionPurgeParticipantPhase.PREPARED,
            operation=prepare_participant,
        )

        cleanup_state = await self.operations.prepare_files(
            root_session_id=job.root_session_id, session_ids=session_ids, now=now
        )
        model_file_count = cleanup_state.model_file_count
        artifact_count = cleanup_state.artifact_count
        exchange_file_count = cleanup_state.exchange_file_count
        worktree_count = 0

        async def cleanup_participant(
            participant: SessionLifecycleParticipantDefinition,
        ) -> dict[str, object] | None:
            match participant.key:
                case "session.scheduled-task" | "session.external-channel":
                    return await self.operations.cleanup_participant(
                        participant, context=context
                    )
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
                    return {"cleanup_owner": "archive_best_effort"}
                case _:
                    return None

        await self.lifecycle_orchestrator.run_purge_phase(
            context=context,
            phase=ArchivedSessionPurgeParticipantPhase.CLEANUP_COMPLETED,
            operation=cleanup_participant,
        )
        marked = await self.operations.mark_cleaning(
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
            if participant.key in {
                "session.scheduled-task",
                "session.external-channel",
            }:
                return await self.operations.verify_participant(
                    participant, context=context
                )
            if participant.key in {
                "session.model-files",
                "session.artifacts",
                "session.exchange-files",
            }:
                return await self.operations.verify_files(
                    kind=participant.key, context=context
                )
            return None

        await self.lifecycle_orchestrator.run_purge_phase(
            context=context,
            phase=ArchivedSessionPurgeParticipantPhase.VERIFIED,
            operation=verify_participant,
        )

        return await self.operations.finalize(
            job=job,
            lease_owner=lease_owner,
            session_ids=session_ids,
            context=context,
            worktree_count=worktree_count,
        )

    async def _prepare_purge_participant(
        self,
        participant: SessionLifecycleParticipantDefinition,
        *,
        context: SessionLifecyclePurgeContext,
    ) -> dict[str, object] | None:
        """Sequence one completed participant preparation before cleanup."""
        return await self.operations.prepare_participant(participant, context=context)

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
                bucket=require_workspace_s3_bucket(self.config.workspace_s3),
                key=item.storage_key,
            )
            await self.file_operations.settle_model_file(
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
                bucket=require_workspace_s3_bucket(self.config.workspace_s3),
                key=item.storage_key,
            )
            await self.file_operations.settle_artifact(
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
                bucket=require_workspace_s3_bucket(self.config.workspace_s3),
                key=item.object_key,
            )
            await self.file_operations.settle_exchange_file(
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
        """Sequence a completed lease-bound retry operation."""
        await self.operations.retry(
            job_id=job_id,
            lease_owner=lease_owner,
            attempt_count=attempt_count,
            error_kind=error_kind,
            error_summary=error_summary,
            error_participant_key=error_participant_key,
            error_phase=error_phase,
        )
