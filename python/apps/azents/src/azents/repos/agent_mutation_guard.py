"""Commit-boundary lifecycle guard for user-originated Agent mutations."""

import sqlalchemy as sa

from azents.core.agent_mutation import AgentMutationReadOnly, AgentMutationTargetMissing
from azents.core.enums import AgentLifecycleStatus
from azents.rdb.models.agent import RDBAgent
from azents.rdb.session_capabilities import WriteSession


async def require_active_agent(session: WriteSession, *, agent_id: str) -> None:
    """Serialize the caller's durable change with Agent deletion admission.

    Authorization is the owning service/operation's responsibility. Native cleanup
    uses its explicit deletion-owner operations instead of this user-write guard.
    """
    lifecycle = await session.write_session.scalar(
        sa.select(RDBAgent.lifecycle_status)
        .where(RDBAgent.id == agent_id)
        .with_for_update()
    )
    if lifecycle is None:
        raise AgentMutationTargetMissing()
    if lifecycle is not AgentLifecycleStatus.ACTIVE:
        raise AgentMutationReadOnly()
