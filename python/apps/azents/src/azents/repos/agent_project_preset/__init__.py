"""Agent Project preset repository."""

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.agent_project_preset import RDBAgentProjectPreset

from .data import AgentProjectPreset


class AgentProjectPresetRepository:
    """Agent Project preset CRUD repository."""

    async def upsert_preset(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        path: str,
    ) -> AgentProjectPreset:
        """Create or refresh an Agent Project preset row."""
        result = await session.execute(
            pg_insert(RDBAgentProjectPreset)
            .values(
                id=uuid7().hex,
                agent_id=agent_id,
                path=path,
            )
            .on_conflict_do_update(
                constraint="uq_agent_project_presets_agent_path",
                set_={"updated_at": sa.func.now()},
            )
            .returning(RDBAgentProjectPreset)
        )
        rdb = result.scalar_one()
        await session.flush()
        return self._build(rdb)

    async def list_presets(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> list[AgentProjectPreset]:
        """Fetch Agent Project presets ordered by recent use."""
        result = await session.execute(
            sa.select(RDBAgentProjectPreset)
            .where(RDBAgentProjectPreset.agent_id == agent_id)
            .order_by(
                RDBAgentProjectPreset.updated_at.desc(),
                RDBAgentProjectPreset.path.asc(),
            )
        )
        return [self._build(rdb) for rdb in result.scalars()]

    def _build(self, rdb: RDBAgentProjectPreset) -> AgentProjectPreset:
        """Convert RDB model to domain model."""
        return AgentProjectPreset(
            id=rdb.id,
            agent_id=rdb.agent_id,
            path=rdb.path,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
