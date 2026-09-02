"""Canonical Session execution projection repository tests."""

import datetime
from typing import Literal

import pytest
from azcommon.result import Success
from azcommon.uuid import uuid7
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRunStatus,
    AgentSessionProductMode,
    AgentSessionRunState,
    AgentSessionStatus,
    LLMProvider,
    MailboxItemKind,
    MailboxSchedulingMode,
    ScheduledTaskScheduleType,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.data import MailboxItemCreate
from azents.repos.scheduled_task_cycle.data import ScheduledTaskCycleState
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.toolkit_state.data import ToolkitStateUpsert
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from . import CanonicalExecutionSnapshotError, SessionExecutionRepository


async def _create_execution_subject(
    session: AsyncSession,
    *,
    handle: str,
) -> tuple[RDBAgentSession, str]:
    """Create a complete active root Session authority fixture."""
    workspace_repository = WorkspaceRepository()
    result = await workspace_repository.create(
        session,
        WorkspaceCreate(name="Session execution test", handle=handle),
    )
    assert isinstance(result, Success)
    workspace_id = await workspace_repository.resolve_id(session, handle)
    assert workspace_id is not None

    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{handle}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()

    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Session execution test agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{handle}-model",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{handle}-model",
        ),
    )
    session.add(agent)
    await session.flush()
    runtime = RDBAgentRuntime(
        workspace_id=workspace_id,
        agent_id=agent.id,
    )
    runtime.workspace_path = "/workspace/agent"
    session.add(runtime)
    await session.flush()

    created = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            product_mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
            agent_id=agent.id,
            title=None,
        ),
    )
    agent_session = await session.get(RDBAgentSession, created.id)
    assert agent_session is not None
    await AgentSessionRepository().mark_running(session, created.id)
    await session.refresh(agent_session)
    return agent_session, agent.id


async def _archive_with_scheduled_continuation(
    session: AsyncSession,
    *,
    agent_session: RDBAgentSession,
    phase: Literal["admitted", "started"],
) -> str:
    """Archive a Session with one typed Scheduled continuation and cycle state."""
    cycle_id = uuid7().hex
    run = RDBAgentRun(
        session_id=agent_session.id,
        scheduled_task_cycle_id=cycle_id,
        run_index=1,
        parent_agent_run_id=None,
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        status=AgentRunStatus.COMPLETED,
    )
    session.add(run)
    await session.flush()
    state = ScheduledTaskCycleState(
        cycle_id=cycle_id,
        task_id=uuid7().hex,
        phase=phase,
        workspace_id=agent_session.workspace_id,
        agent_id=agent_session.agent_id,
        session_id=agent_session.id,
        binding_id=None,
        title="Daily report",
        objective="Prepare the report.",
        schedule_type=ScheduledTaskScheduleType.ONCE,
        scheduled_at=datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC),
        cron_expression=None,
        timezone=None,
        scheduled_for=datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC),
        current_run_id=run.id if phase == "started" else None,
        started_at=(
            datetime.datetime(2026, 8, 16, tzinfo=datetime.UTC)
            if phase == "started"
            else None
        ),
        progress_title=None,
        ordered_tasks=[],
        tracker_desired_revision=0,
        tracker_current_projection_parts=[],
    )
    await ToolkitStateRepository().save(
        session,
        ToolkitStateUpsert(
            agent_id=state.agent_id,
            session_id=state.session_id,
            toolkit_namespace="scheduled",
            state_name=f"cycle:{cycle_id}",
            state_json=state.model_dump(mode="json"),
            schema_version=1,
            expected_version=None,
        ),
    )
    mailbox_item = await MailboxRepository().create(
        session,
        MailboxItemCreate(
            session_id=agent_session.id,
            kind=MailboxItemKind.SCHEDULED_TASK_CONTINUATION,
            scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            sender_user_id=None,
            order_group=None,
            order_sequence=0,
            content="Continue the Scheduled Task.",
            idempotency_key=f"idle_continuation:{run.id}:scheduled:0",
            metadata={"cycle_id": cycle_id, "title": "Daily report"},
            action=None,
            attachments=[],
            file_parts=[],
            payload=None,
        ),
    )
    agent_session.status = AgentSessionStatus.ARCHIVED
    await session.flush()
    return mailbox_item.id


