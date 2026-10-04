"""Completed Skill state facade and owner binding at the repository boundary."""

from typing import Annotated

from fastapi import Depends

from azents.core.enums import AgentSessionRunState
from azents.core.skill_projection import SkillProjectionSnapshot, SkillProjectionState
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.skill_state import SkillStateRepository


class SkillStateStore:
    """Engine-facing façade for repository-owned Skill state operations."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[WriteSession],
    ) -> None:
        """Create Skill state store."""
        self.session_manager = session_manager
        self.repository = SkillStateRepository(session_manager=session_manager)

    async def load(self, agent_id: str, session_id: str) -> SkillProjectionState:
        """Fetch Skill projection state."""
        return await self.repository.load(agent_id=agent_id, session_id=session_id)

    async def replace_latest(
        self,
        agent_id: str,
        session_id: str,
        snapshot: SkillProjectionSnapshot,
    ) -> SkillProjectionState:
        """Replace latest projection snapshot."""
        return await self.repository.replace_latest(
            agent_id=agent_id,
            session_id=session_id,
            snapshot=snapshot,
        )

    async def adopt_latest(
        self, agent_id: str, session_id: str
    ) -> SkillProjectionState:
        """Copy latest projection into active projection."""
        return await self.repository.adopt_latest(
            agent_id=agent_id,
            session_id=session_id,
        )

    async def invalidate_project(
        self,
        agent_id: str,
        session_id: str,
        *,
        project_id: str,
        project_path: str,
        session_run_state: AgentSessionRunState,
    ) -> SkillProjectionState:
        """Remove deleted Project items without reading runtime files."""
        return await self.repository.invalidate_project(
            agent_id=agent_id,
            session_id=session_id,
            project_id=project_id,
            project_path=project_path,
            session_run_state=session_run_state,
        )


def get_skill_state_store(
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ],
) -> SkillStateStore:
    """Compose the completed Skill store without exposing a session to callers."""
    return SkillStateStore(session_manager=session_manager)
