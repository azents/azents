"""Archived-session purge workflow tests."""

import datetime
import logging
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from azcommon.infra.s3.service import S3Service
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.types import SessionBroker, SessionStopSignal
from azents.core.config import Config
from azents.core.enums import (
    AgentSessionKind,
    AgentSessionStartReason,
    AgentSessionStatus,
    ArchivedSessionPurgeParticipantPhase,
    ArchivedSessionPurgeStatus,
    ArtifactStatus,
    ExchangeFileOrigin,
    ExchangeFileStatus,
    ModelFileStatus,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.archived_session_retention.data import (
    ArchivedSessionPurgeJob,
    ArchivedSessionPurgeParticipantExecution,
    ArchivedSessionPurgeParticipantSnapshot,
)
from azents.repos.artifact import ArtifactRepository
from azents.repos.artifact.data import Artifact
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.model_file import ModelFileRepository
from azents.repos.model_file.data import ModelFile
from azents.services.archived_session_purge import ArchivedSessionPurgeService
from azents.services.session_git_worktree import SessionGitWorktreeService
from azents.services.session_lifecycle.registry import (
    get_session_lifecycle_orchestrator,
    get_session_lifecycle_registry,
)


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession, None]:
    """Yield a placeholder transaction for repository doubles."""
    yield cast(AsyncSession, object())


class _RetentionRepository:
    """Durable purge job repository double."""

    def __init__(
        self,
        job: ArchivedSessionPurgeJob | None,
        events: list[str],
    ) -> None:
        self.job = job
        self.additional_jobs: list[ArchivedSessionPurgeJob] = []
        self.events = events
        self.retry: dict[str, object] | None = None
        self.completed = False
        self.stale_job_count = 0
        self.materialized_participants: list[
            ArchivedSessionPurgeParticipantSnapshot
        ] = []
        self.participant_executions: list[ArchivedSessionPurgeParticipantExecution] = []

    async def cancel_invalid_unstarted_purge_jobs(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        limit: int,
    ) -> int:
        del session, now, limit
        self.events.append("reconcile")
        return self.stale_job_count

    async def claim_due_purge_job(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        lease_owner: str,
        lease_until: datetime.datetime,
    ) -> ArchivedSessionPurgeJob | None:
        del session, now, lease_owner, lease_until
        self.events.append("claim")
        if self.job is not None:
            job = self.job
            self.job = None
            return job
        if self.additional_jobs:
            return self.additional_jobs.pop(0)
        return None

    async def mark_purge_cleaning(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        model_file_count: int,
        artifact_count: int,
        exchange_file_count: int,
        worktree_count: int,
        now: datetime.datetime,
    ) -> bool:
        del (
            session,
            job_id,
            lease_owner,
            model_file_count,
            artifact_count,
            exchange_file_count,
            worktree_count,
            now,
        )
        self.events.append("mark_cleaning")
        return True

    async def materialize_purge_participant_executions(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        participants: tuple[ArchivedSessionPurgeParticipantSnapshot, ...],
    ) -> list[object]:
        del session, job_id, lease_owner
        self.events.append("materialize_participants")
        self.materialized_participants = list(participants)
        now = datetime.datetime.now(datetime.UTC)
        self.participant_executions = [
            ArchivedSessionPurgeParticipantExecution(
                purge_job_id="job-1",
                participant_key=participant.participant_key,
                policy_version=participant.policy_version,
                phase=ArchivedSessionPurgeParticipantPhase.PENDING,
                attempt_count=0,
                blocked_by_participant_key=None,
                last_error_kind=None,
                last_error_summary=None,
                operational_summary=None,
                prepared_at=None,
                cleanup_completed_at=None,
                verified_at=None,
                last_attempt_at=None,
                created_at=now,
                updated_at=now,
            )
            for participant in participants
        ]
        return list(self.participant_executions)

    async def list_purge_participant_executions(
        self,
        session: AsyncSession,
        *,
        job_id: str,
    ) -> list[ArchivedSessionPurgeParticipantExecution]:
        del session, job_id
        return list(self.participant_executions)

    async def start_purge_participant_attempt(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        participant_key: str,
        now: datetime.datetime,
    ) -> bool:
        del session, job_id, lease_owner, now
        self.events.append(f"start:{participant_key}")
        return True

    async def mark_purge_participant_blocked(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        participant_key: str,
        blocked_by_participant_key: str,
        now: datetime.datetime,
    ) -> bool:
        del session, job_id, lease_owner
        del participant_key, blocked_by_participant_key, now
        return True

    async def checkpoint_purge_participant(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        participant_key: str,
        phase: ArchivedSessionPurgeParticipantPhase,
        operational_summary: dict[str, object] | None,
        now: datetime.datetime,
    ) -> bool:
        del session, job_id, lease_owner, now
        self.events.append(f"checkpoint:{participant_key}:{phase}")
        self.participant_executions = [
            execution.model_copy(
                update={
                    "phase": phase,
                    "operational_summary": operational_summary,
                }
            )
            if execution.participant_key == participant_key
            else execution
            for execution in self.participant_executions
        ]
        return True

    async def record_purge_participant_failure(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        participant_key: str,
        phase: ArchivedSessionPurgeParticipantPhase,
        error_kind: str,
        error_summary: str,
        now: datetime.datetime,
    ) -> bool:
        del session, job_id, lease_owner, now
        self.events.append(f"failure:{participant_key}:{phase}")
        self.retry = {
            "error_kind": error_kind,
            "error_summary": error_summary,
            "error_participant_key": participant_key,
            "error_phase": phase,
        }
        return True

    async def mark_purge_retry(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        next_attempt_at: datetime.datetime,
        error_kind: str,
        error_summary: str,
        error_participant_key: str | None,
        error_phase: ArchivedSessionPurgeParticipantPhase | None,
        now: datetime.datetime,
    ) -> None:
        del session, job_id, lease_owner, now
        self.events.append("retry")
        self.retry = {
            "next_attempt_at": next_attempt_at,
            "error_kind": error_kind,
            "error_summary": error_summary,
            "error_participant_key": error_participant_key,
            "error_phase": error_phase,
        }

    async def complete_purge_job(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_owner: str,
        now: datetime.datetime,
    ) -> bool:
        del session, job_id, lease_owner, now
        self.events.append("complete")
        self.completed = True
        return True


