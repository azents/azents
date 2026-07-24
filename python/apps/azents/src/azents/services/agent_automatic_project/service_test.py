"""Agent automatic Project policy management service tests."""

import dataclasses
import datetime
from collections.abc import AsyncGenerator, Awaitable, Callable
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
from azents.rdb.models.agent_automatic_project_setting import (
    RDBAgentAutomaticProjectSetting,
)
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_admin.data import AgentAdminCreate
from azents.repos.agent_automatic_project import AgentAutomaticProjectRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.runtime.control_protocol.runner_operations import (
    RuntimeFileStatResult,
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
)
from azents.services.agent.data import NotAdmin
from azents.services.session_workspace_project import InvalidProjectPath
from azents.testing.model_selection import make_test_model_selection_dict

from . import AgentAutomaticProjectService
from .data import (
    AutomaticSessionProjectsRevisionConflict,
    AutomaticSessionProjectsRuntimeUnavailable,
)


@dataclasses.dataclass
class _TrackingSessionManager:
    """Wrap a session manager and expose whether a service session is open."""

    wrapped: SessionManager[AsyncSession]
    active_contexts: int = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[AsyncSession]:
        """Yield one database session while tracking its context lifetime."""
        self.active_contexts += 1
        try:
            async with self.wrapped() as session:
                yield session
        finally:
            self.active_contexts -= 1


@dataclasses.dataclass(frozen=True)
class _Fixture:
    """Persisted policy service test fixture identities."""

    workspace_id: str
    agent_id: str
    admin_workspace_user_id: str
    owner_workspace_user_id: str


