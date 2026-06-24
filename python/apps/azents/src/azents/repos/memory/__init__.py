"""Memory repository."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.memory import RDBAgentMemory

from .data import (
    Memory,
    MemoryCreate,
    MemoryScope,
    MemorySummary,
)


class MemoryRepository:
    """Memory CRUD repository."""

    async def upsert(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        user_id: str | None,
        create: MemoryCreate,
    ) -> Memory:
        """Create or update memory.

        Update existing record when name matches within same scope.

        :param session: Database session
        :param agent_id: Agent ID
        :param user_id: User ID (None=agent scope)
        :param create: Create/update data
        :return: Created or updated Memory
        """
        # Fetch existing record
        stmt = sa.select(RDBAgentMemory).where(
            RDBAgentMemory.agent_id == agent_id,
            RDBAgentMemory.name == create.name,
        )
        if user_id is None:
            stmt = stmt.where(RDBAgentMemory.user_id.is_(None))
        else:
            stmt = stmt.where(RDBAgentMemory.user_id == user_id)

        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            # UPDATE
            existing.description = create.description
            existing.content = create.content
            existing.type = create.type
            existing.scope = create.scope.value
            await session.flush()
            await session.refresh(existing)
            return self._build(existing)

        # INSERT
        scope = MemoryScope.AGENT if user_id is None else MemoryScope.USER
        rdb = RDBAgentMemory(
            agent_id=agent_id,
            user_id=user_id,
            scope=scope.value,
            type=create.type,
            name=create.name,
            description=create.description,
            content=create.content,
        )
        session.add(rdb)
        await session.flush()
        return self._build(rdb)

    async def get_by_name(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        user_id: str | None,
        name: str,
    ) -> Memory | None:
        """Fetch memory by name.

        :param session: Database session
        :param agent_id: Agent ID
        :param user_id: User ID (None=agent scope)
        :param name: Memory identifier
        :return: Memory or None
        """
        stmt = sa.select(RDBAgentMemory).where(
            RDBAgentMemory.agent_id == agent_id,
            RDBAgentMemory.name == name,
        )
        if user_id is None:
            stmt = stmt.where(RDBAgentMemory.user_id.is_(None))
        else:
            stmt = stmt.where(RDBAgentMemory.user_id == user_id)

        result = await session.execute(stmt)
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def list_summaries(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        user_id: str | None,
        type: str | None = None,
    ) -> list[MemorySummary]:
        """Fetch memory summary list.

        :param session: Database session
        :param agent_id: Agent ID
        :param user_id: User ID (None=agent scope)
        :param type: Type to filter (optional)
        :return: MemorySummary list
        """
        stmt = sa.select(RDBAgentMemory).where(
            RDBAgentMemory.agent_id == agent_id,
        )
        if user_id is None:
            stmt = stmt.where(RDBAgentMemory.user_id.is_(None))
        else:
            stmt = stmt.where(RDBAgentMemory.user_id == user_id)

        if type is not None:
            stmt = stmt.where(RDBAgentMemory.type == type)

        stmt = stmt.order_by(RDBAgentMemory.type, RDBAgentMemory.name).limit(100)

        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._build_summary(r) for r in rows]

    async def search(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        user_id: str | None,
        query: str,
    ) -> list[MemorySummary]:
        """Search memory.

        Search name, description, and content with ILIKE.
        Search both agent scope and user scope when user_id is provided.

        :param session: Database session
        :param agent_id: Agent ID
        :param user_id: User ID (None=agent scope only)
        :param query: Search string
        :return: MemorySummary list
        """
        pattern = f"%{query}%"
        like_filter = sa.or_(
            RDBAgentMemory.name.ilike(pattern),
            RDBAgentMemory.description.ilike(pattern),
            RDBAgentMemory.content.ilike(pattern),
        )

        scope_filter: sa.ColumnElement[bool]
        if user_id is None:
            scope_filter = RDBAgentMemory.user_id.is_(None)
        else:
            # Search both agent scope and user scope
            scope_filter = sa.or_(
                RDBAgentMemory.user_id.is_(None),
                RDBAgentMemory.user_id == user_id,
            )

        stmt = (
            sa.select(RDBAgentMemory)
            .where(
                RDBAgentMemory.agent_id == agent_id,
                scope_filter,
                like_filter,
            )
            .order_by(RDBAgentMemory.type, RDBAgentMemory.name)
            .limit(50)
        )

        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._build_summary(r) for r in rows]

    async def delete_by_name(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        user_id: str | None,
        name: str,
    ) -> bool:
        """Delete memory by name.

        :param session: Database session
        :param agent_id: Agent ID
        :param user_id: User ID (None=agent scope)
        :param name: Memory identifier
        :return: Deletion flag (True=existed, False=absent)
        """
        stmt = sa.delete(RDBAgentMemory).where(
            RDBAgentMemory.agent_id == agent_id,
            RDBAgentMemory.name == name,
        )
        if user_id is None:
            stmt = stmt.where(RDBAgentMemory.user_id.is_(None))
        else:
            stmt = stmt.where(RDBAgentMemory.user_id == user_id)

        result = await session.execute(stmt)
        return result.rowcount > 0  # pyright: ignore[reportAttributeAccessIssue]  # SQLAlchemy CursorResult.rowcount returns int at runtime but is inferred as generic Result type

    async def count(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        user_id: str | None = None,
    ) -> int:
        """Fetch memory count in scope.

        :param session: Database session
        :param agent_id: Agent ID
        :param user_id: User ID (None=agent scope)
        :return: Memory count
        """
        stmt = (
            sa.select(sa.func.count())
            .select_from(RDBAgentMemory)
            .where(
                RDBAgentMemory.agent_id == agent_id,
            )
        )
        if user_id is None:
            stmt = stmt.where(RDBAgentMemory.user_id.is_(None))
        else:
            stmt = stmt.where(RDBAgentMemory.user_id == user_id)

        result = await session.execute(stmt)
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build(self, rdb: RDBAgentMemory) -> Memory:
        """Convert RDB model to domain model."""
        return Memory(
            id=rdb.id,
            agent_id=rdb.agent_id,
            user_id=rdb.user_id,
            scope=MemoryScope(rdb.scope),
            type=rdb.type,
            name=rdb.name,
            description=rdb.description,
            content=rdb.content,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    def _build_summary(self, rdb: RDBAgentMemory) -> MemorySummary:
        """Convert RDB model to summary model."""
        return MemorySummary(
            name=rdb.name,
            type=rdb.type,
            description=rdb.description,
        )
