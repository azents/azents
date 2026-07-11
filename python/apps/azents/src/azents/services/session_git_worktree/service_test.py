"""SessionGitWorktreeService tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ActionExecutionStatus,
    AgentProjectCatalogStatus,
    AgentSessionKind,
    AgentSessionStartReason,
    AgentSessionStatus,
    EventKind,
    LLMProvider,
    RuntimeRunnerState,
    SessionGitWorktreeStatus,
    WorkspaceUserRole,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.engine.events.action_messages import (
    ActionMessagePayload,
    CreateGitWorktreeAction,
)
from azents.engine.run.input import InputMessage
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.session_agent_context import RDBSessionAgentContextGitWorktree
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.action_execution.data import ActionExecutionProjection
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.data import AgentProjectCatalogEntry
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, AgentSessionCreate
from azents.repos.input_buffer import InputBufferRepository
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProjectCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.runtime.control_protocol.runner_operations import (
    RuntimeFileDeleteResult,
    RuntimeFileListResult,
    RuntimeGitCreateWorktreeResult,
    RuntimeGitDeleteBranchResult,
    RuntimeGitRefEntry,
    RuntimeGitRefsResult,
    RuntimeGitRemoveWorktreeResult,
    RuntimeOperationTextCallback,
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
)
from azents.services.agent_project_catalog import AgentProjectCatalogService
from azents.services.agent_session_input import AgentSessionInputService
from azents.services.exchange_file import ExchangeFileService
from azents.services.input_buffer import InputBufferService
from azents.services.model_file import ModelFileService
from azents.services.session_git_worktree import (
    GitWorktreeActionExecutionSubagentReadOnly,
    GitWorktreeCleanupNotFound,
    GitWorktreeCleanupSubagentReadOnly,
    SessionGitWorktreeService,
)
from azents.services.session_workspace_project import InvalidProjectPath
from azents.testing.model_selection import make_test_model_selection_dict

_TEST_INFERENCE_PROFILE = RequestedInferenceProfile(
    model_target_label="Primary",
    reasoning_effort=None,
)


@asynccontextmanager
async def _session_manager_double() -> AsyncGenerator[AsyncSession, None]:
    """Yield a placeholder DB session for service-double tests."""
    yield cast(AsyncSession, object())


class _ReadonlyAgentSessionRepository(AgentSessionRepository):
    """AgentSession repository double returning a child subagent session."""

    async def get_by_id(
        self,
        session: AsyncSession,
        agent_session_id: str,
    ) -> AgentSession | None:
        """Return a subagent session before other collaborators are touched."""
        del session
        now = datetime.datetime.now(datetime.UTC)
        return AgentSession(
            inference_state=None,
            id=agent_session_id,
            workspace_id="workspace-1",
            agent_id="agent-1",
            handle="subagent-session",
            session_kind=AgentSessionKind.SUBAGENT,
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


def _readonly_service() -> SessionGitWorktreeService:
    """Build a service that can test read-only checks without DB fixtures."""
    return SessionGitWorktreeService(
        agent_repository=cast(AgentRepository, object()),
        agent_session_repository=_ReadonlyAgentSessionRepository(),
        workspace_user_repository=cast(WorkspaceUserRepository, object()),
        agent_runtime_repository=cast(AgentRuntimeRepository, object()),
        session_git_worktree_repository=cast(SessionGitWorktreeRepository, object()),
        session_workspace_project_repository=cast(
            SessionWorkspaceProjectRepository,
            object(),
        ),
        agent_project_catalog_repository=cast(AgentProjectCatalogRepository, object()),
        agent_project_catalog_service=cast(AgentProjectCatalogService, object()),
        action_execution_repository=cast(ActionExecutionRepository, object()),
        event_transcript_repository=cast(EventTranscriptRepository, object()),
        session_manager=_session_manager_double,
        runner_operations=cast(RuntimeRunnerOperationClient, object()),
    )


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
        owner_session_id: str | None = None,
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
        owner_session_id: str | None = None,
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
        owner_session_id: str | None = None,
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
        owner_session_id: str | None = None,
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
        """Record directory listing for parent cleanup."""
        del deadline_at, exclude_patterns
        self.calls.append(
            {
                "operation": "list_files",
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "path": path,
                "recursive": recursive,
            }
        )
        return RuntimeFileListResult(entries=(), final_cursor="cursor-list")

    async def delete_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None = None,
        path: str,
        recursive: bool,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileDeleteResult:
        """Record empty parent directory deletion."""
        del deadline_at
        self.calls.append(
            {
                "operation": "delete_file",
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "path": path,
                "recursive": recursive,
            }
        )
        return RuntimeFileDeleteResult(path=path, final_cursor="cursor-delete")


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
        session_git_worktree_repository=SessionGitWorktreeRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        agent_project_catalog_repository=catalog_repository
        or AgentProjectCatalogRepository(),
        agent_project_catalog_service=_CatalogRefreshService(refresh_status),
        action_execution_repository=ActionExecutionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        session_manager=session_manager,
        runner_operations=runner,  # pyright: ignore[reportArgumentType]
    )


def _input_service(
    session_manager: SessionManager[AsyncSession],
    worktree_service: SessionGitWorktreeService,
) -> AgentSessionInputService:
    """Build AgentSessionInputService for setup action enqueue tests."""
    del worktree_service
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
            agent_run_repository=AgentRunRepository(),
        ),
        session_manager=session_manager,
    )


async def _execute_first_setup_action(
    rdb_session_manager: SessionManager[AsyncSession],
    worktree_service: SessionGitWorktreeService,
    *,
    agent_id: str,
    session_id: str,
) -> str:
    """Promote and execute the first pending setup action."""
    promoted = await InputBufferService(
        session_manager=rdb_session_manager,
        input_buffer_repository=InputBufferRepository(),
        exchange_file_service=_ExchangeFileService(),
        model_file_service=_ModelFileService(),
        agent_session_repository=AgentSessionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        agent_run_repository=AgentRunRepository(),
    ).flush_session_input_buffers(
        session_id=session_id,
        model=None,
        required_inference_profile=None,
        active_run_id=None,
        limit=1,
        include_action_messages=True,
    )
    assert len(promoted.events) == 1
    event = promoted.events[0]
    assert event.kind is EventKind.ACTION_MESSAGE
    payload = event.payload
    assert isinstance(payload, ActionMessagePayload)
    action = payload.action
    assert isinstance(action, CreateGitWorktreeAction)
    await worktree_service.run_git_worktree_action(
        agent_id=agent_id,
        session_id=session_id,
        action_event_id=event.id,
        action=action,
    )
    return event.id


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
        inference_profile=_TEST_INFERENCE_PROFILE,
        user_id=user_id,
        existing_project_paths=[],
        setup_actions=[
            CreateGitWorktreeAction(
                source_project_path="/workspace/agent/repo",
                starting_ref="main",
            )
        ],
        client_request_id=f"worktree-{slug}",
    )
    assert isinstance(result, Success)
    session_id = result.value.agent_session.id
    await _execute_first_setup_action(
        rdb_session_manager,
        worktree_service,
        agent_id=agent_id,
        session_id=session_id,
    )
    async with rdb_session_manager() as session:
        await AgentSessionRepository().mark_idle(session, session_id)
    return worktree_service, user_id, agent_id, session_id


class TestSessionGitWorktreeService:
    """Session Git worktree service tests."""

    async def test_action_execution_retry_rejects_subagent_session(self) -> None:
        """Do not allow direct retry mutations from child subagent detail views."""
        result = await _readonly_service().request_action_execution_retry(
            agent_id="agent-1",
            session_id="subagent-session",
            action_execution_id="action-1".rjust(32, "0"),
            user_id="user-1",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, GitWorktreeActionExecutionSubagentReadOnly)

    async def test_action_execution_discard_rejects_subagent_session(self) -> None:
        """Do not allow direct discard mutations from child subagent detail views."""
        result = await _readonly_service().request_action_execution_discard(
            agent_id="agent-1",
            session_id="subagent-session",
            action_execution_id="action-1".rjust(32, "0"),
            user_id="user-1",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, GitWorktreeActionExecutionSubagentReadOnly)

    async def test_manual_cleanup_rejects_subagent_session(self) -> None:
        """Do not allow direct worktree cleanup mutations for child subagents."""
        result = await _readonly_service().request_manual_cleanup(
            agent_id="agent-1",
            session_id="subagent-session",
            user_id="user-1",
            session_workspace_project_id=None,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, GitWorktreeCleanupSubagentReadOnly)

    async def test_run_git_worktree_action_registers_project_and_catalog(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """create_git_worktree TurnAction execution creates a Project boundary."""
        async with rdb_session_manager() as session:
            workspace_id, _, agent_id = await _create_agent_context(session, "action")
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action_payload = ActionMessagePayload(
                action=CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/repo",
                    starting_ref="main",
                ),
                message="",
            )
            action_event = await EventTranscriptRepository().append(
                session,
                EventCreate(
                    session_id=agent_session.id,
                    kind=EventKind.ACTION_MESSAGE,
                    payload=action_payload.model_dump(mode="json"),
                    external_id="action-worktree-buffer",
                ),
            )
        runner = _RunnerOperations()
        service = _service(rdb_session_manager, runner)
        published_statuses: list[ActionExecutionStatus] = []

        async def publish_projection(
            projection: ActionExecutionProjection,
        ) -> None:
            published_statuses.append(projection.execution.status)

        assert isinstance(action_payload.action, CreateGitWorktreeAction)
        result = await service.run_git_worktree_action(
            agent_id=agent_id,
            session_id=agent_session.id,
            action_event_id=action_event.id,
            action=action_payload.action,
            on_projection_updated=publish_projection,
        )

        assert result.completed is True
        assert published_statuses[-1] is ActionExecutionStatus.COMPLETED
        assert result.context_invalidated is True
        async with rdb_session_manager() as session:
            allocations = await SessionGitWorktreeRepository().list_by_session_id(
                session,
                session_id=agent_session.id,
            )
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=agent_session.id,
            )
            projection = (
                await ActionExecutionRepository().get_projection_by_action_event_id(
                    session,
                    action_event_id=action_event.id,
                )
            )
        assert len(allocations) == 1
        assert allocations[0].action_execution_id is not None
        assert allocations[0].status is SessionGitWorktreeStatus.READY
        assert [project.path for project in projects] == [allocations[0].worktree_path]
        assert projection is not None
        assert projection.execution.status is ActionExecutionStatus.COMPLETED
        assert runner.calls == [
            {
                "operation": "create_git_worktree",
                "runtime_id": "runtime-1",
                "runner_generation": 7,
                "source_project_path": "/workspace/agent/repo",
                "worktree_path": allocations[0].worktree_path,
                "branch_name": allocations[0].branch_name,
                "starting_ref": "main",
            }
        ]

    async def test_request_action_execution_retry_resets_failed_execution(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Retry resets only the failed action execution for another attempt."""
        async with rdb_session_manager() as session:
            workspace_id, user_id, agent_id = await _create_agent_context(
                session,
                "action-retry",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action_payload = ActionMessagePayload(
                action=CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/repo",
                    starting_ref="missing-ref",
                ),
                message="",
            )
            action_event = await EventTranscriptRepository().append(
                session,
                EventCreate(
                    session_id=agent_session.id,
                    kind=EventKind.ACTION_MESSAGE,
                    payload=action_payload.model_dump(mode="json"),
                    external_id="action-worktree-retry-buffer",
                ),
            )
        runner = _RunnerOperations(failures=["fatal: invalid ref"])
        service = _service(rdb_session_manager, runner)
        assert isinstance(action_payload.action, CreateGitWorktreeAction)
        first_result = await service.run_git_worktree_action(
            agent_id=agent_id,
            session_id=agent_session.id,
            action_event_id=action_event.id,
            action=action_payload.action,
        )
        assert first_result.completed is True
        async with rdb_session_manager() as session:
            failed = await ActionExecutionRepository().get_by_action_event_id(
                session,
                action_event_id=action_event.id,
            )
        assert failed is not None
        assert failed.status is ActionExecutionStatus.FAILED

        retry_result = await service.request_action_execution_retry(
            agent_id=agent_id,
            session_id=agent_session.id,
            action_execution_id=failed.id,
            user_id=user_id,
        )

        assert isinstance(retry_result, Success)
        assert retry_result.value.requested is True
        assert (
            retry_result.value.projection.execution.status
            is ActionExecutionStatus.PENDING
        )
        assert retry_result.value.projection.execution.attempt == 2
        assert retry_result.value.projection.events[-1].kind.value == "retry_requested"

    async def test_request_action_execution_discard_marks_failed_final(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Discard records failed_final without marking the action successful."""
        async with rdb_session_manager() as session:
            workspace_id, user_id, agent_id = await _create_agent_context(
                session,
                "action-discard",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action_payload = ActionMessagePayload(
                action=CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/repo",
                    starting_ref="missing-ref",
                ),
                message="",
            )
            action_event = await EventTranscriptRepository().append(
                session,
                EventCreate(
                    session_id=agent_session.id,
                    kind=EventKind.ACTION_MESSAGE,
                    payload=action_payload.model_dump(mode="json"),
                    external_id="action-worktree-discard-buffer",
                ),
            )
        runner = _RunnerOperations(failures=["fatal: invalid ref"])
        service = _service(rdb_session_manager, runner)
        assert isinstance(action_payload.action, CreateGitWorktreeAction)
        first_result = await service.run_git_worktree_action(
            agent_id=agent_id,
            session_id=agent_session.id,
            action_event_id=action_event.id,
            action=action_payload.action,
        )
        assert first_result.completed is True
        async with rdb_session_manager() as session:
            failed = await ActionExecutionRepository().get_by_action_event_id(
                session,
                action_event_id=action_event.id,
            )
        assert failed is not None

        discard_result = await service.request_action_execution_discard(
            agent_id=agent_id,
            session_id=agent_session.id,
            action_execution_id=failed.id,
            user_id=user_id,
        )

        assert isinstance(discard_result, Success)
        assert discard_result.value.requested is True
        assert (
            discard_result.value.projection.execution.status
            is ActionExecutionStatus.FAILED_FINAL
        )
        assert discard_result.value.projection.execution.failed_final_at is not None
        assert (
            discard_result.value.projection.events[-1].kind.value == "failed_finalized"
        )

    async def test_action_execution_retry_requires_failed_status(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Retry rejects completed action executions."""
        async with rdb_session_manager() as session:
            workspace_id, user_id, agent_id = await _create_agent_context(
                session,
                "action-retry-unavailable",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                ),
            )
            action_payload = ActionMessagePayload(
                action=CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/repo",
                    starting_ref="main",
                ),
                message="",
            )
            action_event = await EventTranscriptRepository().append(
                session,
                EventCreate(
                    session_id=agent_session.id,
                    kind=EventKind.ACTION_MESSAGE,
                    payload=action_payload.model_dump(mode="json"),
                    external_id="action-worktree-unavailable-buffer",
                ),
            )
        service = _service(rdb_session_manager, _RunnerOperations())
        assert isinstance(action_payload.action, CreateGitWorktreeAction)
        await service.run_git_worktree_action(
            agent_id=agent_id,
            session_id=agent_session.id,
            action_event_id=action_event.id,
            action=action_payload.action,
        )
        async with rdb_session_manager() as session:
            completed = await ActionExecutionRepository().get_by_action_event_id(
                session,
                action_event_id=action_event.id,
            )
        assert completed is not None

        retry_result = await service.request_action_execution_retry(
            agent_id=agent_id,
            session_id=agent_session.id,
            action_execution_id=completed.id,
            user_id=user_id,
        )

        assert isinstance(retry_result, Failure)

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
        """Valid worktree action creates Project and catalog rows."""
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
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[
                CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/repo",
                    starting_ref="main",
                )
            ],
            client_request_id="worktree-ready",
        )

        assert isinstance(result, Success)
        created = result.value.agent_session
        async with rdb_session_manager() as session:
            projects_before_action = (
                await SessionWorkspaceProjectRepository().list_projects(
                    session,
                    session_id=created.id,
                )
            )
        assert projects_before_action == []

        await _execute_first_setup_action(
            rdb_session_manager,
            worktree_service,
            agent_id=agent_id,
            session_id=created.id,
        )
        async with rdb_session_manager() as session:
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=created.id,
            )
            catalog = await AgentProjectCatalogRepository().list_entries(
                session,
                agent_id=agent_id,
            )

        project_paths = [project.path for project in projects]
        assert project_paths == [runner.calls[-1]["worktree_path"]]
        assert "/workspace/agent/repo" not in project_paths
        assert [entry.path for entry in catalog] == [runner.calls[-1]["worktree_path"]]

    async def test_invalid_ref_fails_action_and_keeps_input_pending(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Runner invalid ref failure leaves the action failed and input pending."""
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
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[
                CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/repo",
                    starting_ref="missing",
                )
            ],
            client_request_id="worktree-invalid",
        )

        assert isinstance(result, Success)
        action_event_id = await _execute_first_setup_action(
            rdb_session_manager,
            worktree_service,
            agent_id=agent_id,
            session_id=result.value.agent_session.id,
        )
        async with rdb_session_manager() as session:
            projection = (
                await ActionExecutionRepository().get_projection_by_action_event_id(
                    session,
                    action_event_id=action_event_id,
                )
            )
            buffers = await InputBufferRepository().list_by_session_id(
                session,
                result.value.agent_session.id,
            )
        assert projection is not None
        assert projection.execution.status is ActionExecutionStatus.FAILED
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
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[
                CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/repo",
                    starting_ref="main",
                )
            ],
            client_request_id="worktree-branch",
        )

        assert isinstance(result, Success)
        await _execute_first_setup_action(
            rdb_session_manager,
            worktree_service,
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
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[
                CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/repo",
                    starting_ref="main",
                )
            ],
            client_request_id="worktree-path",
        )

        assert isinstance(result, Success)
        await _execute_first_setup_action(
            rdb_session_manager,
            worktree_service,
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
        """Catalog upsert failure marks the action execution failed."""
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
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[
                CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/repo",
                    starting_ref="main",
                )
            ],
            client_request_id="worktree-catalog",
        )

        assert isinstance(result, Success)
        action_event_id = await _execute_first_setup_action(
            rdb_session_manager,
            worktree_service,
            agent_id=agent_id,
            session_id=result.value.agent_session.id,
        )
        async with rdb_session_manager() as session:
            projection = (
                await ActionExecutionRepository().get_projection_by_action_event_id(
                    session,
                    action_event_id=action_event_id,
                )
            )
        assert projection is not None
        assert projection.execution.status is ActionExecutionStatus.FAILED

    async def test_status_refresh_warning_does_not_block_ready(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Non-blocking status refresh warning keeps action execution completed."""
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
            inference_profile=_TEST_INFERENCE_PROFILE,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[
                CreateGitWorktreeAction(
                    source_project_path="/workspace/agent/repo",
                    starting_ref="main",
                )
            ],
            client_request_id="worktree-warning",
        )

        assert isinstance(result, Success)
        action_event_id = await _execute_first_setup_action(
            rdb_session_manager,
            worktree_service,
            agent_id=agent_id,
            session_id=result.value.agent_session.id,
        )
        async with rdb_session_manager() as session:
            projection = (
                await ActionExecutionRepository().get_projection_by_action_event_id(
                    session,
                    action_event_id=action_event_id,
                )
            )
        assert projection is not None
        assert projection.execution.status is ActionExecutionStatus.COMPLETED
        assert any(event.kind.value == "warning" for event in projection.events)

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
        assert request.cleanup_requested is True
        assert allocation is not None
        assert allocation.status is SessionGitWorktreeStatus.CLEANUP_PENDING
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
            session_workspace_project_id=None,
        )

        async with rdb_session_manager() as session:
            allocation = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
            catalog = await AgentProjectCatalogRepository().list_entries(
                session,
                agent_id=agent_id,
            )
            projects = await SessionWorkspaceProjectRepository().list_projects(
                session,
                session_id=session_id,
            )
        assert allocation is not None
        assert allocation.status is SessionGitWorktreeStatus.CLEANED
        assert catalog == []
        assert projects == []
        assert [call["operation"] for call in runner.calls] == [
            "create_git_worktree",
            "remove_git_worktree",
            "delete_git_branch",
            "list_files",
            "delete_file",
        ]
        remove_call = runner.calls[1]
        assert remove_call["force"] is False

    async def test_manual_cleanup_rejects_ordinary_project_target(
        self,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Project-targeted cleanup cannot delete ordinary Project rows."""
        runner = _RunnerOperations()
        (
            worktree_service,
            user_id,
            agent_id,
            session_id,
        ) = await _create_ready_worktree_session(
            rdb_session_manager,
            slug="cleanup-ordinary-project",
            runner=runner,
        )
        async with rdb_session_manager() as session:
            ordinary_project = await SessionWorkspaceProjectRepository().create_project(
                session,
                SessionWorkspaceProjectCreate(
                    session_id=session_id,
                    path="/workspace/agent/ordinary",
                ),
            )

        result = await worktree_service.request_manual_cleanup(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            session_workspace_project_id=ordinary_project.id,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, GitWorktreeCleanupNotFound)
        assert [call["operation"] for call in runner.calls] == ["create_git_worktree"]

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
            session_workspace_project_id=None,
        )

        async with rdb_session_manager() as session:
            allocation = await SessionGitWorktreeRepository().get_by_session_id(
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
        remove_call = runner.calls[1]
        assert remove_call["force"] is False
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
            session_workspace_project_id=None,
        )

        retry = await worktree_service.request_manual_cleanup(
            agent_id=agent_id,
            session_id=session_id,
            user_id=user_id,
            session_workspace_project_id=None,
        )
        assert isinstance(retry, Success)
        assert retry.value.cleanup_requested is True
        await worktree_service.run_cleanup_for_session(
            agent_id=agent_id,
            session_id=session_id,
            session_workspace_project_id=None,
        )

        async with rdb_session_manager() as session:
            allocation = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
        assert allocation is not None
        assert allocation.status is SessionGitWorktreeStatus.CLEANED

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
            row = await session.get(RDBSessionAgentContextGitWorktree, allocation.id)
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
            session_workspace_project_id=None,
        )

        async with rdb_session_manager() as session:
            allocation = await SessionGitWorktreeRepository().get_by_session_id(
                session,
                session_id=session_id,
            )
        assert allocation is not None
        assert allocation.status is SessionGitWorktreeStatus.CLEANUP_FAILED
        assert [call["operation"] for call in runner.calls] == ["create_git_worktree"]