class TestSessionExecutionRepository:
    """Fail-closed tests for the canonical Session execution projection."""

    async def test_load_canonical_snapshot_rejects_idle_session(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Mailbox work cannot execute without durable running admission."""
        agent_session, _agent_id = await _create_execution_subject(
            rdb_session,
            handle="execution-idle-session",
        )
        agent_session.run_state = AgentSessionRunState.IDLE
        await rdb_session.flush()

        with pytest.raises(
            CanonicalExecutionSnapshotError,
            match="AgentSession is not running",
        ):
            await SessionExecutionRepository().load_canonical_snapshot(
                rdb_session,
                session_id=agent_session.id,
                owner_generation=agent_session.owner_generation,
            )

    async def test_load_canonical_snapshot_rejects_stale_owner_generation(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A wake-up cannot execute after durable ownership changes."""
        agent_session, _agent_id = await _create_execution_subject(
            rdb_session,
            handle="execution-stale-owner",
        )

        with pytest.raises(
            CanonicalExecutionSnapshotError,
            match="owner generation is stale",
        ):
            await SessionExecutionRepository().load_canonical_snapshot(
                rdb_session,
                session_id=agent_session.id,
                owner_generation=agent_session.owner_generation + 1,
            )

    async def test_load_canonical_snapshot_rejects_incomplete_pending_command(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A partial durable command is never projected for execution."""
        agent_session, _agent_id = await _create_execution_subject(
            rdb_session,
            handle="execution-partial-command",
        )
        agent_session.pending_command_id = "command-001"
        agent_session.pending_command_name = "compact"
        agent_session.pending_command_payload = {}
        agent_session.pending_command_created_at = None
        await rdb_session.flush()

        with pytest.raises(
            CanonicalExecutionSnapshotError,
            match="Pending command is incomplete",
        ):
            await SessionExecutionRepository().load_canonical_snapshot(
                rdb_session,
                session_id=agent_session.id,
                owner_generation=agent_session.owner_generation,
            )

    async def test_load_canonical_snapshot_projects_only_matching_recoverable_run(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """The durable snapshot carries the unique Session-local recoverable Run."""
        agent_session, _agent_id = await _create_execution_subject(
            rdb_session,
            handle="execution-recoverable-run",
        )
        run = RDBAgentRun(
            session_id=agent_session.id,
            scheduled_task_cycle_id=None,
            run_index=1,
            parent_agent_run_id=None,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            status=AgentRunStatus.RUNNING,
        )
        rdb_session.add(run)
        await rdb_session.flush()

        snapshot = await SessionExecutionRepository().load_canonical_snapshot(
            rdb_session,
            session_id=agent_session.id,
            owner_generation=agent_session.owner_generation,
        )

        assert snapshot.session_id == agent_session.id
        assert snapshot.agent_id == agent_session.agent_id
        assert snapshot.recoverable_run_id == run.id
        assert snapshot.recoverable_run_status is AgentRunStatus.RUNNING

    async def test_load_canonical_snapshot_accepts_archived_started_continuation(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A typed continuation may resume its pre-archive started cycle."""
        agent_session, _agent_id = await _create_execution_subject(
            rdb_session,
            handle="execution-archived-scheduled",
        )
        await _archive_with_scheduled_continuation(
            rdb_session,
            agent_session=agent_session,
            phase="started",
        )

        snapshot = await SessionExecutionRepository().load_canonical_snapshot(
            rdb_session,
            session_id=agent_session.id,
            owner_generation=agent_session.owner_generation,
        )

        assert snapshot.session_id == agent_session.id
        assert snapshot.recoverable_run_id is None

    async def test_archived_started_continuation_survives_agent_decommission_fence(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A preserved cycle may finish while its Agent decommission waits."""
        agent_session, agent_id = await _create_execution_subject(
            rdb_session,
            handle="execution-archived-decommissioning",
        )
        await _archive_with_scheduled_continuation(
            rdb_session,
            agent_session=agent_session,
            phase="started",
        )
        agent = await rdb_session.get(RDBAgent, agent_id)
        assert agent is not None
        agent.lifecycle_status = AgentLifecycleStatus.DECOMMISSIONING
        await rdb_session.flush()

        snapshot = await SessionExecutionRepository().load_canonical_snapshot(
            rdb_session,
            session_id=agent_session.id,
            owner_generation=agent_session.owner_generation,
        )

        assert snapshot.session_id == agent_session.id
        assert snapshot.agent_id == agent_id

    async def test_load_canonical_snapshot_rejects_archived_admitted_continuation(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """An admitted cycle never grants archived execution authority."""
        agent_session, _agent_id = await _create_execution_subject(
            rdb_session,
            handle="execution-archived-admitted",
        )
        await _archive_with_scheduled_continuation(
            rdb_session,
            agent_session=agent_session,
            phase="admitted",
        )

        with pytest.raises(
            CanonicalExecutionSnapshotError,
            match="AgentSession is not active",
        ):
            await SessionExecutionRepository().load_canonical_snapshot(
                rdb_session,
                session_id=agent_session.id,
                owner_generation=agent_session.owner_generation,
            )

    async def test_load_canonical_snapshot_rejects_archived_ordinary_input(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Archived Sessions remain closed to ordinary mailbox input."""
        agent_session, _agent_id = await _create_execution_subject(
            rdb_session,
            handle="execution-archived-ordinary",
        )
        await MailboxRepository().create(
            rdb_session,
            MailboxItemCreate(
                session_id=agent_session.id,
                kind=MailboxItemKind.USER_MESSAGE,
                scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                sender_user_id=None,
                order_group=None,
                order_sequence=0,
                content="Reopen this Session.",
                idempotency_key=None,
                metadata={},
                action=None,
                attachments=[],
                file_parts=[],
                payload=None,
            ),
        )
        agent_session.status = AgentSessionStatus.ARCHIVED
        await rdb_session.flush()

        with pytest.raises(
            CanonicalExecutionSnapshotError,
            match="AgentSession is not active",
        ):
            await SessionExecutionRepository().load_canonical_snapshot(
                rdb_session,
                session_id=agent_session.id,
                owner_generation=agent_session.owner_generation,
            )
