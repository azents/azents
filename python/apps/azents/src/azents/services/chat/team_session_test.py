"""ChatSessionService team session tests."""

import datetime
import logging
from typing import Literal, cast

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionPrimaryKind,
    AgentSessionRunState,
    AgentSessionStatus,
    AgentSessionTitleSource,
    EventKind,
    LLMProvider,
    RuntimeRunnerState,
    SessionWorkingFolderCleanupStatus,
    WorkspaceUserRole,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_automatic_project_setting import (
    RDBAgentAutomaticProjectSetting,
)
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.session_agent_context import RDBSessionAgentContext
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent_automatic_project import AgentAutomaticProjectRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.external_channel.lifecycle import ExternalChannelLifecycleRepository
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.message import MessageRepository
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.runtime.control_protocol.runner_operations import (
    RuntimeFileDeleteResult,
    RuntimeFileStatResult,
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
)
from azents.services.chat.data import (
    InvalidSessionTitle,
)
from azents.services.exchange_file import ExchangeFileService
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.lifecycle import ExternalChannelLifecycleService
from azents.services.mailbox import MailboxService
from azents.services.model_file import ModelFileService
from azents.services.root_agent_session_creation import (
    RootAgentSessionCreationService,
)
from azents.services.session_git_worktree import SessionGitWorktreeService
from azents.services.session_lifecycle.registry import (
    get_session_lifecycle_orchestrator,
)
from azents.testing.model_selection import make_test_model_selection_dict

from . import ChatSessionService
from .data import (
    PrimarySessionArchiveBlocked,
    PrimarySessionPinBlocked,
    RunningSessionArchiveBlocked,
)


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


async def _create_agent(
    session: AsyncSession,
    workspace_id: str,
    slug: str,
    *,
    workspace_path: str | None = "/workspace/agent",
) -> str:
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
    session.add(RDBAgentAutomaticProjectSetting(agent_id=agent.id))
    runtime_repository = AgentRuntimeRepository()
    runtime = await runtime_repository.ensure_for_agent(session, agent.id)
    if workspace_path is not None:
        await runtime_repository.record_runner_state(
            session,
            runtime.id,
            RuntimeRunnerState.UNKNOWN,
            1,
            expected_desired_generation=runtime.desired_generation,
            workspace_path=workspace_path,
        )
    return agent.id


def _service(
    rdb_session_manager: SessionManager[AsyncSession],
    *,
    session_git_worktree_repository: SessionGitWorktreeRepository | None = None,
    session_git_worktree_service: SessionGitWorktreeService | None = None,
    agent_runtime_repository: AgentRuntimeRepository | None = None,
    runner_operations: RuntimeRunnerOperationClient | None = None,
) -> ChatSessionService:
    """Create ChatSessionService for tests."""
    return ChatSessionService(
        message_repository=MessageRepository(),
        agent_repository=AgentRepository(),
        agent_project_preset_repository=AgentProjectPresetRepository(),
        agent_project_catalog_repository=AgentProjectCatalogRepository(),
        agent_project_default_repository=AgentProjectDefaultRepository(),
        session_git_worktree_repository=(
            session_git_worktree_repository or SessionGitWorktreeRepository()
        ),
        agent_run_repository=AgentRunRepository(),
        action_execution_repository=ActionExecutionRepository(),
        event_transcript_repository=EventTranscriptRepository(),
        agent_session_repository=AgentSessionRepository(),
        agent_runtime_repository=(agent_runtime_repository or AgentRuntimeRepository()),
        root_agent_session_creation_service=RootAgentSessionCreationService(
            agent_session_repository=AgentSessionRepository(),
            automatic_project_repository=AgentAutomaticProjectRepository(),
            agent_runtime_repository=AgentRuntimeRepository(),
            session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        ),
        archived_session_retention_repository=ArchivedSessionRetentionRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        mailbox_item_service=MailboxService(
            session_manager=rdb_session_manager,
            mailbox_item_repository=MailboxRepository(),
            exchange_file_service=_ExchangeFileService(),
            model_file_service=cast(ModelFileService, object()),
            agent_session_repository=AgentSessionRepository(),
            event_transcript_repository=EventTranscriptRepository(),
            agent_run_repository=AgentRunRepository(),
            action_execution_repository=ActionExecutionRepository(),
            vfs_projection_service=None,
            external_channel_repository=ExternalChannelRepository(),
        ),
        session_git_worktree_service=(
            session_git_worktree_service
            or cast(
                SessionGitWorktreeService,
                _ArchiveCleanupService(rdb_session_manager),
            )
        ),
        lifecycle_orchestrator=get_session_lifecycle_orchestrator(),
        external_channel_lifecycle_service=ExternalChannelLifecycleService(
            repository=ExternalChannelLifecycleRepository(),
            action_service=cast(ExternalChannelActionService, _ChannelActionService()),
        ),
        session_manager=rdb_session_manager,
        runner_operations=runner_operations,
    )


class _ExchangeFileService(ExchangeFileService):
    """ExchangeFileService for tests."""

    def __init__(self) -> None:
        """Bypass Base dataclass initialization."""


class _ChannelActionService:
    """Return an empty archive delivery sweep for Session tests."""

    async def drain_archive_cleanup(self, delivery_ids: object) -> int:
        """Report that no provider cleanup intent was pending."""
        del delivery_ids
        return 0


class _OwnedWorktreeRepository(SessionGitWorktreeRepository):
    """Identify Azents-owned worktree paths from an in-memory set."""

    def __init__(self, paths: set[str]) -> None:
        """Initialize owned worktree paths."""
        self.paths = paths

    async def exists_by_worktree_path(
        self,
        session: AsyncSession,
        *,
        worktree_path: str,
    ) -> bool:
        """Return whether the path is an owned worktree."""
        del session
        return worktree_path in self.paths


