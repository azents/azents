"""SessionWorkspaceProjectRepository tests."""

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import LLMProvider
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from . import SessionWorkspaceProjectRepository
from .data import SessionWorkspaceProjectCreate


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    repo = WorkspaceRepository()
    await repo.create(session, WorkspaceCreate(name="Project test", handle=handle))
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_session(session: AsyncSession, workspace_id: str, slug: str) -> str:
    """Create AgentSession for tests."""

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
        name="Project test agent",
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

    agent_session = await AgentSessionRepository().ensure_team_primary_for_agent(
        session,
        workspace_id=workspace_id,
        agent_id=agent.id,
    )
    return agent_session.id


class TestSessionWorkspaceProjectRepository:
    """SessionWorkspaceProjectRepository tests."""

    async def test_create_and_list_projects(self, rdb_session: AsyncSession) -> None:
        """Create Project and fetch in path order."""
        workspace_id = await _create_workspace(rdb_session, "swp-list")
        session_id = await _create_session(rdb_session, workspace_id, "swp-list")
        repo = SessionWorkspaceProjectRepository()

        second = await repo.create_project(
            rdb_session,
            SessionWorkspaceProjectCreate(
                session_id=session_id,
                path="/workspace/agent/backend",
            ),
        )
        first = await repo.create_project(
            rdb_session,
            SessionWorkspaceProjectCreate(
                session_id=session_id,
                path="/workspace/agent/api",
            ),
        )

        projects = await repo.list_projects(rdb_session, session_id=session_id)

        assert [project.id for project in projects] == [first.id, second.id]

    async def test_get_project_by_path(self, rdb_session: AsyncSession) -> None:
        """Fetch Project by AgentSession and path."""
        workspace_id = await _create_workspace(rdb_session, "swp-by-path")
        session_id = await _create_session(rdb_session, workspace_id, "swp-by-path")
        repo = SessionWorkspaceProjectRepository()
        project = await repo.create_project(
            rdb_session,
            SessionWorkspaceProjectCreate(
                session_id=session_id,
                path="/workspace/agent/lookup",
            ),
        )

        loaded = await repo.get_project_by_path(
            rdb_session,
            session_id=session_id,
            path="/workspace/agent/lookup",
        )

        assert loaded is not None
        assert loaded.id == project.id

    async def test_delete_project(self, rdb_session: AsyncSession) -> None:
        """Delete Project row."""
        workspace_id = await _create_workspace(rdb_session, "swp-delete")
        session_id = await _create_session(rdb_session, workspace_id, "swp-delete")
        repo = SessionWorkspaceProjectRepository()
        project = await repo.create_project(
            rdb_session,
            SessionWorkspaceProjectCreate(
                session_id=session_id,
                path="/workspace/agent/delete-me",
            ),
        )

        deleted = await repo.delete_project(
            rdb_session,
            project.id,
            session_id=session_id,
        )
        loaded = await repo.get_project_by_id(rdb_session, project.id)

        assert deleted is True
        assert loaded is None
