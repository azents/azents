"""AgentSessionInputService tests."""

import datetime

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionPrimaryKind,
    AgentSessionRunState,
    AgentSessionStartReason,
    AgentSessionStatus,
    LLMProvider,
    WorkspaceUserRole,
)
from azents.engine.run.input import InputMessage
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.input_buffer import InputBufferRepository
from azents.repos.input_buffer.data import InputBuffer
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProjectCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.services.exchange_file import ExchangeFileService
from azents.services.model_file import ModelFileService
from azents.testing.model_selection import make_test_model_selection_dict

from .agent_session_input import (
    AgentSessionInputInactiveSession,
    AgentSessionInputService,
)
from .input_buffer import (
    InputBufferEnqueue,
    InputBufferEnqueueResult,
    InputBufferService,
)


class _RuntimeRepositoryDouble(AgentRuntimeRepository):
    """Runtime repository for tests."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def ensure_for_agent(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        default_runtime_provider_id: str | None = None,
    ) -> AgentRuntime:
        """Ensure runtime."""
        del session, agent_id, default_runtime_provider_id
        self.calls.append("ensure_for_agent")
        now = datetime.datetime.now(datetime.UTC)
        return AgentRuntime(
            id="runtime-1",
            workspace_id="workspace-1",
            agent_id="agent-1",
            created_at=now,
            updated_at=now,
        )


class _AgentSessionRepositoryDouble(AgentSessionRepository):
    """AgentSession repository for tests."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession:
        """Fetch session."""
        del session
        self.calls.append("get_by_id")
        now = datetime.datetime.now(datetime.UTC)
        return AgentSession(
            id=agent_session_id,
            workspace_id="workspace-1",
            agent_id="agent-1",
            status=AgentSessionStatus.ACTIVE,
            start_reason=AgentSessionStartReason.INITIAL,
            title=None,
            title_source=None,
            title_generated_at=None,
            title_generation_event_id=None,
            last_user_input_at=now,
            started_at=now,
            created_at=now,
            updated_at=now,
        )


