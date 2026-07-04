"""SessionGitWorktreeService tests."""

import datetime

from azcommon.result import Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentProjectCatalogStatus,
    LLMProvider,
    RuntimeRunnerState,
    SessionGitWorktreeStatus,
    SessionInitializationStatus,
    SessionInitializationStepStatus,
    WorkspaceUserRole,
)
from azents.engine.run.input import InputMessage
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.session_git_worktree import RDBSessionGitWorktree
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.data import AgentProjectCatalogEntry
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.input_buffer import InputBufferRepository
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_initialization import SessionInitializationRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.runtime.control_protocol.runner_operations import (
    RuntimeGitCreateWorktreeResult,
    RuntimeGitDeleteBranchResult,
    RuntimeGitRefEntry,
    RuntimeGitRefsResult,
    RuntimeGitRemoveWorktreeResult,
    RuntimeOperationTextCallback,
    RuntimeRunnerOperationFailedError,
)
from azents.services.agent_project_catalog import AgentProjectCatalogService
from azents.services.agent_session_input import AgentSessionInputService
from azents.services.exchange_file import ExchangeFileService
from azents.services.input_buffer import InputBufferService
from azents.services.model_file import ModelFileService
from azents.services.session_git_worktree import (
    ExplicitProjectsWorkspaceMode,
    GitWorktreeWorkspaceMode,
    SessionGitWorktreeService,
)
from azents.services.session_initialization import SessionInitializationService
from azents.services.session_workspace_project import InvalidProjectPath
from azents.testing.model_selection import make_test_model_selection_dict


class _RuntimeRepository(AgentRuntimeRepository):
    """Runtime repository double returning a ready Runner."""

    async def get_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> AgentRuntime | None:
        """Return a ready runtime."""
        del session
        now = datetime.datetime.now(datetime.UTC)
        return AgentRuntime(
            id="runtime-1",
            workspace_id="workspace-1",
            agent_id=agent_id,
            runner_state=RuntimeRunnerState.READY,
            runner_generation=7,
            created_at=now,
            updated_at=now,
        )

    async def ensure_for_agent(
        self,
        session: AsyncSession,
        agent_id: str,
        *,
        default_runtime_provider_id: str | None = None,
    ) -> AgentRuntime:
        """Return a ready runtime for first-message creation."""
        del default_runtime_provider_id
        runtime = await self.get_by_agent_id(session, agent_id)
        assert runtime is not None
        return runtime