class _AgentSessionRepository:
    """AgentSession repository double for one purge subtree."""

    def __init__(self, sessions: list[AgentSession], events: list[str]) -> None:
        self.sessions = sessions
        self.events = events
        self.deleted = False
        self.lock_calls = 0
        self.final_sessions: list[AgentSession] | None = None

    async def lock_root_tree_sessions(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
    ) -> list[AgentSession]:
        del session, root_session_id
        self.lock_calls += 1
        if self.deleted:
            return []
        if self.lock_calls > 1 and self.final_sessions is not None:
            return list(self.final_sessions)
        return list(self.sessions)

    async def fence_archived_owner_generations(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> int:
        del session
        fenced = 0
        for item in self.sessions:
            if (
                item.id not in session_ids
                or item.status is not AgentSessionStatus.ARCHIVED
            ):
                continue
            item.owner_generation += 1
            fenced += 1
        self.events.append("fence_generations")
        return fenced

    async def request_stop(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        stop_request_id: str,
        user_id: str | None,
    ) -> AgentSession | None:
        del session, stop_request_id, user_id
        self.events.append(f"stop:{session_id}")
        return next(item for item in self.sessions if item.id == session_id)

    async def delete_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> None:
        del session, agent_session_id
        self.events.append("delete_session")
        self.deleted = True


class _AgentRunRepository:
    """AgentRun activity repository double."""

    def __init__(self, active_checks: Sequence[bool]) -> None:
        self.active_checks = list(active_checks)

    async def has_active_for_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> bool:
        del session, session_ids
        return self.active_checks.pop(0) if self.active_checks else False


class _ModelFileRepository:
    """ModelFile lifecycle repository double."""

    def __init__(
        self,
        files: list[ModelFile],
        events: list[str],
        *,
        pinned_ids: set[str] | None = None,
    ) -> None:
        self.files = files
        self.events = events
        self.pinned_ids = pinned_ids or set()

    async def list_for_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> list[ModelFile]:
        del session, session_ids
        return list(self.files)

    async def mark_deleted_for_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
        deleted_at: datetime.datetime,
    ) -> list[ModelFile]:
        del session, session_ids
        marked: list[ModelFile] = []
        for item in self.files:
            if item.id in self.pinned_ids or item.status is ModelFileStatus.DELETED:
                continue
            item.status = ModelFileStatus.DELETED
            item.deleted_at = deleted_at
            marked.append(item)
        return marked

    async def mark_blob_deleted(
        self,
        session: AsyncSession,
        *,
        model_file_id: str,
        blob_deleted_at: datetime.datetime,
    ) -> None:
        del session
        item = next(file for file in self.files if file.id == model_file_id)
        item.blob_deleted_at = blob_deleted_at

    async def delete_purged_for_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> int:
        del session, session_ids
        deleted = [
            item
            for item in self.files
            if item.status is ModelFileStatus.DELETED
            and item.blob_deleted_at is not None
        ]
        self.events.append("delete_model_metadata")
        self.files = [item for item in self.files if item not in deleted]
        return len(deleted)


