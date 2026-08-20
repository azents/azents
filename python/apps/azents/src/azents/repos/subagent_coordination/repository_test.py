"""SubagentCoordinationRepository PostgreSQL projection tests."""

import datetime
from typing import NamedTuple

import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunPhase,
    AgentRunStatus,
    AgentSessionProductMode,
    AgentSessionRunState,
    LLMProvider,
    MailboxItemKind,
    MailboxSchedulingMode,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.mailbox_item import RDBMailboxItem
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate, SessionAgent
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from .repository import SubagentCoordinationRepository


class _RootFixture(NamedTuple):
    """Created root Session tree dependencies."""

    repository: AgentSessionRepository
    session_id: str
    session_agent: SessionAgent


async def _create_agent(
    session: AsyncSession,
    *,
    workspace_id: str,
    slug: str,
) -> str:
    """Create one Agent and managed Runtime fixture."""
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{slug}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()
    agent = RDBAgent(
        workspace_id=workspace_id,
        name=f"{slug} agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-model",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-model",
        ),
    )
    session.add(agent)
    await session.flush()
    runtime = RDBAgentRuntime(workspace_id=workspace_id, agent_id=agent.id)
    runtime.workspace_path = "/workspace/agent"
    session.add(runtime)
    await session.flush()
    return agent.id


async def _create_root(
    session: AsyncSession,
    *,
    slug: str,
) -> _RootFixture:
    """Create one root AgentSession and SessionAgent tree."""
    workspace_result = await WorkspaceRepository().create(
        session,
        WorkspaceCreate(name=f"{slug} workspace", handle=f"{slug}-workspace"),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await WorkspaceRepository().resolve_id(
        session,
        f"{slug}-workspace",
    )
    assert workspace_id is not None
    agent_id = await _create_agent(session, workspace_id=workspace_id, slug=slug)
    repository = AgentSessionRepository()
    root_session = await repository.create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=agent_id,
            title=None,
            product_mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
        ),
    )
    root_agent = await repository.get_session_agent_by_session_id(
        session,
        root_session.id,
    )
    assert root_agent is not None
    return _RootFixture(
        repository=repository,
        session_id=root_session.id,
        session_agent=root_agent,
    )


async def _create_child(
    session: AsyncSession,
    *,
    repository: AgentSessionRepository,
    parent: SessionAgent,
    name: str,
) -> SessionAgent:
    """Create one linked child SessionAgent fixture."""
    return await repository.create_child_session_agent(
        session,
        parent_session_agent_id=parent.id,
        name=name,
        agent_type="default",
        title=name,
        last_task_message=None,
    )


def _add_run(
    session: AsyncSession,
    *,
    session_id: str,
    run_index: int,
    status: AgentRunStatus,
) -> None:
    """Add one durable AgentRun row with an explicit status."""
    session.add(
        RDBAgentRun(
            session_id=session_id,
            scheduled_task_cycle_id=None,
            run_index=run_index,
            parent_agent_run_id=None,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            phase=AgentRunPhase.IDLE,
            status=status,
        )
    )


