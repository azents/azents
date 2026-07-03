"""SessionWorkspaceProjectService tests."""

import dataclasses
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentProjectCatalogStatus,
    LLMProvider,
    RuntimeRunnerState,
    WorkspaceUserRole,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.runtime.control_protocol.runner_operations import (
    RuntimeFileListResult,
    RuntimeRunnerOperationClient,
)
from azents.testing.model_selection import make_test_model_selection_dict

from . import (
    InvalidProjectPath,
    ProjectAccessDenied,
    ProjectPathConflict,
    SessionWorkspaceProjectService,
    normalize_session_workspace_path,
)


class _SessionManager:
    """session manager for tests."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[AsyncSession]:
        """Return same session as context manager."""
        yield self._session


@dataclasses.dataclass(frozen=True)
class _RuntimeFixture:
    """AgentRuntime fixture for tests."""

    agent_id: str
    runtime_id: str
    session_id: str


class _FakeRunnerOperations(RuntimeRunnerOperationClient):
    """Runner operation fake for tests."""

    def __init__(self) -> None:
        self.paths: list[str] = []

    async def list_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        path: str,
        recursive: bool = False,
        exclude_patterns: list[str] | None = None,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileListResult:
        """Treat Directory existence check as success."""
        del runtime_id, runner_generation, recursive, exclude_patterns, deadline_at
        self.paths.append(path)
        return RuntimeFileListResult(entries=(), final_cursor="0")


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests."""
    repo = WorkspaceRepository()
    await repo.create(session, WorkspaceCreate(name="Project service", handle=handle))
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_runtime_fixture(
    session: AsyncSession, workspace_id: str, slug: str
) -> _RuntimeFixture:
    """Create AgentRuntime and team primary AgentSession for tests."""

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
        name="Project service agent",
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

    runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent.id)
    agent_session = await AgentSessionRepository().ensure_team_primary_for_agent(
        session,
        workspace_id=workspace_id,
        agent_id=agent.id,
    )
    return _RuntimeFixture(
        agent_id=agent.id,
        runtime_id=runtime.id,
        session_id=agent_session.id,
    )


async def _create_session(session: AsyncSession, workspace_id: str, slug: str) -> str:
    """Create AgentSession ID for tests."""
    fixture = await _create_runtime_fixture(session, workspace_id, slug)
    return fixture.session_id


async def _create_workspace_user(
    session: AsyncSession,
    *,
    workspace_id: str,
    email: str,
) -> str:
    """Create WorkspaceUser for tests."""
    user = await UserRepository().create(session, UserCreate(email=email))
    result = await WorkspaceUserRepository().create(
        session,
        WorkspaceUserCreate(
            workspace_id=workspace_id,
            user_id=user.id,
            name="Project service user",
            role=WorkspaceUserRole.MEMBER,
        ),
    )
    assert isinstance(result, Success)
    return user.id


def _service(
    session: AsyncSession,
    *,
    runner_operations: RuntimeRunnerOperationClient | None = None,
) -> SessionWorkspaceProjectService:
    """Create service for tests."""
    return SessionWorkspaceProjectService(
        repository=SessionWorkspaceProjectRepository(),
        agent_project_preset_repository=AgentProjectPresetRepository(),
        agent_project_catalog_repository=AgentProjectCatalogRepository(),
        agent_runtime_repository=AgentRuntimeRepository(),
        agent_session_repository=AgentSessionRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        session_manager=_SessionManager(session),
        runner_operations=runner_operations,
    )