class _ArtifactRepository:
    """Artifact lifecycle repository double."""

    def __init__(self, artifacts: list[Artifact], events: list[str]) -> None:
        self.artifacts = artifacts
        self.events = events

    async def list_for_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> list[Artifact]:
        del session, session_ids
        return list(self.artifacts)

    async def expire_for_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
        expired_at: datetime.datetime,
    ) -> list[Artifact]:
        del session, session_ids
        for item in self.artifacts:
            item.status = ArtifactStatus.EXPIRED
            item.expired_at = expired_at
        return list(self.artifacts)

    async def mark_blob_deleted(
        self,
        session: AsyncSession,
        *,
        artifact_id: str,
        blob_deleted_at: datetime.datetime,
    ) -> None:
        del session
        item = next(
            artifact for artifact in self.artifacts if artifact.id == artifact_id
        )
        item.blob_deleted_at = blob_deleted_at

    async def delete_purged_for_session_ids(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
    ) -> int:
        del session, session_ids
        deleted = [
            item
            for item in self.artifacts
            if item.status is ArtifactStatus.EXPIRED
            and item.blob_deleted_at is not None
        ]
        self.events.append("delete_artifact_metadata")
        self.artifacts = [item for item in self.artifacts if item not in deleted]
        return len(deleted)


class _ExchangeFileRepository:
    """ExchangeFile lifecycle repository double."""

    def __init__(self, files: list[ExchangeFile], events: list[str]) -> None:
        self.files = files
        self.events = events

    async def list_for_retention_root(
        self,
        session: AsyncSession,
        *,
        retention_root_session_id: str,
    ) -> list[ExchangeFile]:
        del session, retention_root_session_id
        return list(self.files)

    async def expire_for_retention_root(
        self,
        session: AsyncSession,
        *,
        retention_root_session_id: str,
        expired_at: datetime.datetime,
    ) -> list[ExchangeFile]:
        del session, retention_root_session_id
        for item in self.files:
            item.status = ExchangeFileStatus.EXPIRED
            item.expired_at = expired_at
        return list(self.files)

    async def mark_blob_deleted(
        self,
        session: AsyncSession,
        *,
        file_id: str,
        blob_deleted_at: datetime.datetime,
    ) -> None:
        del session
        item = next(file for file in self.files if file.id == file_id)
        item.blob_deleted_at = blob_deleted_at

    async def delete_purged_for_retention_root(
        self,
        session: AsyncSession,
        *,
        retention_root_session_id: str,
    ) -> int:
        del session, retention_root_session_id
        deleted = [
            item
            for item in self.files
            if item.status is ExchangeFileStatus.EXPIRED
            and item.blob_deleted_at is not None
        ]
        self.events.append("delete_exchange_metadata")
        self.files = [item for item in self.files if item not in deleted]
        return len(deleted)


