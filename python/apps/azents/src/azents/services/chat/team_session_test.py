"""ChatSessionService team session tests."""

from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionPrimaryKind,
    LLMProvider,
    WorkspaceUserRole,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.input_buffer import InputBufferRepository
from azents.repos.message import MessageRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProjectCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.services.exchange_file import ExchangeFileService
from azents.services.input_buffer import InputBufferService
from azents.services.model_file import ModelFileService
from azents.testing.model_selection import make_test_model_selection_dict

from . import ChatSessionService


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session,
        WorkspaceCreate(name="Team session test", handle=handle),
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_user(session: AsyncSession, email: str) -> str:
    """Create User for tests."""
    user = await UserRepository().create(session, UserCreate(email=email))
    return user.id


async def _add_workspace_user(
    session: AsyncSession,
    *,
    workspace_id: str,
    user_id: str,
) -> None:
    """Create WorkspaceUser for tests."""
    result = await WorkspaceUserRepository().create(
        session,
        WorkspaceUserCreate(
            workspace_id=workspace_id,
            user_id=user_id,
            name="Team session user",
            role=WorkspaceUserRole.OWNER,
        ),
    )
    assert isinstance(result, Success)


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
        name="Team session test agent",
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


def _service(
    rdb_session_manager: SessionManager[AsyncSession],
) -> ChatSessionService:
    """Create ChatSessionService for tests."""
    return ChatSessionService(
        message_repository=MessageRepository(),
        agent_repository=AgentRepository(),
        agent_run_repository=AgentRunRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        agent_runtime_repository=AgentRuntimeRepository(),
        agent_session_repository=AgentSessionRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        input_buffer_service=InputBufferService(
            session_manager=rdb_session_manager,
            input_buffer_repository=InputBufferRepository(),
            exchange_file_service=_ExchangeFileService(),
            model_file_service=_ModelFileService(),
            agent_session_repository=AgentSessionRepository(),
            event_transcript_repository=EventTranscriptRepository(),
        ),
        session_manager=rdb_session_manager,
    )


class _ExchangeFileService(ExchangeFileService):
    """ExchangeFileService for tests."""

    def __init__(self) -> None:
        """Bypass Base dataclass initialization."""


class _ModelFileService(ModelFileService):
    """ModelFileService for tests."""

    def __init__(self) -> None:
        """Bypass Base dataclass initialization."""


class TestChatSessionTeamSessions:
    """Team session service behavior."""

    async def test_create_team_session_copies_primary_projects_once(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """New team sessions receive a snapshot of primary projects."""
        workspace_id = await _create_workspace(rdb_session, "team-session-copy")
        user_id = await _create_user(rdb_session, "team-session-copy@example.com")
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(rdb_session, workspace_id, "team-copy-agent")
        primary = await AgentSessionRepository().ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        project_repo = SessionWorkspaceProjectRepository()
        await project_repo.create_project(
            rdb_session,
            SessionWorkspaceProjectCreate(
                session_id=primary.id,
                path="/workspace/agent/project-a",
            ),
        )
        await rdb_session.commit()

        create_result = await _service(rdb_session_manager).create_team_session(
            agent_id=agent_id,
            user_id=user_id,
        )

        assert isinstance(create_result, Success)
        created = create_result.value
        assert created.agent_id == agent_id
        assert created.primary_kind is None

        async with rdb_session_manager() as verify_session:
            copied_projects = await project_repo.list_projects(
                verify_session,
                session_id=created.id,
            )
            assert [project.path for project in copied_projects] == [
                "/workspace/agent/project-a"
            ]
            await project_repo.create_project(
                verify_session,
                SessionWorkspaceProjectCreate(
                    session_id=primary.id,
                    path="/workspace/agent/project-b",
                ),
            )
            await verify_session.commit()

        async with rdb_session_manager() as verify_session:
            copied_projects = await project_repo.list_projects(
                verify_session,
                session_id=created.id,
            )
            assert [project.path for project in copied_projects] == [
                "/workspace/agent/project-a"
            ]

    async def test_list_agent_sessions_returns_primary_first(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Agent session list is active-only with team primary first."""
        workspace_id = await _create_workspace(rdb_session, "team-session-list")
        user_id = await _create_user(rdb_session, "team-session-list@example.com")
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(rdb_session, workspace_id, "team-list-agent")
        primary = await AgentSessionRepository().ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        await rdb_session.commit()
        create_result = await _service(rdb_session_manager).create_team_session(
            agent_id=agent_id,
            user_id=user_id,
        )
        assert isinstance(create_result, Success)

        list_result = await _service(rdb_session_manager).list_agent_sessions(
            agent_id=agent_id,
            user_id=user_id,
        )

        assert isinstance(list_result, Success)
        sessions = list_result.value
        assert [session.id for session in sessions] == [
            primary.id,
            create_result.value.id,
        ]
        assert sessions[0].primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY
        assert sessions[1].primary_kind is None