class TestSessionWorkspaceProjectService:
    """SessionWorkspaceProjectService tests."""

    def test_normalize_rejects_workspace_root(self) -> None:
        """Session Workspace root itself cannot become Project."""
        try:
            normalize_session_workspace_path("/workspace/agent")
        except ValueError as exc:
            assert "root" in str(exc)
        else:
            raise AssertionError("root path was accepted")

    async def test_create_project_rejects_prefix_outside_path(
        self, rdb_session: AsyncSession
    ) -> None:
        """Reject path outside Session Workspace."""
        workspace_id = await _create_workspace(rdb_session, "swp-svc-prefix")
        session_id = await _create_session(rdb_session, workspace_id, "swp-svc-prefix")
        service = _service(rdb_session)

        result = await service.create_project(
            session_id=session_id,
            path="/tmp/bad",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, InvalidProjectPath)

    async def test_create_project_allows_nested_path(
        self, rdb_session: AsyncSession
    ) -> None:
        """Allow parent and nested child Project paths in the same session."""
        workspace_id = await _create_workspace(rdb_session, "swp-svc-nested")
        session_id = await _create_session(rdb_session, workspace_id, "swp-svc-nested")
        service = _service(rdb_session)
        first = await service.create_project(
            session_id=session_id,
            path="/workspace/agent/app",
        )
        assert isinstance(first, Success)

        result = await service.create_project(
            session_id=session_id,
            path="/workspace/agent/app/frontend",
        )

        assert isinstance(result, Success)
        assert result.value.path == "/workspace/agent/app/frontend"

    async def test_create_project_rejects_duplicate_path(
        self, rdb_session: AsyncSession
    ) -> None:
        """Reject path same as existing Project."""
        workspace_id = await _create_workspace(rdb_session, "swp-svc-duplicate")
        session_id = await _create_session(
            rdb_session, workspace_id, "swp-svc-duplicate"
        )
        service = _service(rdb_session)
        first = await service.create_project(
            session_id=session_id,
            path="/workspace/agent/app",
        )
        assert isinstance(first, Success)

        result = await service.create_project(
            session_id=session_id,
            path="/workspace/agent/app",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProjectPathConflict)

    async def test_register_existing_folder_rejects_invalid_path_before_runtime_check(
        self, rdb_session: AsyncSession
    ) -> None:
        """Reject invalid path without passing to Runner operation."""
        workspace_id = await _create_workspace(rdb_session, "swp-svc-register-bad")
        fixture = await _create_runtime_fixture(
            rdb_session,
            workspace_id,
            "swp-svc-register-bad",
        )
        user_id = await _create_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            email="swp-svc-register-bad@example.com",
        )
        runtime = await rdb_session.get(RDBAgentRuntime, fixture.runtime_id)
        assert runtime is not None
        runtime.runner_state = RuntimeRunnerState.READY
        runner_operations = _FakeRunnerOperations()
        service = _service(
            rdb_session,
            runner_operations=runner_operations,
        )

        result = await service.register_existing_folder_for_session(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            user_id=user_id,
            path="/tmp/not-project",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, InvalidProjectPath)
        assert runner_operations.paths == []

    async def test_register_existing_folder_creates_project(
        self, rdb_session: AsyncSession
    ) -> None:
        """Register existing runtime directory as Project."""
        workspace_id = await _create_workspace(rdb_session, "swp-svc-register")
        fixture = await _create_runtime_fixture(
            rdb_session,
            workspace_id,
            "swp-svc-register",
        )
        user_id = await _create_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            email="swp-svc-register@example.com",
        )
        runtime = await rdb_session.get(RDBAgentRuntime, fixture.runtime_id)
        assert runtime is not None
        runtime.runner_state = RuntimeRunnerState.READY
        runner_operations = _FakeRunnerOperations()
        service = _service(
            rdb_session,
            runner_operations=runner_operations,
        )

        result = await service.register_existing_folder_for_session(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            user_id=user_id,
            path="/workspace/agent/app",
        )

        assert isinstance(result, Success)
        assert result.value.session_id == fixture.session_id
        assert result.value.path == "/workspace/agent/app"
        presets = await AgentProjectPresetRepository().list_presets(
            rdb_session,
            agent_id=fixture.agent_id,
        )
        catalog_entries = await AgentProjectCatalogRepository().list_entries(
            rdb_session,
            agent_id=fixture.agent_id,
        )
        assert [preset.path for preset in presets] == ["/workspace/agent/app"]
        assert [entry.path for entry in catalog_entries] == ["/workspace/agent/app"]
        assert catalog_entries[0].status == AgentProjectCatalogStatus.AVAILABLE
        assert catalog_entries[0].checked_at is not None
        assert runner_operations.paths == ["/workspace/agent/app"]

    async def test_list_projects_for_session_requires_matching_agent(
        self, rdb_session: AsyncSession
    ) -> None:
        """Reject Project list fetch when session is not owned by Agent."""
        workspace_id = await _create_workspace(rdb_session, "swp-svc-agent-mismatch")
        fixture = await _create_runtime_fixture(
            rdb_session,
            workspace_id,
            "swp-svc-agent-mismatch",
        )
        user_id = await _create_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            email="swp-svc-agent-mismatch@example.com",
        )
        service = _service(rdb_session)

        result = await service.list_projects_for_session(
            agent_id="0123456789abcdef0123456789abcdef",
            session_id=fixture.session_id,
            user_id=user_id,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProjectAccessDenied)

    async def test_list_projects_for_session_requires_workspace_member(
        self, rdb_session: AsyncSession
    ) -> None:
        """Reject Project list fetch for user without Workspace membership."""
        workspace_id = await _create_workspace(rdb_session, "swp-svc-access-denied")
        fixture = await _create_runtime_fixture(
            rdb_session,
            workspace_id,
            "swp-svc-access-denied",
        )
        service = _service(rdb_session)

        result = await service.list_projects_for_session(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            user_id="external-user",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProjectAccessDenied)

    async def test_list_projects_for_session_returns_registered_projects(
        self, rdb_session: AsyncSession
    ) -> None:
        """Workspace member fetches Project list registered in selected session."""
        workspace_id = await _create_workspace(rdb_session, "swp-svc-access-list")
        fixture = await _create_runtime_fixture(
            rdb_session,
            workspace_id,
            "swp-svc-access-list",
        )
        user_id = await _create_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            email="swp-svc-access-list@example.com",
        )
        service = _service(rdb_session)
        created = await service.create_project(
            session_id=fixture.session_id,
            path="/workspace/agent/app",
        )
        assert isinstance(created, Success)

        result = await service.list_projects_for_session(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            user_id=user_id,
        )

        assert isinstance(result, Success)
        assert [project.path for project in result.value] == ["/workspace/agent/app"]