class _WorktreeService:
    """Root-tree worktree cleanup double."""

    def __init__(self, events: list[str], *, count: int = 0) -> None:
        self.events = events
        self.count = count
        self.calls = 0

    async def run_cleanup_for_root_tree(
        self,
        *,
        agent_id: str,
        root_session_id: str,
        subtree_session_ids: Sequence[str],
    ) -> int:
        del agent_id, root_session_id, subtree_session_ids
        self.calls += 1
        self.events.append("cleanup_worktrees")
        return self.count


class _Broker:
    """Session broker cleanup double."""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.purged_session_ids: list[str] = []

    async def send_message(self, message: SessionStopSignal) -> None:
        self.events.append(f"signal:{message.session_id}")

    async def purge_session_state(self, session_id: str) -> None:
        self.events.append(f"purge_broker:{session_id}")
        self.purged_session_ids.append(session_id)


class _S3Service:
    """Object deletion double."""

    def __init__(self, events: list[str], *, fail_key: str | None = None) -> None:
        self.events = events
        self.fail_key = fail_key
        self.deleted_keys: list[str] = []

    async def delete(self, bucket: str, key: str) -> None:
        del bucket
        self.events.append(f"delete_blob:{key}")
        if key == self.fail_key:
            self.fail_key = None
            raise RuntimeError("object delete failed")
        self.deleted_keys.append(key)


def _job(now: datetime.datetime) -> ArchivedSessionPurgeJob:
    return ArchivedSessionPurgeJob(
        id="job-1",
        root_session_id="root-session",
        eligible_at=now,
        policy_revision=1,
        status=ArchivedSessionPurgeStatus.FENCING,
        fencing_started_at=now,
        attempt_count=1,
        lease_owner="worker-1",
        lease_until=now + datetime.timedelta(minutes=15),
        next_attempt_at=None,
        last_error_kind=None,
        last_error_summary=None,
        last_error_participant_key=None,
        last_error_phase=None,
        model_file_count=0,
        artifact_count=0,
        exchange_file_count=0,
        worktree_count=0,
        started_at=now,
        last_attempt_at=now,
        cancelled_at=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )


def _deadline() -> datetime.datetime:
    """Return a scheduler deadline with enough room for test jobs."""
    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5)


def _agent_session(
    session_id: str,
    *,
    kind: AgentSessionKind,
    now: datetime.datetime,
) -> AgentSession:
    return AgentSession(
        id=session_id,
        workspace_id="workspace-1",
        agent_id="agent-1",
        handle=session_id,
        inference_state=None,
        session_kind=kind,
        status=AgentSessionStatus.ARCHIVED,
        start_reason=AgentSessionStartReason.INITIAL,
        title=None,
        title_source=None,
        title_generated_at=None,
        title_generation_event_id=None,
        last_user_input_at=now,
        started_at=now,
        owner_generation=1,
        archived_at=now,
        purge_after=now,
        archive_policy_revision=1,
        archive_retention_days_snapshot=0,
        created_at=now,
        updated_at=now,
    )


def _model_file(now: datetime.datetime) -> ModelFile:
    return ModelFile(
        id="model-file-1",
        workspace_id="workspace-1",
        session_id="root-session",
        agent_id="agent-1",
        name="model.bin",
        media_type="application/octet-stream",
        kind="file",
        size_bytes=3,
        created_run_index=1,
        storage_key="model-key",
        status=ModelFileStatus.AVAILABLE,
        normalized_format="raw",
        sha256="a" * 64,
        created_at=now,
    )


def _artifact(now: datetime.datetime) -> Artifact:
    return Artifact(
        id="artifact-1",
        workspace_id="workspace-1",
        session_id="child-session",
        agent_id="agent-1",
        created_run_id="run-1",
        created_run_index=1,
        expires_at=now + datetime.timedelta(days=1),
        name="artifact.bin",
        media_type="application/octet-stream",
        size_bytes=4,
        storage_key="artifact-key",
        status=ArtifactStatus.AVAILABLE,
        created_at=now,
    )


