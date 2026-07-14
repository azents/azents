"""Chat session service. Session management + message lookup + access control."""

import dataclasses
import datetime
import logging
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentProjectDefaultItemType,
    AgentRunStatus,
    AgentSessionKind,
    AgentSessionPrimaryKind,
    AgentSessionRunState,
    AgentSessionStatus,
    AgentSessionTitleSource,
    EventKind,
    InputBufferKind,
)
from azents.core.inference_profile import AppliedInferenceProfile
from azents.engine.events.action_messages import CreateGitWorktreeAction
from azents.engine.events.types import AgentRunState, ClientToolCallPayload, Event
from azents.engine.tools.goal import GoalState, GoalStateSnapshot, GoalStateStore
from azents.engine.tools.todo import TodoStateSnapshot, TodoStateStore
from azents.rdb.deps import get_session_manager
from azents.rdb.models.event import JSONValue
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_default.data import (
    AgentProjectDefault,
    AgentProjectDefaultCreate,
)
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_project_preset.data import AgentProjectPreset
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import (
    AgentSession,
    AgentSessionCreate,
    SessionAgent,
)
from azents.repos.message import MessageRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProjectCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.input_buffer import InputBufferEnqueue, InputBufferService
from azents.services.session_git_worktree import (
    ExistingProjectWorkspaceItem,
    GitWorktreeWorkspaceItem,
    NewSessionWorkspaceItem,
    SessionGitWorktreeService,
)
from azents.services.session_workspace_project import (
    InvalidProjectPath,
    normalize_session_workspace_path,
    normalize_session_workspace_project_paths,
)

from .data import (
    AgentNotFound,
    ArchiveSessionError,
    ArchiveSessionResult,
    ChatLiveRunRetryAttempt,
    ChatLiveRunRetryState,
    ChatLiveRunState,
    ChatLiveStateSnapshot,
    DeleteInputBufferError,
    DeleteSessionError,
    EnsureSessionError,
    InvalidGoalStatusTransition,
    InvalidSessionTitle,
    NewSessionDefaultExistingProjectWorkspaceItem,
    NewSessionDefaultGitWorktreeWorkspaceItem,
    NewSessionProjectDefaults,
    NewSessionProjectDefaultsSource,
    NewSessionProjectDefaultWorkspaceItem,
    NotWorkspaceMember,
    PaginatedEvents,
    PrimarySessionArchiveBlocked,
    RunningSessionArchiveBlocked,
    SessionAccessDenied,
    SessionAccessError,
    SessionNotFound,
    SubagentSessionReadOnly,
    SubagentTreeNode,
    SubagentTreeProjection,
    UpdateGoalError,
    UpdateGoalResult,
    UpdateGoalStatusInput,
    UpdateSessionTitleError,
)
from .live_events import (
    LiveEventStore,
    active_tool_call_to_live_event,
    input_buffer_to_live_event,
)

logger = logging.getLogger(__name__)


def _latest_agent_message_at(
    agent: SessionAgent,
    latest_run: AgentRunState | None,
) -> datetime.datetime | None:
    """Return the latest explicit or terminal message activity for an agent."""
    timestamps = [agent.last_message_at]
    if latest_run is not None and latest_run.terminal_result_message is not None:
        timestamps.append(latest_run.ended_at)
    present = [timestamp for timestamp in timestamps if timestamp is not None]
    return max(present) if present else None


def _subagent_tree_node(
    agent: SessionAgent,
    *,
    session: AgentSession | None,
    latest_run: AgentRunState | None,
) -> SubagentTreeNode:
    """Build a Subagent Tree projection node."""
    run_status = latest_run.status if latest_run is not None else None
    run_index = latest_run.run_index if latest_run is not None else None
    terminal_result_event_id = (
        latest_run.terminal_result_event_id if latest_run is not None else None
    )
    terminal_result_message = (
        latest_run.terminal_result_message if latest_run is not None else None
    )
    return SubagentTreeNode(
        session_agent_id=agent.id,
        agent_session_id=agent.agent_session_id,
        parent_session_agent_id=agent.parent_session_agent_id,
        name=agent.name,
        path=agent.path,
        agent_type=agent.agent_type,
        status=_project_subagent_status(session, run_status),
        last_task_message=agent.last_task_message,
        last_message_at=_latest_agent_message_at(agent, latest_run),
        unread_result=_has_unread_subagent_result(agent, run_status, run_index),
        latest_run_id=latest_run.id if latest_run is not None else None,
        latest_run_index=run_index,
        latest_run_status=run_status,
        terminal_result_event_id=terminal_result_event_id,
        terminal_result_message=terminal_result_message,
    )


def _project_subagent_status(
    session: AgentSession | None,
    latest_run_status: AgentRunStatus | None,
) -> str:
    """Project AgentSession/run status for Subagent Tree consumers."""
    if session is None:
        return "not_found"
    if session.run_state == AgentSessionRunState.RUNNING:
        return "running"
    if latest_run_status is None:
        return "idle"
    if latest_run_status == AgentRunStatus.COMPLETED:
        return "completed"
    if latest_run_status == AgentRunStatus.FAILED:
        return "errored"
    if latest_run_status in {
        AgentRunStatus.STOPPED,
        AgentRunStatus.INTERRUPTED,
        AgentRunStatus.CANCELLED,
    }:
        return "interrupted"
    return latest_run_status.value


def _subagent_status_sort_rank(status: str) -> int:
    """Return Subagent Tree display order rank for a projected status."""
    match status:
        case "running":
            return 0
        case "failed" | "errored" | "completed":
            return 1
        case "interrupted":
            return 2
        case "pending" | "idle" | "not_found":
            return 3
        case _:
            return 4


def _subagent_tree_sort_key(
    node: SubagentTreeNode,
) -> tuple[bool, float, int, str]:
    """Sort siblings with recent message activity first, then stable fallbacks."""
    sent_at = node.last_message_at
    return (
        sent_at is None,
        -sent_at.timestamp() if sent_at is not None else 0.0,
        _subagent_status_sort_rank(node.status),
        node.name,
    )


def _finalize_subagent_tree_nodes(
    nodes: list[SubagentTreeNode],
    *,
    ancestor_interrupted: bool = False,
) -> list[SubagentTreeNode]:
    """Sort tree nodes and propagate interrupted status to descendants."""
    finalized: list[SubagentTreeNode] = []
    for node in nodes:
        effective_status = "interrupted" if ancestor_interrupted else node.status
        node_interrupted = ancestor_interrupted or effective_status == "interrupted"
        finalized.append(
            dataclasses.replace(
                node,
                status=effective_status,
                children=_finalize_subagent_tree_nodes(
                    node.children,
                    ancestor_interrupted=node_interrupted,
                ),
            )
        )
    return sorted(finalized, key=_subagent_tree_sort_key)


def _has_unread_subagent_result(
    agent: SessionAgent,
    latest_run_status: AgentRunStatus | None,
    latest_run_index: int | None,
) -> bool:
    """Return whether latest terminal result is unread by the parent."""
    if agent.parent_session_agent_id is None:
        return False
    if latest_run_status not in {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.FAILED,
        AgentRunStatus.STOPPED,
        AgentRunStatus.INTERRUPTED,
        AgentRunStatus.CANCELLED,
    }:
        return False
    if latest_run_index is None:
        return False
    if agent.parent_observed_run_index is None:
        return True
    return latest_run_index > agent.parent_observed_run_index


def _require_session_inference_profile(
    session: AgentSession,
) -> AppliedInferenceProfile:
    """Return the prepared public inference profile for an active run."""
    if session.inference_state is None:
        raise ValueError("Active AgentRun has no Session inference state")
    return session.inference_state.applied_profile


class _InvalidGoalStatusTransitionError(Exception):
    """Service-internal Goal status transition error."""


_SESSION_TITLE_MAX_LENGTH = 200