class _ArchiveCleanupService:
    """Observe post-commit archive cleanup and optionally fail."""

    def __init__(
        self,
        session_manager: SessionManager[AsyncSession],
        *,
        failure: Exception | None = None,
    ) -> None:
        self.session_manager = session_manager
        self.failure = failure
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []
        self.observed_statuses: list[AgentSessionStatus] = []
        self.observed_cleanup_statuses: list[SessionWorkingFolderCleanupStatus] = []

    async def run_archive_cleanup_for_root_tree(
        self,
        *,
        agent_id: str,
        root_session_id: str,
        subtree_session_ids: list[str],
    ) -> int:
        """Record that cleanup starts only after the root is archived."""
        self.calls.append((agent_id, root_session_id, tuple(subtree_session_ids)))
        async with self.session_manager() as session:
            root = await AgentSessionRepository().get_by_id(
                session,
                root_session_id,
            )
            context = (
                await AgentSessionRepository().get_working_folder_context_by_session_id(
                    session,
                    session_id=root_session_id,
                )
            )
        assert root is not None
        assert context is not None
        self.observed_statuses.append(root.status)
        self.observed_cleanup_statuses.append(context.cleanup_status)
        if self.failure is not None:
            raise self.failure
        return 1


class _ReadyRuntimeRepository(AgentRuntimeRepository):
    """Return the fixture's ready Runtime for archive cleanup tests."""

    async def get_by_agent_id(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> AgentRuntime | None:
        """Return one ready Runtime without a fixture persistence dependency."""
        del session
        now = datetime.datetime.now(datetime.UTC)
        return AgentRuntime(
            id="runtime-archive-cleanup",
            workspace_id="workspace-archive-cleanup",
            agent_id=agent_id,
            runner_state=RuntimeRunnerState.READY,
            runner_generation=7,
            workspace_path="/workspace/agent",
            created_at=now,
            updated_at=now,
        )


class _FolderDeleteRunner(RuntimeRunnerOperationClient):
    """Record one archive-owned recursive Session-folder delete."""

    def __init__(
        self,
        *,
        failure: RuntimeRunnerOperationFailedError | None = None,
        target_kind: Literal[
            "directory", "file", "symlink", "other", "missing"
        ] = "directory",
    ) -> None:
        self.failure = failure
        self.target_kind: Literal[
            "directory", "file", "symlink", "other", "missing"
        ] = target_kind
        self.calls: list[dict[str, object]] = []
        self.stat_calls: list[dict[str, object]] = []

    async def stat_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileStatResult:
        """Return a lexical root kind for archive cleanup validation."""
        del deadline_at
        self.stat_calls.append(
            {
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "owner_session_id": owner_session_id,
                "path": path,
            }
        )
        return RuntimeFileStatResult(
            path=path,
            kind=self.target_kind,
            size_bytes=None,
            symlink=self.target_kind == "symlink",
            real_path=None,
            resolved_kind=self.target_kind,
            modified_at=None,
            final_cursor="folder-stat",
        )

    async def delete_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        recursive: bool,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileDeleteResult:
        """Record or fail one exact recursive delete."""
        del deadline_at
        self.calls.append(
            {
                "runtime_id": runtime_id,
                "runner_generation": runner_generation,
                "owner_session_id": owner_session_id,
                "path": path,
                "recursive": recursive,
            }
        )
        if self.failure is not None:
            raise self.failure
        return RuntimeFileDeleteResult(path=path, final_cursor="folder-delete")


class TestChatSessionTeamSessions:
    """Team session service behavior."""

    async def test_create_empty_team_session_without_workspace_path(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Root Session creation requires a persisted Runner workspace path."""
        workspace_id = await _create_workspace(rdb_session, "team-empty-no-runtime")
        user_id = await _create_user(
            rdb_session,
            "team-empty-no-runtime@example.com",
        )
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "team-empty-no-runtime",
            workspace_path=None,
        )
        await rdb_session.commit()

        with pytest.raises(
            RuntimeError,
            match="Agent Runtime workspace path is unavailable",
        ):
            await _service(rdb_session_manager).create_team_session(
                agent_id=agent_id,
                user_id=user_id,
                existing_project_paths=[],
                setup_actions=[],
            )

    async def test_create_team_session_uses_explicit_projects(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """New team sessions receive exactly the submitted Project paths."""
        workspace_id = await _create_workspace(rdb_session, "team-session-projects")
        user_id = await _create_user(rdb_session, "team-session-projects@example.com")
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "team-explicit-projects",
        )
        await AgentSessionRepository().ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        await rdb_session.commit()

        create_result = await _service(rdb_session_manager).create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=[
                "/workspace/agent/project-a",
                "/workspace/agent/project-a/nested",
                "/workspace/agent/project-a",
            ],
            setup_actions=[],
        )

        assert isinstance(create_result, Success)
        created = create_result.value
        assert created.agent_id == agent_id
        assert created.primary_kind is None

        async with rdb_session_manager() as verify_session:
            projects = await SessionWorkspaceProjectRepository().list_projects(
                verify_session,
                session_id=created.id,
            )
            presets = await AgentProjectPresetRepository().list_presets(
                verify_session,
                agent_id=agent_id,
            )
            catalog_entries = await AgentProjectCatalogRepository().list_entries(
                verify_session,
                agent_id=agent_id,
            )

        assert [project.path for project in projects] == [
            "/workspace/agent/project-a",
            "/workspace/agent/project-a/nested",
        ]
        assert {preset.path for preset in presets} == {
            "/workspace/agent/project-a",
            "/workspace/agent/project-a/nested",
        }
        assert {entry.path for entry in catalog_entries} == {
            "/workspace/agent/project-a",
            "/workspace/agent/project-a/nested",
        }

    async def test_new_session_project_defaults_use_stored_last_created_projects(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """New session Project defaults use stored last non-empty creation paths."""
        workspace_id = await _create_workspace(rdb_session, "team-session-defaults")
        user_id = await _create_user(rdb_session, "team-session-defaults@example.com")
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "team-default-projects",
        )
        await AgentSessionRepository().ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        await rdb_session.commit()

        empty_result = await _service(
            rdb_session_manager
        ).get_new_session_project_defaults(
            agent_id=agent_id,
            user_id=user_id,
        )

        assert isinstance(empty_result, Success)
        assert empty_result.value.project_paths == []
        assert empty_result.value.source.type == "empty"
        assert empty_result.value.source.session_id is None

        create_result = await _service(rdb_session_manager).create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=["/workspace/agent/project-a"],
            setup_actions=[],
        )
        assert isinstance(create_result, Success)

        recent_result = await _service(
            rdb_session_manager
        ).get_new_session_project_defaults(
            agent_id=agent_id,
            user_id=user_id,
        )

        assert isinstance(recent_result, Success)
        assert recent_result.value.project_paths == ["/workspace/agent/project-a"]
        assert recent_result.value.source.type == "last_created_session"
        assert recent_result.value.source.session_id is None

        empty_create_result = await _service(rdb_session_manager).create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
        )
        assert isinstance(empty_create_result, Success)

        after_empty_result = await _service(
            rdb_session_manager
        ).get_new_session_project_defaults(
            agent_id=agent_id,
            user_id=user_id,
        )

        assert isinstance(after_empty_result, Success)
        assert after_empty_result.value.project_paths == ["/workspace/agent/project-a"]
        assert after_empty_result.value.source.type == "last_created_session"
        assert after_empty_result.value.source.session_id is None

        replace_result = await _service(rdb_session_manager).create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=[
                "/workspace/agent/project-b",
                "/workspace/agent/project-c",
            ],
            setup_actions=[],
        )
        assert isinstance(replace_result, Success)

        replaced_defaults = await _service(
            rdb_session_manager
        ).get_new_session_project_defaults(
            agent_id=agent_id,
            user_id=user_id,
        )

        assert isinstance(replaced_defaults, Success)
        assert replaced_defaults.value.project_paths == [
            "/workspace/agent/project-b",
            "/workspace/agent/project-c",
        ]
        assert replaced_defaults.value.source.type == "last_created_session"
        assert replaced_defaults.value.source.session_id is None

    async def test_owned_worktree_project_is_not_saved_as_reusable_default(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Concrete owned worktrees remain session-only Projects."""
        workspace_id = await _create_workspace(
            rdb_session,
            "team-session-owned-worktree-default",
        )
        user_id = await _create_user(
            rdb_session,
            "team-session-owned-worktree-default@example.com",
        )
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "team-owned-worktree-default",
        )
        await AgentSessionRepository().ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        await AgentProjectDefaultRepository().replace_defaults(
            rdb_session,
            agent_id=agent_id,
            paths=["/workspace/agent/previous-project"],
        )
        await rdb_session.commit()

        worktree_path = "/workspace/agent/.azents/worktrees/example/azents"
        service = _service(
            rdb_session_manager,
            session_git_worktree_repository=_OwnedWorktreeRepository({worktree_path}),
        )
        create_result = await service.create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=[worktree_path],
            setup_actions=[],
        )
        assert isinstance(create_result, Success)

        defaults_result = await service.get_new_session_project_defaults(
            agent_id=agent_id,
            user_id=user_id,
        )
        presets_result = await service.list_agent_project_presets(
            agent_id=agent_id,
            user_id=user_id,
        )
        async with rdb_session_manager() as verify_session:
            projects = await SessionWorkspaceProjectRepository().list_projects(
                verify_session,
                session_id=create_result.value.id,
            )

        assert isinstance(defaults_result, Success)
        assert defaults_result.value.project_paths == []
        assert defaults_result.value.items == []
        assert defaults_result.value.source.type == "empty"
        assert isinstance(presets_result, Success)
        assert presets_result.value == []
        assert [project.path for project in projects] == [worktree_path]

    async def test_update_session_title_trims_and_clears_title(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Session title updates normalize whitespace and explicit null clears it."""
        workspace_id = await _create_workspace(rdb_session, "team-session-title")
        user_id = await _create_user(rdb_session, "team-session-title@example.com")
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(rdb_session, workspace_id, "team-title-agent")
        agent_session = (
            await AgentSessionRepository().ensure_team_primary_for_agent(
                rdb_session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
        ).session
        await rdb_session.commit()

        titled = await _service(rdb_session_manager).update_session_title(
            session_id=agent_session.id,
            user_id=user_id,
            title="  Design review  ",
        )
        cleared = await _service(rdb_session_manager).update_session_title(
            session_id=agent_session.id,
            user_id=user_id,
            title=None,
        )

        assert isinstance(titled, Success)
        assert titled.value.title == "Design review"
        assert titled.value.title_source == AgentSessionTitleSource.MANUAL
        assert isinstance(cleared, Success)
        assert cleared.value.title is None
        assert cleared.value.title_source is None

    async def test_initial_auto_title_only_applies_when_unset(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Initial automatic titles do not overwrite manual titles."""
        workspace_id = await _create_workspace(rdb_session, "team-session-auto-title")
        agent_id = await _create_agent(rdb_session, workspace_id, "team-auto-title")
        agent_session = (
            await AgentSessionRepository().ensure_team_primary_for_agent(
                rdb_session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
        ).session
        event = await EventTranscriptRepository().append(
            rdb_session,
            EventCreate(
                session_id=agent_session.id,
                kind=EventKind.USER_MESSAGE,
                payload={
                    "content": "Plan a family trip to Kyoto next month",
                    "attachments": [],
                    "metadata": {},
                },
            ),
        )

        initial = await AgentSessionRepository().set_initial_auto_title_if_unset(
            rdb_session,
            session_id=agent_session.id,
            title="Plan a family trip to Kyoto next month",
            event_id=event.id,
        )
        manual = await AgentSessionRepository().update_title(
            rdb_session,
            session_id=agent_session.id,
            title="Manual title",
            title_source=AgentSessionTitleSource.MANUAL,
        )
        skipped = await AgentSessionRepository().set_initial_auto_title_if_unset(
            rdb_session,
            session_id=agent_session.id,
            title="Automatic overwrite",
            event_id=event.id,
        )

        assert initial is not None
        assert initial.title_source == AgentSessionTitleSource.AUTO_INITIAL
        assert manual is not None
        assert manual.title == "Manual title"
        assert skipped is None

    async def test_generated_auto_title_only_replaces_initial_auto_title(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """LLM-generated titles only replace the initial automatic title state."""
        workspace_id = await _create_workspace(rdb_session, "team-session-gen-title")
        agent_id = await _create_agent(rdb_session, workspace_id, "team-gen-title")
        agent_session = (
            await AgentSessionRepository().ensure_team_primary_for_agent(
                rdb_session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
        ).session
        event = await EventTranscriptRepository().append(
            rdb_session,
            EventCreate(
                session_id=agent_session.id,
                kind=EventKind.USER_MESSAGE,
                payload={
                    "content": "Compare two insurance options",
                    "attachments": [],
                    "metadata": {},
                },
            ),
        )
        initial = await AgentSessionRepository().set_initial_auto_title_if_unset(
            rdb_session,
            session_id=agent_session.id,
            title="Compare two insurance options",
            event_id=event.id,
        )
        assert initial is not None

        generated = await AgentSessionRepository().replace_initial_auto_title(
            rdb_session,
            session_id=agent_session.id,
            title="Insurance option comparison",
            event_id=event.id,
        )
        skipped = await AgentSessionRepository().replace_initial_auto_title(
            rdb_session,
            session_id=agent_session.id,
            title="Second automatic title",
            event_id=event.id,
        )

        assert generated is not None
        assert generated.title == "Insurance option comparison"
        assert generated.title_source == AgentSessionTitleSource.AUTO_GENERATED
        assert skipped is None

    async def test_generated_auto_title_uses_initial_prompt_boundary(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """LLM-generated titles can apply after later assistant activity."""
        workspace_id = await _create_workspace(rdb_session, "team-session-stale-title")
        agent_id = await _create_agent(rdb_session, workspace_id, "team-stale-title")
        agent_session = (
            await AgentSessionRepository().ensure_team_primary_for_agent(
                rdb_session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
        ).session
        first_event = await EventTranscriptRepository().append(
            rdb_session,
            EventCreate(
                session_id=agent_session.id,
                kind=EventKind.USER_MESSAGE,
                payload={
                    "content": "Compare two insurance options",
                    "attachments": [],
                    "metadata": {},
                },
            ),
        )
        initial = await AgentSessionRepository().set_initial_auto_title_if_unset(
            rdb_session,
            session_id=agent_session.id,
            title="Compare two insurance options",
            event_id=first_event.id,
        )
        await EventTranscriptRepository().append(
            rdb_session,
            EventCreate(
                session_id=agent_session.id,
                kind=EventKind.ASSISTANT_MESSAGE,
                payload={
                    "content": "I can compare coverage and cost.",
                    "attachments": [],
                    "native_artifact": {
                        "adapter": "test",
                        "provider": "test",
                        "model": "test",
                        "native_format": "test",
                        "schema_version": "1",
                        "compat_key": "test:test:test:test:1",
                        "item": {},
                    },
                },
            ),
        )

        generated = await AgentSessionRepository().replace_initial_auto_title(
            rdb_session,
            session_id=agent_session.id,
            title="Insurance option comparison",
            event_id=first_event.id,
        )

        assert initial is not None
        assert generated is not None
        assert generated.title == "Insurance option comparison"

    async def test_update_session_title_rejects_empty_title(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Whitespace-only session titles are rejected instead of cleared."""
        workspace_id = await _create_workspace(rdb_session, "team-session-empty-title")
        user_id = await _create_user(
            rdb_session, "team-session-empty-title@example.com"
        )
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(rdb_session, workspace_id, "team-title-empty")
        agent_session = (
            await AgentSessionRepository().ensure_team_primary_for_agent(
                rdb_session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
        ).session
        await rdb_session.commit()

        result = await _service(rdb_session_manager).update_session_title(
            session_id=agent_session.id,
            user_id=user_id,
            title="   ",
        )

        assert isinstance(result, Failure)
        assert result.error == InvalidSessionTitle(
            reason="Session title must not be empty."
        )

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
        primary = (
            await AgentSessionRepository().ensure_team_primary_for_agent(
                rdb_session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
        ).session
        await rdb_session.commit()
        create_result = await _service(rdb_session_manager).create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
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

    async def test_list_agent_sessions_projects_tree_auto_archive_deadline(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Automatic archive deadline uses the latest activity in the root tree."""
        workspace_id = await _create_workspace(
            rdb_session,
            "team-session-auto-archive-deadline",
        )
        user_id = await _create_user(
            rdb_session,
            "team-session-auto-archive-deadline@example.com",
        )
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "team-auto-archive-deadline-agent",
        )
        await rdb_session.commit()
        create_result = await _service(rdb_session_manager).create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
        )
        assert isinstance(create_result, Success)
        root_session = create_result.value
        repo = AgentSessionRepository()
        root_agent = await repo.get_session_agent_by_session_id(
            rdb_session,
            root_session.id,
        )
        assert root_agent is not None
        child_agent = await repo.create_child_session_agent(
            rdb_session,
            parent_session_agent_id=root_agent.id,
            name="worker",
            agent_type="default",
            title=None,
            last_task_message=None,
        )
        root_activity = datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC)
        child_activity = datetime.datetime(2026, 7, 10, tzinfo=datetime.UTC)
        await rdb_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == root_session.id)
            .values(last_activity_at=root_activity)
        )
        await rdb_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == child_agent.agent_session_id)
            .values(last_activity_at=child_activity)
        )
        await rdb_session.commit()

        list_result = await _service(
            rdb_session_manager
        ).list_agent_sessions_with_unread_terminal_run(
            agent_id=agent_id,
            user_id=user_id,
        )

        assert isinstance(list_result, Success)
        projection = next(
            item for item in list_result.value if item.session.id == root_session.id
        )
        assert projection.auto_archive_after == child_activity + datetime.timedelta(
            days=30
        )
        primary = next(
            item
            for item in list_result.value
            if item.session.primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY
        )
        assert primary.auto_archive_after is None

        await rdb_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == root_session.id)
            .values(pinned=True)
        )
        await rdb_session.commit()
        pinned_list_result = await _service(
            rdb_session_manager
        ).list_agent_sessions_with_unread_terminal_run(
            agent_id=agent_id,
            user_id=user_id,
        )
        assert isinstance(pinned_list_result, Success)
        pinned_projection = next(
            item
            for item in pinned_list_result.value
            if item.session.id == root_session.id
        )
        assert pinned_projection.auto_archive_after is None

    async def test_list_agent_sessions_orders_non_primary_by_latest_user_input(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Non-primary sessions sort by user input recency after team primary."""
        workspace_id = await _create_workspace(
            rdb_session, "team-session-user-input-sort"
        )
        user_id = await _create_user(
            rdb_session, "team-session-user-input-sort@example.com"
        )
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(
            rdb_session, workspace_id, "team-user-input-sort-agent"
        )
        primary = (
            await AgentSessionRepository().ensure_team_primary_for_agent(
                rdb_session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
        ).session
        await rdb_session.commit()

        first_result = await _service(rdb_session_manager).create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
        )
        second_result = await _service(rdb_session_manager).create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
        )
        assert isinstance(first_result, Success)
        assert isinstance(second_result, Success)
        first_session = first_result.value
        second_session = second_result.value

        old_user_event = await EventTranscriptRepository().append(
            rdb_session,
            EventCreate(
                session_id=first_session.id,
                kind=EventKind.USER_MESSAGE,
                payload={
                    "content": "Older user request",
                    "attachments": [],
                    "metadata": {},
                },
            ),
        )
        await EventTranscriptRepository().append(
            rdb_session,
            EventCreate(
                session_id=first_session.id,
                kind=EventKind.ASSISTANT_MESSAGE,
                payload={
                    "content": "Later assistant activity",
                    "attachments": [],
                    "native_artifact": {
                        "adapter": "test",
                        "provider": "test",
                        "model": "test",
                        "native_format": "test",
                        "schema_version": "1",
                        "compat_key": "test:test:test:test:1",
                        "item": {},
                    },
                },
            ),
        )
        recent_user_event = await EventTranscriptRepository().append(
            rdb_session,
            EventCreate(
                session_id=second_session.id,
                kind=EventKind.USER_MESSAGE,
                payload={
                    "content": "Recent user request",
                    "attachments": [],
                    "metadata": {},
                },
            ),
        )
        first_last_user_input_at = await rdb_session.scalar(
            sa.select(RDBAgentSession.last_user_input_at).where(
                RDBAgentSession.id == first_session.id
            )
        )
        second_last_user_input_at = await rdb_session.scalar(
            sa.select(RDBAgentSession.last_user_input_at).where(
                RDBAgentSession.id == second_session.id
            )
        )
        assert first_last_user_input_at == old_user_event.created_at
        assert second_last_user_input_at == recent_user_event.created_at
        await rdb_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == first_session.id)
            .values(
                last_user_input_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
                updated_at=datetime.datetime(2026, 1, 5, tzinfo=datetime.UTC),
            )
        )
        await rdb_session.execute(
            sa.update(RDBAgentSession)
            .where(RDBAgentSession.id == second_session.id)
            .values(
                last_user_input_at=datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC),
                updated_at=datetime.datetime(2026, 1, 3, tzinfo=datetime.UTC),
            )
        )
        await rdb_session.commit()

        list_result = await _service(rdb_session_manager).list_agent_sessions(
            agent_id=agent_id,
            user_id=user_id,
        )

        assert isinstance(list_result, Success)
        assert [session.id for session in list_result.value] == [
            primary.id,
            second_session.id,
            first_session.id,
        ]

    async def test_archive_non_primary_session_removes_it_from_active_list(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Archiving a non-primary session hides it from active session lists."""
        workspace_id = await _create_workspace(rdb_session, "team-session-archive")
        user_id = await _create_user(rdb_session, "team-session-archive@example.com")
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(rdb_session, workspace_id, "team-archive-agent")
        primary = (
            await AgentSessionRepository().ensure_team_primary_for_agent(
                rdb_session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
        ).session
        await rdb_session.commit()
        create_result = await _service(rdb_session_manager).create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
        )
        assert isinstance(create_result, Success)

        folder_delete_runner = _FolderDeleteRunner()
        archive_result = await _service(
            rdb_session_manager,
            agent_runtime_repository=_ReadyRuntimeRepository(),
            runner_operations=folder_delete_runner,
        ).archive_agent_session(
            agent_id=agent_id,
            session_id=create_result.value.id,
            user_id=user_id,
        )

        assert isinstance(archive_result, Success)
        assert archive_result.value.archived_session_id == create_result.value.id
        list_result = await _service(rdb_session_manager).list_agent_sessions(
            agent_id=agent_id,
            user_id=user_id,
        )
        assert isinstance(list_result, Success)
        assert [session.id for session in list_result.value] == [primary.id]
        async with rdb_session_manager() as verify_session:
            archived = await AgentSessionRepository().get_by_id(
                verify_session,
                create_result.value.id,
            )
            assert archived is not None
            assert archived.status == AgentSessionStatus.ARCHIVED
            assert archived.archived_at is not None
            assert archived.purge_after == archived.archived_at + datetime.timedelta(
                days=30
            )
            assert archived.archive_policy_revision == 1
            assert archived.archive_retention_days_snapshot == 30
            context = (
                await AgentSessionRepository().get_working_folder_context_by_session_id(
                    verify_session,
                    session_id=create_result.value.id,
                )
            )
            assert context is not None
            context_row = await verify_session.get(
                RDBSessionAgentContext,
                context.id,
            )
            assert context_row is not None
            assert (
                context_row.working_folder_cleanup_status
                is SessionWorkingFolderCleanupStatus.SUCCEEDED
            )
            assert context_row.working_folder_cleanup_summary == (
                "Session working-folder cleanup completed: deleted."
            )
            assert context_row.working_folder_cleanup_completed_at is not None
        assert len(folder_delete_runner.calls) == 1
        assert (
            folder_delete_runner.calls[0]["owner_session_id"] == create_result.value.id
        )
        assert folder_delete_runner.calls[0]["path"] == (
            f"/workspace/agent/.azents/sessions/{create_result.value.handle}"
        )
        assert folder_delete_runner.calls[0]["recursive"] is True

        archived_list = await _service(
            rdb_session_manager
        ).list_archived_agent_sessions(
            agent_id=agent_id,
            user_id=user_id,
        )
        assert isinstance(archived_list, Success)
        assert [item.id for item in archived_list.value] == [create_result.value.id]

        restore_result = await _service(rdb_session_manager).restore_agent_session(
            agent_id=agent_id,
            session_id=create_result.value.id,
            user_id=user_id,
        )
        assert isinstance(restore_result, Success)
        assert restore_result.value.status == AgentSessionStatus.ACTIVE
        assert restore_result.value.archived_at is None
        assert restore_result.value.purge_after is None
        async with rdb_session_manager() as verify_session:
            restored_context = (
                await AgentSessionRepository().get_working_folder_context_by_session_id(
                    verify_session,
                    session_id=create_result.value.id,
                )
            )
        assert restored_context is not None
        assert (
            restored_context.cleanup_status
            is SessionWorkingFolderCleanupStatus.NOT_ATTEMPTED
        )

        rearchive_result = await _service(
            rdb_session_manager,
            agent_runtime_repository=_ReadyRuntimeRepository(),
            runner_operations=folder_delete_runner,
        ).archive_agent_session(
            agent_id=agent_id,
            session_id=create_result.value.id,
            user_id=user_id,
        )
        assert isinstance(rearchive_result, Success)
        assert len(folder_delete_runner.calls) == 2

    async def test_archive_worktree_cleanup_failure_keeps_archive_successful(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Post-commit worktree cleanup failure cannot roll back archive."""
        workspace_id = await _create_workspace(
            rdb_session,
            "team-session-worktree-integrity",
        )
        user_id = await _create_user(
            rdb_session,
            "team-session-worktree-integrity@example.com",
        )
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "team-worktree-integrity-agent",
        )
        await AgentSessionRepository().ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        await rdb_session.commit()
        create_result = await _service(rdb_session_manager).create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
        )
        assert isinstance(create_result, Success)
        cleanup_service = _ArchiveCleanupService(
            rdb_session_manager,
            failure=RuntimeError("Runtime runner is unavailable."),
        )
        folder_delete_runner = _FolderDeleteRunner()

        with caplog.at_level(
            logging.ERROR,
            logger="azents.services.chat",
        ):
            archive_result = await _service(
                rdb_session_manager,
                session_git_worktree_service=cast(
                    SessionGitWorktreeService,
                    cleanup_service,
                ),
                agent_runtime_repository=_ReadyRuntimeRepository(),
                runner_operations=folder_delete_runner,
            ).archive_agent_session(
                agent_id=agent_id,
                session_id=create_result.value.id,
                user_id=user_id,
            )

        assert isinstance(archive_result, Success)
        assert cleanup_service.calls == [
            (
                agent_id,
                create_result.value.id,
                (create_result.value.id,),
            )
        ]
        assert cleanup_service.observed_statuses == [AgentSessionStatus.ARCHIVED]
        assert cleanup_service.observed_cleanup_statuses == [
            SessionWorkingFolderCleanupStatus.PENDING
        ]
        assert len(folder_delete_runner.calls) == 1
        assert any(
            record.message == "Archived Session Git worktree cleanup failed"
            for record in caplog.records
        )
        async with rdb_session_manager() as verify_session:
            archived = await AgentSessionRepository().get_by_id(
                verify_session,
                create_result.value.id,
            )
        assert archived is not None
        assert archived.status is AgentSessionStatus.ARCHIVED
        assert archived.archived_at is not None

    @pytest.mark.parametrize(
        (
            "failure",
            "target_kind",
            "expected_status",
            "expected_summary",
            "expected_delete_count",
        ),
        [
            (
                None,
                "directory",
                SessionWorkingFolderCleanupStatus.SUCCEEDED,
                "Session working-folder cleanup completed: deleted.",
                1,
            ),
            (
                RuntimeRunnerOperationFailedError(
                    "Folder does not exist.",
                    code="NOT_FOUND",
                ),
                "directory",
                SessionWorkingFolderCleanupStatus.SUCCEEDED,
                "Session working-folder cleanup completed: already_absent.",
                1,
            ),
            (
                RuntimeRunnerOperationFailedError(
                    "Permission denied.",
                    code="DELETE_FAILED",
                ),
                "directory",
                SessionWorkingFolderCleanupStatus.FAILED,
                "Session working-folder cleanup failed: DELETE_FAILED.",
                1,
            ),
            (
                None,
                "file",
                SessionWorkingFolderCleanupStatus.FAILED,
                "Session working-folder cleanup failed: invalid_target_kind.",
                0,
            ),
            (
                None,
                "symlink",
                SessionWorkingFolderCleanupStatus.SUCCEEDED,
                "Session working-folder cleanup completed: deleted.",
                1,
            ),
            (
                None,
                "missing",
                SessionWorkingFolderCleanupStatus.SUCCEEDED,
                "Session working-folder cleanup completed: already_absent.",
                0,
            ),
        ],
    )
    async def test_archive_folder_cleanup_terminalizes_without_changing_success(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
        failure: RuntimeRunnerOperationFailedError | None,
        target_kind: Literal["directory", "file", "symlink", "missing"],
        expected_status: SessionWorkingFolderCleanupStatus,
        expected_summary: str,
        expected_delete_count: int,
    ) -> None:
        """Folder delete outcomes are terminal observations, not archive results."""
        workspace_id = await _create_workspace(
            rdb_session,
            "team-session-folder-cleanup-terminal",
        )
        user_id = await _create_user(
            rdb_session,
            "team-session-folder-cleanup-terminal@example.com",
        )
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "team-folder-cleanup-terminal-agent",
        )
        await AgentSessionRepository().ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        await rdb_session.commit()
        create_result = await _service(rdb_session_manager).create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
        )
        assert isinstance(create_result, Success)
        folder_delete_runner = _FolderDeleteRunner(
            failure=failure,
            target_kind=target_kind,
        )

        archive_result = await _service(
            rdb_session_manager,
            agent_runtime_repository=_ReadyRuntimeRepository(),
            runner_operations=folder_delete_runner,
        ).archive_agent_session(
            agent_id=agent_id,
            session_id=create_result.value.id,
            user_id=user_id,
        )

        assert isinstance(archive_result, Success)
        assert len(folder_delete_runner.stat_calls) == 1
        assert len(folder_delete_runner.calls) == expected_delete_count
        async with rdb_session_manager() as verify_session:
            context = (
                await AgentSessionRepository().get_working_folder_context_by_session_id(
                    verify_session,
                    session_id=create_result.value.id,
                )
            )
            assert context is not None
            context_row = await verify_session.get(
                RDBSessionAgentContext,
                context.id,
            )
        assert context_row is not None
        assert context_row.working_folder_cleanup_status is expected_status
        assert context_row.working_folder_cleanup_summary == expected_summary
        assert context_row.working_folder_cleanup_completed_at is not None

    async def test_archive_team_primary_session_is_blocked(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Team-primary sessions cannot be archived."""
        workspace_id = await _create_workspace(rdb_session, "team-session-primary")
        user_id = await _create_user(rdb_session, "team-session-primary@example.com")
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(rdb_session, workspace_id, "team-primary-agent")
        primary = (
            await AgentSessionRepository().ensure_team_primary_for_agent(
                rdb_session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
        ).session
        await rdb_session.commit()

        archive_result = await _service(rdb_session_manager).archive_agent_session(
            agent_id=agent_id,
            session_id=primary.id,
            user_id=user_id,
        )

        assert isinstance(archive_result, Failure)
        assert isinstance(archive_result.error, PrimarySessionArchiveBlocked)

    async def test_pin_team_primary_session_is_blocked(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Team-primary sessions cannot be pinned for automatic archive."""
        workspace_id = await _create_workspace(rdb_session, "team-session-primary-pin")
        user_id = await _create_user(
            rdb_session,
            "team-session-primary-pin@example.com",
        )
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "team-primary-pin-agent",
        )
        primary = (
            await AgentSessionRepository().ensure_team_primary_for_agent(
                rdb_session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
        ).session
        await rdb_session.commit()

        pin_result = await _service(rdb_session_manager).set_session_pinned(
            agent_id=agent_id,
            session_id=primary.id,
            user_id=user_id,
            pinned=True,
        )

        assert isinstance(pin_result, Failure)
        assert isinstance(pin_result.error, PrimarySessionPinBlocked)

    async def test_archive_running_session_is_blocked(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Running sessions cannot be archived until stopped."""
        workspace_id = await _create_workspace(rdb_session, "team-session-running")
        user_id = await _create_user(rdb_session, "team-session-running@example.com")
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(rdb_session, workspace_id, "team-running-agent")
        await AgentSessionRepository().ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        await rdb_session.commit()
        create_result = await _service(rdb_session_manager).create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
        )
        assert isinstance(create_result, Success)
        async with rdb_session_manager() as update_session:
            rdb = await update_session.get(RDBAgentSession, create_result.value.id)
            assert rdb is not None
            rdb.run_state = AgentSessionRunState.RUNNING
            await update_session.commit()

        archive_result = await _service(rdb_session_manager).archive_agent_session(
            agent_id=agent_id,
            session_id=create_result.value.id,
            user_id=user_id,
        )

        assert isinstance(archive_result, Failure)
        assert isinstance(archive_result.error, RunningSessionArchiveBlocked)

    async def test_auto_archive_uses_current_agent_ttl(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Current Agent TTL changes determine existing Session eligibility."""
        workspace_id = await _create_workspace(rdb_session, "auto-archive-ttl")
        user_id = await _create_user(rdb_session, "auto-archive-ttl@example.com")
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(rdb_session, workspace_id, "auto-archive-ttl")
        await rdb_session.commit()
        create_result = await _service(rdb_session_manager).create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
        )
        assert isinstance(create_result, Success)
        stale_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=60)
        async with rdb_session_manager() as update_session:
            agent = await update_session.get(RDBAgent, agent_id)
            root = await update_session.get(RDBAgentSession, create_result.value.id)
            assert agent is not None
            assert root is not None
            agent.auto_archive_ttl_days = 90
            root.last_activity_at = stale_at
            await update_session.commit()

        service = _service(rdb_session_manager)
        await service.auto_archive_once()
        async with rdb_session_manager() as verify_session:
            active = await AgentSessionRepository().get_by_id(
                verify_session,
                create_result.value.id,
            )
        assert active is not None
        assert active.status is AgentSessionStatus.ACTIVE

        async with rdb_session_manager() as update_session:
            agent = await update_session.get(RDBAgent, agent_id)
            assert agent is not None
            agent.auto_archive_ttl_days = 30
            await update_session.commit()

        await service.auto_archive_once()
        async with rdb_session_manager() as verify_session:
            archived = await AgentSessionRepository().get_by_id(
                verify_session,
                create_result.value.id,
            )
        assert archived is not None
        assert archived.status is AgentSessionStatus.ARCHIVED

    async def test_auto_archive_excludes_pinned_and_running_sessions(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Pins exclude candidates while running roots are rechecked and skipped."""
        workspace_id = await _create_workspace(rdb_session, "auto-archive-guards")
        user_id = await _create_user(
            rdb_session,
            "auto-archive-guards@example.com",
        )
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id,
            "auto-archive-guards",
        )
        primary = (
            await AgentSessionRepository().ensure_team_primary_for_agent(
                rdb_session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
        ).session
        await rdb_session.commit()
        service = _service(rdb_session_manager)
        pinned_result = await service.create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
        )
        running_result = await service.create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
        )
        assert isinstance(pinned_result, Success)
        assert isinstance(running_result, Success)
        pin_result = await service.set_session_pinned(
            agent_id=agent_id,
            session_id=pinned_result.value.id,
            user_id=user_id,
            pinned=True,
        )
        assert isinstance(pin_result, Success)
        assert pin_result.value.pinned is True
        stale_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=31)
        async with rdb_session_manager() as update_session:
            pinned = await update_session.get(RDBAgentSession, pinned_result.value.id)
            running = await update_session.get(
                RDBAgentSession,
                running_result.value.id,
            )
            assert pinned is not None
            assert running is not None
            primary_rdb = await update_session.get(RDBAgentSession, primary.id)
            assert primary_rdb is not None
            pinned.last_activity_at = stale_at
            running.last_activity_at = stale_at
            primary_rdb.last_activity_at = stale_at
            running.run_state = AgentSessionRunState.RUNNING
            await update_session.commit()

        await service.auto_archive_once()
        async with rdb_session_manager() as verify_session:
            pinned = await AgentSessionRepository().get_by_id(
                verify_session,
                pinned_result.value.id,
            )
            running = await AgentSessionRepository().get_by_id(
                verify_session,
                running_result.value.id,
            )
            primary_after = await AgentSessionRepository().get_by_id(
                verify_session,
                primary.id,
            )
        assert pinned is not None
        assert pinned.status is AgentSessionStatus.ACTIVE
        assert pinned.pinned is True
        assert running is not None
        assert running.status is AgentSessionStatus.ACTIVE
        assert primary_after is not None
        assert primary_after.status is AgentSessionStatus.ACTIVE

    async def test_auto_archive_uses_latest_activity_across_child_tree(
        self,
        rdb_session: AsyncSession,
        rdb_session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Recent child activity protects an otherwise stale root tree."""
        workspace_id = await _create_workspace(rdb_session, "auto-archive-tree")
        user_id = await _create_user(rdb_session, "auto-archive-tree@example.com")
        await _add_workspace_user(
            rdb_session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        agent_id = await _create_agent(rdb_session, workspace_id, "auto-archive-tree")
        await rdb_session.commit()
        create_result = await _service(rdb_session_manager).create_team_session(
            agent_id=agent_id,
            user_id=user_id,
            existing_project_paths=[],
            setup_actions=[],
        )
        assert isinstance(create_result, Success)
        stale_at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=31)
        async with rdb_session_manager() as update_session:
            repository = AgentSessionRepository()
            root_agent = await repository.get_session_agent_by_session_id(
                update_session,
                create_result.value.id,
            )
            assert root_agent is not None
            child = await repository.create_child_session_agent(
                update_session,
                parent_session_agent_id=root_agent.id,
                name="fresh-child",
                agent_type="default",
                title=None,
                last_task_message=None,
            )
            root = await update_session.get(RDBAgentSession, create_result.value.id)
            child_session = await update_session.get(
                RDBAgentSession,
                child.agent_session_id,
            )
            assert root is not None
            assert child_session is not None
            root.last_activity_at = stale_at
            child_session.last_activity_at = datetime.datetime.now(datetime.UTC)
            await update_session.commit()

        await _service(rdb_session_manager).auto_archive_once()
        async with rdb_session_manager() as verify_session:
            root = await AgentSessionRepository().get_by_id(
                verify_session,
                create_result.value.id,
            )
        assert root is not None
        assert root.status is AgentSessionStatus.ACTIVE