def _exchange_file(now: datetime.datetime) -> ExchangeFile:
    return ExchangeFile(
        id="exchange-file-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        origin_type=ExchangeFileOrigin.UPLOAD,
        status=ExchangeFileStatus.AVAILABLE,
        object_key="exchange-key",
        filename="exchange.bin",
        media_type="application/octet-stream",
        size_bytes=5,
        sha256="b" * 64,
        created_by_user_id="user-1",
        retention_root_session_id="root-session",
        retention_bound_at=now,
        expires_at=now + datetime.timedelta(days=1),
        created_at=now,
    )


def _build_service(
    *,
    events: list[str],
    active_checks: Sequence[bool],
    pinned_model_file: bool = False,
    s3_fail_key: str | None = None,
) -> tuple[
    ArchivedSessionPurgeService,
    _RetentionRepository,
    _AgentSessionRepository,
    _ModelFileRepository,
    _WorktreeService,
    _Broker,
    _S3Service,
]:
    now = datetime.datetime.now(datetime.UTC)
    retention_repository = _RetentionRepository(_job(now), events)
    agent_session_repository = _AgentSessionRepository(
        [
            _agent_session("root-session", kind=AgentSessionKind.ROOT, now=now),
            _agent_session("child-session", kind=AgentSessionKind.SUBAGENT, now=now),
        ],
        events,
    )
    model_file_repository = _ModelFileRepository(
        [_model_file(now)],
        events,
        pinned_ids={"model-file-1"} if pinned_model_file else set(),
    )
    artifact_repository = _ArtifactRepository([_artifact(now)], events)
    exchange_file_repository = _ExchangeFileRepository([_exchange_file(now)], events)
    worktree_service = _WorktreeService(events, count=2)
    broker = _Broker(events)
    s3_service = _S3Service(events, fail_key=s3_fail_key)
    service = ArchivedSessionPurgeService(
        session_manager=cast(SessionManager[AsyncSession], _session_manager),
        retention_repository=cast(
            ArchivedSessionRetentionRepository,
            retention_repository,
        ),
        agent_session_repository=cast(
            AgentSessionRepository,
            agent_session_repository,
        ),
        agent_run_repository=cast(
            AgentRunRepository,
            _AgentRunRepository(active_checks),
        ),
        model_file_repository=cast(ModelFileRepository, model_file_repository),
        artifact_repository=cast(ArtifactRepository, artifact_repository),
        exchange_file_repository=cast(
            ExchangeFileRepository,
            exchange_file_repository,
        ),
        session_git_worktree_service=cast(
            SessionGitWorktreeService,
            worktree_service,
        ),
        broker=cast(SessionBroker, broker),
        s3_service=cast(S3Service, s3_service),
        config=cast(
            Config,
            SimpleNamespace(workspace_s3=SimpleNamespace(bucket="test-bucket")),
        ),
        lifecycle_orchestrator=get_session_lifecycle_orchestrator(),
    )
    return (
        service,
        retention_repository,
        agent_session_repository,
        model_file_repository,
        worktree_service,
        broker,
        s3_service,
    )


async def test_purge_reconciles_stale_unstarted_jobs_before_claiming() -> None:
    """Scheduler passes cancel stale unstarted work even when nothing is due."""
    events: list[str] = []
    service, retention_repository, *_ = _build_service(
        events=events,
        active_checks=[],
    )
    retention_repository.job = None
    retention_repository.stale_job_count = 2

    summary = await service.purge_once(
        lease_owner="worker-1",
        deadline=_deadline(),
    )

    assert summary.claimed_count == 0
    assert summary.stale_job_count == 2
    assert events[:2] == ["reconcile", "claim"]


