"""Real common lifecycle targets and retained internal execution records."""

import datetime
from typing import NamedTuple

import pytest
import sqlalchemy as sa
from azcommon.uuid import uuid7

from azents.core.enums import AgentSessionRunState, AgentSessionStatus, EventKind
from azents.core.session_lifecycle import (
    SessionArchiveMutation,
    SessionLifecycleTransitionContext,
)
from azents.core.session_lifecycle_registry import get_session_lifecycle_registry
from azents.engine.events.types import UserMessagePayload
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.archived_session_retention import (
    RDBArchivedSessionPurgeJob,
    RDBSystemFileLifecycleSetting,
)
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.session_execution_file import RDBSessionExecutionFile
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.external_channel.lifecycle import ExternalChannelLifecycleRepository
from azents.repos.lifecycle_target import LifecycleTargetRepository
from azents.repos.scheduled_task.lifecycle import ScheduledTaskLifecycleRepository
from azents.repos.session_archive_operations import SessionArchiveOperations
from azents.repos.session_diagnostics import SessionDiagnosticRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError
from azents.repos.session_lifecycle_finalizer import SessionLifecycleFinalizerRepository
from azents.repos.session_lifecycle_operations import (
    SessionLifecycleOperationsRepository,
)
from azents.services.archived_session_retention_test import _create_root


class SeededInternalSession(NamedTuple):
    """Exact common execution identity and scope for lifecycle test setup."""

    session_id: str
    workspace_id: str


def lifecycle_pipeline() -> SessionLifecycleOperationsRepository:
    """Compose the exact common archive policy and related-resource handlers."""
    return SessionLifecycleOperationsRepository(
        registry=get_session_lifecycle_registry(),
        agent_session_repository=AgentSessionRepository(),
        lifecycle_target_repository=LifecycleTargetRepository(),
        retention_repository=ArchivedSessionRetentionRepository(),
        external_channel_repository=ExternalChannelLifecycleRepository.create(),
        scheduled_task_repository=ScheduledTaskLifecycleRepository.create(),
    )


async def seed_internal_session(
    session: WriteSession, *, suffix: str
) -> SeededInternalSession:
    """Create real common execution data without a Conversation or SessionAgent."""
    public_id = await _create_root(session, suffix=suffix)
    public = await session.read_session.get(RDBAgentSession, public_id)
    assert public is not None
    session_id = await session.write_session.scalar(
        sa.insert(RDBAgentSession)
        .values(
            id=uuid7().hex,
            agent_id=public.agent_id,
            workspace_id=public.workspace_id,
            lifecycle_root_session_id=None,
        )
        .returning(RDBAgentSession.id)
    )
    assert session_id is not None
    await session.write_session.flush()
    return SeededInternalSession(session_id, public.workspace_id)


@pytest.mark.parametrize("retention_days", [None, 7])
async def test_internal_archive_retains_files_events_and_uses_shared_policy(
    rdb_session_manager: SessionManager[WriteSession], retention_days: int | None
) -> None:
    """Finite/Unlimited policy applies without public-root placeholders."""
    target = LifecycleTargetRepository()
    retention = ArchivedSessionRetentionRepository()
    now = datetime.datetime.now(datetime.UTC)
    async with rdb_session_manager() as session:
        session_id, workspace_id = await seed_internal_session(
            session, suffix="common-retained"
        )
        settings = await retention.get_settings(session)
        await session.write_session.execute(
            sa.update(RDBSystemFileLifecycleSetting)
            .where(RDBSystemFileLifecycleSetting.id == 1)
            .values(archived_session_retention_days=retention_days)
        )
        session.write_session.add(
            RDBSessionExecutionFile(
                session_id=session_id,
                path="summaries/session.md",
                content="Retained original prepared summary.",
                writable=False,
            )
        )
        event = RDBEvent(
            session_id=session_id,
            kind=EventKind.USER_MESSAGE,
            payload=UserMessagePayload(
                sender_user_id=None,
                content="Inspect retained execution input.",
                attachments=[],
                metadata={},
                requested_inference_profile=None,
                applied_inference_profile=None,
            ).model_dump(mode="json"),
        )
        session.write_session.add(event)
        await session.write_session.flush()
        event_id = event.id
        members = await target.lock_target_sessions(session, root_session_id=session_id)
        assert [item.id for item in members] == [session_id]
        policy = await target.resolve_retention(
            session, retention_repository=retention, archived_at=now
        )
        assert policy.policy_revision == settings.revision
        assert policy.retention_days == retention_days
        await lifecycle_pipeline().archive(
            session,
            SessionArchiveMutation(
                context=SessionLifecycleTransitionContext(
                    transition_id=uuid7().hex,
                    root_session_id=session_id,
                    subtree_session_ids=(session_id,),
                ),
                archived_at=now,
            ),
        )
    diagnostic = SessionDiagnosticRepository(session_manager=rdb_session_manager)
    metadata = await diagnostic.metadata(
        session_id=session_id, workspace_id=workspace_id
    )
    assert metadata is not None and metadata.status is AgentSessionStatus.ARCHIVED
    page = await diagnostic.events(
        session_id=session_id, workspace_id=workspace_id, after=None, limit=1
    )
    assert page is not None and page.items[0].event_id == event_id
    file = await diagnostic.file(
        session_id=session_id,
        workspace_id=workspace_id,
        path="summaries/session.md",
        offset=0,
        limit=100,
    )
    assert file is not None and file.content == "Retained original prepared summary."
    async with rdb_session_manager() as session:
        assert await session.read_session.get(RDBConversation, session_id) is None
        job = await session.read_session.scalar(
            sa.select(RDBArchivedSessionPurgeJob).where(
                RDBArchivedSessionPurgeJob.root_session_id == session_id
            )
        )
        assert (job is None) is (retention_days is None)
        if retention_days is not None:
            assert job is not None and job.eligible_at == now + datetime.timedelta(
                days=7
            )
        # Rootless internal targets must be real deletion targets, not empty trees.
        await SessionLifecycleFinalizerRepository().finalize_purged_root_tree(
            session, root_session_id=session_id, session_ids=[session_id]
        )
        assert await session.read_session.get(RDBAgentSession, session_id) is None
        assert await session.read_session.get(RDBEvent, event_id) is None
        assert (
            await session.read_session.get(
                RDBSessionExecutionFile, (session_id, "summaries/session.md")
            )
            is None
        )
        if job is not None:
            assert (
                await session.read_session.get(RDBArchivedSessionPurgeJob, job.id)
                is not None
            )


