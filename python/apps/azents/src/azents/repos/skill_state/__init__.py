"""Repository-owned Skill projection state operations."""

import dataclasses
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionRunState
from azents.core.skill_projection import (
    SKILL_TOOLKIT_NAMESPACE,
    SKILL_TOOLKIT_STATE_NAME,
    SkillProjectionSnapshot,
    SkillProjectionState,
    invalidate_skill_project,
    make_skill_project_invalidation,
)
from azents.core.toolkit_state import ToolkitStateIdentity
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.toolkit_state.store import ToolkitStateHandle, ToolkitStateStore


@dataclasses.dataclass
class SkillStateRepository:
    """Own completed and transaction-composed Skill state operations."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def load(self, *, agent_id: str, session_id: str) -> SkillProjectionState:
        """Load Skill state in one completed read transaction."""
        async with self.session_manager() as session:
            return await self.load_in_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
            )

    async def load_in_session(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
    ) -> SkillProjectionState:
        """Load Skill state for a database-only composing repository."""
        handle = self._make_handle(session, agent_id=agent_id, session_id=session_id)
        if handle is None:
            return SkillProjectionState()
        return await handle.load(default_factory=SkillProjectionState)

    async def replace_latest(
        self,
        *,
        agent_id: str,
        session_id: str,
        snapshot: SkillProjectionSnapshot,
    ) -> SkillProjectionState:
        """Replace the latest projection in one completed transaction."""
        async with self.session_manager() as session:
            return await self._update_in_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                mutator=lambda current: current.model_copy(update={"latest": snapshot}),
            )

    async def adopt_latest(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> SkillProjectionState:
        """Adopt the latest projection in one completed transaction."""
        async with self.session_manager() as session:
            return await self._update_in_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                mutator=lambda current: current.model_copy(
                    update={"active": current.latest}
                ),
            )

    async def invalidate_project(
        self,
        *,
        agent_id: str,
        session_id: str,
        project_id: str,
        project_path: str,
        session_run_state: AgentSessionRunState,
    ) -> SkillProjectionState:
        """Remove Project items in one completed transaction."""
        async with self.session_manager() as session:
            return await self.invalidate_project_in_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                project_id=project_id,
                project_path=project_path,
                session_run_state=session_run_state,
            )

    async def invalidate_project_in_session(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        project_id: str,
        project_path: str,
        session_run_state: AgentSessionRunState,
    ) -> SkillProjectionState:
        """Remove Project items inside a database-only composing repository."""
        invalidation = make_skill_project_invalidation(
            project_id=project_id,
            project_path=project_path,
            session_run_state=session_run_state,
        )
        return await self._update_in_session(
            session,
            agent_id=agent_id,
            session_id=session_id,
            mutator=lambda current: invalidate_skill_project(
                current,
                invalidation,
            ),
        )

    async def _update_in_session(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
        mutator: Callable[[SkillProjectionState], SkillProjectionState],
    ) -> SkillProjectionState:
        """Apply one typed repository operation with optimistic retry."""
        handle = self._make_handle(session, agent_id=agent_id, session_id=session_id)
        if handle is None:
            return SkillProjectionState()
        saved_state: SkillProjectionState | None = None

        def capture(current: SkillProjectionState) -> SkillProjectionState:
            nonlocal saved_state
            saved_state = mutator(current)
            return saved_state

        await handle.update(default_factory=SkillProjectionState, mutator=capture)
        return saved_state or SkillProjectionState()

    @staticmethod
    def _make_handle(
        session: AsyncSession,
        *,
        agent_id: str,
        session_id: str,
    ) -> ToolkitStateHandle[SkillProjectionState] | None:
        """Create one DB-only typed Skill state handle."""
        if not agent_id or not session_id:
            return None
        return ToolkitStateStore(session=session).handle(
            ToolkitStateIdentity(
                agent_id=agent_id,
                session_id=session_id,
                toolkit_namespace=SKILL_TOOLKIT_NAMESPACE,
                state_name=SKILL_TOOLKIT_STATE_NAME,
            ),
            SkillProjectionState,
        )