class _FakeRunnerOperations(RuntimeRunnerOperationClient):
    """Runtime Runner fake returning a configured stat result."""

    def __init__(
        self,
        *,
        session_manager: _TrackingSessionManager,
        kind: str = "directory",
        error_code: str | None = None,
        on_stat: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.session_manager = session_manager
        self.kind = kind
        self.error_code = error_code
        self.on_stat = on_stat
        self.paths: list[str] = []
        self.owner_session_ids: list[str | None] = []
        self.transaction_context_counts: list[int] = []

    async def stat_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileStatResult:
        """Record validation context and return one configured file kind."""
        del runtime_id, runner_generation, deadline_at
        self.paths.append(path)
        self.owner_session_ids.append(owner_session_id)
        self.transaction_context_counts.append(self.session_manager.active_contexts)
        if self.on_stat is not None:
            await self.on_stat()
        if self.error_code is not None:
            raise RuntimeRunnerOperationFailedError(
                "Runtime stat failed.",
                code=self.error_code,
            )
        if self.kind == "missing":
            return RuntimeFileStatResult(
                path=path,
                kind="missing",
                size_bytes=None,
                symlink=False,
                real_path=None,
                resolved_kind=None,
                modified_at=None,
                final_cursor="0",
            )
        if self.kind == "file":
            return RuntimeFileStatResult(
                path=path,
                kind="file",
                size_bytes=1,
                symlink=False,
                real_path=None,
                resolved_kind="file",
                modified_at=None,
                final_cursor="0",
            )
        return RuntimeFileStatResult(
            path=path,
            kind="directory",
            size_bytes=None,
            symlink=False,
            real_path=None,
            resolved_kind="directory",
            modified_at=None,
            final_cursor="0",
        )


async def _create_workspace(
    session: AsyncSession,
    *,
    handle: str,
) -> str:
    """Create a Workspace and return its ID."""
    result = await WorkspaceRepository().create(
        session,
        WorkspaceCreate(name="Automatic Project policy service", handle=handle),
    )
    assert isinstance(result, Success)
    workspace_id = await WorkspaceRepository().resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_workspace_user(
    session: AsyncSession,
    *,
    workspace_id: str,
    email: str,
    role: WorkspaceUserRole,
) -> str:
    """Create a WorkspaceUser and return its ID."""
    user = await UserRepository().create(session, UserCreate(email=email))
    result = await WorkspaceUserRepository().create(
        session,
        WorkspaceUserCreate(
            workspace_id=workspace_id,
            user_id=user.id,
            name="Automatic Project policy user",
            role=role,
        ),
    )
    assert isinstance(result, Success)
    return result.value.id


async def _create_fixture(
    session_manager: SessionManager[AsyncSession],
    *,
    handle: str,
) -> _Fixture:
    """Create an Agent with its empty revision-one policy and Runtime."""
    async with session_manager() as session:
        workspace_id = await _create_workspace(session, handle=handle)
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
            name="Automatic Project policy Agent",
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
        session.add(RDBAgentAutomaticProjectSetting(agent_id=agent.id))
        admin_workspace_user_id = await _create_workspace_user(
            session,
            workspace_id=workspace_id,
            email=f"{handle}-admin@example.com",
            role=WorkspaceUserRole.MEMBER,
        )
        admin_result = await AgentAdminRepository().create(
            session,
            AgentAdminCreate(
                agent_id=agent.id,
                workspace_user_id=admin_workspace_user_id,
            ),
        )
        assert isinstance(admin_result, Success)
        owner_workspace_user_id = await _create_workspace_user(
            session,
            workspace_id=workspace_id,
            email=f"{handle}-owner@example.com",
            role=WorkspaceUserRole.OWNER,
        )
        runtime = await AgentRuntimeRepository().ensure_for_agent(session, agent.id)
        rdb_runtime = await session.get(RDBAgentRuntime, runtime.id)
        assert rdb_runtime is not None
        rdb_runtime.runner_state = RuntimeRunnerState.READY
        return _Fixture(
            workspace_id=workspace_id,
            agent_id=agent.id,
            admin_workspace_user_id=admin_workspace_user_id,
            owner_workspace_user_id=owner_workspace_user_id,
        )


def _service(
    session_manager: _TrackingSessionManager,
    *,
    runner_operations: RuntimeRunnerOperationClient | None,
) -> AgentAutomaticProjectService:
    """Create the management service with real repositories."""
    return AgentAutomaticProjectService(
        agent_repository=AgentRepository(),
        agent_admin_repository=AgentAdminRepository(),
        policy_repository=AgentAutomaticProjectRepository(),
        catalog_repository=AgentProjectCatalogRepository(),
        runtime_repository=AgentRuntimeRepository(),
        session_manager=session_manager,
        runner_operations=runner_operations,
    )


class TestAgentAutomaticProjectService:
    """Agent automatic Project policy management behavior."""

    async def test_get_requires_explicit_agent_admin_without_runtime_io(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Workspace ownership alone does not grant policy read access."""
        fixture = await _create_fixture(
            rdb_session_manager,
            handle="automatic-project-get-owner",
        )
        session_manager = _TrackingSessionManager(rdb_session_manager)
        runner = _FakeRunnerOperations(session_manager=session_manager)
        service = _service(session_manager, runner_operations=runner)

        owner_result = await service.get_policy(
            agent_id=fixture.agent_id,
            workspace_id=fixture.workspace_id,
            workspace_user_id=fixture.owner_workspace_user_id,
        )
        admin_result = await service.get_policy(
            agent_id=fixture.agent_id,
            workspace_id=fixture.workspace_id,
            workspace_user_id=fixture.admin_workspace_user_id,
        )

        assert isinstance(owner_result, Failure)
        assert isinstance(owner_result.error, NotAdmin)
        assert isinstance(admin_result, Success)
        assert admin_result.value.revision == 1
        assert admin_result.value.project_paths == ()
        assert runner.paths == []

    async def test_replace_normalizes_deduplicates_and_updates_catalog(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Valid replacement preserves normalized order and catalog status."""
        fixture = await _create_fixture(
            rdb_session_manager,
            handle="automatic-project-replace",
        )
        session_manager = _TrackingSessionManager(rdb_session_manager)
        runner = _FakeRunnerOperations(session_manager=session_manager)
        service = _service(session_manager, runner_operations=runner)

        result = await service.replace_policy(
            agent_id=fixture.agent_id,
            workspace_id=fixture.workspace_id,
            workspace_user_id=fixture.admin_workspace_user_id,
            expected_revision=1,
            project_paths=[
                "/workspace/agent/payments/../payments",
                "/workspace/agent/orders",
                "/workspace/agent/payments",
            ],
        )

        assert isinstance(result, Success)
        assert result.value.revision == 2
        assert result.value.project_paths == (
            "/workspace/agent/payments",
            "/workspace/agent/orders",
        )
        assert runner.paths == ["/workspace/agent/payments", "/workspace/agent/orders"]
        assert runner.owner_session_ids == [None, None]
        assert runner.transaction_context_counts == [0, 0]
        async with rdb_session_manager() as session:
            persisted = await AgentAutomaticProjectRepository().get_policy(
                session,
                agent_id=fixture.agent_id,
            )
            entries = await AgentProjectCatalogRepository().list_entries(
                session,
                agent_id=fixture.agent_id,
            )
        assert persisted is not None
        assert persisted.project_paths == result.value.project_paths
        assert {entry.path for entry in entries} == {
            "/workspace/agent/payments",
            "/workspace/agent/orders",
        }
        assert {entry.status for entry in entries} == {
            AgentProjectCatalogStatus.AVAILABLE
        }

    async def test_replace_rejects_stale_revision_before_runtime_validation(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """An already stale write performs no Runtime operation."""
        fixture = await _create_fixture(
            rdb_session_manager,
            handle="automatic-project-stale-early",
        )
        session_manager = _TrackingSessionManager(rdb_session_manager)
        runner = _FakeRunnerOperations(session_manager=session_manager)
        service = _service(session_manager, runner_operations=runner)

        result = await service.replace_policy(
            agent_id=fixture.agent_id,
            workspace_id=fixture.workspace_id,
            workspace_user_id=fixture.admin_workspace_user_id,
            expected_revision=2,
            project_paths=["/workspace/agent/payments"],
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, AutomaticSessionProjectsRevisionConflict)
        assert runner.paths == []

    async def test_replace_detects_revision_change_during_runtime_validation(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """The lock-time revision check rejects a concurrent completed replacement."""
        fixture = await _create_fixture(
            rdb_session_manager,
            handle="automatic-project-stale-late",
        )
        session_manager = _TrackingSessionManager(rdb_session_manager)

        async def replace_concurrently() -> None:
            assert session_manager.active_contexts == 0
            async with rdb_session_manager() as session:
                replacement = await AgentAutomaticProjectRepository().replace_policy(
                    session,
                    agent_id=fixture.agent_id,
                    expected_revision=1,
                    paths=["/workspace/agent/concurrent"],
                    updated_by_workspace_user_id=fixture.admin_workspace_user_id,
                )
                assert isinstance(replacement, Success)
                await session.commit()

        runner = _FakeRunnerOperations(
            session_manager=session_manager,
            on_stat=replace_concurrently,
        )
        service = _service(session_manager, runner_operations=runner)

        result = await service.replace_policy(
            agent_id=fixture.agent_id,
            workspace_id=fixture.workspace_id,
            workspace_user_id=fixture.admin_workspace_user_id,
            expected_revision=1,
            project_paths=["/workspace/agent/payments"],
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, AutomaticSessionProjectsRevisionConflict)
        assert runner.paths == ["/workspace/agent/payments"]
        async with rdb_session_manager() as session:
            persisted = await AgentAutomaticProjectRepository().get_policy(
                session,
                agent_id=fixture.agent_id,
            )
        assert persisted is not None
        assert persisted.revision == 2
        assert persisted.project_paths == ("/workspace/agent/concurrent",)

    async def test_replace_empty_policy_clears_without_runtime(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Empty replacement clears stored paths even when no Runner is supplied."""
        fixture = await _create_fixture(
            rdb_session_manager,
            handle="automatic-project-clear",
        )
        session_manager = _TrackingSessionManager(rdb_session_manager)
        populated = await _service(
            session_manager,
            runner_operations=_FakeRunnerOperations(session_manager=session_manager),
        ).replace_policy(
            agent_id=fixture.agent_id,
            workspace_id=fixture.workspace_id,
            workspace_user_id=fixture.admin_workspace_user_id,
            expected_revision=1,
            project_paths=["/workspace/agent/payments"],
        )
        assert isinstance(populated, Success)
        service = _service(session_manager, runner_operations=None)

        result = await service.replace_policy(
            agent_id=fixture.agent_id,
            workspace_id=fixture.workspace_id,
            workspace_user_id=fixture.admin_workspace_user_id,
            expected_revision=2,
            project_paths=[],
        )

        assert isinstance(result, Success)
        assert result.value.revision == 3
        assert result.value.project_paths == ()

    async def test_replace_reports_runtime_unavailable_for_nonempty_paths(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Non-empty replacement requires a ready Runtime Runner."""
        fixture = await _create_fixture(
            rdb_session_manager,
            handle="automatic-project-runtime-unavailable",
        )
        session_manager = _TrackingSessionManager(rdb_session_manager)
        service = _service(session_manager, runner_operations=None)

        result = await service.replace_policy(
            agent_id=fixture.agent_id,
            workspace_id=fixture.workspace_id,
            workspace_user_id=fixture.admin_workspace_user_id,
            expected_revision=1,
            project_paths=["/workspace/agent/payments"],
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, AutomaticSessionProjectsRuntimeUnavailable)

    async def test_replace_maps_runtime_timeout_to_retryable_unavailable(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Runner operation timeouts remain retryable Runtime conflicts."""
        fixture = await _create_fixture(
            rdb_session_manager,
            handle="automatic-project-runtime-timeout",
        )
        session_manager = _TrackingSessionManager(rdb_session_manager)
        service = _service(
            session_manager,
            runner_operations=_FakeRunnerOperations(
                session_manager=session_manager,
                error_code="operation_timeout",
            ),
        )

        result = await service.replace_policy(
            agent_id=fixture.agent_id,
            workspace_id=fixture.workspace_id,
            workspace_user_id=fixture.admin_workspace_user_id,
            expected_revision=1,
            project_paths=["/workspace/agent/payments"],
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, AutomaticSessionProjectsRuntimeUnavailable)

    async def test_replace_rejects_workspace_root_and_outside_paths_before_runtime(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Workspace root and outside paths never reach Runtime validation."""
        fixture = await _create_fixture(
            rdb_session_manager,
            handle="automatic-project-invalid-syntax",
        )
        session_manager = _TrackingSessionManager(rdb_session_manager)
        runner = _FakeRunnerOperations(session_manager=session_manager)
        service = _service(session_manager, runner_operations=runner)

        root_result = await service.replace_policy(
            agent_id=fixture.agent_id,
            workspace_id=fixture.workspace_id,
            workspace_user_id=fixture.admin_workspace_user_id,
            expected_revision=1,
            project_paths=["/workspace/agent"],
        )
        outside_result = await service.replace_policy(
            agent_id=fixture.agent_id,
            workspace_id=fixture.workspace_id,
            workspace_user_id=fixture.admin_workspace_user_id,
            expected_revision=1,
            project_paths=["/tmp/payments"],
        )

        assert isinstance(root_result, Failure)
        assert isinstance(root_result.error, InvalidProjectPath)
        assert isinstance(outside_result, Failure)
        assert isinstance(outside_result.error, InvalidProjectPath)
        assert runner.paths == []

    async def test_replace_rejects_missing_or_non_directory_paths(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Missing and file targets are user-safe invalid Project paths."""
        fixture = await _create_fixture(
            rdb_session_manager,
            handle="automatic-project-invalid-target",
        )
        session_manager = _TrackingSessionManager(rdb_session_manager)

        missing = await _service(
            session_manager,
            runner_operations=_FakeRunnerOperations(
                session_manager=session_manager,
                kind="missing",
            ),
        ).replace_policy(
            agent_id=fixture.agent_id,
            workspace_id=fixture.workspace_id,
            workspace_user_id=fixture.admin_workspace_user_id,
            expected_revision=1,
            project_paths=["/workspace/agent/missing"],
        )
        file_target = await _service(
            session_manager,
            runner_operations=_FakeRunnerOperations(
                session_manager=session_manager,
                kind="file",
            ),
        ).replace_policy(
            agent_id=fixture.agent_id,
            workspace_id=fixture.workspace_id,
            workspace_user_id=fixture.admin_workspace_user_id,
            expected_revision=1,
            project_paths=["/workspace/agent/file"],
        )

        assert isinstance(missing, Failure)
        assert isinstance(missing.error, InvalidProjectPath)
        assert isinstance(file_target, Failure)
        assert isinstance(file_target.error, InvalidProjectPath)