class _RunnerOperations:
    """Runner operation double for Git worktree operations."""

    def __init__(
        self,
        failures: list[str] | None = None,
        cleanup_failures: list[str] | None = None,
    ) -> None:
        self.failures = list(failures or [])
        self.cleanup_failures = list(cleanup_failures or [])
        self.calls: list[dict[str, object]] = []

    async def list_git_refs(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        source_project_path: str,
        deadline_at: datetime.datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitRefsResult:
        """Return deterministic Git refs."""
        del deadline_at, text_output_callback
        self.calls.append(
            {
                "operation": "list_git_refs",
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "source_project_path": source_project_path,
            }
        )
        return RuntimeGitRefsResult(
            refs=(
                RuntimeGitRefEntry(
                    name="main",
                    ref="refs/heads/main",
                    type="branch",
                    target="abc123",
                    default=True,
                ),
            ),
            default_branch="main",
            head_commit="abc123",
            final_cursor="cursor-refs",
        )

    async def create_git_worktree(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        source_project_path: str,
        worktree_path: str,
        branch_name: str,
        starting_ref: str,
        deadline_at: datetime.datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitCreateWorktreeResult:
        """Record the attempt and optionally fail with a semantic error."""
        del deadline_at, text_output_callback
        self.calls.append(
            {
                "operation": "create_git_worktree",
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "source_project_path": source_project_path,
                "worktree_path": worktree_path,
                "branch_name": branch_name,
                "starting_ref": starting_ref,
            }
        )
        if self.failures:
            raise RuntimeRunnerOperationFailedError(self.failures.pop(0))
        return RuntimeGitCreateWorktreeResult(
            base_commit="abc123",
            worktree_path=worktree_path,
            branch_name=branch_name,
            final_cursor="cursor-1",
        )

    async def remove_git_worktree(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        source_project_path: str,
        worktree_path: str,
        force: bool,
        deadline_at: datetime.datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitRemoveWorktreeResult:
        """Record worktree removal."""
        del deadline_at, text_output_callback
        self.calls.append(
            {
                "operation": "remove_git_worktree",
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "source_project_path": source_project_path,
                "worktree_path": worktree_path,
                "force": force,
            }
        )
        if self.cleanup_failures:
            raise RuntimeRunnerOperationFailedError(self.cleanup_failures.pop(0))
        return RuntimeGitRemoveWorktreeResult(
            worktree_path=worktree_path,
            final_cursor="cursor-remove",
        )

    async def delete_git_branch(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        source_project_path: str,
        branch_name: str,
        deadline_at: datetime.datetime,
        text_output_callback: RuntimeOperationTextCallback | None,
    ) -> RuntimeGitDeleteBranchResult:
        """Record branch deletion."""
        del deadline_at, text_output_callback
        self.calls.append(
            {
                "operation": "delete_git_branch",
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "source_project_path": source_project_path,
                "branch_name": branch_name,
            }
        )
        return RuntimeGitDeleteBranchResult(
            branch_name=branch_name,
            final_cursor="cursor-branch",
        )


class _CatalogRefreshService(AgentProjectCatalogService):
    """Catalog status refresh double."""

    def __init__(self, status: AgentProjectCatalogStatus) -> None:
        self.status = status

    async def refresh_project_status(
        self,
        *,
        agent_id: str,
        path: str,
    ) -> Result[AgentProjectCatalogEntry, InvalidProjectPath]:
        """Return the configured status without touching the runner."""
        now = datetime.datetime.now(datetime.UTC)
        status_detail = (
            None if self.status is AgentProjectCatalogStatus.AVAILABLE else "Not ready."
        )
        return Success(
            AgentProjectCatalogEntry(
                id="catalog-1",
                agent_id=agent_id,
                path=path,
                status=self.status,
                status_detail=status_detail,
                checked_at=now,
                created_at=now,
                updated_at=now,
            )
        )


class _FailingCatalogRepository(AgentProjectCatalogRepository):
    """Catalog repository double that fails upsert."""

    async def upsert_entry(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        path: str,
    ) -> AgentProjectCatalogEntry:
        """Fail catalog upsert."""
        del session, agent_id, path
        raise RuntimeError("catalog upsert failed")


class _ExchangeFileService(ExchangeFileService):
    """ExchangeFileService test double."""

    def __init__(self) -> None:
        """Bypass base dataclass initialization."""


class _ModelFileService(ModelFileService):
    """ModelFileService test double."""

    def __init__(self) -> None:
        """Bypass base dataclass initialization."""


async def _create_agent_context(
    session: AsyncSession, slug: str
) -> tuple[str, str, str]:
    """Create workspace, user, and agent fixtures."""
    workspace = await WorkspaceRepository().create(
        session,
        WorkspaceCreate(name=f"Worktree {slug}", handle=f"worktree-{slug}"),
    )
    assert isinstance(workspace, Success)
    workspace_id = await WorkspaceRepository().resolve_id(session, f"worktree-{slug}")
    assert workspace_id is not None
    user = await UserRepository().create(
        session,
        UserCreate(email=f"{slug}@example.com"),
    )
    member = await WorkspaceUserRepository().create(
        session,
        WorkspaceUserCreate(
            workspace_id=workspace_id,
            user_id=user.id,
            name="Worktree User",
            role=WorkspaceUserRole.OWNER,
        ),
    )
    assert isinstance(member, Success)
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
        name=f"Worktree {slug}",
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
    return workspace_id, user.id, agent.id


def _service(
    session_manager: SessionManager[AsyncSession],
    runner: _RunnerOperations,
    *,
    catalog_repository: AgentProjectCatalogRepository | None = None,
    refresh_status: AgentProjectCatalogStatus = AgentProjectCatalogStatus.AVAILABLE,
) -> SessionGitWorktreeService:
    """Build the service under test."""
    return SessionGitWorktreeService(
        agent_repository=AgentRepository(),
        agent_session_repository=AgentSessionRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        agent_runtime_repository=_RuntimeRepository(),
        session_initialization_repository=SessionInitializationRepository(),
        session_git_worktree_repository=SessionGitWorktreeRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        agent_project_catalog_repository=catalog_repository
        or AgentProjectCatalogRepository(),
        agent_project_catalog_service=_CatalogRefreshService(refresh_status),
        session_manager=session_manager,
        runner_operations=runner,  # pyright: ignore[reportArgumentType]
    )


def _input_service(
    session_manager: SessionManager[AsyncSession],
    worktree_service: SessionGitWorktreeService,
) -> AgentSessionInputService:
    """Build AgentSessionInputService with worktree support."""
    return AgentSessionInputService(
        agent_repository=AgentRepository(),
        agent_project_preset_repository=AgentProjectPresetRepository(),
        agent_project_catalog_repository=AgentProjectCatalogRepository(),
        agent_project_default_repository=AgentProjectDefaultRepository(),
        agent_runtime_repository=_RuntimeRepository(),
        agent_session_repository=AgentSessionRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        input_buffer_service=InputBufferService(
            session_manager=session_manager,
            input_buffer_repository=InputBufferRepository(),
            exchange_file_service=_ExchangeFileService(),
            model_file_service=_ModelFileService(),
            agent_session_repository=AgentSessionRepository(),
            event_transcript_repository=EventTranscriptRepository(),
        ),
        session_initialization_service=SessionInitializationService(
            session_initialization_repository=SessionInitializationRepository(),
            session_manager=session_manager,
        ),
        session_manager=session_manager,
        session_git_worktree_service=worktree_service,
    )


async def _create_ready_worktree_session(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    slug: str,
    runner: _RunnerOperations,
) -> tuple[SessionGitWorktreeService, str, str, str]:
    """Create a ready worktree session through the first-message path."""
    async with rdb_session_manager() as session:
        _, user_id, agent_id = await _create_agent_context(session, slug)
    worktree_service = _service(rdb_session_manager, runner)
    input_service = _input_service(rdb_session_manager, worktree_service)
    result = await input_service.create_team_session_with_buffered_input(
        agent_id=agent_id,
        message=InputMessage(
            text=f"start {slug}",
            user_id=user_id,
            headers=[],
            metadata={"source": "chat"},
            attachments=[],
        ),
        user_id=user_id,
        workspace_mode=GitWorktreeWorkspaceMode(
            source_project_path="/workspace/agent/repo",
            starting_ref="main",
        ),
        client_request_id=f"worktree-{slug}",
    )
    assert isinstance(result, Success)
    await worktree_service.run_git_worktree_initialization(
        agent_id=agent_id,
        session_id=result.value.agent_session.id,
    )
    return worktree_service, user_id, agent_id, result.value.agent_session.id


class TestSessionGitWorktreeService:
    """Session Git worktree service tests."""

    async def test_preview_git_refs_lists_source_project_refs(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Git ref preview validates access and calls the Runtime Runner."""
        async with rdb_session_manager() as session:
            _, user_id, agent_id = await _create_agent_context(session, "preview")
        runner = _RunnerOperations()
        service = _service(rdb_session_manager, runner)

        result = await service.preview_git_refs(
            agent_id=agent_id,
            user_id=user_id,
            source_project_path="/workspace/agent/repo",
        )

        assert isinstance(result, Success)
        assert result.value.default_branch == "main"
        assert result.value.refs[0].ref == "refs/heads/main"
        assert runner.calls == [
            {
                "operation": "list_git_refs",
                "runtime_id": "runtime-1",
                "runner_generation": 7,
                "source_project_path": "/workspace/agent/repo",
            }
        ]

    async def test_valid_first_message_worktree_registers_project_and_catalog(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Valid worktree session creates ready initialization and Project rows."""
        async with rdb_session_manager() as session:
            _, user_id, agent_id = await _create_agent_context(session, "ready")
        runner = _RunnerOperations()
        worktree_service = _service(rdb_session_manager, runner)
        input_service = _input_service(rdb_session_manager, worktree_service)

        result = await input_service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="start worktree",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id=user_id,
            workspace_mode=GitWorktreeWorkspaceMode(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            ),
            client_request_id="worktree-ready",
        )

        assert isinstance(result, Success)
        created = result.value.agent_session
        await worktree_service.run_git_worktree_initialization(
            agent_id=agent_id,
            session_id=created.id,
        )
        async with rdb_session_manager() as session:
            initialization = await SessionInitializationRepository().get_by_session_id(
                session,
                session_id=created.id,
            )
            assert initialization is not None
            steps = await SessionInitializationRepository().list_steps(
                session,
                initialization_id=initialization.id,
            )
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=created.id,
            )
            catalog = await AgentProjectCatalogRepository().list_entries(
                session,
                agent_id=agent_id,
            )

        assert initialization.status is SessionInitializationStatus.READY
        assert [project.path for project in projects] == [
            runner.calls[-1]["worktree_path"]
        ]
        assert [entry.path for entry in catalog] == [runner.calls[-1]["worktree_path"]]
        assert all(
            step.status is SessionInitializationStepStatus.COMPLETED for step in steps
        )

    async def test_invalid_ref_blocks_initialization_and_keeps_input_pending(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Runner invalid ref failure leaves initialization failed and input pending."""
        async with rdb_session_manager() as session:
            _, user_id, agent_id = await _create_agent_context(session, "invalid-ref")
        runner = _RunnerOperations(failures=["invalid_ref: unknown revision"])
        worktree_service = _service(rdb_session_manager, runner)
        input_service = _input_service(rdb_session_manager, worktree_service)

        result = await input_service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="start invalid",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id=user_id,
            workspace_mode=GitWorktreeWorkspaceMode(
                source_project_path="/workspace/agent/repo",
                starting_ref="missing",
            ),
            client_request_id="worktree-invalid",
        )

        assert isinstance(result, Success)
        await worktree_service.run_git_worktree_initialization(
            agent_id=agent_id,
            session_id=result.value.agent_session.id,
        )
        async with rdb_session_manager() as session:
            initialization = await SessionInitializationRepository().get_by_session_id(
                session,
                session_id=result.value.agent_session.id,
            )
            buffers = await InputBufferRepository().list_by_session_id(
                session,
                result.value.agent_session.id,
            )
        assert initialization is not None
        assert initialization.status is SessionInitializationStatus.FAILED
        assert [buffer.content for buffer in buffers] == ["start invalid"]

    async def test_branch_collision_suffixes_final_branch(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Branch collision retries with an independently suffixed branch name."""
        async with rdb_session_manager() as session:
            _, user_id, agent_id = await _create_agent_context(session, "branch")
        runner = _RunnerOperations(failures=["branch_exists: branch exists"])
        worktree_service = _service(rdb_session_manager, runner)
        input_service = _input_service(rdb_session_manager, worktree_service)

        result = await input_service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="start branch",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id=user_id,
            workspace_mode=GitWorktreeWorkspaceMode(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            ),
            client_request_id="worktree-branch",
        )

        assert isinstance(result, Success)
        await worktree_service.run_git_worktree_initialization(
            agent_id=agent_id,
            session_id=result.value.agent_session.id,
        )
        first_branch = runner.calls[0]["branch_name"]
        second_branch = runner.calls[1]["branch_name"]
        assert isinstance(first_branch, str)
        assert isinstance(second_branch, str)
        assert first_branch.startswith("azents/")
        assert second_branch.endswith("-2")

    async def test_path_collision_suffixes_final_worktree_path(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Path collision retries with an independently suffixed path leaf."""
        async with rdb_session_manager() as session:
            _, user_id, agent_id = await _create_agent_context(session, "path")
        runner = _RunnerOperations(failures=["worktree_path_exists: path exists"])
        worktree_service = _service(rdb_session_manager, runner)
        input_service = _input_service(rdb_session_manager, worktree_service)

        result = await input_service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="start path",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id=user_id,
            workspace_mode=GitWorktreeWorkspaceMode(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            ),
            client_request_id="worktree-path",
        )

        assert isinstance(result, Success)
        await worktree_service.run_git_worktree_initialization(
            agent_id=agent_id,
            session_id=result.value.agent_session.id,
        )
        first_path = runner.calls[0]["worktree_path"]
        second_path = runner.calls[1]["worktree_path"]
        assert isinstance(first_path, str)
        assert isinstance(second_path, str)
        assert first_path.endswith("/repo")
        assert second_path.endswith("/repo-2")

    async def test_catalog_upsert_failure_blocks_initialization(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Catalog upsert is blocking for worktree initialization."""
        async with rdb_session_manager() as session:
            _, user_id, agent_id = await _create_agent_context(session, "catalog")
        runner = _RunnerOperations()
        worktree_service = _service(
            rdb_session_manager,
            runner,
            catalog_repository=_FailingCatalogRepository(),
        )
        input_service = _input_service(rdb_session_manager, worktree_service)

        result = await input_service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="start catalog",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id=user_id,
            workspace_mode=GitWorktreeWorkspaceMode(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            ),
            client_request_id="worktree-catalog",
        )

        assert isinstance(result, Success)
        await worktree_service.run_git_worktree_initialization(
            agent_id=agent_id,
            session_id=result.value.agent_session.id,
        )
        async with rdb_session_manager() as session:
            initialization = await SessionInitializationRepository().get_by_session_id(
                session,
                session_id=result.value.agent_session.id,
            )
        assert initialization is not None
        assert initialization.status is SessionInitializationStatus.FAILED

    async def test_status_refresh_warning_does_not_block_ready(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Non-blocking status refresh warning keeps initialization ready."""
        async with rdb_session_manager() as session:
            _, user_id, agent_id = await _create_agent_context(session, "warning")
        runner = _RunnerOperations()
        worktree_service = _service(
            rdb_session_manager,
            runner,
            refresh_status=AgentProjectCatalogStatus.UNAVAILABLE,
        )
        input_service = _input_service(rdb_session_manager, worktree_service)

        result = await input_service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="start warning",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id=user_id,
            workspace_mode=GitWorktreeWorkspaceMode(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            ),
            client_request_id="worktree-warning",
        )

        assert isinstance(result, Success)
        await worktree_service.run_git_worktree_initialization(
            agent_id=agent_id,
            session_id=result.value.agent_session.id,
        )
        async with rdb_session_manager() as session:
            initialization = await SessionInitializationRepository().get_by_session_id(
                session,
                session_id=result.value.agent_session.id,
            )
            assert initialization is not None
            steps = await SessionInitializationRepository().list_steps(
                session,
                initialization_id=initialization.id,
            )
        assert initialization.status is SessionInitializationStatus.READY
        assert steps[-1].status is SessionInitializationStepStatus.FAILED

    async def test_archive_cleanup_request_only_marks_pending(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Archive-time cleanup request does not run Git cleanup inline."""
        runner = _RunnerOperations()
        worktree_service, _, _, session_id = await _create_ready_worktree_session(
            rdb_session_manager,
            slug="archive-cleanup",
            runner=runner,
        )

        async with rdb_session_manager() as session:
            request = await worktree_service.mark_cleanup_pending_for_session(
                session,
                session_id=session_id,
            )
            allocation = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
            initialization = await SessionInitializationRepository().get_by_session_id(
                session,
                session_id=session_id,
            )

        assert request.cleanup_requested is True
        assert allocation is not None
        assert allocation.status is SessionGitWorktreeStatus.CLEANUP_PENDING
        assert initialization is not None
        assert initialization.status is SessionInitializationStatus.CLEANUP_REQUIRED
        assert [call["operation"] for call in runner.calls] == ["create_git_worktree"]

    async def test_cleanup_removes_worktree_branch_and_catalog(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Cleanup removes Git resources and deletes the catalog entry."""
        runner = _RunnerOperations()
        (
            worktree_service,
            _,
            agent_id,
            session_id,
        ) = await _create_ready_worktree_session(
            rdb_session_manager,
            slug="cleanup-success",
            runner=runner,
        )
        async with rdb_session_manager() as session:
            await worktree_service.mark_cleanup_pending_for_session(
                session,
                session_id=session_id,
            )

        await worktree_service.run_cleanup_for_session(
            agent_id=agent_id,
            session_id=session_id,
        )

        async with rdb_session_manager() as session:
            allocation = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
            initialization = await SessionInitializationRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
            catalog = await AgentProjectCatalogRepository().list_entries(
                session,
                agent_id=agent_id,
            )
        assert allocation is not None
        assert allocation.status is SessionGitWorktreeStatus.CLEANED
        assert initialization is not None
        assert initialization.status is SessionInitializationStatus.CLEANED
        assert catalog == []
        assert [call["operation"] for call in runner.calls] == [
            "create_git_worktree",
            "remove_git_worktree",
            "delete_git_branch",
        ]
        remove_call = runner.calls[1]
        assert remove_call["force"] is True

    async def test_cleanup_failure_marks_failed_without_raising(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Cleanup failures are recorded without blocking callers."""
        runner = _RunnerOperations(cleanup_failures=["worktree remove failed"])
        (
            worktree_service,
            _,
            agent_id,
            session_id,
        ) = await _create_ready_worktree_session(
            rdb_session_manager,
            slug="cleanup-failure",
            runner=runner,
        )
        async with rdb_session_manager() as session:
            await worktree_service.mark_cleanup_pending_for_session(
                session,
                session_id=session_id,
            )

        await worktree_service.run_cleanup_for_session(
            agent_id=agent_id,
            session_id=session_id,
        )

        async with rdb_session_manager() as session:
            allocation = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
            initialization = await SessionInitializationRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
            catalog = await AgentProjectCatalogRepository().list_entries(
                session,
                agent_id=agent_id,
            )
        assert allocation is not None
        assert allocation.status is SessionGitWorktreeStatus.CLEANUP_FAILED
        assert allocation.cleanup_summary == "worktree remove failed"
        assert initialization is not None
        assert initialization.status is SessionInitializationStatus.CLEANUP_REQUIRED
        assert initialization.failure_summary == (
            "Git worktree cleanup failed: worktree remove failed"
        )
        assert len(catalog) == 1

    async def test_manual_cleanup_retry_succeeds_after_failure(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Manual cleanup retry can recover a previously failed cleanup."""
        runner = _RunnerOperations(cleanup_failures=["first cleanup failed"])
        (
            worktree_service,
            user_id,
            agent_id,
            session_id,
        ) = await _create_ready_worktree_session(
            rdb_session_manager,
            slug="cleanup-retry",
            runner=runner,
        )
        async with rdb_session_manager() as session:
            await worktree_service.mark_cleanup_pending_for_session(
                session,
                session_id=session_id,
            )
        await worktree_service.run_cleanup_for_session(
            agent_id=agent_id,
            session_id=session_id,
        )

        retry = await worktree_service.request_manual_cleanup(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
        )
        assert isinstance(retry, Success)
        assert retry.value.cleanup_requested is True
        await worktree_service.run_cleanup_for_session(
            agent_id=agent_id,
            session_id=session_id,
        )

        async with rdb_session_manager() as session:
            allocation = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
            initialization = await SessionInitializationRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
        assert allocation is not None
        assert allocation.status is SessionGitWorktreeStatus.CLEANED
        assert initialization is not None
        assert initialization.status is SessionInitializationStatus.CLEANED

    async def test_cleanup_rejects_path_without_matching_ownership_boundary(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Cleanup never deletes a path outside the recorded Azents root boundary."""
        runner = _RunnerOperations()
        (
            worktree_service,
            _,
            agent_id,
            session_id,
        ) = await _create_ready_worktree_session(
            rdb_session_manager,
            slug="cleanup-ownership",
            runner=runner,
        )
        async with rdb_session_manager() as session:
            allocation = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
            assert allocation is not None
            row = await session.get(RDBSessionGitWorktree, allocation.id)
            assert row is not None
            row.worktree_path = "/workspace/agent/user-owned/repo"
            await session.flush()
            await worktree_service.mark_cleanup_pending_for_session(
                session,
                session_id=session_id,
            )

        await worktree_service.run_cleanup_for_session(
            agent_id=agent_id,
            session_id=session_id,
        )

        async with rdb_session_manager() as session:
            allocation = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
        assert allocation is not None
        assert allocation.status is SessionGitWorktreeStatus.CLEANUP_FAILED
        assert [call["operation"] for call in runner.calls] == ["create_git_worktree"]

    async def test_explicit_project_mode_still_bootstraps_noop_initialization(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Explicit Project mode continues to use no-op initialization."""
        async with rdb_session_manager() as session:
            _, user_id, agent_id = await _create_agent_context(session, "explicit")
        input_service = _input_service(
            rdb_session_manager,
            _service(rdb_session_manager, _RunnerOperations()),
        )

        result = await input_service.create_team_session_with_buffered_input(
            agent_id=agent_id,
            message=InputMessage(
                text="start explicit",
                user_id=user_id,
                headers=[],
                metadata={"source": "chat"},
                attachments=[],
            ),
            user_id=user_id,
            workspace_mode=ExplicitProjectsWorkspaceMode(
                project_paths=["/workspace/agent/app"]
            ),
            client_request_id="explicit-project",
        )

        assert isinstance(result, Success)
        async with rdb_session_manager() as session:
            initialization = await SessionInitializationRepository().get_by_session_id(
                session,
                session_id=result.value.agent_session.id,
            )
        assert initialization is not None
        assert initialization.status is SessionInitializationStatus.READY
