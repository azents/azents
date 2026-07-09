"""ChatSessionService Subagent Tree projection tests."""

import datetime
from typing import cast

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunStatus,
    AgentSessionStartReason,
    LLMProvider,
    WorkspaceUserRole,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import AgentRunCreate
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.message import MessageRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.services.input_buffer import InputBufferService
from azents.testing.model_selection import make_test_model_selection_dict

from . import ChatSessionService
from .data import SessionAccessDenied


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    result = await WorkspaceRepository().create(
        session, WorkspaceCreate(name="Subagent Tree test", handle=handle)
    )
    assert isinstance(result, Success)
    workspace_id = await WorkspaceRepository().resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _add_workspace_user(
    session: AsyncSession,
    *,
    workspace_id: str,
    email: str,
) -> str:
    """Create User and WorkspaceUser for tests."""
    user = await UserRepository().create(session, UserCreate(email=email))
    result = await WorkspaceUserRepository().create(
        session,
        WorkspaceUserCreate(
            workspace_id=workspace_id,
            user_id=user.id,
            name="Subagent Tree user",
            role=WorkspaceUserRole.OWNER,
        ),
    )
    assert isinstance(result, Success)
    return user.id


async def _create_agent(session: AsyncSession, workspace_id: str, slug: str) -> str:
    """Create Agent for tests."""
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
        name="Subagent Tree test agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-id",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-id",
        ),
    )
    session.add(agent)
    await session.flush()
    return agent.id


def _service(rdb_session_manager: SessionManager[AsyncSession]) -> ChatSessionService:
    """Create ChatSessionService for tests."""
    return ChatSessionService(
        message_repository=MessageRepository(),
        agent_repository=AgentRepository(),
        agent_project_preset_repository=AgentProjectPresetRepository(),
        agent_project_catalog_repository=AgentProjectCatalogRepository(),
        agent_project_default_repository=AgentProjectDefaultRepository(),
        agent_run_repository=AgentRunRepository(),
        action_execution_repository=ActionExecutionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        agent_session_repository=AgentSessionRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        input_buffer_service=cast(InputBufferService, object()),
        session_manager=rdb_session_manager,
    )


class TestSubagentTreeProjection:
    """Subagent Tree projection tests."""

    async def test_projects_nested_tree_from_child_session_access(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Build a reconnect-safe tree projection from durable DB state."""
        repo = AgentSessionRepository()
        run_repo = AgentRunRepository()
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "subagent-tree-projection")
            user_id = await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                email="subagent-tree-user@example.com",
            )
            agent_id = await _create_agent(session, workspace_id, "subagent-tree")
            root_session = await repo.create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                    primary_kind=None,
                    start_reason=AgentSessionStartReason.INITIAL,
                ),
            )
            root_agent = await repo.get_session_agent_by_session_id(
                session,
                root_session.id,
            )
            assert root_agent is not None
            child = await repo.create_child_session_agent(
                session,
                parent_session_agent_id=root_agent.id,
                name="reviewer",
                agent_type="default",
                title="Reviewer",
                last_task_message="Review current branch",
            )
            nested = await repo.create_child_session_agent(
                session,
                parent_session_agent_id=child.id,
                name="fixer",
                agent_type="default",
                title="Fixer",
                last_task_message=None,
            )
            await repo.update_session_agent_observation_cursor(
                session,
                session_agent_id=child.id,
                parent_observed_run_index=1,
                parent_observed_event_id="observed-event",
            )
            root_run = await run_repo.create(
                session,
                AgentRunCreate(
                    session_id=root_agent.agent_session_id,
                    run_index=1,
                ),
            )
            await run_repo.mark_terminal(
                session,
                root_run.id,
                AgentRunStatus.COMPLETED,
                ended_at=datetime.datetime.now(datetime.UTC),
                terminal_result_event_id="root-terminal-event",
                terminal_result_message="Root complete",
            )
            child_run = await run_repo.create(
                session,
                AgentRunCreate(
                    session_id=child.agent_session_id,
                    run_index=2,
                ),
            )
            await run_repo.mark_terminal(
                session,
                child_run.id,
                AgentRunStatus.COMPLETED,
                ended_at=datetime.datetime.now(datetime.UTC),
                terminal_result_event_id="terminal-event",
                terminal_result_message="Review complete",
            )
            await repo.mark_running(session, nested.agent_session_id)
            await run_repo.create(
                session,
                AgentRunCreate(
                    session_id=nested.agent_session_id,
                    run_index=1,
                ),
            )

        result = await _service(rdb_session_manager).get_subagent_tree(
            agent_id=agent_id,
            session_id=child.agent_session_id,
            user_id=user_id,
        )

        assert isinstance(result, Success)
        tree = result.value
        assert tree.root_session_agent_id == root_agent.id
        assert tree.root_agent_session_id == root_session.id
        assert tree.current_session_agent_id == child.id
        assert [node.session_agent_id for node in tree.nodes] == [root_agent.id]
        root_node = tree.nodes[0]
        assert root_node.status == "completed"
        assert root_node.unread_result is False
        child_node = root_node.children[0]
        assert child_node.session_agent_id == child.id
        assert child_node.path == "/root/reviewer"
        assert child_node.status == "completed"
        assert child_node.last_task_message == "Review current branch"
        assert child_node.unread_result is True
        assert child_node.latest_run_index == 2
        assert child_node.latest_run_status == AgentRunStatus.COMPLETED
        assert child_node.terminal_result_event_id == "terminal-event"
        assert child_node.terminal_result_message == "Review complete"
        nested_node = child_node.children[0]
        assert nested_node.session_agent_id == nested.id
        assert nested_node.status == "running"
        assert nested_node.unread_result is False

    async def test_denies_tree_projection_without_workspace_membership(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Do not expose hidden subagent sessions to non-members."""
        repo = AgentSessionRepository()
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "subagent-tree-denied")
            agent_id = await _create_agent(
                session, workspace_id, "subagent-tree-denied"
            )
            root_session = await repo.create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                    primary_kind=None,
                    start_reason=AgentSessionStartReason.INITIAL,
                ),
            )

        result = await _service(rdb_session_manager).get_subagent_tree(
            agent_id=agent_id,
            session_id=root_session.id,
            user_id="outside-user",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, SessionAccessDenied)