@dataclasses.dataclass
class ChatSessionService:
    """Chat session service. Session management + message lookup + access control."""

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
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
    session_workspace_project_repository: Annotated[
        SessionWorkspaceProjectRepository,
        Depends(SessionWorkspaceProjectRepository),
    ]
    input_buffer_service: Annotated[InputBufferService, Depends(InputBufferService)]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    session_git_worktree_service: Annotated[
        SessionGitWorktreeService | None, Depends(SessionGitWorktreeService)
    ] = None

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
            agent_session = (
                await self.agent_session_repository.ensure_team_primary_for_agent(
                    session,
                    workspace_id=agent.workspace_id,
                    agent_id=agent_id,
                )
            )
            return Success(agent_session)

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
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent_session.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(SessionAccessDenied())
            return Success(agent_session)

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
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent_session.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(SessionNotFound())
            return Success(agent_session)

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
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent_session.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(SessionAccessDenied())
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
            ensure_primary = self.agent_session_repository.ensure_team_primary_for_agent
            await ensure_primary(
                session,
                workspace_id=agent.workspace_id,
                agent_id=agent_id,
            )
            sessions = await self.agent_session_repository.list_active_by_agent_id(
                session,
                agent_id,
            )
            return Success(sessions)

    async def create_team_session(
        self,
        *,
        agent_id: str,
        user_id: str,
        existing_project_paths: list[str],
        setup_actions: list[CreateGitWorktreeAction],
    ) -> Result[AgentSession, EnsureSessionError | InvalidProjectPath]:
        """Create a non-primary team session with setup actions."""
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
            ensure_primary = self.agent_session_repository.ensure_team_primary_for_agent
            await ensure_primary(
                session,
                workspace_id=agent.workspace_id,
                agent_id=agent_id,
            )
            workspace_items_result = _workspace_items_from_request(
                existing_project_paths=existing_project_paths,
                setup_actions=setup_actions,
            )
            match workspace_items_result:
                case Success(workspace_items):
                    pass
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(workspace_items_result)
            created = await self.agent_session_repository.create(
                session,
                AgentSessionCreate(
                    workspace_id=agent.workspace_id,
                    agent_id=agent_id,
                    title=None,
                    primary_kind=None,
                ),
            )
            workspace_result = await self._create_session_workspace_items(
                session,
                agent_id=agent_id,
                session_id=created.id,
                session_handle=created.handle,
                workspace_items=workspace_items,
            )
            match workspace_result:
                case Success():
                    pass
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(workspace_result)
            setup_input_created = await self._enqueue_setup_actions(
                session,
                agent_session=created,
                workspace_items=workspace_items,
                user_id=user_id,
            )
            if setup_input_created:
                await self.agent_session_repository.mark_running_for_input_wakeup(
                    session,
                    created.id,
                )
            await session.commit()
        return Success(created)

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

    async def _create_session_workspace_items(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        session_handle: str,
        workspace_items: list[NewSessionWorkspaceItem],
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
        for path in existing_project_paths:
            await self.session_workspace_project_repository.create_project(
                session,
                SessionWorkspaceProjectCreate(session_id=session_id, path=path),
            )
            await self.agent_project_preset_repository.upsert_preset(
                session,
                agent_id=agent_id,
                path=path,
            )
            await self.agent_project_catalog_repository.upsert_entry(
                session,
                agent_id=agent_id,
                path=path,
            )
        for item in worktree_items:
            await self.agent_project_preset_repository.upsert_preset(
                session,
                agent_id=agent_id,
                path=item.source_project_path,
            )
        if workspace_items:
            await self.agent_project_default_repository.replace_default_items(
                session,
                agent_id=agent_id,
                items=[
                    _default_item_from_workspace_item(item) for item in workspace_items
                ],
            )
        return Success(None)

    async def _enqueue_setup_actions(
        self,
        session: AsyncSession,
        *,
        agent_session: AgentSession,
        workspace_items: list[NewSessionWorkspaceItem],
        user_id: str,
    ) -> bool:
        """Enqueue ordered setup TurnActions for a newly created session."""
        metadata = {
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "source": "chat",
        }
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
                    result = await self.input_buffer_service.enqueue(
                        session,
                        InputBufferEnqueue(
                            session_id=agent_session.id,
                            kind=InputBufferKind.ACTION_MESSAGE,
                            requested_model_target_label=None,
                            requested_reasoning_effort=None,
                            actor_user_id=user_id,
                            content="",
                            idempotency_key=None,
                            metadata=metadata,
                            action=action.model_dump(mode="json"),
                            attachments=[],
                            file_parts=[],
                        ),
                    )
                    created = created or result.created
                case _:
                    assert_never(item)
        return created

    async def _create_session_projects(
        self,
        session: AsyncSession,
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
        )
        match workspace_result:
            case Success():
                return
            case Failure(error):
                raise ValueError(error.reason)
            case _:
                assert_never(workspace_result)

    async def archive_agent_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[ArchiveSessionResult, ArchiveSessionError]:
        """Archive an active non-primary AgentSession after access validation."""
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
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent_session.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(SessionAccessDenied())
            if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                return Failure(SubagentSessionReadOnly())
            if agent_session.primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY:
                return Failure(PrimarySessionArchiveBlocked())
            if agent_session.run_state == AgentSessionRunState.RUNNING:
                return Failure(RunningSessionArchiveBlocked())
            cleanup_requested = False
            worktree_service = self.session_git_worktree_service
            if worktree_service is not None:
                mark_cleanup_pending = worktree_service.mark_cleanup_pending_for_session
                cleanup_request = await mark_cleanup_pending(
                    session,
                    session_id=session_id,
                )
                cleanup_requested = cleanup_request.cleanup_requested
            await self.agent_session_repository.archive(
                session,
                session_id,
                ended_at=datetime.datetime.now(datetime.UTC),
            )
            await session.commit()
            return Success(
                ArchiveSessionResult(
                    archived_session_id=session_id,
                    cleanup_requested=cleanup_requested,
                )
            )

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
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent_session.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(SessionAccessDenied())
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
            await session.commit()
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
            return await self.agent_session_repository.list_by_workspace(
                session, workspace_id=workspace_id
            )

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
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent_session.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(SessionAccessDenied())
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

    async def list_live_events(
        self,
        session_id: str,
        *,
        user_id: str,
        live_event_store: LiveEventStore | None = None,
    ) -> Result[ChatLiveStateSnapshot, SessionAccessError]:
        """Fetch current live state taxonomy snapshot of session."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            if (
                agent_session is None
                or agent_session.status != AgentSessionStatus.ACTIVE
            ):
                return Failure(SessionNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent_session.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(SessionAccessDenied())
            input_buffers = await self.input_buffer_service.list_by_session_id(
                session, session_id
            )
            partial_history_events = []
            if live_event_store is not None:
                partial_history_events = await live_event_store.list_by_session_id(
                    session_id
                )
            input_buffer_events = [
                input_buffer_to_live_event(input_buffer)
                for input_buffer in input_buffers
            ]
            run = await self.agent_run_repository.get_running_by_session_id(
                session,
                session_id=session_id,
            )
            partial_history_events = [
                event
                for event in partial_history_events
                if not isinstance(event.payload, ClientToolCallPayload)
            ]
            if run is not None:
                partial_history_events.extend(
                    active_tool_call_to_live_event(session_id, active)
                    for active in run.active_tool_calls
                )
            partial_history_events.sort(key=lambda event: (event.created_at, event.id))
            goal_store = GoalStateStore(session_manager=self.session_manager)
            goal = GoalStateSnapshot.from_state(
                await goal_store.load(agent_session.agent_id, session_id)
            )
            todo_store = TodoStateStore(session_manager=self.session_manager)
            todo = TodoStateSnapshot.from_state(
                await todo_store.load(agent_session.agent_id, session_id)
            )
            action_executions = (
                await self.action_execution_repository.list_projections_by_session_id(
                    session,
                    session_id=session_id,
                )
            )
            session_run_state = agent_session.run_state
            if run is not None:
                if session_run_state != AgentSessionRunState.RUNNING:
                    logger.warning(
                        "Active AgentRun contradicts persisted Session run state",
                        extra={
                            "session_id": session_id,
                            "run_id": run.id,
                            "run_status": run.status,
                            "session_run_state": session_run_state,
                        },
                    )
                session_run_state = AgentSessionRunState.RUNNING
            return Success(
                ChatLiveStateSnapshot(
                    partial_history_events=partial_history_events,
                    input_buffer_events=input_buffer_events,
                    run=None
                    if run is None
                    else ChatLiveRunState(
                        run_id=run.id,
                        phase=run.phase,
                        status=run.status,
                        inference_profile=_require_session_inference_profile(
                            agent_session
                        ),
                        model_call_started_at=run.model_call_started_at,
                        retry=None
                        if run.retry_state is None
                        else ChatLiveRunRetryState(
                            status=run.retry_state.status,
                            last_error_message=run.retry_state.last_user_message,
                            failed_attempt_count=run.retry_state.failed_attempt_count,
                            max_retries=run.retry_state.max_retries,
                            backoff_seconds=run.retry_state.backoff_seconds,
                            next_retry_at=run.retry_state.next_retry_at.isoformat(),
                            attempts=[
                                ChatLiveRunRetryAttempt(
                                    attempt_number=attempt.attempt_number,
                                    user_message=attempt.user_message,
                                    error_type=attempt.error_type,
                                    source=attempt.source,
                                    failed_at=attempt.failed_at.isoformat(),
                                    backoff_seconds=attempt.backoff_seconds,
                                    next_retry_at=attempt.next_retry_at.isoformat(),
                                    retryability=attempt.retryability,
                                    failure_code=attempt.failure_code,
                                    truncated=attempt.truncated,
                                )
                                for attempt in run.retry_state.attempts
                            ],
                        ),
                    ),
                    session_run_state=session_run_state,
                    todo=todo,
                    goal=goal,
                    action_executions=action_executions,
                )
            )

    async def delete_session(
        self,
        session_id: str,
        *,
        user_id: str,
    ) -> Result[None, DeleteSessionError]:
        """Delete session.

        :param session_id: Session ID to delete
        :param user_id: Requester user ID
        :return: None on success, error on failure
        """
        # Access control: reuse get_session
        get_result = await self.get_session(session_id, user_id=user_id)
        match get_result:
            case Success(agent_session):
                if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                    return Failure(SubagentSessionReadOnly())
            case Failure(error):
                match error:
                    case SessionNotFound():
                        # Already deleted session — treat as idempotent success
                        return Success(None)
                    case SessionAccessDenied():
                        return Failure(error)
                    case _:
                        assert_never(error)

        worktree_service = self.session_git_worktree_service
        if worktree_service is not None:
            cleanup_requested = False
            async with self.session_manager() as session:
                mark_cleanup_pending = worktree_service.mark_cleanup_pending_for_session
                cleanup_request = await mark_cleanup_pending(
                    session,
                    session_id=session_id,
                )
                cleanup_requested = cleanup_request.cleanup_requested
            if cleanup_requested:
                await worktree_service.run_cleanup_for_session(
                    agent_id=agent_session.agent_id,
                    session_id=session_id,
                    session_workspace_project_id=None,
                )

        # Delete DB record
        async with self.session_manager() as session:
            await self.agent_session_repository.delete_by_id(session, session_id)

        return Success(None)

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
        match get_result:
            case Success(agent_session):
                if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                    return Failure(SubagentSessionReadOnly())
            case Failure(error):
                match error:
                    case SessionNotFound() | SessionAccessDenied():
                        return Failure(error)
                    case _:
                        assert_never(error)

        goal_store = GoalStateStore(session_manager=self.session_manager)
        if objective is None:
            updated = await goal_store.update(
                agent_session.agent_id,
                session_id,
                lambda _current: GoalState(),
            )
            return Success(
                UpdateGoalResult(
                    goal=GoalStateSnapshot.from_state(updated),
                    agent_id=agent_session.agent_id,
                    workspace_id=agent_session.workspace_id,
                    wake_up=False,
                )
            )

        changed = False
        updated_at = datetime.datetime.now(datetime.UTC).isoformat()

        def mutate(current: GoalState) -> GoalState:
            nonlocal changed
            if not current.objective or current.status is None:
                return current
            changed = current.objective != objective
            return current.model_copy(
                update={"objective": objective, "updated_at": updated_at}
            )

        updated = await goal_store.update(agent_session.agent_id, session_id, mutate)
        snapshot = GoalStateSnapshot.from_state(updated)
        wake_up = changed and bool(snapshot.objective) and snapshot.status == "active"
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
        match get_result:
            case Success(agent_session):
                if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                    return Failure(SubagentSessionReadOnly())
            case Failure(error):
                match error:
                    case SessionNotFound() | SessionAccessDenied():
                        return Failure(error)
                    case _:
                        assert_never(error)

        goal_store = GoalStateStore(session_manager=self.session_manager)
        changed = False
        previous_status: str | None = None
        updated_at = datetime.datetime.now(datetime.UTC).isoformat()

        def mutate(current: GoalState) -> GoalState:
            nonlocal changed, previous_status
            if not current.objective or current.status is None:
                raise _InvalidGoalStatusTransitionError
            if input.status == "paused":
                if current.status != "active":
                    raise _InvalidGoalStatusTransitionError
            elif input.status == "active":
                if current.status not in {"paused", "blocked"}:
                    raise _InvalidGoalStatusTransitionError
            else:
                raise _InvalidGoalStatusTransitionError
            previous_status = current.status
            changed = current.status != input.status
            return current.model_copy(
                update={"status": input.status, "updated_at": updated_at}
            )

        try:
            updated = await goal_store.update(
                agent_session.agent_id, session_id, mutate
            )
        except _InvalidGoalStatusTransitionError:
            return Failure(InvalidGoalStatusTransition())
        snapshot = GoalStateSnapshot.from_state(updated)
        wake_up = changed and snapshot.status == "active" and bool(snapshot.objective)
        event_metadata = {
            "goal_control_action": "resume",
            "previous_goal_status": previous_status or "",
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

    async def delete_input_buffer(
        self,
        session_id: str,
        buffer_id: str,
        *,
        user_id: str,
    ) -> Result[None, DeleteInputBufferError]:
        """Delete Pending InputBuffer idempotently.

        :param session_id: Target session ID
        :param buffer_id: InputBuffer ID to delete
        :param user_id: Requester user ID
        :return: None on success, error on failure
        """
        get_result = await self.get_session(session_id, user_id=user_id)
        match get_result:
            case Success(agent_session):
                if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                    return Failure(SubagentSessionReadOnly())
            case Failure(error):
                match error:
                    case SessionNotFound() | SessionAccessDenied():
                        return Failure(error)
                    case _:
                        assert_never(error)

        async with self.session_manager() as session:
            await self.input_buffer_service.delete_by_session_and_id(
                session,
                session_id=session_id,
                buffer_id=buffer_id,
            )
        return Success(None)


def _workspace_item_from_default(
    default: AgentProjectDefault,
) -> NewSessionProjectDefaultWorkspaceItem:
    """Convert stored default metadata to a workspace item default."""
    if default.item_type is AgentProjectDefaultItemType.GIT_WORKTREE:
        return NewSessionDefaultGitWorktreeWorkspaceItem(
            source_project_path=default.path,
            starting_ref=None,
        )
    return NewSessionDefaultExistingProjectWorkspaceItem(path=default.path)


def _workspace_items_from_request(
    *,
    existing_project_paths: list[str],
    setup_actions: list[CreateGitWorktreeAction],
) -> Result[list[NewSessionWorkspaceItem], InvalidProjectPath]:
    """Normalize direct Project paths and setup actions for session creation."""
    try:
        normalized_project_paths = normalize_session_workspace_project_paths(
            existing_project_paths
        )
    except ValueError as exc:
        return Failure(InvalidProjectPath(path="", reason=str(exc)))
    workspace_items: list[NewSessionWorkspaceItem] = [
        ExistingProjectWorkspaceItem(path=path) for path in normalized_project_paths
    ]
    for action in setup_actions:
        try:
            normalized_source_path = normalize_session_workspace_path(
                action.source_project_path
            )
        except ValueError as exc:
            return Failure(
                InvalidProjectPath(
                    path=action.source_project_path,
                    reason=str(exc),
                )
            )
        starting_ref = action.starting_ref.strip()
        if not starting_ref:
            return Failure(
                InvalidProjectPath(
                    path=normalized_source_path,
                    reason="Starting Git ref is required.",
                )
            )
        workspace_items.append(
            GitWorktreeWorkspaceItem(
                source_project_path=normalized_source_path,
                starting_ref=starting_ref,
            )
        )
    return Success(_dedupe_existing_project_items(workspace_items))


def _dedupe_existing_project_items(
    items: list[NewSessionWorkspaceItem],
) -> list[NewSessionWorkspaceItem]:
    """Deduplicate exact existing Project rows while preserving worktree items."""
    seen_project_paths: set[str] = set()
    deduped: list[NewSessionWorkspaceItem] = []
    for item in items:
        match item:
            case ExistingProjectWorkspaceItem(path=path):
                if path in seen_project_paths:
                    continue
                seen_project_paths.add(path)
                deduped.append(item)
            case GitWorktreeWorkspaceItem():
                deduped.append(item)
            case _:
                assert_never(item)
    return deduped


def _default_item_from_workspace_item(
    item: NewSessionWorkspaceItem,
) -> AgentProjectDefaultCreate:
    """Convert a selected workspace item to reusable default metadata."""
    match item:
        case ExistingProjectWorkspaceItem(path=path):
            return AgentProjectDefaultCreate(
                path=path,
                item_type=AgentProjectDefaultItemType.EXISTING_PROJECT,
            )
        case GitWorktreeWorkspaceItem(source_project_path=source_project_path):
            return AgentProjectDefaultCreate(
                path=source_project_path,
                item_type=AgentProjectDefaultItemType.GIT_WORKTREE,
            )
        case _:
            assert_never(item)
