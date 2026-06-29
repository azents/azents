"""Agent Project default repository."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.agent_project_default import RDBAgentProjectDefault

from .data import AgentProjectDefault


class AgentProjectDefaultRepository:
    """Agent Project default CRUD repository."""

    async def replace_defaults(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        paths: list[str],
    ) -> list[AgentProjectDefault]:
        """Replace Agent default Project paths with the provided ordered list."""
        await session.execute(
            sa.delete(RDBAgentProjectDefault).where(
                RDBAgentProjectDefault.agent_id == agent_id,
            )
        )
        defaults: list[AgentProjectDefault] = []
        for position, path in enumerate(paths):
            rdb = RDBAgentProjectDefault(
                agent_id=agent_id,
                path=path,
                position=position,
            )
            session.add(rdb)
            await session.flush()
            defaults.append(self._build(rdb))
        return defaults

    async def list_defaults(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> list[AgentProjectDefault]:
        """Fetch Agent default Project paths in creation selection order."""
        result = await session.execute(
            sa.select(RDBAgentProjectDefault)
            .where(RDBAgentProjectDefault.agent_id == agent_id)
            .order_by(
                RDBAgentProjectDefault.position.asc(),
                RDBAgentProjectDefault.path.asc(),
            )
        )
        return [self._build(rdb) for rdb in result.scalars()]

    def _build(self, rdb: RDBAgentProjectDefault) -> AgentProjectDefault:
        """Convert RDB model to domain model."""
        return AgentProjectDefault(
            id=rdb.id,
            agent_id=rdb.agent_id,
            path=rdb.path,
            position=rdb.position,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
