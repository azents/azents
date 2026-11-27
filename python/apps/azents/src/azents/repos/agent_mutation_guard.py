"""Commit-boundary lifecycle guard for user-originated Agent mutations."""

import sqlalchemy as sa

from azents.core.agent_mutation import AgentMutationReadOnly, AgentMutationTargetMissing
from azents.core.enums import AgentLifecycleStatus
from azents.rdb.models.agent import RDBAgent
from azents.rdb.session_capabilities import WriteSession


async def require_active_agent(
    session: WriteSession, *, agent_id: str, allow_foreign_key_reads: bool = False
) -> None:
    """Serialize the caller's durable change with Agent deletion admission.

    Authorization is the owning service/operation's responsibility. Native cleanup
    uses its explicit deletion-owner operations instead of this user-write guard.
    Key-preserving writes can allow foreign-key checks while excluding all writes
    to the Agent. This matters if another transaction holds a later grant lock
    and needs to validate an Agent foreign key before releasing it.
    """
    lifecycle = await session.write_session.scalar(
        sa.select(RDBAgent.lifecycle_status)
        .where(RDBAgent.id == agent_id)
        .with_for_update(key_share=allow_foreign_key_reads)
    )
    if lifecycle is None:
        raise AgentMutationTargetMissing()
    if lifecycle is not AgentLifecycleStatus.ACTIVE:
        raise AgentMutationReadOnly()