async def test_purge_materializes_participants_before_subtree_fencing() -> None:
    """A claimed job persists the active participant set before cleanup begins."""
    events: list[str] = []
    service, retention_repository, *_ = _build_service(
        events=events,
        active_checks=[],
    )

    await service.purge_once(
        lease_owner="worker-1",
        deadline=_deadline(),
    )

    assert events.index("materialize_participants") < events.index("fence_generations")
    assert retention_repository.materialized_participants == [
        ArchivedSessionPurgeParticipantSnapshot(
            participant_key=participant.key,
            policy_version=participant.policy_version,
        )
        for participant in get_session_lifecycle_registry().participants
    ]


async def test_purge_stops_before_claiming_near_scheduler_deadline() -> None:
    """A pass does not claim another root without cleanup time remaining."""
    events: list[str] = []
    service, *_ = _build_service(
        events=events,
        active_checks=[],
    )

    summary = await service.purge_once(
        lease_owner="worker-1",
        deadline=datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=20),
    )

    assert summary.claimed_count == 0
    assert summary.deadline_reached is True
    assert events == ["reconcile"]


async def test_purge_deletes_external_resources_before_session_tree() -> None:
    """Successful purge cleans external resources before the DB cascade."""
    events: list[str] = []
    (
        service,
        retention_repository,
        agent_session_repository,
        _,
        worktree_service,
        broker,
        s3_service,
    ) = _build_service(events=events, active_checks=[False, False])

    summary = await service.purge_once(
        lease_owner="worker-1",
        deadline=_deadline(),
    )

    assert summary.claimed_count == 1
    assert summary.completed_count == 1
    assert summary.retry_scheduled_count == 0
    assert summary.failed_count == 0
    assert summary.model_file_count == 1
    assert summary.artifact_count == 1
    assert summary.exchange_file_count == 1
    assert summary.worktree_count == 2
    assert retention_repository.completed is True
    assert agent_session_repository.deleted is True
    assert all(item.owner_generation == 2 for item in agent_session_repository.sessions)
    assert worktree_service.calls == 1
    assert broker.purged_session_ids == ["root-session", "child-session"]
    assert s3_service.deleted_keys == ["model-key", "artifact-key", "exchange-key"]
    session_delete_index = events.index("delete_session")
    assert events.index("fence_generations") < events.index("signal:root-session")
    assert events.index("cleanup_worktrees") < session_delete_index
    assert events.index("delete_blob:model-key") < session_delete_index
    assert events.index("delete_blob:artifact-key") < session_delete_index
    assert events.index("delete_blob:exchange-key") < session_delete_index
    assert events.index("complete") > session_delete_index


async def test_active_run_schedules_retry_before_external_cleanup() -> None:
    """Unexpected active work remains fenced and retries without deletion."""
    events: list[str] = []
    (
        service,
        retention_repository,
        agent_session_repository,
        _,
        worktree_service,
        broker,
        s3_service,
    ) = _build_service(events=events, active_checks=[True])

    summary = await service.purge_once(
        lease_owner="worker-1",
        deadline=_deadline(),
    )

    assert summary.completed_count == 0
    assert summary.retry_scheduled_count == 1
    assert summary.failed_count == 0
    assert retention_repository.retry is not None
    assert retention_repository.retry["error_kind"] == "ActiveAgentRun"
    assert agent_session_repository.deleted is False
    assert worktree_service.calls == 0
    assert broker.purged_session_ids == []
    assert s3_service.deleted_keys == []


async def test_object_delete_failure_preserves_tree_for_retry() -> None:
    """Object-storage failure leaves terminal metadata and the tree retryable."""
    events: list[str] = []
    (
        service,
        retention_repository,
        agent_session_repository,
        model_file_repository,
        _,
        _,
        s3_service,
    ) = _build_service(
        events=events,
        active_checks=[False],
        s3_fail_key="model-key",
    )

    summary = await service.purge_once(
        lease_owner="worker-1",
        deadline=_deadline(),
    )

    assert summary.claimed_count == 1
    assert summary.completed_count == 0
    assert summary.retry_scheduled_count == 1
    assert summary.failed_count == 1
    assert retention_repository.retry is not None
    assert retention_repository.retry["error_kind"] == "RuntimeError"
    assert retention_repository.retry["error_participant_key"] == "session.model-files"
    assert (
        retention_repository.retry["error_phase"]
        is ArchivedSessionPurgeParticipantPhase.CLEANUP_COMPLETED
    )
    assert agent_session_repository.deleted is False
    assert model_file_repository.files[0].status is ModelFileStatus.DELETED
    assert model_file_repository.files[0].blob_deleted_at is None
    assert s3_service.deleted_keys == []
    assert "delete_session" not in events