class _InputBufferServiceDouble(InputBufferService):
    """InputBufferService double for tests."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.enqueued: InputBufferEnqueue | None = None
        self.moved: tuple[str, str] | None = None

    async def enqueue(
        self,
        session: AsyncSession,
        input: InputBufferEnqueue,
    ) -> InputBufferEnqueueResult:
        """Record InputBuffer creation."""
        del session
        self.calls.append("enqueue_input_buffer")
        self.enqueued = input
        input_buffer = InputBuffer(
            id="buffer-1",
            session_id=input.session_id,
            kind=input.kind,
            actor_user_id=input.actor_user_id,
            content=input.content,
            idempotency_key=input.idempotency_key,
            metadata=input.metadata,
            attachments=input.attachments,
            file_parts=input.file_parts,
            created_at=datetime.datetime.now(datetime.UTC),
        )
        return InputBufferEnqueueResult(input_buffer=input_buffer, created=True)

    async def move_by_session_id(
        self,
        session: AsyncSession,
        *,
        from_session_id: str,
        to_session_id: str,
    ) -> int:
        """Record InputBuffer move request."""
        del session
        self.calls.append("move_input_buffer")
        self.moved = (from_session_id, to_session_id)
        return 1


class _ExchangeFileService(ExchangeFileService):
    """ExchangeFileService for tests."""

    def __init__(self) -> None:
        """Bypass Base dataclass initialization."""


class _ModelFileService(ModelFileService):
    """ModelFileService for tests."""

    def __init__(self) -> None:
        """Bypass Base dataclass initialization."""


def _input_buffer_service(
    rdb_session_manager: SessionManager[AsyncSession],
) -> InputBufferService:
    """Create InputBufferService for integration tests."""
    return InputBufferService(
        session_manager=rdb_session_manager,
        input_buffer_repository=InputBufferRepository(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        agent_session_repository=AgentSessionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
    )


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name="AgentSession input test", handle=handle)
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


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
        name="AgentSession input test agent",
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
            name="AgentSession input user",
            role=WorkspaceUserRole.OWNER,
        ),
    )
    assert isinstance(result, Success)


class TestAgentSessionInputService:
    """AgentSessionInputService tests."""

    async def test_create_buffered_agent_input_marks_running_before_return(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """REST input storage marks runtime running before broker send."""
        calls: list[str] = []
        runtime_repository = _RuntimeRepositoryDouble(calls)
        session_repository = _AgentSessionRepositoryDouble(calls)
        input_buffer_service = _InputBufferServiceDouble(calls)
        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=runtime_repository,
            agent_session_repository=session_repository,
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            input_buffer_service=input_buffer_service,
            session_manager=rdb_session_manager,
        )

        result = await service.create_buffered_agent_input(
            agent_id="agent-1",
            agent_session_id="session-1",
            message=InputMessage(
                text="restore me",
                user_id="user-1",
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id="user-1",
        )

        assert isinstance(result, Success)
        value = result.value
        assert value.agent_runtime_id == "runtime-1"
        assert value.agent_session_id == "session-1"
        assert value.input_buffer.id == "buffer-1"
        assert calls == [
            "get_by_id",
            "ensure_for_agent",
            "enqueue_input_buffer",
        ]
        assert input_buffer_service.enqueued is not None
        assert input_buffer_service.enqueued.session_id == "session-1"
        assert input_buffer_service.enqueued.content == "restore me"

    async def test_create_team_session_with_buffered_input_bootstraps_session(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """First draft input creates a session with explicit Projects."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "draft-session-input")
            user_id = await _create_user(session, "draft-session-input@example.com")
            await _add_workspace_user(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            agent_id = await _create_agent(session, workspace_id, "draft-session-input")
            primary = await AgentSessionRepository().ensure_team_primary_for_agent(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
            await SessionWorkspaceProjectRepository().create_project(
                session,
                SessionWorkspaceProjectCreate(
                    session_id=primary.id,
                    path="/workspace/agent/project-a",
                ),
            )

        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        result = await service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="first draft message",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id=user_id,
            project_paths=[
                "/workspace/agent/project-a/nested",
                "/workspace/agent/project-a/nested",
            ],
            client_request_id="draft-client-1",
        )

        assert isinstance(result, Success)
        created = result.value.agent_session
        assert created.agent_id == agent_id
        assert created.primary_kind is None
        assert result.value.input_buffer.session_id == created.id
        assert result.value.input_buffer.content == "first draft message"
        assert result.value.input_buffer.idempotency_key == "draft-client-1"
        async with rdb_session_manager() as session:
            sessions = await AgentSessionRepository().list_active_by_agent_id(
                session,
                agent_id,
            )
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=created.id,
            )
            defaults = await AgentProjectDefaultRepository().list_defaults(
                session,
                agent_id=agent_id,
            )
            catalog_entries = await AgentProjectCatalogRepository().list_entries(
                session,
                agent_id=agent_id,
            )
            updated = await AgentSessionRepository().get_by_id(session, created.id)

        assert [item.primary_kind for item in sessions] == [
            AgentSessionPrimaryKind.TEAM_PRIMARY,
            None,
        ]
        assert [project.path for project in projects] == [
            "/workspace/agent/project-a/nested"
        ]
        assert [default.path for default in defaults] == [
            "/workspace/agent/project-a/nested"
        ]
        assert [entry.path for entry in catalog_entries] == [
            "/workspace/agent/project-a/nested"
        ]
        assert updated is not None
        assert updated.run_state == AgentSessionRunState.RUNNING

    async def test_buffered_agent_input_rejects_archived_session_after_rollover(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """User input with stale session id is rejected instead of redirected."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(
                session, "agent-session-stale-buffer"
            )
            user_id = await _create_user(session, "stale-buffer@example.com")
            agent_id = await _create_agent(
                session, workspace_id, "agent-session-stale-buffer"
            )
            runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
            old_session = await AgentSessionRepository().ensure_team_primary_for_agent(
                session,
                workspace_id=runtime.workspace_id,
                agent_id=runtime.agent_id,
            )
            await AgentSessionRepository().archive(
                session,
                old_session.id,
                ended_at=datetime.datetime.now(datetime.timezone.utc),
            )

        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        result = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=old_session.id,
            message=InputMessage(
                text="after rollover",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id=user_id,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, AgentSessionInputInactiveSession)

        async with rdb_session_manager() as session:
            old_buffers = await InputBufferRepository().list_by_session_id(
                session, old_session.id
            )
        assert old_buffers == []

    async def test_create_buffered_agent_input_marks_session_running(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """REST input storage marks Session running to cover broker loss."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "buffered-chat-running")
            user_id = await _create_user(session, "buffered-running@example.com")
            agent_id = await _create_agent(
                session, workspace_id, "buffered-chat-running"
            )
            runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
            agent_session = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=runtime.workspace_id,
                    agent_id=runtime.agent_id,
                )
            )

        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        result = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=InputMessage(
                text="restore me",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id=user_id,
        )
        assert isinstance(result, Success)

        async with rdb_session_manager() as session:
            updated = await AgentSessionRepository().get_by_id(
                session,
                agent_session.id,
            )

        assert updated is not None
        assert updated.run_state == AgentSessionRunState.RUNNING
        assert updated.run_heartbeat_at is not None

    async def test_create_buffered_agent_input_dedupes_client_request_id(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Same client_request_id returns same InputBuffer."""
        async with rdb_session_manager() as session:
            workspace_id = await _create_workspace(session, "buffered-chat-idempotent")
            user_id = await _create_user(session, "buffered-idempotent@example.com")
            agent_id = await _create_agent(
                session, workspace_id, "buffered-chat-idempotent"
            )
            runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent_id)
            agent_session = (
                await AgentSessionRepository().ensure_team_primary_for_agent(
                    session,
                    workspace_id=runtime.workspace_id,
                    agent_id=runtime.agent_id,
                )
            )

        service = AgentSessionInputService(
            agent_repository=AgentRepository(),
            agent_project_preset_repository=AgentProjectPresetRepository(),
            agent_project_catalog_repository=AgentProjectCatalogRepository(),
            agent_project_default_repository=AgentProjectDefaultRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            agent_session_repository=AgentSessionRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
            workspace_user_repository=WorkspaceUserRepository(),
            input_buffer_service=_input_buffer_service(rdb_session_manager),
            session_manager=rdb_session_manager,
        )

        first = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=InputMessage(
                text="first",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id=user_id,
            client_request_id="client-request-1",
        )
        second = await service.create_buffered_agent_input(
            agent_id=agent_id,
            agent_session_id=agent_session.id,
            message=InputMessage(
                text="retry payload ignored",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id=user_id,
            client_request_id="client-request-1",
        )

        assert isinstance(first, Success)
        assert isinstance(second, Success)
        first_value = first.value
        second_value = second.value
        assert second_value.input_buffer.id == first_value.input_buffer.id
        assert second_value.input_buffer.content == "first"
        assert second_value.input_buffer.idempotency_key == "client-request-1"
        async with rdb_session_manager() as session:
            buffers = await InputBufferRepository().list_by_session_id(
                session, agent_session.id
            )
        assert [buffer.id for buffer in buffers] == [first_value.input_buffer.id]
