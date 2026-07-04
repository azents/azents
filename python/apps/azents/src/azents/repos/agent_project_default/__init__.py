"""Agent Project default repository."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentProjectDefaultItemType
from azents.rdb.models.agent_project_default import RDBAgentProjectDefault

from .data import AgentProjectDefault, AgentProjectDefaultCreate


class AgentProjectDefaultRepository:
    """Agent Project default CRUD repository."""

    async def replace_defaults(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        paths: list[str],
    ) -> list[AgentProjectDefault]:
        """Replace Agent default Project paths with existing-Project items."""
        return await self.replace_default_items(
            session,
            agent_id=agent_id,
            items=[
                AgentProjectDefaultCreate(
                    path=path,
                    item_type=AgentProjectDefaultItemType.EXISTING_PROJECT,
                )
                for path in paths
            ],
        )

    async def replace_default_items(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        items: list[AgentProjectDefaultCreate],
    ) -> list[AgentProjectDefault]:
        """Replace Agent default workspace items with the provided ordered list."""
        await session.execute(
            sa.delete(RDBAgentProjectDefault).where(
                RDBAgentProjectDefault.agent_id == agent_id,
            )
        )
        defaults: list[AgentProjectDefault] = []
        for position, item in enumerate(items):
            rdb = RDBAgentProjectDefault(
                agent_id=agent_id,
                path=item.path,
                item_type=item.item_type,
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
        """Fetch Agent default workspace items in creation selection order."""
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
            item_type=rdb.item_type,
            position=rdb.position,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