async def test_pinned_model_file_is_not_deleted_and_blocks_finalization() -> None:
    """A stale active-run pin protects its blob and keeps purge retryable."""
    events: list[str] = []
    (
        service,
        retention_repository,
        agent_session_repository,
        model_file_repository,
        _,
        _,
        s3_service,
    ) = _build_service(
        events=events,
        active_checks=[False],
        pinned_model_file=True,
    )

    summary = await service.purge_once(
        lease_owner="worker-1",
        deadline=_deadline(),
    )

    assert summary.claimed_count == 1
    assert summary.completed_count == 0
    assert summary.retry_scheduled_count == 1
    assert summary.failed_count == 1
    assert retention_repository.retry is not None
    assert retention_repository.retry["error_kind"] == "RuntimeError"
    assert "ModelFile purge cleanup is incomplete" in str(
        retention_repository.retry["error_summary"]
    )
    assert agent_session_repository.deleted is False
    assert model_file_repository.files[0].status is ModelFileStatus.AVAILABLE
    assert model_file_repository.files[0].blob_deleted_at is None
    assert "model-key" not in s3_service.deleted_keys
    assert "delete_blob:model-key" not in events


async def test_finalization_rejects_changed_subtree_boundary() -> None:
    """Final deletion re-locks and rejects a changed subtree boundary."""
    events: list[str] = []
    (
        service,
        retention_repository,
        agent_session_repository,
        _,
        _,
        _,
        _,
    ) = _build_service(events=events, active_checks=[False])
    agent_session_repository.final_sessions = [
        item for item in agent_session_repository.sessions if item.id == "root-session"
    ]

    summary = await service.purge_once(
        lease_owner="worker-1",
        deadline=_deadline(),
    )

    assert summary.claimed_count == 1
    assert summary.completed_count == 0
    assert summary.retry_scheduled_count == 1
    assert summary.failed_count == 1
    assert retention_repository.retry is not None
    assert retention_repository.retry["error_kind"] == "RuntimeError"
    assert agent_session_repository.deleted is False
    assert "delete_session" not in events


async def test_job_failure_logs_and_continues_to_next_due_job(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One failed root is retried without blocking the next due root."""
    events: list[str] = []
    (
        service,
        retention_repository,
        agent_session_repository,
        _,
        _,
        _,
        s3_service,
    ) = _build_service(
        events=events,
        active_checks=[False, False, False],
        s3_fail_key="model-key",
    )
    second_job = _job(datetime.datetime.now(datetime.UTC)).model_copy(
        update={"id": "job-2"}
    )
    retention_repository.additional_jobs.append(second_job)

    with caplog.at_level(
        logging.ERROR,
        logger="azents.services.archived_session_purge",
    ):
        summary = await service.purge_once(
            lease_owner="worker-1",
            deadline=_deadline(),
        )

    assert summary.claimed_count == 2
    assert summary.completed_count == 1
    assert summary.retry_scheduled_count == 1
    assert summary.failed_count == 1
    assert retention_repository.completed is True
    assert agent_session_repository.deleted is True
    assert s3_service.deleted_keys == [
        "model-key",
        "artifact-key",
        "exchange-key",
    ]
    assert events.count("claim") == 3
    failure_record = next(
        record
        for record in caplog.records
        if record.message == "Archived-session purge job failed; retry scheduled"
    )
    assert failure_record.__dict__["purge_job_id"] == "job-1"
    assert failure_record.__dict__["root_session_id"] == "root-session"
