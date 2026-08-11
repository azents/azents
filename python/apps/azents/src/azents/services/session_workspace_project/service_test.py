"""SessionWorkspaceProjectService tests."""

import dataclasses
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ActionExecutionStatus,
    AgentProjectCatalogStatus,
    GitWorktreePathClaimState,
    LLMProvider,
    RuntimeRunnerState,
    WorkspaceUserRole,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.git_worktree_cleanup_claim import (
    RDBGitWorktreePathClaim,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.action_execution.data import ActionExecutionCreate
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
    RuntimeFileStatResult,
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
)
from azents.services.agent_runtime.lifecycle_data import (
    RuntimeOperationAuthority,
    RuntimeOperationTarget,
    RuntimeOperationTargetResolver,
)
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderAuthority,
    SessionWorkingFolderBindingError,
    SessionWorkingFolderBindingService,
)
from azents.testing.model_selection import make_test_model_selection_dict

from . import (
    InvalidProjectPath,
    ProjectAccessDenied,
    ProjectPathCleanupInProgress,
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

    def __init__(
        self,
        *,
        kind: str = "directory",
        error_code: str | None = None,
    ) -> None:
        self.kind = kind
        self.error_code = error_code
        self.paths: list[str] = []

    async def stat_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileStatResult:
        """Return one configured Runtime path outcome."""
        del runtime_id, runner_generation, owner_session_id, deadline_at
        self.paths.append(path)
        if self.error_code is not None:
            raise RuntimeRunnerOperationFailedError(
                "Runtime stat failed.",
                code=self.error_code,
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


class _FakeRuntimeTargetResolver(RuntimeOperationTargetResolver):
    """Return one qualified Runtime target without lifecycle I/O."""

    def __init__(self) -> None:
        self.start_if_stopped_calls: list[bool] = []

    async def resolve_operation_target(
        self,
        agent_id: str,
        *,
        wait_timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 1.0,
        expected_authority: RuntimeOperationAuthority | None = None,
        start_if_stopped: bool = True,
    ) -> RuntimeOperationTarget:
        """Return deterministic exact Runtime evidence."""
        self.start_if_stopped_calls.append(start_if_stopped)
        del (
            agent_id,
            wait_timeout_seconds,
            poll_interval_seconds,
            expected_authority,
        )
        return RuntimeOperationTarget(
            id="runtime-1",
            runtime_capability_version=1,
            desired_generation=1,
            runner_generation=1,
            configuration_sequence=1,
            configuration_digest="a" * 64,
            workspace_path="/workspace/agent",
        )


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

    runtime_repository = AgentRuntimeRepository()
    runtime = await runtime_repository.ensure_for_agent(session, agent.id)
    await runtime_repository.record_runner_state(
        session,
        runtime.id,
        RuntimeRunnerState.UNKNOWN,
        1,
        expected_desired_generation=runtime.desired_generation,
        workspace_path="/workspace/agent",
    )
    agent_session = (
        await AgentSessionRepository().ensure_team_primary_for_agent(
            session,
            workspace_id=workspace_id,
            agent_id=agent.id,
        )
    ).session
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
    binding_error: SessionWorkingFolderBindingError | None = None,
    runtime_target_resolver: RuntimeOperationTargetResolver | None = None,
) -> SessionWorkspaceProjectService:
    """Create service for tests."""
    binding_service = AsyncMock(spec=SessionWorkingFolderBindingService)

    async def resolve_binding(
        *,
        agent_id: str,
        session_id: str,
        runtime_target: RuntimeOperationTarget,
    ) -> SessionWorkingFolderAuthority:
        return SessionWorkingFolderAuthority(
            context_id="context-1",
            agent_id=agent_id,
            agent_runtime_id=runtime_target.id,
            working_folder_path=(
                f"{runtime_target.workspace_path}/.azents/sessions/{session_id}"
            ),
            runtime_capability_version=runtime_target.runtime_capability_version,
        )

    binding_service.resolve_authority_for_target.side_effect = resolve_binding

    async def resolve_binding_in_transaction(
        transaction: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        runtime_target: RuntimeOperationTarget,
    ) -> SessionWorkingFolderAuthority:
        del transaction
        return await resolve_binding(
            agent_id=agent_id,
            session_id=session_id,
            runtime_target=runtime_target,
        )

    binding_service.resolve_authority_in_transaction.side_effect = (
        resolve_binding_in_transaction
    )
    binding_service.resolve_bound_authority_in_transaction.side_effect = (
        resolve_binding_in_transaction
    )
    if binding_error is not None:
        binding_service.require_bindable_context.side_effect = binding_error
        binding_service.require_bound_context.side_effect = binding_error
        binding_service.resolve_authority_for_target.side_effect = binding_error
        binding_service.resolve_authority_in_transaction.side_effect = binding_error
        binding_service.resolve_bound_authority_in_transaction.side_effect = (
            binding_error
        )
    return SessionWorkspaceProjectService(
        repository=SessionWorkspaceProjectRepository(),
        agent_project_preset_repository=AgentProjectPresetRepository(),
        agent_project_catalog_repository=AgentProjectCatalogRepository(),
        agent_session_repository=AgentSessionRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        session_manager=_SessionManager(session),
        runtime_target_resolver=(
            runtime_target_resolver or _FakeRuntimeTargetResolver()
        ),
        session_working_folder_binding_service=binding_service,
        runner_operations=runner_operations,
    )


class TestSessionWorkspaceProjectService:
    """SessionWorkspaceProjectService tests."""

    def test_normalize_rejects_workspace_root(self) -> None:
        """Session Workspace root itself cannot become Project."""
        try:
            normalize_session_workspace_path(
                "/runtime/home",
                workspace_root="/runtime/home",
            )
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

    @pytest.mark.parametrize(
        ("claim_suffix", "project_suffix"),
        [
            ("repo", "repo/nested"),
            ("repo/nested", "repo"),
        ],
    )
    async def test_create_project_rejects_overlapping_cleanup_claim(
        self,
        rdb_session: AsyncSession,
        claim_suffix: str,
        project_suffix: str,
    ) -> None:
        """Reject Project attachment while manual cleanup owns an ancestor path."""
        workspace_id = await _create_workspace(rdb_session, "swp-svc-cleanup-claim")
        fixture = await _create_runtime_fixture(
            rdb_session,
            workspace_id,
            "swp-svc-cleanup-claim",
        )
        execution = await ActionExecutionRepository().create(
            rdb_session,
            ActionExecutionCreate(
                id=None,
                session_id=fixture.session_id,
                mailbox_item_id="01900000000070008000000000000010",
                sender_user_id=None,
                action_type="cleanup_orphan_git_worktrees",
                action={"type": "cleanup_orphan_git_worktrees"},
                status=ActionExecutionStatus.RUNNING,
                owner_generation=0,
            ),
        )
        repository = SessionWorkspaceProjectRepository()
        claim_path = f"/workspace/agent/.azents/worktrees/orphan/{claim_suffix}"
        claim_result = await repository.try_claim_orphan_git_worktree(
            rdb_session,
            runtime_id=fixture.runtime_id,
            action_execution_id=execution.id,
            owner_generation=execution.owner_generation,
            worktree_path=claim_path,
            discovery_fingerprint="test-discovery-fingerprint",
        )
        assert claim_result == "claimed"

        result = await _service(rdb_session).create_project(
            session_id=fixture.session_id,
            path=f"/workspace/agent/.azents/worktrees/orphan/{project_suffix}",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProjectPathCleanupInProgress)
        await repository.release_orphan_git_worktree_claim(
            rdb_session,
            action_execution_id=execution.id,
            worktree_path=claim_path,
            state=GitWorktreePathClaimState.UNRESOLVED,
        )
        after_release = await _service(rdb_session).create_project(
            session_id=fixture.session_id,
            path=f"/workspace/agent/.azents/worktrees/orphan/{project_suffix}",
        )
        assert isinstance(after_release, Success)

    async def test_expired_cleanup_claim_with_current_owner_still_blocks_reclaim(
        self, rdb_session: AsyncSession
    ) -> None:
        """Keep an expired claim while its owning action remains current."""
        workspace_id = await _create_workspace(rdb_session, "swp-svc-current-claim")
        fixture = await _create_runtime_fixture(
            rdb_session,
            workspace_id,
            "swp-svc-current-claim",
        )
        action_repository = ActionExecutionRepository()
        owner = await action_repository.create(
            rdb_session,
            ActionExecutionCreate(
                id=None,
                session_id=fixture.session_id,
                mailbox_item_id="01900000000070008000000000000011",
                sender_user_id=None,
                action_type="cleanup_orphan_git_worktrees",
                action={"type": "cleanup_orphan_git_worktrees"},
                status=ActionExecutionStatus.RUNNING,
                owner_generation=0,
            ),
        )
        repository = SessionWorkspaceProjectRepository()
        path = "/workspace/agent/.azents/worktrees/orphan/current"
        assert (
            await repository.try_claim_orphan_git_worktree(
                rdb_session,
                runtime_id=fixture.runtime_id,
                action_execution_id=owner.id,
                owner_generation=owner.owner_generation,
                worktree_path=path,
                discovery_fingerprint="owner-fingerprint",
            )
            == "claimed"
        )
        claim = await rdb_session.scalar(
            sa.select(RDBGitWorktreePathClaim).where(
                RDBGitWorktreePathClaim.action_execution_id == owner.id
            )
        )
        assert claim is not None
        claim.lease_until = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            seconds=1
        )
        contender = await action_repository.create(
            rdb_session,
            ActionExecutionCreate(
                id=None,
                session_id=fixture.session_id,
                mailbox_item_id="01900000000070008000000000000012",
                sender_user_id=None,
                action_type="cleanup_orphan_git_worktrees",
                action={"type": "cleanup_orphan_git_worktrees"},
                status=ActionExecutionStatus.RUNNING,
                owner_generation=0,
            ),
        )

        result = await repository.try_claim_orphan_git_worktree(
            rdb_session,
            runtime_id=fixture.runtime_id,
            action_execution_id=contender.id,
            owner_generation=contender.owner_generation,
            worktree_path=path,
            discovery_fingerprint="contender-fingerprint",
        )

        assert result == "cleanup_in_progress"

    async def test_expired_cleanup_claim_with_stale_owner_is_reassigned(
        self, rdb_session: AsyncSession
    ) -> None:
        """Reclaim an expired manual claim when ownership generation advanced."""
        workspace_id = await _create_workspace(rdb_session, "swp-svc-stale-claim")
        fixture = await _create_runtime_fixture(
            rdb_session,
            workspace_id,
            "swp-svc-stale-claim",
        )
        action_repository = ActionExecutionRepository()
        owner = await action_repository.create(
            rdb_session,
            ActionExecutionCreate(
                id=None,
                session_id=fixture.session_id,
                mailbox_item_id="01900000000070008000000000000013",
                sender_user_id=None,
                action_type="cleanup_orphan_git_worktrees",
                action={"type": "cleanup_orphan_git_worktrees"},
                status=ActionExecutionStatus.RUNNING,
                owner_generation=0,
            ),
        )
        repository = SessionWorkspaceProjectRepository()
        path = "/workspace/agent/.azents/worktrees/orphan/stale"
        assert (
            await repository.try_claim_orphan_git_worktree(
                rdb_session,
                runtime_id=fixture.runtime_id,
                action_execution_id=owner.id,
                owner_generation=owner.owner_generation,
                worktree_path=path,
                discovery_fingerprint="owner-fingerprint",
            )
            == "claimed"
        )
        claim = await rdb_session.scalar(
            sa.select(RDBGitWorktreePathClaim).where(
                RDBGitWorktreePathClaim.action_execution_id == owner.id
            )
        )
        assert claim is not None
        claim.lease_until = datetime.datetime.now(datetime.UTC) - datetime.timedelta(
            seconds=1
        )
        agent_session = await rdb_session.get(RDBAgentSession, fixture.session_id)
        assert agent_session is not None
        agent_session.owner_generation = 1
        contender = await action_repository.create(
            rdb_session,
            ActionExecutionCreate(
                id=None,
                session_id=fixture.session_id,
                mailbox_item_id="01900000000070008000000000000014",
                sender_user_id=None,
                action_type="cleanup_orphan_git_worktrees",
                action={"type": "cleanup_orphan_git_worktrees"},
                status=ActionExecutionStatus.RUNNING,
                owner_generation=1,
            ),
        )

        result = await repository.try_claim_orphan_git_worktree(
            rdb_session,
            runtime_id=fixture.runtime_id,
            action_execution_id=contender.id,
            owner_generation=contender.owner_generation,
            worktree_path=path,
            discovery_fingerprint="contender-fingerprint",
        )

        assert result == "claimed"
        await rdb_session.refresh(claim)
        assert claim.action_execution_id == contender.id
        assert claim.owner_generation == contender.owner_generation

    async def test_cancellation_retains_removing_claim_after_action_handover(
        self, rdb_session: AsyncSession
    ) -> None:
        """Keep a bounded claim while a cancelled Runner removal may still settle."""
        workspace_id = await _create_workspace(rdb_session, "swp-svc-removing-claim")
        fixture = await _create_runtime_fixture(
            rdb_session,
            workspace_id,
            "swp-svc-removing-claim",
        )
        action_repository = ActionExecutionRepository()
        execution = await action_repository.create(
            rdb_session,
            ActionExecutionCreate(
                id=None,
                session_id=fixture.session_id,
                mailbox_item_id="01900000000070008000000000000015",
                sender_user_id=None,
                action_type="cleanup_orphan_git_worktrees",
                action={"type": "cleanup_orphan_git_worktrees"},
                status=ActionExecutionStatus.RUNNING,
                owner_generation=0,
            ),
        )
        repository = SessionWorkspaceProjectRepository()
        path = "/workspace/agent/.azents/worktrees/orphan/removing"
        assert (
            await repository.try_claim_orphan_git_worktree(
                rdb_session,
                runtime_id=fixture.runtime_id,
                action_execution_id=execution.id,
                owner_generation=execution.owner_generation,
                worktree_path=path,
                discovery_fingerprint="removing-fingerprint",
            )
            == "claimed"
        )
        await repository.mark_orphan_git_worktree_claim_removing(
            rdb_session,
            action_execution_id=execution.id,
            worktree_path=path,
        )

        await repository.release_nonremoving_orphan_git_worktree_claims(
            rdb_session,
            action_execution_id=execution.id,
        )
        await action_repository.delete_by_id(
            rdb_session,
            action_execution_id=execution.id,
        )
        claim = await rdb_session.scalar(
            sa.select(RDBGitWorktreePathClaim).where(
                RDBGitWorktreePathClaim.worktree_path == path
            )
        )

        assert claim is not None
        assert claim.action_execution_id is None
        assert claim.state == GitWorktreePathClaimState.REMOVING
        assert claim.lease_until > datetime.datetime.now(datetime.UTC)

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

    async def test_register_existing_folder_rejects_non_directory(
        self, rdb_session: AsyncSession
    ) -> None:
        """Session registration shares strict Runtime directory semantics."""
        workspace_id = await _create_workspace(rdb_session, "swp-svc-register-file")
        fixture = await _create_runtime_fixture(
            rdb_session,
            workspace_id,
            "swp-svc-register-file",
        )
        user_id = await _create_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            email="swp-svc-register-file@example.com",
        )
        runtime = await rdb_session.get(RDBAgentRuntime, fixture.runtime_id)
        assert runtime is not None
        runtime.runner_state = RuntimeRunnerState.READY
        service = _service(
            rdb_session,
            runner_operations=_FakeRunnerOperations(kind="file"),
        )

        result = await service.register_existing_folder_for_session(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            user_id=user_id,
            path="/workspace/agent/file",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, InvalidProjectPath)
        assert result.error.reason == "Project path must be a runtime directory."

    async def test_register_existing_folder_preserves_timeout_error_contract(
        self, rdb_session: AsyncSession
    ) -> None:
        """Session registration maps shared unavailability to its existing error."""
        workspace_id = await _create_workspace(rdb_session, "swp-svc-register-timeout")
        fixture = await _create_runtime_fixture(
            rdb_session,
            workspace_id,
            "swp-svc-register-timeout",
        )
        user_id = await _create_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            email="swp-svc-register-timeout@example.com",
        )
        runtime = await rdb_session.get(RDBAgentRuntime, fixture.runtime_id)
        assert runtime is not None
        runtime.runner_state = RuntimeRunnerState.READY
        service = _service(
            rdb_session,
            runner_operations=_FakeRunnerOperations(
                error_code="operation_timeout",
            ),
        )

        result = await service.register_existing_folder_for_session(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            user_id=user_id,
            path="/workspace/agent/app",
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, InvalidProjectPath)
        assert result.error.reason == (
            "Project path can only be approved from a ready runtime."
        )

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
        runtime_target_resolver = _FakeRuntimeTargetResolver()
        service = _service(
            rdb_session,
            runtime_target_resolver=runtime_target_resolver,
        )
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
        assert runtime_target_resolver.start_if_stopped_calls == [True, False]

    async def test_list_projects_for_session_requires_bound_context(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Persisted Project paths remain hidden without current bound authority."""
        workspace_id = await _create_workspace(rdb_session, "swp-svc-bound-list")
        fixture = await _create_runtime_fixture(
            rdb_session,
            workspace_id,
            "swp-svc-bound-list",
        )
        user_id = await _create_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            email="swp-svc-bound-list@example.com",
        )
        created = await _service(rdb_session).create_project(
            session_id=fixture.session_id,
            path="/workspace/agent/app",
        )
        assert isinstance(created, Success)
        runtime_target_resolver = _FakeRuntimeTargetResolver()
        service = _service(
            rdb_session,
            binding_error=SessionWorkingFolderBindingError("binding_invalidated"),
            runtime_target_resolver=runtime_target_resolver,
        )

        result = await service.list_projects_for_session(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            user_id=user_id,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProjectAccessDenied)
        assert runtime_target_resolver.start_if_stopped_calls == []

    async def test_delete_project_for_session_requires_bound_context(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Project registry mutation is denied after binding authority is lost."""
        workspace_id = await _create_workspace(rdb_session, "swp-svc-bound-delete")
        fixture = await _create_runtime_fixture(
            rdb_session,
            workspace_id,
            "swp-svc-bound-delete",
        )
        user_id = await _create_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            email="swp-svc-bound-delete@example.com",
        )
        created = await _service(rdb_session).create_project(
            session_id=fixture.session_id,
            path="/workspace/agent/app",
        )
        assert isinstance(created, Success)
        runtime_target_resolver = _FakeRuntimeTargetResolver()
        service = _service(
            rdb_session,
            binding_error=SessionWorkingFolderBindingError("binding_invalidated"),
            runtime_target_resolver=runtime_target_resolver,
        )

        result = await service.delete_project_for_session(
            agent_id=fixture.agent_id,
            session_id=fixture.session_id,
            user_id=user_id,
            project_id=created.value.id,
        )

        assert isinstance(result, Failure)
        assert isinstance(result.error, ProjectAccessDenied)
        assert runtime_target_resolver.start_if_stopped_calls == []
        stored = await SessionWorkspaceProjectRepository().get_project_by_id(
            rdb_session,
            created.value.id,
        )
        assert stored is not None
