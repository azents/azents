"""Project browser manifest service tests."""

import dataclasses
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentProjectCatalogStatus,
    LLMProvider,
    SessionGitWorktreeBranchCreatedBy,
    SessionGitWorktreeStatus,
    WorkspaceUserRole,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent import AgentRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.data import AgentProjectCatalogStatusPatch
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_git_worktree.data import SessionGitWorktreeCreate
from azents.repos.session_initialization import SessionInitializationRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProjectCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.services.agent_project_catalog import AgentProjectCatalogService
from azents.testing.model_selection import make_test_model_selection_dict

from .project_browser_manifest import (
    ProjectBrowserAccessDenied,
    ProjectBrowserManifestService,
    ProjectBrowserSessionNotFound,
)


class _SessionManager:
    """Session manager for tests."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[AsyncSession]:
        """Return the same session as context manager."""
        yield self.session


@dataclasses.dataclass(frozen=True)
class _Fixture:
    """Project browser manifest fixture."""

    agent_id: str
    session_id: str
    user_id: str


async def _create_fixture(
    session: AsyncSession,
    slug: str,
    *,
    create_workspace_user: bool = True,
) -> _Fixture:
    """Create workspace, agent, team primary session, and optional member."""
    workspace_repo = WorkspaceRepository()
    result = await workspace_repo.create(
        session,
        WorkspaceCreate(name="Project browser manifest", handle=slug),
    )
    assert isinstance(result, Success)
    workspace_id = await workspace_repo.resolve_id(session, slug)
    assert workspace_id is not None

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
        name="Project browser manifest agent",
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

    user_id = "external-user"
    if create_workspace_user:
        user = await UserRepository().create(
            session,
            UserCreate(email=f"{slug}@example.com"),
        )
        workspace_user = await WorkspaceUserRepository().create(
            session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id=user.id,
                name="Project browser manifest user",
                role=WorkspaceUserRole.MEMBER,
            ),
        )
        assert isinstance(workspace_user, Success)
        user_id = user.id

    return _Fixture(agent_id=agent.id, session_id=agent_session.id, user_id=user_id)


def _service(session: AsyncSession) -> ProjectBrowserManifestService:
    """Create service for tests."""
    session_manager = _SessionManager(session)
    catalog_repository = AgentProjectCatalogRepository()
    return ProjectBrowserManifestService(
        agent_repository=AgentRepository(),
        agent_session_repository=AgentSessionRepository(),
        project_repository=SessionWorkspaceProjectRepository(),
        worktree_repository=SessionGitWorktreeRepository(),
        catalog_repository=catalog_repository,
        workspace_user_repository=WorkspaceUserRepository(),
        catalog_service=AgentProjectCatalogService(
            catalog_repository=catalog_repository,
            agent_runtime_repository=AgentRuntimeRepository(),
            session_manager=session_manager,
            runner_operations=None,
        ),
        session_manager=session_manager,
    )


class TestProjectBrowserManifestService:
    """ProjectBrowserManifestService behavior."""

    async def test_session_manifest_returns_project_entries_with_capabilities(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Existing-session manifest returns Project roots and backend action policy."""
        fixture = await _create_fixture(rdb_session, "pbm-session")
        project = await SessionWorkspaceProjectRepository().create_project(
            rdb_session,
            SessionWorkspaceProjectCreate(
                session_id=fixture.session_id,
                path="/workspace/agent/app",
            ),
        )
        checked_at = datetime.datetime.now(datetime.UTC)
        await AgentProjectCatalogRepository().update_status(
            rdb_session,
            agent_id=fixture.agent_id,
            path="/workspace/agent/app",
            patch=AgentProjectCatalogStatusPatch(
                status=AgentProjectCatalogStatus.AVAILABLE,
                status_detail=None,
                checked_at=checked_at,
            ),
        )

        result = await _service(rdb_session).get_session_manifest(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            user_id=fixture.user_id,
        )

        assert isinstance(result, Success)
        assert result.value.refresh_paths == []
        manifest = result.value.manifest
        assert manifest.active_mode == "projects"
        assert [entry.path for entry in manifest.entries] == ["/workspace/agent/app"]
        entry = manifest.entries[0]
        assert entry.name == "app"
        assert entry.repository_type is None
        assert entry.source.type == "session_project"
        assert entry.source.project_id == project.id
        assert entry.status.value == AgentProjectCatalogStatus.AVAILABLE
        assert entry.status.checked_at == checked_at
        assert entry.capabilities.remove_project is True
        assert entry.capabilities.filesystem_delete is False
        assert entry.capabilities.filesystem_move is False
        assert entry.capabilities.filesystem_rename is False

    async def test_session_manifest_marks_git_worktree_projects(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Project roots linked to Git worktree allocations expose Git metadata."""
        fixture = await _create_fixture(rdb_session, "pbm-git-worktree")
        project = await SessionWorkspaceProjectRepository().create_project(
            rdb_session,
            SessionWorkspaceProjectCreate(
                session_id=fixture.session_id,
                path="/workspace/agent/.azents/worktrees/session-1/app",
            ),
        )
        initialization = (
            await SessionInitializationRepository().create_ready_noop_if_absent(
                rdb_session,
                session_id=fixture.session_id,
                completed_at=datetime.datetime.now(datetime.UTC),
            )
        )
        steps = await SessionInitializationRepository().list_steps(
            rdb_session,
            initialization_id=initialization.id,
        )
        await SessionGitWorktreeRepository().create(
            rdb_session,
            SessionGitWorktreeCreate(
                id="0123456789abcdef0123456789abcdef",
                session_id=fixture.session_id,
                initialization_id=initialization.id,
                step_id=steps[0].id,
                session_workspace_project_id=project.id,
                source_project_path="/workspace/agent/app",
                starting_ref="main",
                worktree_path="/workspace/agent/.azents/worktrees/session-1/app",
                branch_name="azents/session-1-app",
                branch_created_by=SessionGitWorktreeBranchCreatedBy.AZENTS,
                status=SessionGitWorktreeStatus.READY,
            ),
        )

        result = await _service(rdb_session).get_session_manifest(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            user_id=fixture.user_id,
        )

        assert isinstance(result, Success)
        assert [entry.repository_type for entry in result.value.manifest.entries] == [
            "git"
        ]

    async def test_session_manifest_empty_projects_has_empty_state(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Empty Project sessions do not fall back to Agent Workspace root entries."""
        fixture = await _create_fixture(rdb_session, "pbm-empty")

        result = await _service(rdb_session).get_session_manifest(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            user_id=fixture.user_id,
        )

        assert isinstance(result, Success)
        assert result.value.manifest.entries == []
        assert result.value.manifest.empty_state is not None
        assert result.value.manifest.root == "/workspace/agent"
        assert [mode.id for mode in result.value.manifest.modes] == [
            "projects",
            "all_files",
        ]

    async def test_preview_manifest_normalizes_and_marks_missing_projection_stale(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Pre-session preview uses the same entry model without a session row."""
        fixture = await _create_fixture(rdb_session, "pbm-preview")

        result = await _service(rdb_session).preview_manifest(
            agent_id=fixture.agent_id,
            user_id=fixture.user_id,
            project_paths=["/workspace/agent/app/../app", "/workspace/agent/app"],
        )

        assert isinstance(result, Success)
        assert result.value.manifest.session_id is None
        assert [entry.path for entry in result.value.manifest.entries] == [
            "/workspace/agent/app"
        ]
        entry = result.value.manifest.entries[0]
        assert entry.repository_type is None
        assert entry.source.type == "preview_project"
        assert entry.source.project_id is None
        assert entry.status.value == AgentProjectCatalogStatus.UNCHECKED
        assert entry.status.stale is True
        assert entry.capabilities.remove_project is False
        assert result.value.refresh_paths == ["/workspace/agent/app"]

    async def test_session_manifest_rejects_agent_mismatch(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Existing-session manifests require a matching AgentSession Agent."""
        fixture = await _create_fixture(rdb_session, "pbm-agent-mismatch")

        result = await _service(rdb_session).get_session_manifest(
            agent_id="0123456789abcdef0123456789abcdef",
            session_id=fixture.session_id,
            user_id=fixture.user_id,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProjectBrowserSessionNotFound)

    async def test_session_manifest_rejects_non_member(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Existing-session manifests require workspace membership."""
        fixture = await _create_fixture(
            rdb_session,
            "pbm-non-member",
            create_workspace_user=False,
        )

        result = await _service(rdb_session).get_session_manifest(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            user_id=fixture.user_id,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProjectBrowserAccessDenied)
