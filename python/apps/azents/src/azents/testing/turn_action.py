"""TurnAction capability fixtures shared by backend tests."""

from sqlalchemy.ext.asyncio import AsyncSession

from azents.engine.tools.skill import SkillStateStore
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.goal.store import GoalStateStore
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.promotion import MailboxPromotionRepository
from azents.repos.skill_state import SkillStateRepository
from azents.services.turn_action import TurnActionCapabilityRegistry


def make_test_turn_action_capabilities(
    session_manager: SessionManager[AsyncSession],
) -> TurnActionCapabilityRegistry:
    """Create the production registry with deterministic repository-backed stores."""
    return TurnActionCapabilityRegistry(
        skill_store=SkillStateStore(session_manager=session_manager),
        vfs_projection_service=None,
    )


def make_test_mailbox_promotion_repository(
    session_manager: SessionManager[AsyncSession],
) -> MailboxPromotionRepository:
    """Create the production Mailbox promotion composition for tests."""
    return MailboxPromotionRepository(
        session_manager=session_manager,
        mailbox_repository=MailboxRepository(),
        session_repository=AgentSessionRepository(),
        event_repository=EventTranscriptRepository(),
        run_repository=AgentRunRepository(),
        action_execution_repository=ActionExecutionRepository(),
        goal_store=GoalStateStore(session_manager=session_manager),
        skill_state_repository=SkillStateRepository(
            session_manager=session_manager,
        ),
    )
