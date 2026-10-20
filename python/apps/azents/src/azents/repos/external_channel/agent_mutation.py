"""Agent-owned Single App publication fence, distinct from shared connections."""

import sqlalchemy as sa

from azents.core.agent_mutation import AgentMutationTargetMissing
from azents.core.enums import ExternalChannelAppMode
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelConnection,
)
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_mutation_guard import require_active_agent


async def require_active_single_app_agent(
    session: WriteSession, *, connection_id: str
) -> None:
    """Fence user activation before provider work and at final publication.

    Multi App configuration belongs to the Workspace. Single App configuration
    belongs to its one durable Agent route; a detached route cannot be reactivated.
    Gateway health, callback cleanup and deletion use their native operations.
    """
    row = (
        await session.read_session.execute(
            sa.select(
                RDBExternalChannelConnection.app_mode,
                RDBExternalChannelAgentRoute.agent_id,
            )
            .outerjoin(
                RDBExternalChannelAgentRoute,
                sa.and_(
                    RDBExternalChannelAgentRoute.connection_id
                    == RDBExternalChannelConnection.id,
                    RDBExternalChannelAgentRoute.connection_app_mode
                    == ExternalChannelAppMode.SINGLE,
                ),
            )
            .where(RDBExternalChannelConnection.id == connection_id)
        )
    ).one_or_none()
    if row is None:
        return
    if row.app_mode is ExternalChannelAppMode.SINGLE:
        if row.agent_id is None:
            raise AgentMutationTargetMissing()
        await require_active_agent(session, agent_id=row.agent_id)
