"""Explicit Session execution validation and exact critical mutation fencing."""

import dataclasses

import sqlalchemy as sa

from azents.core.agent_session_data import AgentSession
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.session_execution import CanonicalExecutionOwnerGenerationStaleError


async def validate_session_execution_owner(
    session: ReadSession,
    owner: SessionExecutionOwner,
) -> AgentSession:
    """Validate one observed owner without holding a lock across external I/O."""
    current = await AgentSessionRepository().get_by_id(session, owner.session_id)
    if current is None:
        raise ValueError("AgentSession not found")
    if current.owner_generation != owner.owner_generation:
        raise CanonicalExecutionOwnerGenerationStaleError(
            "Session owner generation is stale"
        )
    return current


async def fence_owned_session_mutation(
    session: WriteSession,
    owner: SessionExecutionOwner,
) -> AgentSession:
    """Exclude owner handover until this critical dependent write group commits.

    Updating the exact owner row retains a real write fence, unlike an unrelated
    INSERT whose MVCC EXISTS check cannot serialize an ownership handover.
    This primitive belongs only at critical operation mutation boundaries.
    """
    result = await session.write_session.execute(
        sa.update(RDBAgentSession)
        .where(
            RDBAgentSession.id == owner.session_id,
            RDBAgentSession.owner_generation == owner.owner_generation,
        )
        .values(
            owner_generation=RDBAgentSession.owner_generation,
            updated_at=RDBAgentSession.updated_at,
        )
        .returning(RDBAgentSession)
        .execution_options(populate_existing=True)
    )
    current = result.scalar_one_or_none()
    if current is None:
        await validate_session_execution_owner(session, owner)
        raise CanonicalExecutionOwnerGenerationStaleError(
            "Session owner generation is stale"
        )
    return AgentSessionRepository()._build(current)


@dataclasses.dataclass(frozen=True)
class SessionExecutionAuthorityRepository:
    """Completed nonlocking admission observation before an external effect."""

    session_manager: SessionManager[ReadSession]
    owner: SessionExecutionOwner

    async def assert_current(self) -> None:
        """Reject an observed stale owner; final result writes fence independently."""
        async with self.session_manager() as session:
            await validate_session_execution_owner(session, self.owner)