async def test_common_target_membership_and_owner_fence_include_internal(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Common group collection includes no-Conversation children and fences all."""
    target = LifecycleTargetRepository()
    async with rdb_session_manager() as session:
        root_id, _ = await seed_internal_session(session, suffix="common-owner")
        child_id, _ = await seed_internal_session(session, suffix="common-child")
        root = await session.read_session.get(RDBAgentSession, root_id)
        assert root is not None
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == child_id)
            .values(
                lifecycle_root_session_id=root_id,
                agent_id=root.agent_id,
                workspace_id=root.workspace_id,
                run_state=AgentSessionRunState.RUNNING,
            )
        )
        members = await target.lock_target_sessions(session, root_session_id=root_id)
        assert {item.id for item in members} == {root_id, child_id}
        assert (
            await target.lock_target_sessions(session, root_session_id=child_id) == []
        )
        before = {item.id: item.owner_generation for item in members}
        count = await target.fence_purge_owner_generations(
            session, session_ids=(root_id, child_id)
        )
        assert count == 2
        await target.request_stop(
            session,
            session_id=child_id,
            stop_request_id="s" * 32,
            stop_requester_user_id=None,
        )
        await session.write_session.flush()
        child = await session.read_session.get(RDBAgentSession, child_id)
        assert child is not None and child.stop_requested_at is not None
        members = await target.lock_target_sessions(session, root_session_id=root_id)
        assert all(item.owner_generation == before[item.id] + 1 for item in members)


async def test_common_archive_rejects_stale_owner_and_active_execution(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Common terminal archival cannot discard an active or replaced execution."""
    async with rdb_session_manager() as session:
        session_id, _ = await seed_internal_session(session, suffix="archive-admission")
    operations = SessionArchiveOperations(
        session_manager=rdb_session_manager,
        targets=LifecycleTargetRepository(),
        run_repository=AgentRunRepository(),
        lifecycle=lifecycle_pipeline(),
    )
    with pytest.raises(CanonicalExecutionOwnerGenerationStaleError):
        await operations.archive(
            root_session_id=session_id, expected_owner_generation=1
        )
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(run_state=AgentSessionRunState.RUNNING)
        )
    with pytest.raises(ValueError, match="still active"):
        await operations.archive(
            root_session_id=session_id, expected_owner_generation=0
        )
    async with rdb_session_manager() as session:
        root = await session.read_session.get(RDBAgentSession, session_id)
        assert root is not None and root.status is AgentSessionStatus.ACTIVE
        assert root.archived_at is None
        await session.write_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == session_id)
            .values(run_state=AgentSessionRunState.IDLE)
        )
    accepted = await operations.archive(
        root_session_id=session_id, expected_owner_generation=0
    )
    assert accepted is not None and accepted.session_ids == (session_id,)
    assert accepted.cleanup_plans == ()
    assert (
        await operations.archive(
            root_session_id=session_id, expected_owner_generation=0
        )
        is None
    )