async def test_project_root_tree_bounds_inactive_rows_and_keeps_required_rows(
    rdb_session: AsyncSession,
) -> None:
    """Project one scoped tree with active overflow and deterministic recent fill."""
    session = rdb_session
    repository, root_session_id, root = await _create_root(
        session,
        slug="coordination-primary",
    )
    active = await _create_child(
        session,
        repository=repository,
        parent=root,
        name="active",
    )
    latest = await _create_child(
        session,
        repository=repository,
        parent=active,
        name="latest",
    )
    wake = await _create_child(
        session,
        repository=repository,
        parent=root,
        name="wake",
    )
    recent = await _create_child(
        session,
        repository=repository,
        parent=root,
        name="recent",
    )
    old = await _create_child(
        session,
        repository=repository,
        parent=root,
        name="old",
    )
    equal_a = await _create_child(
        session,
        repository=repository,
        parent=root,
        name="equal-a",
    )
    equal_b = await _create_child(
        session,
        repository=repository,
        parent=root,
        name="equal-b",
    )

    await session.execute(
        sa.update(RDBAgentSession)
        .where(RDBAgentSession.id == active.agent_session_id)
        .values(run_state=AgentSessionRunState.RUNNING)
    )
    _add_run(
        session,
        session_id=latest.agent_session_id,
        run_index=1,
        status=AgentRunStatus.COMPLETED,
    )
    _add_run(
        session,
        session_id=latest.agent_session_id,
        run_index=2,
        status=AgentRunStatus.PENDING,
    )
    mailbox_item = RDBMailboxItem(
        session_id=wake.agent_session_id,
        kind=MailboxItemKind.AGENT_MESSAGE,
        scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        sender_user_id=None,
        idempotency_key=None,
        payload={},
    )
    mailbox_item.order_group = mailbox_item.id
    mailbox_item.order_sequence = 0
    session.add(mailbox_item)

    now = datetime.datetime.now(datetime.UTC)
    equal_created = now - datetime.timedelta(days=1)
    activity = {
        recent.id: now,
        old.id: None,
        equal_a.id: None,
        equal_b.id: None,
    }
    for session_agent_id, last_message_at in activity.items():
        await session.execute(
            sa.update(RDBSessionAgent)
            .where(RDBSessionAgent.id == session_agent_id)
            .values(last_message_at=last_message_at)
        )
    await session.execute(
        sa.update(RDBSessionAgent)
        .where(RDBSessionAgent.id.in_([equal_a.id, equal_b.id]))
        .values(created_at=equal_created)
    )
    await session.execute(
        sa.update(RDBSessionAgent)
        .where(RDBSessionAgent.id == old.id)
        .values(created_at=now - datetime.timedelta(days=3))
    )

    other_repository, _other_root_session_id, other_root = await _create_root(
        session,
        slug="coordination-other",
    )
    other_child = await _create_child(
        session,
        repository=other_repository,
        parent=other_root,
        name="outside",
    )
    await session.execute(
        sa.update(RDBAgentSession)
        .where(RDBAgentSession.id == other_child.agent_session_id)
        .values(run_state=AgentSessionRunState.RUNNING)
    )
    await session.flush()

    projection_repository = SubagentCoordinationRepository()
    overflow = await projection_repository.project_root_tree(
        session,
        current_session_id=latest.agent_session_id,
        configured_capacity=2,
    )

    assert overflow is not None
    assert [row.path for row in overflow.rows] == [
        "/root",
        "/root/active",
        "/root/active/latest",
        "/root/wake",
    ]
    assert overflow.required_count == 3
    assert overflow.selected_inactive_count == 0
    assert overflow.omitted_inactive_count == 4
    assert {row.path for row in overflow.rows if row.required} == {
        "/root/active",
        "/root/active/latest",
        "/root/wake",
    }
    latest_row = next(row for row in overflow.rows if row.path.endswith("/latest"))
    wake_row = next(row for row in overflow.rows if row.path.endswith("/wake"))
    assert latest_row.latest_run_status is AgentRunStatus.PENDING
    assert wake_row.wake_pending
    assert all("outside" not in row.path for row in overflow.rows)

    bounded = await projection_repository.project_root_tree(
        session,
        current_session_id=root_session_id,
        configured_capacity=5,
    )

    assert bounded is not None
    assert [row.path for row in bounded.rows] == [
        "/root",
        "/root/active",
        "/root/active/latest",
        "/root/equal-a",
        "/root/recent",
        "/root/wake",
    ]
    assert bounded.required_count == 3
    assert bounded.selected_inactive_count == 2
    assert bounded.omitted_inactive_count == 2
    assert len({row.session_agent_id for row in bounded.rows}) == len(bounded.rows)


async def test_project_root_tree_returns_none_for_unknown_session(
    rdb_session: AsyncSession,
) -> None:
    """Return no projection when the caller has no SessionAgent identity."""
    projection = await SubagentCoordinationRepository().project_root_tree(
        rdb_session,
        current_session_id="missing-session".rjust(32, "0"),
        configured_capacity=3,
    )

    assert projection is None
