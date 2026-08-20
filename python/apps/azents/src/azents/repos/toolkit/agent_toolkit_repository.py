"""Agent Toolkit attachment repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from azcommon.sqlalchemy.postgres import is_constrained_by
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.toolkit import RDBAgentToolkit

from .data import AgentToolkit, AgentToolkitCreate, DuplicateAgentToolkit


class AgentToolkitRepository:
    """AgentToolkit repository."""

    async def create(
        self,
        session: AsyncSession,
        create: AgentToolkitCreate,
    ) -> Result[AgentToolkit, DuplicateAgentToolkit]:
        """AgentCreate Toolkit.

        :param session: Database session
        :param create: Create data
        :return: Created AgentToolkit or error
        """
        try:
            rdb_agent_toolkit = RDBAgentToolkit(
                agent_id=create.agent_id,
                toolkit_id=create.toolkit_id,
                toolkit_type=create.toolkit_type,
            )
            session.add(rdb_agent_toolkit)
            await session.flush()
            return Success(self._build(rdb_agent_toolkit))
        except IntegrityError as e:
            await session.rollback()
            if is_constrained_by(e, RDBAgentToolkit.UQ_AGENT_TOOLKIT):
                return Failure(
                    DuplicateAgentToolkit(
                        agent_id=create.agent_id,
                        toolkit_id=create.toolkit_id,
                    )
                )
            raise

    async def list_by_agent(
        self, session: AsyncSession, agent_id: str
    ) -> list[AgentToolkit]:
        """Fetch all AgentToolkits of agent.

        :param session: Database session
        :param agent_id: Agent ID
        :return: AgentToolkit list
        """
        result = await session.execute(
            sa.select(RDBAgentToolkit)
            .where(RDBAgentToolkit.agent_id == agent_id)
            .order_by(RDBAgentToolkit.created_at.asc())
        )
        return [self._build(rdb) for rdb in result.scalars().all()]

    async def get_by_id(
        self, session: AsyncSession, agent_toolkit_id: str
    ) -> AgentToolkit | None:
        """Fetch AgentToolkit by ID.

        :param session: Database session
        :param agent_toolkit_id: AgentToolkit ID
        :return: AgentToolkit or None
        """
        rdb = await session.get(RDBAgentToolkit, agent_toolkit_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def delete_by_id(self, session: AsyncSession, agent_toolkit_id: str) -> None:
        """Delete AgentToolkit by ID.

        :param session: Database session
        :param agent_toolkit_id: AgentToolkit ID
        """
        await session.execute(
            sa.delete(RDBAgentToolkit).where(RDBAgentToolkit.id == agent_toolkit_id)
        )

    def _build(self, rdb: RDBAgentToolkit) -> AgentToolkit:
        """Convert RDB model to domain model."""
        return AgentToolkit(
            id=rdb.id,
            agent_id=rdb.agent_id,
            toolkit_id=rdb.toolkit_id,
            toolkit_type=rdb.toolkit_type,
            created_at=rdb.created_at,
        )
