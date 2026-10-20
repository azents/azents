"""Same-transaction ownership fencing for Agent-owned deletion operations."""

import sqlalchemy as sa

from azents.core.agent_deletion import AgentDeletionContext, AgentDeletionOwnershipLost
from azents.core.enums import AgentDecommissionStatus, AgentLifecycleStatus
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_decommission import RDBAgentDecommissionJob
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_decommission.data import AgentDecommissionJob


def deletion_context(
    job: AgentDecommissionJob, *, lease_owner: str
) -> AgentDeletionContext:
    """Capture an explicit immutable attempt identity from the claimed job."""
    return AgentDeletionContext(
        job_id=job.id,
        agent_id=job.agent_id,
        workspace_id=job.workspace_id,
        lease_owner=lease_owner,
        expected_attempt=job.attempt_count,
    )


async def require_deletion_ownership(
    session: WriteSession, *, context: AgentDeletionContext
) -> None:
    """Lock job then Agent; every caller's mutation rolls back on ownership loss."""
    job_id = await session.write_session.scalar(
        sa.select(RDBAgentDecommissionJob.id)
        .where(
            RDBAgentDecommissionJob.id == context.job_id,
            RDBAgentDecommissionJob.agent_id == context.agent_id,
            RDBAgentDecommissionJob.workspace_id == context.workspace_id,
            RDBAgentDecommissionJob.lease_owner == context.lease_owner,
            RDBAgentDecommissionJob.attempt_count == context.expected_attempt,
            RDBAgentDecommissionJob.status != AgentDecommissionStatus.COMPLETED,
        )
        .with_for_update()
    )
    if job_id is None:
        raise AgentDeletionOwnershipLost("Agent decommission lease was lost")
    agent_id = await session.write_session.scalar(
        sa.select(RDBAgent.id)
        .where(
            RDBAgent.id == context.agent_id,
            RDBAgent.workspace_id == context.workspace_id,
            RDBAgent.lifecycle_status == AgentLifecycleStatus.DECOMMISSIONING,
        )
        .with_for_update()
    )
    if agent_id is None:
        raise AgentDeletionOwnershipLost("Decommissioning Agent authority was lost")
