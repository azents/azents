"""Chat session service. Session management + message lookup + access control."""

import dataclasses
import datetime
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionPrimaryKind,
    AgentSessionRunState,
    AgentSessionStatus,
    AgentSessionTitleSource,
    EventKind,
)
from azents.engine.events.types import Event
from azents.engine.tools.goal import GoalState, GoalStateSnapshot, GoalStateStore
from azents.engine.tools.todo import TodoStateSnapshot, TodoStateStore
from azents.rdb.deps import get_session_manager
from azents.rdb.models.event import JSONValue
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession, AgentSessionCreate
from azents.repos.message import MessageRepository
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import SessionWorkspaceProjectCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.input_buffer import InputBufferService

from .data import (
    AgentNotFound,
    ArchiveSessionError,
    ArchiveSessionResult,
    ChatLiveRunState,
    ChatLiveStateSnapshot,
    DeleteInputBufferError,
    DeleteSessionError,
    EnsureSessionError,
    InvalidGoalStatusTransition,
    InvalidSessionTitle,
    NotWorkspaceMember,
    PaginatedEvents,
    PrimarySessionArchiveBlocked,
    RunningSessionArchiveBlocked,
    SessionAccessDenied,
    SessionAccessError,
    SessionNotFound,
    UpdateGoalError,
    UpdateGoalResult,
    UpdateGoalStatusInput,
    UpdateSessionTitleError,
)
from .live_events import LiveEventStore, input_buffer_to_live_event


class _InvalidGoalStatusTransitionError(Exception):
    """Service-internal Goal status transition error."""


_SESSION_TITLE_MAX_LENGTH = 200


@dataclasses.dataclass
class ChatSessionService:
    """Chat session service. Session management + message lookup + access control."""

    message_repository: Annotated[MessageRepository, Depends(MessageRepository)]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
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
            await self.agent_session_repository.ensure_team_primary_for_agent(
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
    ) -> Result[AgentSession, EnsureSessionError]:
        """Create a non-primary team session and copy primary projects."""
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
            primary = await self.agent_session_repository.ensure_team_primary_for_agent(
                session,
                workspace_id=agent.workspace_id,
                agent_id=agent_id,
            )
            created = await self.agent_session_repository.create(
                session,
                AgentSessionCreate(
                    workspace_id=agent.workspace_id,
                    agent_id=agent_id,
                    title=None,
                    primary_kind=None,
                ),
            )
            primary_projects = (
                await self.session_workspace_project_repository.list_projects(
                    session,
                    session_id=primary.id,
                )
            )
            for project in primary_projects:
                await self.session_workspace_project_repository.create_project(
                    session,
                    SessionWorkspaceProjectCreate(
                        session_id=created.id,
                        path=project.path,
                    ),
                )
            await session.commit()
            return Success(created)

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
            if agent_session.primary_kind == AgentSessionPrimaryKind.TEAM_PRIMARY:
                return Failure(PrimarySessionArchiveBlocked())
            if agent_session.run_state == AgentSessionRunState.RUNNING:
                return Failure(RunningSessionArchiveBlocked())
            await self.agent_session_repository.archive(
                session,
                session_id,
                ended_at=datetime.datetime.now(datetime.UTC),
            )
            await session.commit()
            return Success(ArchiveSessionResult(archived_session_id=session_id))

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
            goal_store = GoalStateStore(session_manager=self.session_manager)
            goal = GoalStateSnapshot.from_state(
                await goal_store.load(agent_session.agent_id, session_id)
            )
            todo_store = TodoStateStore(session_manager=self.session_manager)
            todo = TodoStateSnapshot.from_state(
                await todo_store.load(agent_session.agent_id, session_id)
            )
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
                    ),
                    session_run_state=agent_session.run_state,
                    todo=todo,
                    goal=goal,
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
            case Success():
                pass
            case Failure(error):
                match error:
                    case SessionNotFound():
                        # Already deleted session — treat as idempotent success
                        return Success(None)
                    case SessionAccessDenied():
                        return Failure(error)
                    case _:
                        assert_never(error)

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
                pass
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
                pass
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
            case Success():
                pass
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
