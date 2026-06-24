"""AgentSubagent repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from azcommon.sqlalchemy.postgres import is_constrained_by
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.agent_subagent import RDBAgentSubagent

from .data import (
    AgentSubagent,
    AgentSubagentCreate,
    AgentSubagentUpdate,
    DuplicateAgentSubagent,
    NotFound,
)


class AgentSubagentRepository:
    """AgentSubagent CRUD repository."""

    async def create(
        self,
        session: AsyncSession,
        create: AgentSubagentCreate,
    ) -> Result[AgentSubagent, DuplicateAgentSubagent]:
        """Create AgentSubagent.

        :param session: Database session
        :param create: Create data
        :return: Created AgentSubagent or error
        """
        try:
            rdb = RDBAgentSubagent(
                agent_id=create.agent_id,
                subagent_id=create.subagent_id,
                description=create.description,
                enabled=create.enabled,
            )
            session.add(rdb)
            await session.flush()
            return Success(self._build(rdb))
        except IntegrityError as e:
            await session.rollback()
            if is_constrained_by(e, RDBAgentSubagent.UQ_AGENT_SUBAGENT):
                return Failure(
                    DuplicateAgentSubagent(
                        agent_id=create.agent_id,
                        subagent_id=create.subagent_id,
                    )
                )
            raise

    async def list_by_agent(
        self, session: AsyncSession, agent_id: str
    ) -> list[AgentSubagent]:
        """Fetch all subagent links for parent agent.

        :param session: Database session
        :param agent_id: Parent agent ID
        :return: AgentSubagent list
        """
        result = await session.execute(
            sa.select(RDBAgentSubagent)
            .where(RDBAgentSubagent.agent_id == agent_id)
            .order_by(RDBAgentSubagent.created_at.asc())
        )
        return [self._build(rdb) for rdb in result.scalars().all()]

    async def list_enabled_by_subagent(
        self, session: AsyncSession, subagent_id: str
    ) -> list[AgentSubagent]:
        """Fetch active parent links using subagent.

        :param session: Database session
        :param subagent_id: Subagent ID
        :return: Active AgentSubagent list
        """
        result = await session.execute(
            sa.select(RDBAgentSubagent)
            .where(
                RDBAgentSubagent.subagent_id == subagent_id,
                RDBAgentSubagent.enabled,
            )
            .order_by(RDBAgentSubagent.created_at.asc())
        )
        return [self._build(rdb) for rdb in result.scalars().all()]

    async def get_by_id(
        self, session: AsyncSession, agent_subagent_id: str
    ) -> AgentSubagent | None:
        """Fetch AgentSubagent by ID.

        :param session: Database session
        :param agent_subagent_id: AgentSubagent ID
        :return: AgentSubagent or None
        """
        rdb = await session.get(RDBAgentSubagent, agent_subagent_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def update_by_id(
        self,
        session: AsyncSession,
        agent_subagent_id: str,
        update: AgentSubagentUpdate,
    ) -> Result[AgentSubagent, NotFound]:
        """Update AgentSubagent by ID.

        :param session: Database session
        :param agent_subagent_id: AgentSubagent ID
        :param update: Update data
        :return: Updated AgentSubagent or error
        """
        if not update:
            existing = await self.get_by_id(session, agent_subagent_id)
            if existing is None:
                return Failure(NotFound(agent_subagent_id=agent_subagent_id))
            return Success(existing)

        db_values: dict[str, object] = {}
        if "description" in update:
            db_values["description"] = update["description"]
        if "enabled" in update:
            db_values["enabled"] = update["enabled"]

        result = await session.execute(
            sa.update(RDBAgentSubagent)
            .where(RDBAgentSubagent.id == agent_subagent_id)
            .values(**db_values)
            .returning(RDBAgentSubagent)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return Failure(NotFound(agent_subagent_id=agent_subagent_id))
        return Success(self._build(rdb))

    async def delete_by_id(self, session: AsyncSession, agent_subagent_id: str) -> None:
        """Delete AgentSubagent by ID.

        :param session: Database session
        :param agent_subagent_id: AgentSubagent ID
        """
        await session.execute(
            sa.delete(RDBAgentSubagent).where(RDBAgentSubagent.id == agent_subagent_id)
        )

    def _build(self, rdb: RDBAgentSubagent) -> AgentSubagent:
        """Convert RDB model to domain model."""
        return AgentSubagent(
            id=rdb.id,
            agent_id=rdb.agent_id,
            subagent_id=rdb.subagent_id,
            description=rdb.description,
            enabled=rdb.enabled,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
