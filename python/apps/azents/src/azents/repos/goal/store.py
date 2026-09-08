"""Repository-owned Goal state operations."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import EventKind
from azents.core.goal import (
    GOAL_TOOLKIT_NAMESPACE,
    GOAL_TOOLKIT_STATE_NAME,
    GoalState,
    GoalUpdateStatus,
)
from azents.core.toolkit_state import ToolkitStateIdentity
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.toolkit_state.store import ToolkitStateHandle, ToolkitStateStore


class GoalAlreadyExistsError(ValueError):
    """An unfinished Goal prevents creation of another Goal."""


class GoalNotActiveError(ValueError):
    """The Session has no active Goal to update."""


class GoalInvalidStatusTransitionError(ValueError):
    """A user-controlled Goal status transition is not allowed."""


@dataclasses.dataclass(frozen=True)
class GoalStatusUpdate:
    """Previous and updated Goal state from one atomic status mutation."""

    previous: GoalState
    updated: GoalState


@dataclasses.dataclass(frozen=True)
class GoalObjectiveUpdate:
    """Updated Goal state and whether its objective changed."""

    updated: GoalState
    changed: bool


@dataclasses.dataclass(frozen=True)
class GoalControlStatusUpdate:
    """Updated Goal state and user-control status transition metadata."""

    updated: GoalState
    changed: bool
    previous_status: str


class GoalStateStore:
    """Repository-owned Goal state operations based on Toolkit State."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
    ) -> None:
        """Create Goal state store."""
        self.session_manager = session_manager

    async def load(self, agent_id: str, session_id: str) -> GoalState:
        """Fetch Session Goal state in a completed transaction."""
        async with self.session_manager() as session:
            return await self.load_in_session(session, agent_id, session_id)

    async def load_in_session(
        self,
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> GoalState:
        """Fetch Session Goal state in a composing repository transaction."""
        handle = self._make_handle(session, agent_id, session_id)
        if handle is None:
            return GoalState()
        return await handle.load(default_factory=GoalState)

    async def create(
        self,
        *,
        agent_id: str,
        session_id: str,
        objective: str,
        updated_at: str,
    ) -> GoalState:
        """Create a Goal in a completed transaction."""
        async with self.session_manager() as session:
            return await self.create_in_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                objective=objective,
                updated_at=updated_at,
            )

    async def create_in_session(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        objective: str,
        updated_at: str,
    ) -> GoalState:
        """Create a Goal in a composing repository transaction."""
        handle = self._make_handle(session, agent_id, session_id)
        if handle is None:
            return GoalState()
        updated: GoalState | None = None

        def create_goal(current: GoalState) -> GoalState:
            nonlocal updated
            if _unfinished(current):
                raise GoalAlreadyExistsError("An unfinished goal already exists.")
            updated = GoalState(
                objective=objective,
                status="active",
                created_at=updated_at,
                updated_at=updated_at,
            )
            return updated

        await handle.update(default_factory=GoalState, mutator=create_goal)
        if updated is None:
            raise RuntimeError("Goal create completed without an updated state")
        return updated

    async def clear(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> GoalState:
        """Clear Goal state in a completed transaction."""
        async with self.session_manager() as session:
            handle = self._make_handle(session, agent_id, session_id)
            if handle is None:
                return GoalState()
            cleared = GoalState()
            await handle.update(
                default_factory=GoalState,
                mutator=lambda _current: cleared,
            )
            return cleared

    async def update_objective(
        self,
        *,
        agent_id: str,
        session_id: str,
        objective: str,
        updated_at: str,
    ) -> GoalObjectiveUpdate:
        """Update an existing Goal objective in a completed transaction."""
        async with self.session_manager() as session:
            handle = self._make_handle(session, agent_id, session_id)
            if handle is None:
                return GoalObjectiveUpdate(updated=GoalState(), changed=False)
            changed = False
            updated: GoalState | None = None

            def update_goal(current: GoalState) -> GoalState:
                nonlocal changed, updated
                if not current.objective or current.status is None:
                    updated = current
                    return current
                changed = current.objective != objective
                updated = current.model_copy(
                    update={"objective": objective, "updated_at": updated_at}
                )
                return updated

            await handle.update(default_factory=GoalState, mutator=update_goal)
            if updated is None:
                raise RuntimeError("Goal objective update completed without state")
            return GoalObjectiveUpdate(updated=updated, changed=changed)

    async def set_control_status(
        self,
        *,
        agent_id: str,
        session_id: str,
        status: str,
        updated_at: str,
    ) -> GoalControlStatusUpdate:
        """Apply a user-controlled pause or resume in a completed transaction."""
        async with self.session_manager() as session:
            handle = self._make_handle(session, agent_id, session_id)
            if handle is None:
                raise GoalInvalidStatusTransitionError
            changed = False
            previous_status: str | None = None
            updated: GoalState | None = None

            def update_goal(current: GoalState) -> GoalState:
                nonlocal changed, previous_status, updated
                if not current.objective or current.status is None:
                    raise GoalInvalidStatusTransitionError
                if status == "paused":
                    if current.status != "active":
                        raise GoalInvalidStatusTransitionError
                elif status == "active":
                    if current.status not in {"paused", "blocked"}:
                        raise GoalInvalidStatusTransitionError
                else:
                    raise GoalInvalidStatusTransitionError
                previous_status = current.status
                changed = current.status != status
                updated = current.model_copy(
                    update={"status": status, "updated_at": updated_at}
                )
                return updated

            await handle.update(default_factory=GoalState, mutator=update_goal)
            if previous_status is None or updated is None:
                raise RuntimeError("Goal control update completed without state")
            return GoalControlStatusUpdate(
                updated=updated,
                changed=changed,
                previous_status=previous_status,
            )

    async def set_status(
        self,
        *,
        agent_id: str,
        session_id: str,
        status: GoalUpdateStatus,
        updated_at: str,
    ) -> GoalStatusUpdate:
        """Update an active Goal status in a completed transaction."""
        async with self.session_manager() as session:
            return await self.set_status_in_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                status=status,
                updated_at=updated_at,
            )

    async def set_status_in_session(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        status: GoalUpdateStatus,
        updated_at: str,
    ) -> GoalStatusUpdate:
        """Update an active Goal status in a composing repository transaction."""
        handle = self._make_handle(session, agent_id, session_id)
        if handle is None:
            raise GoalNotActiveError("No active goal exists.")
        previous: GoalState | None = None
        updated: GoalState | None = None

        def update_goal(current: GoalState) -> GoalState:
            nonlocal previous, updated
            if current.status != "active" or not current.objective:
                raise GoalNotActiveError("No active goal exists.")
            previous = current
            updated = current.model_copy(
                update={"status": status, "updated_at": updated_at}
            )
            return updated

        await handle.update(default_factory=GoalState, mutator=update_goal)
        if previous is None or updated is None:
            raise RuntimeError("Goal status update completed without state")
        return GoalStatusUpdate(previous=previous, updated=updated)

    async def append_briefing_event(
        self,
        session_id: str,
        *,
        objective: str,
        created_at: str,
        completed_at: str,
        duration_seconds: int | None,
    ) -> None:
        """Add Goal completion briefing event in a completed transaction."""
        async with self.session_manager() as session:
            await EventTranscriptRepository().append(
                session,
                EventCreate(
                    session_id=session_id,
                    kind=EventKind.GOAL_BRIEFING,
                    payload={
                        "objective": objective,
                        "created_at": created_at,
                        "completed_at": completed_at,
                        "duration_seconds": duration_seconds,
                    },
                ),
            )

    @staticmethod
    def _make_handle(
        session: AsyncSession,
        agent_id: str,
        session_id: str,
    ) -> ToolkitStateHandle[GoalState] | None:
        """Create the Goal Toolkit State handle for one Session identity."""
        if not agent_id or not session_id:
            return None
        identity = ToolkitStateIdentity(
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=GOAL_TOOLKIT_NAMESPACE,
            state_name=GOAL_TOOLKIT_STATE_NAME,
        )
        return ToolkitStateStore(session=session).handle(identity, GoalState)


def _unfinished(state: GoalState) -> bool:
    """Return whether state is unfinished and blocks new Goal creation."""
    return state.status in {"active", "paused", "blocked"} and bool(state.objective)


def get_goal_state_store(
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
) -> GoalStateStore:
    """Create the repository-owned Goal state store dependency."""
    return GoalStateStore(session_manager=session_manager)
