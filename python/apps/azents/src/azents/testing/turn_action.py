"""TurnAction capability fixtures shared by backend tests."""

from sqlalchemy.ext.asyncio import AsyncSession

from azents.engine.tools.goal import GoalStateStore
from azents.engine.tools.skill import SkillStateStore
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.services.turn_action import TurnActionCapabilityRegistry


def make_test_turn_action_capabilities(
    session_manager: SessionManager[AsyncSession],
) -> TurnActionCapabilityRegistry:
    """Create the production registry with deterministic repository-backed stores."""
    return TurnActionCapabilityRegistry(
        agent_session_repository=AgentSessionRepository(),
        goal_store=GoalStateStore(session_manager=session_manager),
        skill_store=SkillStateStore(session_manager=session_manager),
        vfs_projection_service=None,
    )
