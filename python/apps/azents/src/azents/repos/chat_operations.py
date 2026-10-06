"""Completed Chat database reads and coherent atomic mutations."""

import dataclasses
import datetime
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.agent_project_preset import AgentProjectPreset
from azents.core.agent_session_data import (
    AgentSession,
    AgentSessionCreate,
    AgentSessionUnreadTerminalRunProjection,
    SessionWorkingFolderContext,
)
from azents.core.chat_data import (
    AcknowledgeUnreadTerminalRunError,
    AgentNotFound,
    AgentSessionDirectoryPage,
    AgentSessionSidebarSummary,
    ArchiveSessionError,
    DeleteMailboxItemError,
    EnsureSessionError,
    InvalidGoalStatusTransition,
    InvalidSessionTitle,
    NewSessionProjectDefaults,
    NewSessionProjectDefaultsSource,
    NotWorkspaceMember,
    PaginatedEvents,
    PrepareSessionWorkingFolderError,
    PrimarySessionArchiveBlocked,
    PrimarySessionPinBlocked,
    PurgeStartedRestoreBlocked,
    RestoreSessionError,
    RunningSessionArchiveBlocked,
    SessionAccessDenied,
    SessionAccessError,
    SessionNotFound,
    SetSessionPinnedError,
    SubagentSessionReadOnly,
    SubagentTreeNode,
    SubagentTreeProjection,
    UnreadTerminalRunNotTerminal,
    UpdateGoalError,
    UpdateGoalResult,
    UpdateGoalStatusInput,
    UpdateSessionTitleError,
)
from azents.core.chat_operation_data import (
    ChatArchiveDatabaseResult,
    ChatLiveDatabaseSnapshot,
)
from azents.core.chat_projection import (
    _SESSION_TITLE_MAX_LENGTH,
    _WORKING_FOLDER_CLEANUP_SUMMARY_MAX_LENGTH,
    _default_item_from_workspace_item,
    _finalize_subagent_tree_nodes,
    _session_profile_fallback,
    _session_profile_is_stale,
    _subagent_tree_node,
    _workspace_item_from_default,
)
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentProjectDefaultItemType,
    AgentRunStatus,
    AgentSessionKind,
    AgentSessionPrimaryKind,
    AgentSessionProductMode,
    AgentSessionRunState,
    AgentSessionStatus,
    AgentSessionTitleSource,
    EventKind,
    MailboxItemKind,
    MailboxSchedulingMode,
    SessionWorkingFolderCleanupStatus,
)
from azents.core.goal import GoalStateSnapshot
from azents.core.inference_profile import SessionAppliedInferenceProfile
from azents.core.json_value import JSONValue
from azents.core.root_agent_session_creation import (
    ExplicitRootWorkspaceIntent,
)
from azents.core.session_lifecycle import (
    SessionArchiveMutation,
    SessionLifecycleTransitionContext,
)
from azents.core.session_workspace_items import (
    ExistingProjectWorkspaceItem,
    GitWorktreeWorkspaceItem,
    NewSessionWorkspaceItem,
)
from azents.core.session_workspace_paths import (
    InvalidProjectPath,
)
from azents.core.session_workspace_project import SessionWorkspaceProjectCreate
from azents.engine.events.action_messages import (
    CreateGitWorktreeAction,
    CreateSessionWorkingFolderAction,
)
from azents.engine.events.types import Event
from azents.engine.tools.todo import TodoStateSnapshot
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_default.data import (
    AgentProjectDefaultCreate,
)
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.goal.store import (
    GoalInvalidStatusTransitionError,
    GoalStateStore,
)
from azents.repos.hierarchy_contention import retry_hierarchy_operation
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.admission import MailboxAdmissionRepository
from azents.repos.mailbox.admission_data import (
    MailboxAdmissionResult,
    MailboxEnqueue,
)
from azents.repos.message import MessageRepository
from azents.repos.root_agent_session_creation import (
    RootAgentSessionCreationRepository,
)
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_lifecycle_operations import (
    SessionLifecycleOperationsRepository,
)
from azents.repos.session_resource_authority import (
    PublicSessionResourceDenied,
    PublicSessionResourceNotFound,
    authorize_public_session_resource,
)
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.toolkit_state.engine import TodoStateStore
from azents.repos.workspace_user import WorkspaceUserRepository


def get_chat_goal_state_store(
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ],
) -> GoalStateStore:
    """Compose unbound user-managed Goal persistence at the dependency root."""
    return GoalStateStore(session_manager=session_manager, owner=None)


def get_chat_todo_state_store(
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ],
) -> TodoStateStore:
    """Compose unbound Todo reads at the dependency root."""
    return TodoStateStore(session_manager=session_manager)


