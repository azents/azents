"""ArchivedSessionRetentionService tests."""

import datetime

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionStatus,
    ArchivedSessionPurgeStatus,
    ArchivedSessionRetentionApplicationStatus,
    LLMProvider,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.archived_session_retention import (
    RDBArchivedSessionPurgeJob,
    RDBArchivedSessionRetentionApplication,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
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
