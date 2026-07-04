"""Agent Project catalog repository."""

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentProjectCatalogStatus
from azents.rdb.models.agent_project_catalog import RDBAgentProjectCatalogEntry

from .data import AgentProjectCatalogEntry, AgentProjectCatalogStatusPatch


class AgentProjectCatalogRepository:
    """Agent Project catalog CRUD repository."""

    async def upsert_entry(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        path: str,
    ) -> AgentProjectCatalogEntry:
        """Create or refresh an Agent Project catalog row."""
        result = await session.execute(
            pg_insert(RDBAgentProjectCatalogEntry)
            .values(
                id=uuid7().hex,
                agent_id=agent_id,
                path=path,
                status=AgentProjectCatalogStatus.UNCHECKED,
            )
            .on_conflict_do_update(
                constraint="uq_agent_project_catalog_entries_agent_path",
                set_={"updated_at": sa.func.now()},
            )
            .returning(RDBAgentProjectCatalogEntry)
        )
        rdb = result.scalar_one()
        await session.flush()
        return self._build(rdb)

    async def list_entries(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> list[AgentProjectCatalogEntry]:
        """Fetch Agent Project catalog entries ordered by recent update."""
        result = await session.execute(
            sa.select(RDBAgentProjectCatalogEntry)
            .where(RDBAgentProjectCatalogEntry.agent_id == agent_id)
            .order_by(
                RDBAgentProjectCatalogEntry.updated_at.desc(),
                RDBAgentProjectCatalogEntry.path.asc(),
            )
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def list_entries_by_paths(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        paths: list[str],
    ) -> list[AgentProjectCatalogEntry]:
        """Fetch Agent Project catalog entries matching exact paths."""
        if not paths:
            return []
        result = await session.execute(
            sa.select(RDBAgentProjectCatalogEntry)
            .where(
                RDBAgentProjectCatalogEntry.agent_id == agent_id,
                RDBAgentProjectCatalogEntry.path.in_(paths),
            )
            .order_by(RDBAgentProjectCatalogEntry.path.asc())
        )
        return [self._build(rdb) for rdb in result.scalars()]

    async def get_entry_by_path(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        path: str,
    ) -> AgentProjectCatalogEntry | None:
        """Fetch one Agent Project catalog entry by path."""
        result = await session.execute(
            sa.select(RDBAgentProjectCatalogEntry).where(
                RDBAgentProjectCatalogEntry.agent_id == agent_id,
                RDBAgentProjectCatalogEntry.path == path,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def delete_entry_by_path(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        path: str,
    ) -> None:
        """Delete one Agent Project catalog row by exact path."""
        await session.execute(
            sa.delete(RDBAgentProjectCatalogEntry).where(
                RDBAgentProjectCatalogEntry.agent_id == agent_id,
                RDBAgentProjectCatalogEntry.path == path,
            )
        )
        await session.flush()

    async def update_status(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        path: str,
        patch: AgentProjectCatalogStatusPatch,
    ) -> AgentProjectCatalogEntry:
        """Upsert one path status projection."""
        result = await session.execute(
            pg_insert(RDBAgentProjectCatalogEntry)
            .values(
                id=uuid7().hex,
                agent_id=agent_id,
                path=path,
                status=patch.status,
                status_detail=patch.status_detail,
                checked_at=patch.checked_at,
            )
            .on_conflict_do_update(
                constraint="uq_agent_project_catalog_entries_agent_path",
                set_={
                    "status": patch.status,
                    "status_detail": patch.status_detail,
                    "checked_at": patch.checked_at,
                    "updated_at": sa.func.now(),
                },
            )
            .returning(RDBAgentProjectCatalogEntry)
        )
        rdb = result.scalar_one()
        await session.flush()
        return self._build(rdb)

    def _build(self, rdb: RDBAgentProjectCatalogEntry) -> AgentProjectCatalogEntry:
        """Convert RDB model to domain model."""
        return AgentProjectCatalogEntry(
            id=rdb.id,
            agent_id=rdb.agent_id,
            path=rdb.path,
            status=rdb.status,
            status_detail=rdb.status_detail,
            checked_at=rdb.checked_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
