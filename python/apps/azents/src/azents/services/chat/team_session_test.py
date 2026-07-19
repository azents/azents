"""ChatSessionService team session tests."""

import datetime

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
    WorkspaceUserRole,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.input_buffer import InputBufferRepository
from azents.repos.message import MessageRepository
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.services.chat.data import InvalidSessionTitle
from azents.services.exchange_file import ExchangeFileService
from azents.services.input_buffer import InputBufferService
from azents.testing.model_selection import make_test_model_selection_dict

from . import ChatSessionService
from .data import PrimarySessionArchiveBlocked, RunningSessionArchiveBlocked


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
    *,
    session_git_worktree_repository: SessionGitWorktreeRepository | None = None,
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
        archived_session_retention_repository=ArchivedSessionRetentionRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
        input_buffer_service=InputBufferService(
            session_manager=rdb_session_manager,
            input_buffer_repository=InputBufferRepository(),
            exchange_file_service=_ExchangeFileService(),
            agent_session_repository=AgentSessionRepository(),
            event_transcript_repository=EventTranscriptRepository(),
            agent_run_repository=AgentRunRepository(),
            action_execution_repository=ActionExecutionRepository(),
        ),
        session_manager=rdb_session_manager,
    )


class _ExchangeFileService(ExchangeFileService):
    """ExchangeFileService for tests."""

    def __init__(self) -> None:
        """Bypass Base dataclass initialization."""


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


class TestChatSessionTeamSessions:
    """Team session service behavior."""

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
        agent_session = await AgentSessionRepository().ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
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
        agent_session = await AgentSessionRepository().ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
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
        agent_session = await AgentSessionRepository().ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
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
        agent_session = await AgentSessionRepository().ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
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
        agent_session = await AgentSessionRepository().ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
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
        primary = await AgentSessionRepository().ensure_team_primary_for_agent(
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
        primary = await AgentSessionRepository().ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
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
        primary = await AgentSessionRepository().ensure_team_primary_for_agent(
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

        archive_result = await _service(rdb_session_manager).archive_agent_session(
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
        primary = await AgentSessionRepository().ensure_team_primary_for_agent(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        await rdb_session.commit()

        archive_result = await _service(rdb_session_manager).archive_agent_session(
            agent_id=agent_id,
            session_id=primary.id,
            user_id=user_id,
        )

        assert isinstance(archive_result, Failure)
        assert isinstance(archive_result.error, PrimarySessionArchiveBlocked)

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
