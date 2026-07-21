"""ArchivedSessionRetentionService tests."""

import datetime

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionStatus,
    ArchivedSessionPurgeParticipantPhase,
    ArchivedSessionPurgeStatus,
    ArchivedSessionRetentionApplicationStatus,
    LLMProvider,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.archived_session_retention import (
    RDBArchivedSessionPurgeJob,
    RDBArchivedSessionPurgeParticipantExecution,
    RDBArchivedSessionRetentionApplication,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.archived_session_retention.data import (
    ArchivedSessionPurgeParticipantSnapshot,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.services.archived_session_retention import (
    ArchivedSessionRetentionService,
    RetentionApplicationInProgress,
    RetentionRevisionConflict,
)
from azents.testing.model_selection import make_test_model_selection_dict


def _service(
    session_manager: SessionManager[AsyncSession],
) -> ArchivedSessionRetentionService:
    return ArchivedSessionRetentionService(
        repository=ArchivedSessionRetentionRepository(),
        session_manager=session_manager,
    )


async def _create_user(session: AsyncSession, suffix: str) -> str:
    user = await UserRepository().create(
        session,
        UserCreate(email=f"retention-{suffix}@example.com"),
    )
    return user.id


async def _create_archived_root(
    session: AsyncSession,
    *,
    suffix: str,
    archived_at: datetime.datetime,
) -> str:
    workspace_result = await WorkspaceRepository().create(
        session,
        WorkspaceCreate(
            name=f"Retention {suffix}",
            handle=f"retention-{suffix}",
        ),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await WorkspaceRepository().resolve_id(
        session,
        f"retention-{suffix}",
    )
    assert workspace_id is not None
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"retention-{suffix}",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()
    model_selection = make_test_model_selection_dict(
        integration_id=integration.id,
        provider=LLMProvider.ANTHROPIC,
        model_identifier=f"retention-{suffix}",
    )
    agent = RDBAgent(
        workspace_id=workspace_id,
        name=f"Retention {suffix}",
        model_selection=model_selection,
        lightweight_model_selection=model_selection,
    )
    session.add(agent)
    await session.flush()
    created = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=agent.id,
            title=None,
        ),
    )
    await session.execute(
        sa.update(RDBAgentSession)
        .where(RDBAgentSession.id == created.id)
        .values(
            status=AgentSessionStatus.ARCHIVED,
            archived_at=archived_at,
            purge_after=archived_at + datetime.timedelta(days=30),
            archive_policy_revision=1,
            archive_retention_days_snapshot=30,
            ended_at=archived_at,
        )
    )
    return created.id


async def test_default_settings_and_future_only_revision_update(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    service = _service(rdb_session_manager)
    async with rdb_session_manager() as session:
        user_id = await _create_user(session, "default")

    initial = await service.get_settings()
    updated = await service.update_settings(
        expected_revision=initial.revision,
        retention_days=None,
        application_scope="new_archives_only",
        user_id=user_id,
    )

    assert initial.archived_session_retention_days == 30
    assert updated.settings.archived_session_retention_days is None
    assert updated.settings.revision == initial.revision + 1
    assert updated.application is None


async def test_preview_and_recalculation_skip_started_purge(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    service = _service(rdb_session_manager)
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        user_id = await _create_user(session, "recalculate")
        overdue_id = await _create_archived_root(
            session,
            suffix="overdue",
            archived_at=now - datetime.timedelta(days=10),
        )
        started_id = await _create_archived_root(
            session,
            suffix="started",
            archived_at=now - datetime.timedelta(days=1),
        )
        started_job = RDBArchivedSessionPurgeJob(
            root_session_id=started_id,
            eligible_at=now + datetime.timedelta(days=29),
            policy_revision=1,
        )
        started_job.status = ArchivedSessionPurgeStatus.FENCING
        started_job.fencing_started_at = now
        session.add(started_job)

    preview = await service.preview(5)
    initial = await service.get_settings()
    update = await service.update_settings(
        expected_revision=initial.revision,
        retention_days=5,
        application_scope="recalculate_existing",
        user_id=user_id,
    )
    summary = await service.recalculate_once(lease_owner="retention-test")

    assert preview.affected_count == 1
    assert preview.immediately_eligible_count == 1
    assert preview.scheduled_count == 1
    assert preview.excluded_count == 1
    assert update.application is not None
    assert summary.application_id == update.application.id
    assert summary.affected_count == 1
    assert summary.immediately_eligible_count == 1
    assert summary.skipped_count == 1
    assert summary.completed
    async with rdb_session_manager() as session:
        overdue = await session.get(RDBAgentSession, overdue_id)
        started = await session.get(RDBAgentSession, started_id)
        job = await session.scalar(
            sa.select(RDBArchivedSessionPurgeJob).where(
                RDBArchivedSessionPurgeJob.root_session_id == overdue_id
            )
        )
        application = await session.get(
            RDBArchivedSessionRetentionApplication,
            update.application.id,
        )
        assert overdue is not None
        assert overdue.archived_at is not None
        assert started is not None
        assert job is not None
        assert application is not None
        assert overdue.purge_after == overdue.archived_at + datetime.timedelta(days=5)
        assert overdue.archive_policy_revision == initial.revision + 1
        assert job.status == ArchivedSessionPurgeStatus.PENDING
        assert job.eligible_at == overdue.purge_after
        assert started.archive_policy_revision == 1
        assert application.status == ArchivedSessionRetentionApplicationStatus.COMPLETED
        assert application.skipped_count == 1


async def test_recalculation_to_unlimited_cancels_pending_job(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    service = _service(rdb_session_manager)
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        user_id = await _create_user(session, "unlimited")
        session_id = await _create_archived_root(
            session,
            suffix="unlimited",
            archived_at=now - datetime.timedelta(days=2),
        )
        session.add(
            RDBArchivedSessionPurgeJob(
                root_session_id=session_id,
                eligible_at=now + datetime.timedelta(days=28),
                policy_revision=1,
            )
        )

    initial = await service.get_settings()
    update = await service.update_settings(
        expected_revision=initial.revision,
        retention_days=None,
        application_scope="recalculate_existing",
        user_id=user_id,
    )
    summary = await service.recalculate_once(lease_owner="retention-test")

    assert update.application is not None
    assert summary.cancelled_count == 1
    async with rdb_session_manager() as session:
        archived = await session.get(RDBAgentSession, session_id)
        job = await session.scalar(
            sa.select(RDBArchivedSessionPurgeJob).where(
                RDBArchivedSessionPurgeJob.root_session_id == session_id
            )
        )
        assert archived is not None
        assert job is not None
        assert archived.purge_after is None
        assert archived.archive_retention_days_snapshot is None
        assert job.status == ArchivedSessionPurgeStatus.CANCELLED
        assert job.cancelled_at is not None


async def test_invalid_unstarted_purge_jobs_are_cancelled_in_bounded_batches(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Stale schedule identities become observable cancelled tombstones."""
    repository = ArchivedSessionRetentionRepository()
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        stale_root_id = await _create_archived_root(
            session,
            suffix="stale-purge-job",
            archived_at=now - datetime.timedelta(days=1),
        )
        valid_root_id = await _create_archived_root(
            session,
            suffix="valid-purge-job",
            archived_at=now - datetime.timedelta(days=1),
        )
        stale_root = await session.get(RDBAgentSession, stale_root_id)
        valid_root = await session.get(RDBAgentSession, valid_root_id)
        assert stale_root is not None
        assert stale_root.purge_after is not None
        assert valid_root is not None
        assert valid_root.purge_after is not None
        session.add_all(
            [
                RDBArchivedSessionPurgeJob(
                    root_session_id=stale_root_id,
                    eligible_at=stale_root.purge_after,
                    policy_revision=2,
                ),
                RDBArchivedSessionPurgeJob(
                    root_session_id=valid_root_id,
                    eligible_at=valid_root.purge_after,
                    policy_revision=1,
                ),
            ]
        )

    async with rdb_session_manager() as session:
        cancelled_count = await repository.cancel_invalid_unstarted_purge_jobs(
            session,
            now=now,
            limit=100,
        )

    assert cancelled_count == 1
    async with rdb_session_manager() as session:
        jobs = list(
            (
                await session.scalars(
                    sa.select(RDBArchivedSessionPurgeJob).where(
                        RDBArchivedSessionPurgeJob.root_session_id.in_(
                            (stale_root_id, valid_root_id)
                        )
                    )
                )
            ).all()
        )
    jobs_by_root = {job.root_session_id: job for job in jobs}
    assert jobs_by_root[stale_root_id].status is ArchivedSessionPurgeStatus.CANCELLED
    assert jobs_by_root[stale_root_id].last_error_kind == "InvalidRootSchedule"
    assert jobs_by_root[valid_root_id].status is ArchivedSessionPurgeStatus.PENDING


async def test_purge_job_claim_respects_lease_and_reclaims_after_expiry(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Only one worker owns a valid due purge job until its lease expires."""
    repository = ArchivedSessionRetentionRepository()
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        root_session_id = await _create_archived_root(
            session,
            suffix="purge-lease",
            archived_at=now - datetime.timedelta(days=31),
        )
        root = await session.get(RDBAgentSession, root_session_id)
        assert root is not None
        assert root.purge_after is not None
        session.add(
            RDBArchivedSessionPurgeJob(
                root_session_id=root_session_id,
                eligible_at=root.purge_after,
                policy_revision=1,
            )
        )

    lease_until = now + datetime.timedelta(minutes=1)
    async with rdb_session_manager() as session:
        first = await repository.claim_due_purge_job(
            session,
            now=now,
            lease_owner="purge-worker-1",
            lease_until=lease_until,
        )
    assert first is not None
    assert first.status is ArchivedSessionPurgeStatus.FENCING
    assert first.fencing_started_at is not None
    assert first.attempt_count == 1

    async with rdb_session_manager() as session:
        blocked = await repository.claim_due_purge_job(
            session,
            now=now + datetime.timedelta(seconds=30),
            lease_owner="purge-worker-2",
            lease_until=now + datetime.timedelta(minutes=2),
        )
    assert blocked is None

    reclaimed_at = lease_until + datetime.timedelta(seconds=1)
    async with rdb_session_manager() as session:
        reclaimed = await repository.claim_due_purge_job(
            session,
            now=reclaimed_at,
            lease_owner="purge-worker-2",
            lease_until=reclaimed_at + datetime.timedelta(minutes=1),
        )
    assert reclaimed is not None
    assert reclaimed.id == first.id
    assert reclaimed.attempt_count == 2
    assert reclaimed.lease_owner == "purge-worker-2"
    assert reclaimed.fencing_started_at == first.fencing_started_at


async def test_purge_retry_completion_and_tombstone_survive_root_delete(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Retry state is durable and completion survives the final DB cascade."""
    repository = ArchivedSessionRetentionRepository()
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        root_session_id = await _create_archived_root(
            session,
            suffix="purge-tombstone",
            archived_at=now - datetime.timedelta(days=31),
        )
        root = await session.get(RDBAgentSession, root_session_id)
        assert root is not None
        assert root.purge_after is not None
        session.add(
            RDBArchivedSessionPurgeJob(
                root_session_id=root_session_id,
                eligible_at=root.purge_after,
                policy_revision=1,
            )
        )

    async with rdb_session_manager() as session:
        claimed = await repository.claim_due_purge_job(
            session,
            now=now,
            lease_owner="purge-worker-1",
            lease_until=now + datetime.timedelta(minutes=1),
        )
        assert claimed is not None
        retry_at = now + datetime.timedelta(minutes=5)
        await repository.mark_purge_retry(
            session,
            job_id=claimed.id,
            lease_owner="purge-worker-1",
            next_attempt_at=retry_at,
            error_kind="S3Unavailable",
            error_summary="Object cleanup failed.",
            error_participant_key=None,
            error_phase=None,
            now=now,
        )

    async with rdb_session_manager() as session:
        too_early = await repository.claim_due_purge_job(
            session,
            now=retry_at - datetime.timedelta(seconds=1),
            lease_owner="purge-worker-2",
            lease_until=retry_at + datetime.timedelta(minutes=1),
        )
    assert too_early is None

    async with rdb_session_manager() as session:
        retried = await repository.claim_due_purge_job(
            session,
            now=retry_at,
            lease_owner="purge-worker-2",
            lease_until=retry_at + datetime.timedelta(minutes=1),
        )
        assert retried is not None
        marked = await repository.mark_purge_cleaning(
            session,
            job_id=retried.id,
            lease_owner="purge-worker-2",
            model_file_count=2,
            artifact_count=3,
            exchange_file_count=4,
            worktree_count=5,
            now=retry_at,
        )
        assert marked is True
        await AgentSessionRepository().delete_by_id(session, root_session_id)
        completed = await repository.complete_purge_job(
            session,
            job_id=retried.id,
            lease_owner="purge-worker-2",
            now=retry_at,
        )
        assert completed is True

    async with rdb_session_manager() as session:
        root = await session.get(RDBAgentSession, root_session_id)
        tombstone = await session.get(RDBArchivedSessionPurgeJob, retried.id)
    assert root is None
    assert tombstone is not None
    assert tombstone.status is ArchivedSessionPurgeStatus.COMPLETED
    assert tombstone.completed_at == retry_at
    assert tombstone.model_file_count == 2
    assert tombstone.artifact_count == 3
    assert tombstone.exchange_file_count == 4
    assert tombstone.worktree_count == 5
    assert tombstone.last_error_kind is None
    assert tombstone.last_error_summary is None
    assert tombstone.last_error_participant_key is None
    assert tombstone.last_error_phase is None


async def test_purge_participant_snapshot_and_progress_are_durable(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Fencing materializes immutable participant versions with durable checkpoints."""
    repository = ArchivedSessionRetentionRepository()
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        root_session_id = await _create_archived_root(
            session,
            suffix="purge-participant-progress",
            archived_at=now - datetime.timedelta(days=31),
        )
        root = await session.get(RDBAgentSession, root_session_id)
        assert root is not None
        assert root.purge_after is not None
        session.add(
            RDBArchivedSessionPurgeJob(
                root_session_id=root_session_id,
                eligible_at=root.purge_after,
                policy_revision=1,
            )
        )

    async with rdb_session_manager() as session:
        claimed = await repository.claim_due_purge_job(
            session,
            now=now,
            lease_owner="purge-worker-1",
            lease_until=now + datetime.timedelta(minutes=1),
        )
        assert claimed is not None
        executions = await repository.materialize_purge_participant_executions(
            session,
            job_id=claimed.id,
            lease_owner="purge-worker-1",
            participants=(
                ArchivedSessionPurgeParticipantSnapshot(
                    participant_key="session.execution",
                    policy_version=1,
                ),
                ArchivedSessionPurgeParticipantSnapshot(
                    participant_key="session.git-worktrees",
                    policy_version=1,
                ),
            ),
        )
        assert [execution.participant_key for execution in executions] == [
            "session.execution",
            "session.git-worktrees",
        ]
        assert all(
            execution.phase is ArchivedSessionPurgeParticipantPhase.PENDING
            for execution in executions
        )

        started = await repository.start_purge_participant_attempt(
            session,
            job_id=claimed.id,
            lease_owner="purge-worker-1",
            participant_key="session.git-worktrees",
            now=now,
        )
        blocked = await repository.mark_purge_participant_blocked(
            session,
            job_id=claimed.id,
            lease_owner="purge-worker-1",
            participant_key="session.git-worktrees",
            blocked_by_participant_key="session.execution",
            now=now,
        )
        checkpointed = await repository.checkpoint_purge_participant(
            session,
            job_id=claimed.id,
            lease_owner="purge-worker-1",
            participant_key="session.execution",
            phase=ArchivedSessionPurgeParticipantPhase.PREPARED,
            operational_summary={"prepared_count": 2},
            now=now,
        )
        failed = await repository.record_purge_participant_failure(
            session,
            job_id=claimed.id,
            lease_owner="purge-worker-1",
            participant_key="session.git-worktrees",
            phase=ArchivedSessionPurgeParticipantPhase.PENDING,
            error_kind="RunnerUnavailable",
            error_summary="Runner cleanup is temporarily unavailable.",
            now=now,
        )
        assert started is True
        assert blocked is True
        assert checkpointed is True
        assert failed is True

    async with rdb_session_manager() as session:
        execution_rows = list(
            (
                await session.scalars(
                    sa.select(RDBArchivedSessionPurgeParticipantExecution).where(
                        RDBArchivedSessionPurgeParticipantExecution.purge_job_id
                        == claimed.id
                    )
                )
            ).all()
        )
        job = await session.get(RDBArchivedSessionPurgeJob, claimed.id)
        assert job is not None
        assert job.last_error_participant_key == "session.git-worktrees"
        assert job.last_error_phase is ArchivedSessionPurgeParticipantPhase.PENDING
        by_key = {row.participant_key: row for row in execution_rows}
        assert by_key["session.execution"].phase is (
            ArchivedSessionPurgeParticipantPhase.PREPARED
        )
        assert by_key["session.execution"].operational_summary == {"prepared_count": 2}
        assert by_key["session.git-worktrees"].attempt_count == 1
        assert by_key["session.git-worktrees"].blocked_by_participant_key == (
            "session.execution"
        )
        assert by_key["session.git-worktrees"].last_error_kind == "RunnerUnavailable"

    async with rdb_session_manager() as session:
        with pytest.raises(RuntimeError, match="snapshot is immutable"):
            await repository.materialize_purge_participant_executions(
                session,
                job_id=claimed.id,
                lease_owner="purge-worker-1",
                participants=(
                    ArchivedSessionPurgeParticipantSnapshot(
                        participant_key="session.execution",
                        policy_version=2,
                    ),
                ),
            )


async def test_revision_and_active_application_conflicts(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    service = _service(rdb_session_manager)
    async with rdb_session_manager() as session:
        user_id = await _create_user(session, "conflict")

    initial = await service.get_settings()
    with pytest.raises(RetentionRevisionConflict):
        await service.update_settings(
            expected_revision=initial.revision + 1,
            retention_days=10,
            application_scope="new_archives_only",
            user_id=user_id,
        )
    first = await service.update_settings(
        expected_revision=initial.revision,
        retention_days=10,
        application_scope="recalculate_existing",
        user_id=user_id,
    )
    assert first.application is not None
    with pytest.raises(RetentionApplicationInProgress):
        await service.update_settings(
            expected_revision=first.settings.revision,
            retention_days=20,
            application_scope="new_archives_only",
            user_id=user_id,
        )
