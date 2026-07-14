"""SessionWorkspaceProjectService tests."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentProjectCatalogStatus,
    AgentSessionStatus,
    LLMProvider,
    RuntimeRunnerState,
    WorkspaceUserRole,
)
from azents.engine.tools.skill import SkillProjectionService, SkillStateStore
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
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
        self.active_scopes = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[AsyncSession]:
        """Return same session as context manager."""
        self.active_scopes += 1
        try:
            yield self._session
        finally:
            self.active_scopes -= 1


@dataclasses.dataclass(frozen=True)
class _RuntimeFixture:
    """AgentRuntime fixture for tests."""

    agent_id: str
    runtime_id: str
    session_id: str


class _FakeRunnerOperations(RuntimeRunnerOperationClient):
    """Runner operation fake for tests."""

    def __init__(self, session_manager: _SessionManager | None = None) -> None:
        self.paths: list[str] = []
        self.session_manager = session_manager

    async def list_files(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        path: str,
        recursive: bool = False,
        exclude_patterns: list[str] | None = None,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileListResult:
        """Treat Directory existence check as success."""
        del runtime_id, runner_generation, recursive, exclude_patterns, deadline_at
        if self.session_manager is not None:
            assert self.session_manager.active_scopes == 0
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
    session_manager: _SessionManager | None = None,
    skill_store: SkillStateStore | None = None,
) -> SessionWorkspaceProjectService:
    """Create service for tests."""
    return SessionWorkspaceProjectService(
        repository=SessionWorkspaceProjectRepository(),
        agent_project_preset_repository=AgentProjectPresetRepository(),
        agent_project_catalog_repository=AgentProjectCatalogRepository(),
        agent_runtime_repository=AgentRuntimeRepository(),
        agent_session_repository=AgentSessionRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        session_manager=session_manager or _SessionManager(session),
        runner_operations=runner_operations,
        skill_store=skill_store,
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

    async def test_runner_directory_check_and_projection_never_hold_db_scope(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Runtime I/O is detached and a hung post-commit projection is bounded."""

        async def hang_sync(*args: object, **kwargs: object) -> None:
            del args, kwargs
            await asyncio.Event().wait()

        monkeypatch.setattr(SkillProjectionService, "sync_latest", hang_sync)
        monkeypatch.setattr(
            "azents.services.session_workspace_project."
            "_POST_COMMIT_PROJECTION_TIMEOUT_SECONDS",
            0.01,
        )
        fake_session = SimpleNamespace(commit=AsyncMock())
        session_manager = _SessionManager(cast(AsyncSession, fake_session))
        runner_operations = _FakeRunnerOperations(session_manager)
        repository = AsyncMock()
        repository.get_project_by_path.return_value = None
        repository.create_project.return_value = SimpleNamespace(
            id="project-1",
            session_id="session-1",
            path="/workspace/agent/app",
        )
        lock_order: list[str] = []
        agent_session = SimpleNamespace(
            id="session-1",
            agent_id="agent-1",
            workspace_id="workspace-1",
            status=AgentSessionStatus.ACTIVE,
        )
        agent_session_repository = AsyncMock()
        agent_session_repository.get_by_id.return_value = agent_session

        async def lock_session(*args: object, **kwargs: object) -> object:
            del args, kwargs
            lock_order.append("session")
            return agent_session

        agent_session_repository.lock_by_id.side_effect = lock_session
        workspace_user_repository = AsyncMock()
        workspace_user_repository.get_by_workspace_and_user.return_value = object()

        async def lock_membership(*args: object, **kwargs: object) -> object:
            del args, kwargs
            lock_order.append("membership")
            return object()

        workspace_user_repository.lock_by_workspace_and_user.side_effect = (
            lock_membership
        )
        runtime = SimpleNamespace(
            id="runtime-1",
            runner_generation=7,
            runner_state=RuntimeRunnerState.READY,
        )
        runtime_repository = AsyncMock()
        runtime_repository.get_by_agent_id.return_value = runtime

        async def lock_runtime(*args: object, **kwargs: object) -> object:
            del args, kwargs
            lock_order.append("runtime")
            return runtime

        runtime_repository.lock_by_agent_id.side_effect = lock_runtime
        service = SessionWorkspaceProjectService(
            repository=cast(SessionWorkspaceProjectRepository, repository),
            agent_project_preset_repository=cast(
                AgentProjectPresetRepository, AsyncMock()
            ),
            agent_project_catalog_repository=cast(
                AgentProjectCatalogRepository, AsyncMock()
            ),
            agent_runtime_repository=cast(AgentRuntimeRepository, runtime_repository),
            agent_session_repository=cast(
                AgentSessionRepository, agent_session_repository
            ),
            workspace_user_repository=cast(
                WorkspaceUserRepository, workspace_user_repository
            ),
            session_manager=cast(SessionManager[AsyncSession], session_manager),
            runner_operations=runner_operations,
            skill_store=cast(SkillStateStore, object()),
        )

        result = await asyncio.wait_for(
            service.register_existing_folder_for_session(
                agent_id="agent-1",
                session_id="session-1",
                user_id="user-1",
                path="/workspace/agent/app",
            ),
            timeout=0.5,
        )

        assert isinstance(result, Success)
        assert runner_operations.paths == ["/workspace/agent/app"]
        assert session_manager.active_scopes == 0
        assert repository.create_project.await_count == 1
        assert lock_order == ["runtime", "session", "membership"]

    async def test_delete_returns_after_hung_post_commit_invalidation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Committed deletion succeeds even if Skill invalidation never responds."""
        monkeypatch.setattr(
            "azents.services.session_workspace_project."
            "_POST_COMMIT_PROJECTION_TIMEOUT_SECONDS",
            0.01,
        )
        fake_session = SimpleNamespace(commit=AsyncMock())
        session_manager = _SessionManager(cast(AsyncSession, fake_session))
        repository = AsyncMock()
        repository.get_project_by_id.return_value = SimpleNamespace(
            id="project-1",
            session_id="session-1",
            path="/workspace/agent/app",
        )
        repository.delete_project.return_value = True
        agent_session = SimpleNamespace(
            id="session-1",
            agent_id="agent-1",
            workspace_id="workspace-1",
            status=AgentSessionStatus.ACTIVE,
        )
        agent_session_repository = AsyncMock()
        agent_session_repository.get_by_id.return_value = agent_session
        agent_session_repository.lock_by_id.return_value = agent_session
        workspace_user_repository = AsyncMock()
        workspace_user_repository.get_by_workspace_and_user.return_value = object()
        workspace_user_repository.lock_by_workspace_and_user.return_value = object()
        skill_store = AsyncMock(spec=SkillStateStore)

        async def hang_invalidation(*args: object, **kwargs: object) -> None:
            del args, kwargs
            await asyncio.Event().wait()

        skill_store.invalidate_project.side_effect = hang_invalidation
        service = SessionWorkspaceProjectService(
            repository=cast(SessionWorkspaceProjectRepository, repository),
            agent_project_preset_repository=cast(
                AgentProjectPresetRepository, AsyncMock()
            ),
            agent_project_catalog_repository=cast(
                AgentProjectCatalogRepository, AsyncMock()
            ),
            agent_runtime_repository=cast(AgentRuntimeRepository, AsyncMock()),
            agent_session_repository=cast(
                AgentSessionRepository, agent_session_repository
            ),
            workspace_user_repository=cast(
                WorkspaceUserRepository, workspace_user_repository
            ),
            session_manager=cast(SessionManager[AsyncSession], session_manager),
            skill_store=cast(SkillStateStore, skill_store),
        )

        result = await asyncio.wait_for(
            service.delete_project_for_session(
                agent_id="agent-1",
                session_id="session-1",
                user_id="user-1",
                project_id="project-1",
            ),
            timeout=0.5,
        )

        assert isinstance(result, Success)
        repository.delete_project.assert_awaited_once()
        fake_session.commit.assert_awaited_once()
        skill_store.invalidate_project.assert_awaited_once()
        assert session_manager.active_scopes == 0

    async def test_delete_rechecks_membership_under_final_session_lock(self) -> None:
        """Membership revoke wins before any Project deletion mutation."""
        fake_session = SimpleNamespace(commit=AsyncMock())
        session_manager = _SessionManager(cast(AsyncSession, fake_session))
        repository = AsyncMock()
        agent_session_repository = AsyncMock()
        agent_session_repository.lock_by_id.return_value = SimpleNamespace(
            id="session-1",
            agent_id="agent-1",
            workspace_id="workspace-1",
            status=AgentSessionStatus.ACTIVE,
        )
        workspace_user_repository = AsyncMock()
        workspace_user_repository.lock_by_workspace_and_user.return_value = None
        service = SessionWorkspaceProjectService(
            repository=cast(SessionWorkspaceProjectRepository, repository),
            agent_project_preset_repository=cast(
                AgentProjectPresetRepository, AsyncMock()
            ),
            agent_project_catalog_repository=cast(
                AgentProjectCatalogRepository, AsyncMock()
            ),
            agent_runtime_repository=cast(AgentRuntimeRepository, AsyncMock()),
            agent_session_repository=cast(
                AgentSessionRepository, agent_session_repository
            ),
            workspace_user_repository=cast(
                WorkspaceUserRepository, workspace_user_repository
            ),
            session_manager=cast(SessionManager[AsyncSession], session_manager),
        )

        result = await service.delete_project_for_session(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            project_id="project-1",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProjectAccessDenied)
        repository.get_project_by_id.assert_not_awaited()
        repository.delete_project.assert_not_awaited()
        fake_session.commit.assert_not_awaited()

    async def test_register_existing_folder_rejects_concurrent_runtime_rotation(
        self,
    ) -> None:
        """A Runner result cannot commit against a replaced Runtime generation."""
        fake_session = SimpleNamespace(commit=AsyncMock())
        session_manager = _SessionManager(cast(AsyncSession, fake_session))
        repository = AsyncMock()
        repository.get_project_by_path.return_value = None
        agent_session = SimpleNamespace(
            id="session-1",
            agent_id="agent-1",
            workspace_id="workspace-1",
            status=AgentSessionStatus.ACTIVE,
        )
        agent_session_repository = AsyncMock()
        agent_session_repository.get_by_id.return_value = agent_session
        agent_session_repository.lock_by_id.return_value = agent_session
        workspace_user_repository = AsyncMock()
        workspace_user_repository.get_by_workspace_and_user.return_value = object()
        workspace_user_repository.lock_by_workspace_and_user.return_value = object()
        runtime_repository = AsyncMock()
        runtime_repository.get_by_agent_id.return_value = SimpleNamespace(
            id="runtime-1",
            runner_generation=7,
            runner_state=RuntimeRunnerState.READY,
        )
        runtime_repository.lock_by_agent_id.return_value = SimpleNamespace(
            id="runtime-1",
            runner_generation=8,
            runner_state=RuntimeRunnerState.READY,
        )
        service = SessionWorkspaceProjectService(
            repository=cast(SessionWorkspaceProjectRepository, repository),
            agent_project_preset_repository=cast(
                AgentProjectPresetRepository, AsyncMock()
            ),
            agent_project_catalog_repository=cast(
                AgentProjectCatalogRepository, AsyncMock()
            ),
            agent_runtime_repository=cast(AgentRuntimeRepository, runtime_repository),
            agent_session_repository=cast(
                AgentSessionRepository, agent_session_repository
            ),
            workspace_user_repository=cast(
                WorkspaceUserRepository, workspace_user_repository
            ),
            session_manager=cast(SessionManager[AsyncSession], session_manager),
            runner_operations=_FakeRunnerOperations(session_manager),
        )

        result = await service.register_existing_folder_for_session(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            path="/workspace/agent/app",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, InvalidProjectPath)
        assert "Runtime changed" in result.error.reason
        repository.create_project.assert_not_awaited()

    @pytest.mark.parametrize("authority", ["session", "membership"])
    async def test_register_existing_folder_rejects_concurrent_access_revocation(
        self,
        authority: str,
    ) -> None:
        """A session archive or membership removal wins before registration."""
        fake_session = SimpleNamespace(commit=AsyncMock())
        session_manager = _SessionManager(cast(AsyncSession, fake_session))
        repository = AsyncMock()
        repository.get_project_by_path.return_value = None
        active_session = SimpleNamespace(
            id="session-1",
            agent_id="agent-1",
            workspace_id="workspace-1",
            status=AgentSessionStatus.ACTIVE,
        )
        agent_session_repository = AsyncMock()
        agent_session_repository.get_by_id.return_value = active_session
        agent_session_repository.lock_by_id.return_value = (
            active_session
            if authority == "membership"
            else SimpleNamespace(
                id="session-1",
                agent_id="agent-1",
                workspace_id="workspace-1",
                status=AgentSessionStatus.ARCHIVED,
            )
        )
        workspace_user_repository = AsyncMock()
        workspace_user_repository.get_by_workspace_and_user.return_value = object()
        workspace_user_repository.lock_by_workspace_and_user.return_value = (
            None if authority == "membership" else object()
        )
        runtime = SimpleNamespace(
            id="runtime-1",
            runner_generation=7,
            runner_state=RuntimeRunnerState.READY,
        )
        runtime_repository = AsyncMock()
        runtime_repository.get_by_agent_id.return_value = runtime
        runtime_repository.lock_by_agent_id.return_value = runtime
        service = SessionWorkspaceProjectService(
            repository=cast(SessionWorkspaceProjectRepository, repository),
            agent_project_preset_repository=cast(
                AgentProjectPresetRepository, AsyncMock()
            ),
            agent_project_catalog_repository=cast(
                AgentProjectCatalogRepository, AsyncMock()
            ),
            agent_runtime_repository=cast(AgentRuntimeRepository, runtime_repository),
            agent_session_repository=cast(
                AgentSessionRepository, agent_session_repository
            ),
            workspace_user_repository=cast(
                WorkspaceUserRepository, workspace_user_repository
            ),
            session_manager=cast(SessionManager[AsyncSession], session_manager),
            runner_operations=_FakeRunnerOperations(session_manager),
        )

        result = await service.register_existing_folder_for_session(
            agent_id="agent-1",
            session_id="session-1",
            user_id="user-1",
            path="/workspace/agent/app",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProjectAccessDenied)
        repository.create_project.assert_not_awaited()

    async def test_project_creation_projection_failure_is_post_commit_best_effort(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A projection outage cannot turn committed Project creation into failure."""

        async def fail_sync(*args: object, **kwargs: object) -> None:
            del args, kwargs
            msg = "projection unavailable"
            raise RuntimeError(msg)

        monkeypatch.setattr(SkillProjectionService, "sync_latest", fail_sync)
        service = SessionWorkspaceProjectService(
            repository=cast(SessionWorkspaceProjectRepository, AsyncMock()),
            agent_project_preset_repository=cast(
                AgentProjectPresetRepository, AsyncMock()
            ),
            agent_project_catalog_repository=cast(
                AgentProjectCatalogRepository, AsyncMock()
            ),
            agent_runtime_repository=cast(AgentRuntimeRepository, AsyncMock()),
            agent_session_repository=cast(AgentSessionRepository, AsyncMock()),
            workspace_user_repository=cast(WorkspaceUserRepository, AsyncMock()),
            session_manager=cast(SessionManager[AsyncSession], AsyncMock()),
            runner_operations=_FakeRunnerOperations(),
            skill_store=cast(SkillStateStore, object()),
        )

        await service._sync_skill_projection_for_project_change(  # pyright: ignore[reportPrivateUsage]  # Verify the post-commit projection boundary directly.
            agent_id="agent-1",
            session_id="session-1",
        )

    async def test_project_creation_projection_hang_is_bounded(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A hung projection cannot hold an already committed Project response."""

        async def hang_sync(*args: object, **kwargs: object) -> None:
            del args, kwargs
            await asyncio.Event().wait()

        monkeypatch.setattr(SkillProjectionService, "sync_latest", hang_sync)
        monkeypatch.setattr(
            "azents.services.session_workspace_project."
            "_POST_COMMIT_PROJECTION_TIMEOUT_SECONDS",
            0.01,
        )
        service = SessionWorkspaceProjectService(
            repository=cast(SessionWorkspaceProjectRepository, AsyncMock()),
            agent_project_preset_repository=cast(
                AgentProjectPresetRepository, AsyncMock()
            ),
            agent_project_catalog_repository=cast(
                AgentProjectCatalogRepository, AsyncMock()
            ),
            agent_runtime_repository=cast(AgentRuntimeRepository, AsyncMock()),
            agent_session_repository=cast(AgentSessionRepository, AsyncMock()),
            workspace_user_repository=cast(WorkspaceUserRepository, AsyncMock()),
            session_manager=cast(SessionManager[AsyncSession], AsyncMock()),
            runner_operations=_FakeRunnerOperations(),
            skill_store=cast(SkillStateStore, object()),
        )

        await asyncio.wait_for(
            service._sync_skill_projection_for_project_change(  # pyright: ignore[reportPrivateUsage]  # Verify the hard post-commit deadline directly.
                agent_id="agent-1",
                session_id="session-1",
            ),
            timeout=0.5,
        )

    async def test_project_creation_projection_preserves_caller_cancellation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The post-commit deadline never converts caller cancellation to success."""

        async def cancel_sync(*args: object, **kwargs: object) -> None:
            del args, kwargs
            raise asyncio.CancelledError("caller cancelled")

        monkeypatch.setattr(SkillProjectionService, "sync_latest", cancel_sync)
        service = SessionWorkspaceProjectService(
            repository=cast(SessionWorkspaceProjectRepository, AsyncMock()),
            agent_project_preset_repository=cast(
                AgentProjectPresetRepository, AsyncMock()
            ),
            agent_project_catalog_repository=cast(
                AgentProjectCatalogRepository, AsyncMock()
            ),
            agent_runtime_repository=cast(AgentRuntimeRepository, AsyncMock()),
            agent_session_repository=cast(AgentSessionRepository, AsyncMock()),
            workspace_user_repository=cast(WorkspaceUserRepository, AsyncMock()),
            session_manager=cast(SessionManager[AsyncSession], AsyncMock()),
            runner_operations=_FakeRunnerOperations(),
            skill_store=cast(SkillStateStore, object()),
        )

        with pytest.raises(asyncio.CancelledError, match="caller cancelled"):
            await service._sync_skill_projection_for_project_change(  # pyright: ignore[reportPrivateUsage]  # Verify cancellation semantics directly.
                agent_id="agent-1",
                session_id="session-1",
            )

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
        session_manager = _SessionManager(rdb_session)
        runner_operations = _FakeRunnerOperations(session_manager)
        service = _service(
            rdb_session,
            runner_operations=runner_operations,
            session_manager=session_manager,
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
        session_manager = _SessionManager(rdb_session)
        runner_operations = _FakeRunnerOperations(session_manager)
        service = _service(
            rdb_session,
            runner_operations=runner_operations,
            session_manager=session_manager,
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
        assert session_manager.active_scopes == 0

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
