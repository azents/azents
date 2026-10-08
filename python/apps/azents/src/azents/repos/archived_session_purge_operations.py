"""Completed archive purge database groups and restrictive finalization."""

import dataclasses
import datetime
from typing import Annotated

from azcommon.uuid import uuid7
from fastapi import Depends

from azents.core.archived_session_purge_data import (
    ArchivedSessionPurgeJobSummary,
    PurgeClaim,
    PurgeFileCleanupState,
    PurgeRootPreparation,
)
from azents.core.enums import (
    AgentSessionRunState,
    AgentSessionStatus,
    ArchivedSessionPurgeParticipantPhase,
    ArtifactStatus,
    ExchangeFileStatus,
    ModelFileStatus,
)
from azents.core.session_lifecycle import (
    SessionLifecycleParticipantDefinition,
    SessionLifecyclePurgeContext,
)
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.archived_session_retention.data import ArchivedSessionPurgeJob
from azents.repos.artifact import ArtifactRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.external_channel_lifecycle_participant import (
    ExternalChannelLifecycleParticipantRepository,
)
from azents.repos.hierarchy_contention import retry_hierarchy_operation
from azents.repos.lifecycle_target import LifecycleTargetRepository
from azents.repos.model_file import ModelFileRepository
from azents.repos.scheduled_task_lifecycle_participant import (
    ScheduledTaskLifecycleParticipantRepository,
)
from azents.repos.session_lifecycle_finalizer import SessionLifecycleFinalizerRepository
from azents.repos.session_lifecycle_purge_operations import (
    SessionLifecyclePurgeOperations,
)

_LEASE_DURATION = datetime.timedelta(minutes=15)
_MAX_RETRY_DELAY = datetime.timedelta(minutes=30)
_STALE_JOB_RECONCILIATION_LIMIT = 100


@dataclasses.dataclass
class ArchivedSessionPurgeOperations:
    """Own native archive preparation, checkpoints and finalization scopes."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    retention_repository: Annotated[
        ArchivedSessionRetentionRepository,
        Depends(ArchivedSessionRetentionRepository),
    ]
    lifecycle_target_repository: Annotated[
        LifecycleTargetRepository, Depends(LifecycleTargetRepository)
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
    read_only_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    lifecycle_operations: Annotated[
        SessionLifecyclePurgeOperations, Depends(SessionLifecyclePurgeOperations)
    ]
    scheduled_participant: Annotated[
        ScheduledTaskLifecycleParticipantRepository,
        Depends(ScheduledTaskLifecycleParticipantRepository),
    ]
    external_participant: Annotated[
        ExternalChannelLifecycleParticipantRepository,
        Depends(ExternalChannelLifecycleParticipantRepository),
    ]

    async def cancel_invalid_jobs(self, *, now: datetime.datetime) -> int:
        """Complete bounded stale unstarted job reconciliation."""
        async with self.session_manager() as session:
            return await self.retention_repository.cancel_invalid_unstarted_purge_jobs(
                session, now=now, limit=_STALE_JOB_RECONCILIATION_LIMIT
            )

    async def claim(self, *, now: datetime.datetime, lease_owner: str) -> PurgeClaim:
        """Commit claim and immutable participant materialization together."""
        materialization_error: RuntimeError | ValueError | None = None
        async with self.session_manager() as session:
            job = await self.retention_repository.claim_due_purge_job(
                session,
                now=now,
                lease_owner=lease_owner,
                lease_until=now + _LEASE_DURATION,
            )
            if job is not None:
                try:
                    lifecycle_operations = self.lifecycle_operations
                    materialize = (
                        lifecycle_operations.materialize_claimed_purge_participants
                    )
                    await materialize(
                        session,
                        retention_repository=self.retention_repository,
                        purge_job_id=job.id,
                        lease_owner=lease_owner,
                    )
                except (RuntimeError, ValueError) as error:
                    materialization_error = error
        return PurgeClaim(job=job, materialization_error=materialization_error)

    @retry_hierarchy_operation
    async def prepare_root(
        self, *, job: ArchivedSessionPurgeJob, lease_owner: str, now: datetime.datetime
    ) -> PurgeRootPreparation:
        """Fence root ownership and record stop requests before broker publication."""
        async with self.session_manager() as session:
            sessions = await self.lifecycle_target_repository.lock_target_sessions(
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
                return PurgeRootPreparation(
                    terminal=ArchivedSessionPurgeJobSummary(
                        completed=completed,
                        retry_scheduled=False,
                        model_file_count=0,
                        artifact_count=0,
                        exchange_file_count=0,
                        worktree_count=0,
                    ),
                    session_ids=(),
                    active=False,
                    preserve_scheduled=False,
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
                await self.lifecycle_target_repository.fence_purge_owner_generations(
                    session,
                    session_ids=session_ids,
                )
            )
            if fenced_count != len(session_ids):
                raise RuntimeError("Purge root tree ownership fence is incomplete")
            active = await self.agent_run_repository.has_active_for_session_ids(
                session,
                session_ids=session_ids,
            )
            scheduled_lifecycle = self.scheduled_participant
            preserve_scheduled = (
                active
                and await scheduled_lifecycle.archive_allows_active_runs(
                    session,
                    session_ids=session_ids,
                    running_session_ids=[
                        item.id
                        for item in sessions
                        if item.run_state is AgentSessionRunState.RUNNING
                    ],
                )
            )
            if not preserve_scheduled:
                for session_id in session_ids:
                    await self.lifecycle_target_repository.request_stop(
                        session,
                        session_id=session_id,
                        stop_request_id=uuid7().hex,
                        stop_requester_user_id=None,
                    )

        return PurgeRootPreparation(
            terminal=None,
            session_ids=tuple(session_ids),
            active=active,
            preserve_scheduled=preserve_scheduled,
        )

    async def prepare_files(
        self,
        *,
        root_session_id: str,
        session_ids: tuple[str, ...],
        now: datetime.datetime,
    ) -> PurgeFileCleanupState:
        """Expire and reload all root file metadata as one native mutation group."""
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
                    retention_root_session_id=root_session_id,
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
                retention_root_session_id=root_session_id,
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
                    retention_root_session_id=root_session_id,
                )
            )

        return PurgeFileCleanupState(
            model_files=model_files,
            artifacts=artifacts,
            exchange_files=exchange_files,
            model_file_count=model_file_count,
            artifact_count=artifact_count,
            exchange_file_count=exchange_file_count,
        )

    @retry_hierarchy_operation
    async def finalize(
        self,
        *,
        job: ArchivedSessionPurgeJob,
        lease_owner: str,
        session_ids: tuple[str, ...],
        context: SessionLifecyclePurgeContext,
        worktree_count: int,
    ) -> ArchivedSessionPurgeJobSummary:
        """Verify participants and delete root metadata under current fences."""
        async with self.session_manager() as session:
            final_sessions = (
                await self.lifecycle_target_repository.lock_target_sessions(
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
            participant_executions = (
                await self.retention_repository.list_purge_participant_executions(
                    session,
                    job_id=job.id,
                )
            )
            scheduled_task_execution = next(
                (
                    execution
                    for execution in participant_executions
                    if execution.participant_key == "session.scheduled-task"
                ),
                None,
            )
            if scheduled_task_execution is not None:
                scheduled_task_participant = (
                    self.lifecycle_operations.registry.require_policy_version(
                        key=scheduled_task_execution.participant_key,
                        policy_version=scheduled_task_execution.policy_version,
                    )
                )
                await self.scheduled_participant.finalize_purge_participant(
                    session,
                    scheduled_task_participant,
                    context,
                )
            external_channel_execution = next(
                (
                    execution
                    for execution in participant_executions
                    if execution.participant_key == "session.external-channel"
                ),
                None,
            )
            if external_channel_execution is not None:
                external_channel_participant = (
                    self.lifecycle_operations.registry.require_policy_version(
                        key=external_channel_execution.participant_key,
                        policy_version=external_channel_execution.policy_version,
                    )
                )
                await self.external_participant.finalize_purge_participant(
                    session,
                    external_channel_participant,
                    context,
                )
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
                session_ids=list(session_ids),
            )
            completed = await self.retention_repository.complete_purge_job(
                session,
                job_id=job.id,
                lease_owner=lease_owner,
                now=datetime.datetime.now(datetime.UTC),
            )
            if not completed:
                raise RuntimeError("Archived-session purge lease was lost")

        return ArchivedSessionPurgeJobSummary(
            completed=True,
            retry_scheduled=False,
            model_file_count=len(model_files),
            artifact_count=len(artifacts),
            exchange_file_count=len(exchange_files),
            worktree_count=worktree_count,
        )

    async def prepare_participant(
        self,
        participant: SessionLifecycleParticipantDefinition,
        *,
        context: SessionLifecyclePurgeContext,
    ) -> dict[str, object] | None:
        """Complete one DB participant preparation with detached safe summary."""
        if participant.key == "session.scheduled-task":
            async with self.session_manager() as session:
                summary = await self.scheduled_participant.prepare_purge_participant(
                    session,
                    participant,
                    context,
                )
            return (
                self.scheduled_participant.summary_dict(summary)
                if summary is not None
                else None
            )
        if participant.key != "session.external-channel":
            return None
        async with self.session_manager() as session:
            summary = await self.external_participant.prepare_purge_participant(
                session,
                participant,
                context,
            )
        return summary.model_dump() if summary is not None else None

    async def cleanup_participant(
        self,
        participant: SessionLifecycleParticipantDefinition,
        *,
        context: SessionLifecyclePurgeContext,
    ) -> dict[str, object] | None:
        """Complete one cleanup database participant operation."""
        if participant.key == "session.scheduled-task":
            async with self.session_manager() as session:
                scheduled_summary = (
                    await self.scheduled_participant.cleanup_purge_participant(
                        session, participant, context
                    )
                )
            return (
                None
                if scheduled_summary is None
                else self.scheduled_participant.summary_dict(scheduled_summary)
            )
        async with self.session_manager() as session:
            external_summary = (
                await self.external_participant.cleanup_purge_participant(
                    session, participant, context
                )
            )
        return None if external_summary is None else external_summary.model_dump()

    async def verify_participant(
        self,
        participant: SessionLifecycleParticipantDefinition,
        *,
        context: SessionLifecyclePurgeContext,
    ) -> dict[str, object] | None:
        """Complete one verify database participant operation."""
        if participant.key == "session.scheduled-task":
            async with self.session_manager() as session:
                scheduled_summary = (
                    await self.scheduled_participant.verify_purge_participant(
                        session, participant, context
                    )
                )
            return (
                None
                if scheduled_summary is None
                else self.scheduled_participant.summary_dict(scheduled_summary)
            )
        async with self.session_manager() as session:
            external_summary = await self.external_participant.verify_purge_participant(
                session, participant, context
            )
        return None if external_summary is None else external_summary.model_dump()

    async def verify_files(
        self, *, kind: str, context: SessionLifecyclePurgeContext
    ) -> dict[str, object]:
        """Observe terminal file completion before restrictive finalization."""
        async with self.read_only_session_manager() as session:
            if kind == "session.model-files":
                files = await self.model_file_repository.list_for_session_ids(
                    session, session_ids=context.subtree_session_ids
                )
                if any(
                    file.status is not ModelFileStatus.DELETED
                    or file.blob_deleted_at is None
                    for file in files
                ):
                    raise RuntimeError("ModelFile purge cleanup is incomplete")
                return {"model_file_count": len(files)}
            if kind == "session.artifacts":
                artifacts = await self.artifact_repository.list_for_session_ids(
                    session, session_ids=context.subtree_session_ids
                )
                if any(
                    file.status is not ArtifactStatus.EXPIRED
                    or file.blob_deleted_at is None
                    for file in artifacts
                ):
                    raise RuntimeError("Artifact purge cleanup is incomplete")
                return {"artifact_count": len(artifacts)}
            exchange_files = (
                await self.exchange_file_repository.list_for_retention_root(
                    session, retention_root_session_id=context.root_session_id
                )
            )
            if any(
                file.status is not ExchangeFileStatus.EXPIRED
                or file.blob_deleted_at is None
                for file in exchange_files
            ):
                raise RuntimeError("ExchangeFile purge cleanup is incomplete")
            return {"exchange_file_count": len(exchange_files)}

    async def retry(
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

    async def mark_cleaning(
        self,
        *,
        job_id: str,
        lease_owner: str,
        model_file_count: int,
        artifact_count: int,
        exchange_file_count: int,
        worktree_count: int,
        now: datetime.datetime,
    ) -> bool:
        """Commit the completed purge-cleaning counts under the exact lease."""
        async with self.session_manager() as session:
            return await self.retention_repository.mark_purge_cleaning(
                session,
                job_id=job_id,
                lease_owner=lease_owner,
                model_file_count=model_file_count,
                artifact_count=artifact_count,
                exchange_file_count=exchange_file_count,
                worktree_count=worktree_count,
                now=now,
            )