@dataclasses.dataclass
class ChatOperationsRepository:
    """Own Chat transaction lifetimes and concrete repository composition."""

    message_repository: Annotated[MessageRepository, Depends(MessageRepository)]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_project_preset_repository: Annotated[
        AgentProjectPresetRepository,
        Depends(AgentProjectPresetRepository),
    ]
    agent_project_catalog_repository: Annotated[
        AgentProjectCatalogRepository,
        Depends(AgentProjectCatalogRepository),
    ]
    agent_project_default_repository: Annotated[
        AgentProjectDefaultRepository,
        Depends(AgentProjectDefaultRepository),
    ]
    session_git_worktree_repository: Annotated[
        SessionGitWorktreeRepository,
        Depends(SessionGitWorktreeRepository),
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    action_execution_repository: Annotated[
        ActionExecutionRepository,
        Depends(ActionExecutionRepository),
    ]
    event_transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    agent_runtime_repository: Annotated[
        AgentRuntimeRepository,
        Depends(AgentRuntimeRepository),
    ]
    root_session_repository: Annotated[
        RootAgentSessionCreationRepository,
        Depends(RootAgentSessionCreationRepository),
    ]
    archived_session_retention_repository: Annotated[
        ArchivedSessionRetentionRepository,
        Depends(ArchivedSessionRetentionRepository),
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
    session_workspace_project_repository: Annotated[
        SessionWorkspaceProjectRepository,
        Depends(SessionWorkspaceProjectRepository),
    ]
    mailbox_repository: Annotated[MailboxRepository, Depends(MailboxRepository)]
    mailbox_admission_repository: Annotated[
        MailboxAdmissionRepository, Depends(MailboxAdmissionRepository)
    ]
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    lifecycle_operations: Annotated[
        SessionLifecycleOperationsRepository,
        Depends(SessionLifecycleOperationsRepository),
    ]
    goal_store: Annotated[GoalStateStore, Depends(get_chat_goal_state_store)]
    todo_store: Annotated[TodoStateStore, Depends(get_chat_todo_state_store)]

    async def get_team_primary_session(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[AgentSession, EnsureSessionError]:
        """Ensure team primary AgentSession of Agent and check access permission.

        :param agent_id: Agent ID
        :param user_id: Requester user ID
        :return: team primary AgentSession on success, error on failure
        """
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if (
                agent is None
                or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            ):
                return Failure(AgentNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(NotWorkspaceMember())
            root_session_creation = self.root_session_repository
            root_result = await root_session_creation.ensure_team_primary(
                session,
                workspace_id=agent.workspace_id,
                agent_id=agent_id,
            )
            repaired = await self._project_session_profile_for_read(
                session,
                agent_session=root_result.agent_session,
            )
            return Success(repaired)

    async def get_session(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Result[AgentSession, SessionAccessError]:
        """Fetch session and check access permission.

        :param session_id: Session ID to fetch
        :param user_id: Requester user ID
        :return: AgentSession on success, error on failure
        """
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            if (
                agent_session is None
                or agent_session.status != AgentSessionStatus.ACTIVE
            ):
                return Failure(SessionNotFound())
            authorized = await self._authorize_public_session(
                session,
                agent_session=agent_session,
                user_id=user_id,
                denied_as_not_found=False,
            )
            if authorized is not None:
                return Failure(authorized)
            agent_session = await self._project_session_profile_for_read(
                session,
                agent_session=agent_session,
            )
            return Success(agent_session)

    async def _project_session_profile_for_read(
        self,
        session: ReadSession,
        *,
        agent_session: AgentSession,
    ) -> AgentSession:
        """Project fallback intent without publishing a new applied generation."""
        agent = await self.agent_repository.get_by_id(session, agent_session.agent_id)
        if agent is None:
            return agent_session
        return self._project_session_profile(agent, agent_session)

    @staticmethod
    def _project_session_profile(
        agent: Agent, agent_session: AgentSession
    ) -> AgentSession:
        """Compile fallback intent while retaining the persisted generation."""
        if not _session_profile_is_stale(agent, agent_session):
            return agent_session
        model_target_label, reasoning_effort = _session_profile_fallback(agent)
        return agent_session.model_copy(
            update={
                "applied_inference_profile": SessionAppliedInferenceProfile(
                    model_target_label=model_target_label,
                    reasoning_effort=reasoning_effort,
                    enabled_execution_options=[],
                )
            }
        )

    async def get_agent_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[AgentSession, SessionNotFound]:
        """Fetch an AgentSession by agent/session pair with 404-safe semantics."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if (
                agent_session is None
                or agent_session.agent_id != agent_id
                or agent_session.status != AgentSessionStatus.ACTIVE
            ):
                return Failure(SessionNotFound())
            authorized = await self._authorize_public_session(
                session,
                agent_session=agent_session,
                user_id=user_id,
                denied_as_not_found=True,
            )
            if authorized is not None:
                return Failure(SessionNotFound())
            agent_session = await self._project_session_profile_for_read(
                session,
                agent_session=agent_session,
            )
            return Success(agent_session)

    async def get_agent_session_with_unread_terminal_run(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[AgentSessionUnreadTerminalRunProjection, SessionNotFound]:
        """Fetch an AgentSession and its shared unread Run projection."""
        async with self.session_manager() as session:
            projection = (
                await self.agent_session_repository.get_with_unread_terminal_run_by_id(
                    session,
                    session_id,
                )
            )
            if (
                projection is None
                or projection.session.agent_id != agent_id
                or projection.session.status != AgentSessionStatus.ACTIVE
            ):
                return Failure(SessionNotFound())
            authorized = await self._authorize_public_session(
                session,
                agent_session=projection.session,
                user_id=user_id,
                denied_as_not_found=True,
            )
            if authorized is not None:
                return Failure(SessionNotFound())
            repaired_session = await self._project_session_profile_for_read(
                session,
                agent_session=projection.session,
            )
            projection = dataclasses.replace(projection, session=repaired_session)
            return Success(projection)

    async def acknowledge_agent_session_unread_terminal_run(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        through_run_id: str,
    ) -> Result[None, AcknowledgeUnreadTerminalRunError]:
        """Acknowledge an observed terminal Run for an active root Session."""
        async with self.session_manager() as session:
            projection = (
                await self.agent_session_repository.get_with_unread_terminal_run_by_id(
                    session,
                    session_id,
                )
            )
            if (
                projection is None
                or projection.session.agent_id != agent_id
                or projection.session.status != AgentSessionStatus.ACTIVE
                or projection.session.session_kind != AgentSessionKind.ROOT
            ):
                return Failure(SessionNotFound())
            authorized = await self._authorize_public_session(
                session,
                agent_session=projection.session,
                user_id=user_id,
                denied_as_not_found=True,
            )
            if authorized is not None:
                return Failure(SessionNotFound())
            run = await self.agent_run_repository.acknowledge_unread_terminal_run(
                session,
                session_id=session_id,
                run_id=through_run_id,
            )
            if run is None or run.session_id != session_id:
                return Failure(SessionNotFound())
            if run.status not in {
                AgentRunStatus.COMPLETED,
                AgentRunStatus.FAILED,
                AgentRunStatus.STOPPED,
                AgentRunStatus.INTERRUPTED,
                AgentRunStatus.CANCELLED,
            }:
                return Failure(UnreadTerminalRunNotTerminal())
            await session.write_session.commit()
            return Success(None)

    async def get_subagent_tree(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[SubagentTreeProjection, SessionAccessError]:
        """Fetch the durable Subagent Tree projection for a session tree."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if (
                agent_session is None
                or agent_session.agent_id != agent_id
                or agent_session.status != AgentSessionStatus.ACTIVE
            ):
                return Failure(SessionNotFound())
            authorized = await self._authorize_public_session(
                session,
                agent_session=agent_session,
                user_id=user_id,
                denied_as_not_found=False,
            )
            if authorized is not None:
                return Failure(authorized)
            current_agent = (
                await self.agent_session_repository.get_session_agent_by_session_id(
                    session,
                    session_id,
                )
            )
            if current_agent is None:
                return Failure(SessionNotFound())
            tree_agents = await self.agent_session_repository.list_session_agent_tree(
                session,
                root_session_agent_id=current_agent.root_session_agent_id,
            )
            sessions_by_id = await self.agent_session_repository.list_by_ids(
                session,
                agent_session_ids=[agent.agent_session_id for agent in tree_agents],
            )
            latest_runs = await self.agent_run_repository.list_latest_by_session_ids(
                session,
                session_ids=[agent.agent_session_id for agent in tree_agents],
            )
            nodes_by_id = {
                agent.id: _subagent_tree_node(
                    agent,
                    session=sessions_by_id.get(agent.agent_session_id),
                    latest_run=latest_runs.get(agent.agent_session_id),
                )
                for agent in tree_agents
            }
            roots: list[SubagentTreeNode] = []
            for agent in tree_agents:
                node = nodes_by_id[agent.id]
                if agent.parent_session_agent_id is None:
                    roots.append(node)
                    continue
                parent = nodes_by_id.get(agent.parent_session_agent_id)
                if parent is None:
                    roots.append(node)
                    continue
                parent.children.append(node)
            root_agent = await self.agent_session_repository.get_session_agent_by_id(
                session,
                current_agent.root_session_agent_id,
            )
            if root_agent is None:
                return Failure(SessionNotFound())
            return Success(
                SubagentTreeProjection(
                    root_session_agent_id=root_agent.id,
                    root_agent_session_id=root_agent.agent_session_id,
                    current_session_agent_id=current_agent.id,
                    nodes=_finalize_subagent_tree_nodes(roots),
                )
            )

    async def list_agent_sessions(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[list[AgentSession], EnsureSessionError]:
        """Fetch active team sessions for an agent with primary first."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(AgentNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(NotWorkspaceMember())
            sessions = await self.agent_session_repository.list_active_by_agent_id(
                session,
                agent_id,
            )
            sessions = [self._project_session_profile(agent, item) for item in sessions]
            return Success(sessions)

    async def list_agent_sessions_with_unread_terminal_run(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[list[AgentSessionUnreadTerminalRunProjection], EnsureSessionError]:
        """Fetch active root Sessions and their shared unread Run boundaries."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(AgentNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(NotWorkspaceMember())
            sessions = await (
                self.agent_session_repository.list_active_unread_by_agent_id(
                    session,
                    agent_id,
                    auto_archive_ttl_days=agent.auto_archive_ttl_days,
                )
            )
            sessions = [
                dataclasses.replace(
                    item, session=self._project_session_profile(agent, item.session)
                )
                for item in sessions
            ]
            return Success(sessions)

    async def list_agent_user_sessions(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[list[AgentSession], EnsureSessionError]:
        """Fetch active User Sessions owned by the requester for an Agent."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(AgentNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(NotWorkspaceMember())
            sessions = (
                await self.agent_session_repository.list_active_user_by_agent_and_user(
                    session,
                    agent_id=agent_id,
                    associated_user_id=user_id,
                )
            )
            sessions = [self._project_session_profile(agent, item) for item in sessions]
            return Success(sessions)

    async def list_agent_session_directory(
        self,
        *,
        agent_id: str,
        user_id: str,
        status: AgentSessionStatus,
        offset: int,
        limit: int,
    ) -> Result[AgentSessionDirectoryPage, EnsureSessionError]:
        """Fetch one authorized active or archived root-session directory page."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(AgentNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(NotWorkspaceMember())
            if status is AgentSessionStatus.ACTIVE:
                list_active_page = (
                    self.agent_session_repository.list_active_unread_page_by_agent_id
                )
                page = await list_active_page(
                    session,
                    agent_id,
                    auto_archive_ttl_days=agent.auto_archive_ttl_days,
                    offset=offset,
                    limit=limit,
                )
                return Success(
                    AgentSessionDirectoryPage(
                        items=[
                            dataclasses.replace(
                                item,
                                session=self._project_session_profile(
                                    agent, item.session
                                ),
                            )
                            for item in page.items
                        ],
                        total_count=page.total_count,
                    )
                )
            page = await self.agent_session_repository.list_archived_page_by_agent_id(
                session,
                agent_id,
                offset=offset,
                limit=limit,
            )
            return Success(
                AgentSessionDirectoryPage(
                    items=[
                        AgentSessionUnreadTerminalRunProjection(
                            session=item,
                            unread_terminal_run_id=None,
                            auto_archive_after=None,
                        )
                        for item in page.items
                    ],
                    total_count=page.total_count,
                )
            )

    async def get_agent_session_sidebar_summary(
        self,
        *,
        agent_id: str,
        user_id: str,
        recent_limit: int,
    ) -> Result[AgentSessionSidebarSummary, EnsureSessionError]:
        """Fetch bounded authorized sidebar session projections."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(AgentNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(NotWorkspaceMember())
            get_sidebar_summary = (
                self.agent_session_repository.list_active_sidebar_summary_by_agent_id
            )
            summary = await get_sidebar_summary(
                session,
                agent_id,
                auto_archive_ttl_days=agent.auto_archive_ttl_days,
                recent_limit=recent_limit,
            )
            return Success(
                AgentSessionSidebarSummary(
                    pinned=[
                        dataclasses.replace(
                            item,
                            session=self._project_session_profile(agent, item.session),
                        )
                        for item in summary.pinned
                    ],
                    recent=[
                        dataclasses.replace(
                            item,
                            session=self._project_session_profile(agent, item.session),
                        )
                        for item in summary.recent
                    ],
                )
            )

    async def list_agent_project_presets(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[list[AgentProjectPreset], EnsureSessionError]:
        """Fetch Agent Project path presets after access validation."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(AgentNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(NotWorkspaceMember())
            presets = await self.agent_project_preset_repository.list_presets(
                session,
                agent_id=agent_id,
            )
            return Success(presets)

    async def get_new_session_project_defaults(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[NewSessionProjectDefaults, EnsureSessionError]:
        """Fetch default Project paths for a new non-primary AgentSession."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(AgentNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(NotWorkspaceMember())
            defaults = await self.agent_project_default_repository.list_defaults(
                session,
                agent_id=agent_id,
            )
            if not defaults:
                return Success(
                    NewSessionProjectDefaults(
                        project_paths=[],
                        items=[],
                        source=NewSessionProjectDefaultsSource(type="empty"),
                    )
                )
            return Success(
                NewSessionProjectDefaults(
                    project_paths=[default.path for default in defaults],
                    items=[
                        _workspace_item_from_default(default) for default in defaults
                    ],
                    source=NewSessionProjectDefaultsSource(type="last_created_session"),
                )
            )

    async def _authorize_public_session(
        self,
        session: ReadSession,
        *,
        agent_session: AgentSession,
        user_id: str,
        denied_as_not_found: bool,
    ) -> SessionAccessDenied | SessionNotFound | None:
        """Authorize public access for Team and User Session roots/subagents.

        :param session: Database session
        :param agent_session: Loaded AgentSession row
        :param user_id: Authenticated requester
        :param denied_as_not_found: When true, private denials collapse to not-found
        :return: Error instance when denied, otherwise None
        """
        result = await authorize_public_session_resource(
            session,
            agent_session=agent_session,
            user_id=user_id,
            require_active=False,
            denied_as_not_found=denied_as_not_found,
            expected_workspace_id=None,
            expected_agent_id=None,
            agent_session_repository=self.agent_session_repository,
            workspace_user_repository=self.workspace_user_repository,
        )
        if isinstance(result, PublicSessionResourceDenied):
            return SessionAccessDenied()
        if isinstance(result, PublicSessionResourceNotFound):
            return SessionNotFound()
        return None

    async def _create_session_workspace_items(
        self,
        session: WriteSession,
        *,
        agent_id: str,
        session_id: str,
        session_handle: str,
        workspace_items: list[NewSessionWorkspaceItem],
        create_direct_projects: bool,
    ) -> Result[None, InvalidProjectPath]:
        """Create direct Project rows and queue selected worktree items."""
        existing_project_paths = [
            item.path
            for item in workspace_items
            if isinstance(item, ExistingProjectWorkspaceItem)
        ]
        worktree_items = [
            item
            for item in workspace_items
            if isinstance(item, GitWorktreeWorkspaceItem)
        ]
        default_items: list[AgentProjectDefaultCreate] = []
        for path in existing_project_paths:
            if create_direct_projects:
                await self.session_workspace_project_repository.create_project(
                    session,
                    SessionWorkspaceProjectCreate(session_id=session_id, path=path),
                )
            await self.agent_project_catalog_repository.upsert_entry(
                session,
                agent_id=agent_id,
                path=path,
            )
            if await self.session_git_worktree_repository.exists_by_worktree_path(
                session,
                worktree_path=path,
            ):
                continue
            await self.agent_project_preset_repository.upsert_preset(
                session,
                agent_id=agent_id,
                path=path,
            )
            default_items.append(
                AgentProjectDefaultCreate(
                    path=path,
                    item_type=AgentProjectDefaultItemType.EXISTING_PROJECT,
                )
            )
        for item in worktree_items:
            await self.agent_project_preset_repository.upsert_preset(
                session,
                agent_id=agent_id,
                path=item.source_project_path,
            )
            default_items.append(_default_item_from_workspace_item(item))
        if workspace_items:
            await self.agent_project_default_repository.replace_default_items(
                session,
                agent_id=agent_id,
                items=default_items,
            )
        return Success(None)

    async def _enqueue_setup_actions(
        self,
        session: WriteSession,
        *,
        agent_session: AgentSession,
        workspace_items: list[NewSessionWorkspaceItem],
        user_id: str,
    ) -> bool:
        """Enqueue ordered setup TurnActions for a newly created session."""
        metadata = {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "source": "system",
        }
        await self.mailbox_admission_repository.enqueue_in_session(
            session,
            MailboxEnqueue(
                session_id=agent_session.id,
                kind=MailboxItemKind.ACTION_MESSAGE,
                scheduling_mode=MailboxSchedulingMode.QUEUE_ONLY,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                requested_enabled_execution_options=[],
                sender_user_id=None,
                order_group=None,
                order_sequence=0,
                content="",
                idempotency_key=(f"session-working-folder:initial:{agent_session.id}"),
                metadata=metadata,
                action=CreateSessionWorkingFolderAction().model_dump(mode="json"),
                attachments=[],
                file_parts=[],
                payload=None,
            ),
        )
        created = False
        for item in workspace_items:
            match item:
                case ExistingProjectWorkspaceItem():
                    continue
                case GitWorktreeWorkspaceItem(
                    source_project_path=source_project_path,
                    starting_ref=starting_ref,
                ):
                    action = CreateGitWorktreeAction(
                        source_project_path=source_project_path,
                        starting_ref=starting_ref,
                    )
                    result = await self.mailbox_admission_repository.enqueue_in_session(
                        session,
                        MailboxEnqueue(
                            session_id=agent_session.id,
                            kind=MailboxItemKind.ACTION_MESSAGE,
                            scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                            requested_model_target_label=None,
                            requested_reasoning_effort=None,
                            requested_enabled_execution_options=[],
                            sender_user_id=user_id,
                            order_group=None,
                            order_sequence=0,
                            content="",
                            idempotency_key=None,
                            metadata=metadata,
                            action=action.model_dump(mode="json"),
                            attachments=[],
                            file_parts=[],
                            payload=None,
                        ),
                    )
                    created = created or result.created
                case _:
                    assert_never(item)
        return created

    async def _create_session_projects(
        self,
        session: WriteSession,
        *,
        agent_id: str,
        session_id: str,
        project_paths: list[str],
    ) -> None:
        """Create Project rows and refresh Agent Project presets."""
        workspace_result = await self._create_session_workspace_items(
            session,
            agent_id=agent_id,
            session_id=session_id,
            session_handle="",
            workspace_items=[
                ExistingProjectWorkspaceItem(path=path) for path in project_paths
            ],
            create_direct_projects=True,
        )
        match workspace_result:
            case Success():
                return
            case Failure(error):
                raise ValueError(error.reason)
            case _:
                assert_never(workspace_result)

    async def set_session_pinned(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        pinned: bool,
    ) -> Result[
        AgentSession,
        SetSessionPinnedError,
    ]:
        """Set automatic-archive protection for one accessible active root Session."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if (
                agent_session is None
                or agent_session.agent_id != agent_id
                or agent_session.status is not AgentSessionStatus.ACTIVE
            ):
                return Failure(SessionNotFound())
            authorized = await self._authorize_public_session(
                session,
                agent_session=agent_session,
                user_id=user_id,
                denied_as_not_found=True,
            )
            if authorized is not None:
                return Failure(authorized)
            if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                return Failure(SubagentSessionReadOnly())
            if agent_session.primary_kind is AgentSessionPrimaryKind.TEAM_PRIMARY:
                return Failure(PrimarySessionPinBlocked())
            updated = await self.agent_session_repository.set_pinned(
                session,
                session_id=session_id,
                pinned=pinned,
            )
            if updated is None:
                return Failure(SessionNotFound())
            await session.write_session.commit()
            return Success(updated)

    async def list_archived_agent_sessions(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[list[AgentSession], SessionNotFound]:
        """List archived root sessions for one accessible Agent."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(SessionNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(SessionNotFound())
            return Success(
                await self.agent_session_repository.list_archived_by_agent_id(
                    session,
                    agent_id,
                )
            )

    @retry_hierarchy_operation
    async def restore_agent_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[AgentSession, RestoreSessionError]:
        """Restore an archived root tree before purge fencing starts."""
        async with self.session_manager() as session:
            root = await self.agent_session_repository.get_by_id(session, session_id)
            if (
                root is None
                or root.agent_id != agent_id
                or root.session_kind is not AgentSessionKind.ROOT
                or root.status != AgentSessionStatus.ARCHIVED
            ):
                return Failure(SessionNotFound())
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if (
                agent is None
                or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            ):
                return Failure(SessionNotFound())
            authorized = await self._authorize_public_session(
                session,
                agent_session=root,
                user_id=user_id,
                denied_as_not_found=True,
            )
            if authorized is not None:
                return Failure(authorized)
            tree = await self.agent_session_repository.lock_root_tree_sessions(
                session,
                root_session_id=session_id,
            )
            if not tree or any(
                item.status != AgentSessionStatus.ARCHIVED for item in tree
            ):
                return Failure(SessionNotFound())
            locked_root = next((item for item in tree if item.id == session_id), None)
            if locked_root is None:
                return Failure(SessionNotFound())
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if (
                agent is None
                or agent.lifecycle_status is not AgentLifecycleStatus.ACTIVE
            ):
                return Failure(SessionNotFound())
            authorized = await self._authorize_public_session(
                session,
                agent_session=locked_root,
                user_id=user_id,
                denied_as_not_found=True,
            )
            if authorized is not None:
                return Failure(authorized)
            if await self.archived_session_retention_repository.purge_fencing_started(
                session,
                root_session_id=session_id,
            ):
                return Failure(PurgeStartedRestoreBlocked())
            now = datetime.datetime.now(datetime.UTC)
            await self.archived_session_retention_repository.cancel_unstarted_purge_job(
                session,
                root_session_id=session_id,
                now=now,
            )

            await self.lifecycle_operations.restore(
                session,
                SessionLifecycleTransitionContext(
                    transition_id=f"{session_id}:restore",
                    root_session_id=session_id,
                    subtree_session_ids=tuple(item.id for item in tree),
                ),
            )
            await self.mailbox_admission_repository.enqueue_in_session(
                session,
                MailboxEnqueue(
                    session_id=session_id,
                    kind=MailboxItemKind.ACTION_MESSAGE,
                    scheduling_mode=MailboxSchedulingMode.QUEUE_ONLY,
                    requested_model_target_label=None,
                    requested_reasoning_effort=None,
                    requested_enabled_execution_options=[],
                    sender_user_id=None,
                    order_group=None,
                    order_sequence=0,
                    content="",
                    idempotency_key=(f"session-working-folder:restore:{session_id}"),
                    metadata={
                        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                        "source": "system",
                    },
                    action=CreateSessionWorkingFolderAction().model_dump(mode="json"),
                    attachments=[],
                    file_parts=[],
                    payload=None,
                ),
            )
            restored = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if restored is None:
                raise RuntimeError("Restored AgentSession disappeared")
            await session.write_session.commit()
            return Success(restored)

    async def update_session_title(
        self,
        *,
        session_id: str,
        user_id: str,
        title: str | None,
    ) -> Result[AgentSession, UpdateSessionTitleError]:
        """Update a user-facing AgentSession title after access validation."""
        normalized_title = title.strip() if title is not None else None
        if normalized_title == "":
            return Failure(
                InvalidSessionTitle(reason="Session title must not be empty.")
            )
        if (
            normalized_title is not None
            and len(normalized_title) > _SESSION_TITLE_MAX_LENGTH
        ):
            return Failure(
                InvalidSessionTitle(
                    reason="Session title must be 200 characters or fewer."
                )
            )

        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if (
                agent_session is None
                or agent_session.status != AgentSessionStatus.ACTIVE
            ):
                return Failure(SessionNotFound())
            authorized = await self._authorize_public_session(
                session,
                agent_session=agent_session,
                user_id=user_id,
                denied_as_not_found=True,
            )
            if authorized is not None:
                return Failure(authorized)
            if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                return Failure(SubagentSessionReadOnly())
            updated = await self.agent_session_repository.update_title(
                session,
                session_id=session_id,
                title=normalized_title,
                title_source=AgentSessionTitleSource.MANUAL
                if normalized_title is not None
                else None,
            )
            if updated is None:
                return Failure(SessionNotFound())
            await session.write_session.commit()
            return Success(updated)

    async def list_sessions(
        self, user_id: str, workspace_id: str
    ) -> list[AgentSession]:
        """Fetch user session list in workspace.

        :param user_id: Requester user ID
        :param workspace_id: Workspace ID
        :return: Session list
        """
        async with self.session_manager() as session:
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return []
            sessions = await self.agent_session_repository.list_by_workspace(
                session, workspace_id=workspace_id
            )
            agent_ids = {item.agent_id for item in sessions}
            agents = {
                agent_id: agent
                for agent_id in agent_ids
                if (agent := await self.agent_repository.get_by_id(session, agent_id))
                is not None
            }
            sessions = [
                self._project_session_profile(agent, item)
                if item.status is AgentSessionStatus.ACTIVE
                and (agent := agents.get(item.agent_id)) is not None
                else item
                for item in sessions
            ]
            return sessions

    async def list_history_events(
        self,
        session_id: str,
        *,
        user_id: str,
        limit: int = 50,
        before: str | None = None,
        after: str | None = None,
    ) -> Result[PaginatedEvents, SessionAccessError]:
        """Fetch persisted event history of session."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            if (
                agent_session is None
                or agent_session.status != AgentSessionStatus.ACTIVE
            ):
                return Failure(SessionNotFound())
            authorized = await self._authorize_public_session(
                session,
                agent_session=agent_session,
                user_id=user_id,
                denied_as_not_found=False,
            )
            if authorized is not None:
                return Failure(authorized)
            list_events = self.message_repository.list_events_by_session_id_paginated
            items, has_more, has_newer = await list_events(
                session,
                session_id,
                limit=limit,
                before=before,
                after=after,
            )
            return Success(
                PaginatedEvents(
                    items=items,
                    has_more=has_more,
                    has_newer=has_newer,
                )
            )

    async def _append_goal_updated_event(
        self,
        session_id: str,
        snapshot: GoalStateSnapshot,
        *,
        metadata: dict[str, str] | None = None,
    ) -> Event:
        """Store Goal update control event and transition runtime to wake-up state."""
        event_metadata: dict[str, JSONValue] = {
            "source": "goal",
            "provider_slug": "goal",
            "goal_objective": snapshot.objective or "",
            "goal_status": snapshot.status or "",
            "goal_created_at": snapshot.created_at or "",
            "goal_updated_at": snapshot.updated_at or "",
            **(metadata or {}),
        }
        async with self.session_manager() as session:
            event = await self.event_transcript_repository.append(
                session,
                EventCreate(
                    session_id=session_id,
                    kind=EventKind.GOAL_UPDATED,
                    payload={
                        "content": "",
                        "attachments": [],
                        "metadata": event_metadata,
                    },
                ),
            )
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session, session_id
            )
            return event

    async def update_goal(
        self,
        session_id: str,
        *,
        user_id: str,
        objective: str | None,
    ) -> Result[UpdateGoalResult, UpdateGoalError]:
        """Update or delete Session goal."""
        get_result = await self.get_session(session_id, user_id=user_id)
        if get_result.success:
            agent_session = get_result.value
            if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                return Failure(SubagentSessionReadOnly())
        else:
            error = get_result.error
            match error:
                case SessionNotFound() | SessionAccessDenied():
                    return Failure(error)
                case _:
                    assert_never(error)

        goal_store = self.goal_store
        if objective is None:
            updated = await goal_store.clear(
                agent_id=agent_session.agent_id,
                session_id=session_id,
            )
            return Success(
                UpdateGoalResult(
                    goal=GoalStateSnapshot.from_state(updated),
                    agent_id=agent_session.agent_id,
                    workspace_id=agent_session.workspace_id,
                    wake_up=False,
                )
            )

        updated_at = datetime.datetime.now(datetime.UTC).isoformat()
        objective_update = await goal_store.update_objective(
            agent_id=agent_session.agent_id,
            session_id=session_id,
            objective=objective,
            updated_at=updated_at,
        )
        snapshot = GoalStateSnapshot.from_state(objective_update.updated)
        wake_up = (
            objective_update.changed
            and bool(snapshot.objective)
            and snapshot.status == "active"
        )
        event = (
            await self._append_goal_updated_event(session_id, snapshot)
            if wake_up
            else None
        )
        return Success(
            UpdateGoalResult(
                goal=snapshot,
                agent_id=agent_session.agent_id,
                workspace_id=agent_session.workspace_id,
                wake_up=wake_up,
                event=event,
            )
        )

    async def update_goal_status(
        self,
        session_id: str,
        *,
        user_id: str,
        input: UpdateGoalStatusInput,
    ) -> Result[UpdateGoalResult, UpdateGoalError]:
        """Pause/resume Session goal status by user control."""
        get_result = await self.get_session(session_id, user_id=user_id)
        if get_result.success:
            agent_session = get_result.value
            if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                return Failure(SubagentSessionReadOnly())
        else:
            error = get_result.error
            match error:
                case SessionNotFound() | SessionAccessDenied():
                    return Failure(error)
                case _:
                    assert_never(error)

        goal_store = self.goal_store
        updated_at = datetime.datetime.now(datetime.UTC).isoformat()
        try:
            status_update = await goal_store.set_control_status(
                agent_id=agent_session.agent_id,
                session_id=session_id,
                status=input.status,
                updated_at=updated_at,
            )
        except GoalInvalidStatusTransitionError:
            return Failure(InvalidGoalStatusTransition())
        snapshot = GoalStateSnapshot.from_state(status_update.updated)
        wake_up = (
            status_update.changed
            and snapshot.status == "active"
            and bool(snapshot.objective)
        )
        event_metadata = {
            "goal_control_action": "resume",
            "previous_goal_status": status_update.previous_status,
        }
        if input.resume_hint:
            event_metadata["resume_hint"] = input.resume_hint
        event = (
            await self._append_goal_updated_event(
                session_id,
                snapshot,
                metadata=event_metadata,
            )
            if wake_up
            else None
        )
        return Success(
            UpdateGoalResult(
                goal=snapshot,
                agent_id=agent_session.agent_id,
                workspace_id=agent_session.workspace_id,
                wake_up=wake_up,
                event=event,
            )
        )

    async def delete_mailbox_item(
        self,
        session_id: str,
        buffer_id: str,
        *,
        user_id: str,
    ) -> Result[None, DeleteMailboxItemError]:
        """Delete Pending MailboxItem idempotently.

        :param session_id: Target session ID
        :param buffer_id: MailboxItem ID to delete
        :param user_id: Requester user ID
        :return: None on success, error on failure
        """
        get_result = await self.get_session(session_id, user_id=user_id)
        if get_result.success:
            agent_session = get_result.value
            if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                return Failure(SubagentSessionReadOnly())
        else:
            error = get_result.error
            match error:
                case SessionNotFound() | SessionAccessDenied():
                    return Failure(error)
                case _:
                    assert_never(error)

        async with self.session_manager() as session:
            await self.mailbox_repository.delete_by_session_and_id(
                session,
                session_id=session_id,
                buffer_id=buffer_id,
            )
        return Success(None)

    async def prepare_session_working_folder(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        client_request_id: str,
    ) -> Result[MailboxAdmissionResult, PrepareSessionWorkingFolderError]:
        """Enqueue an explicit retry for the canonical Session working folder."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if (
                agent_session is None
                or agent_session.agent_id != agent_id
                or agent_session.status != AgentSessionStatus.ACTIVE
            ):
                return Failure(SessionNotFound())
            authorized = await self._authorize_public_session(
                session,
                agent_session=agent_session,
                user_id=user_id,
                denied_as_not_found=True,
            )
            if authorized is not None:
                return Failure(authorized)
            if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                return Failure(SubagentSessionReadOnly())
            admission = await self.mailbox_admission_repository.enqueue_in_session(
                session,
                MailboxEnqueue(
                    session_id=session_id,
                    kind=MailboxItemKind.ACTION_MESSAGE,
                    scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                    requested_model_target_label=None,
                    requested_reasoning_effort=None,
                    requested_enabled_execution_options=[],
                    sender_user_id=None,
                    order_group=None,
                    order_sequence=0,
                    content="",
                    idempotency_key=(
                        f"session-working-folder:prepare:{session_id}:"
                        f"{client_request_id}"
                    ),
                    metadata={
                        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
                        "source": "system",
                    },
                    action=CreateSessionWorkingFolderAction().model_dump(mode="json"),
                    attachments=[],
                    file_parts=[],
                    payload=None,
                ),
            )
            await session.write_session.commit()
            return Success(admission)

    async def prepare_team_session_creation(
        self, *, agent_id: str, user_id: str
    ) -> Result[str, EnsureSessionError]:
        """Capture authorized Workspace identity before Runtime preparation."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(AgentNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(NotWorkspaceMember())
            return Success(agent.workspace_id)

    async def finalize_team_session_creation(
        self,
        *,
        agent_id: str,
        user_id: str,
        workspace_id: str,
        workspace_items: list[NewSessionWorkspaceItem],
    ) -> Result[AgentSession, EnsureSessionError | InvalidProjectPath]:
        """Reauthorize and atomically create root, projects and setup mailbox work."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None or agent.workspace_id != workspace_id:
                return Failure(AgentNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(NotWorkspaceMember())
            await self.root_session_repository.ensure_team_primary(
                session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
            root_session_creation = self.root_session_repository
            root_result = await root_session_creation.create_root_session(
                session,
                create=AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                    primary_kind=None,
                    product_mode=AgentSessionProductMode.TEAM,
                    associated_user_id=None,
                ),
                workspace_intent=ExplicitRootWorkspaceIntent(
                    existing_project_paths=[
                        item.path
                        for item in workspace_items
                        if isinstance(item, ExistingProjectWorkspaceItem)
                    ],
                ),
            )
            created = root_result.agent_session
            workspace_result = await self._create_session_workspace_items(
                session,
                agent_id=agent_id,
                session_id=created.id,
                session_handle=created.handle,
                workspace_items=workspace_items,
                create_direct_projects=False,
            )
            match workspace_result:
                case Success():
                    pass
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(workspace_result)
            await self._enqueue_setup_actions(
                session,
                agent_session=created,
                workspace_items=workspace_items,
                user_id=user_id,
            )
            await session.write_session.commit()
        return Success(created)

    @retry_hierarchy_operation
    async def archive_agent_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str | None,
    ) -> Result[ChatArchiveDatabaseResult, ArchiveSessionError]:
        """Archive an active non-primary AgentSession after access validation."""
        archive_cleanup_plans = ()
        working_folder_context: SessionWorkingFolderContext | None = None
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if (
                agent_session is None
                or agent_session.agent_id != agent_id
                or agent_session.status != AgentSessionStatus.ACTIVE
            ):
                return Failure(SessionNotFound())
            if user_id is not None:
                authorized = await self._authorize_public_session(
                    session,
                    agent_session=agent_session,
                    user_id=user_id,
                    denied_as_not_found=True,
                )
                if authorized is not None:
                    return Failure(authorized)
            if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                return Failure(SubagentSessionReadOnly())
            if agent_session.primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY:
                return Failure(PrimarySessionArchiveBlocked())
            tree = await self.agent_session_repository.lock_root_tree_sessions(
                session,
                root_session_id=session_id,
            )
            session_ids = [item.id for item in tree]
            if not tree or any(
                item.status != AgentSessionStatus.ACTIVE for item in tree
            ):
                return Failure(RunningSessionArchiveBlocked())
            root = next((item for item in tree if item.id == session_id), None)
            if root is None:
                return Failure(SessionNotFound())
            if root.primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY:
                return Failure(PrimarySessionArchiveBlocked())
            if user_id is not None:
                authorized = await self._authorize_public_session(
                    session,
                    agent_session=root,
                    user_id=user_id,
                    denied_as_not_found=True,
                )
                if authorized is not None:
                    return Failure(authorized)
            if not await self.lifecycle_operations.archive_allows_active_runs(
                session,
                session_ids=session_ids,
                running_session_ids=[
                    item.id
                    for item in tree
                    if item.run_state == AgentSessionRunState.RUNNING
                ],
            ):
                return Failure(RunningSessionArchiveBlocked())
            archived_at = datetime.datetime.now(datetime.UTC)
            if user_id is None:
                agent = await self.agent_repository.get_by_id(session, agent_id)
                latest_activity = max(item.last_activity_at for item in tree)
                if (
                    agent is None
                    or root.pinned
                    or latest_activity
                    + datetime.timedelta(days=agent.auto_archive_ttl_days)
                    > archived_at
                ):
                    return Failure(SessionNotFound())
            archive_cleanup_plans = await self.lifecycle_operations.archive(
                session,
                SessionArchiveMutation(
                    context=SessionLifecycleTransitionContext(
                        transition_id=f"{session_id}:archive",
                        root_session_id=session_id,
                        subtree_session_ids=tuple(session_ids),
                    ),
                    archived_at=archived_at,
                ),
            )
            working_folder_context = (
                await self.agent_session_repository.mark_working_folder_cleanup_pending(
                    session,
                    root_session_id=session_id,
                )
            )
            if working_folder_context is None:
                raise RuntimeError(
                    "Root Session working-folder cleanup state is unavailable"
                )
            await session.write_session.commit()
            return Success(
                ChatArchiveDatabaseResult(
                    root_session_id=session_id,
                    subtree_session_ids=tuple(session_ids),
                    working_folder_context=working_folder_context,
                    cleanup_plans=archive_cleanup_plans,
                )
            )

    async def capture_live_state(
        self, session_id: str, *, user_id: str
    ) -> Result[ChatLiveDatabaseSnapshot, SessionAccessError]:
        """Finish all authorized durable reads before volatile live transport."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            if (
                agent_session is None
                or agent_session.status != AgentSessionStatus.ACTIVE
            ):
                return Failure(SessionNotFound())
            authorized = await self._authorize_public_session(
                session,
                agent_session=agent_session,
                user_id=user_id,
                denied_as_not_found=False,
            )
            if authorized is not None:
                return Failure(authorized)
            mailbox_items = await self.mailbox_repository.list_by_session_id(
                session, session_id
            )
            run = await self.agent_run_repository.get_running_by_session_id(
                session,
                session_id=session_id,
            )
            goal_store = self.goal_store
            goal = GoalStateSnapshot.from_state(
                await goal_store.load_in_session(
                    session,
                    agent_session.agent_id,
                    session_id,
                )
            )
            todo_store = self.todo_store
            todo = TodoStateSnapshot.from_state(
                await todo_store.load_in_session(
                    session,
                    agent_session.agent_id,
                    session_id,
                )
            )
            action_executions = (
                await self.action_execution_repository.list_projections_by_session_id(
                    session,
                    session_id=session_id,
                )
            )
            return Success(
                ChatLiveDatabaseSnapshot(
                    agent_session=agent_session,
                    mailbox_items=tuple(mailbox_items),
                    run=run,
                    goal=goal,
                    todo=todo,
                    action_executions=tuple(action_executions),
                )
            )

    async def list_auto_archive_candidates(self, *, limit: int) -> list[AgentSession]:
        """Capture a bounded due-root batch without dispatching external cleanup."""
        async with self.session_manager() as session:
            return await self.agent_session_repository.list_auto_archive_candidates(
                session, limit=limit
            )

    async def complete_working_folder_cleanup(
        self,
        *,
        context_id: str,
        status: SessionWorkingFolderCleanupStatus,
        summary: str,
    ) -> bool:
        """Record one bounded post-archive cleanup outcome in its own operation."""
        async with self.session_manager() as session:
            return await self.agent_session_repository.complete_working_folder_cleanup(
                session,
                context_id=context_id,
                status=status,
                summary=summary[:_WORKING_FOLDER_CLEANUP_SUMMARY_MAX_LENGTH],
                completed_at=datetime.datetime.now(datetime.UTC),
            )
