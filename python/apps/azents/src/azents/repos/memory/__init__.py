"""Memory repository."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.memory import RDBAgentMemory

from .data import (
    Memory,
    MemoryCreate,
    MemoryScope,
    MemorySearchMatch,
    MemorySummary,
    MemoryUpdate,
)

_PARTIAL_SEARCH_LIMIT = 10


def _split_search_terms(query: str) -> list[str]:
    """Split search text into distinct case-insensitive terms."""
    terms: list[str] = []
    seen: set[str] = set()
    for term in query.split():
        normalized = term.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        terms.append(term)
    return terms


def _make_term_filter(term: str) -> sa.ColumnElement[bool]:
    """Build a case-insensitive filter for one search term."""
    pattern = f"%{term}%"
    return sa.or_(
        RDBAgentMemory.name.ilike(pattern),
        RDBAgentMemory.description.ilike(pattern),
        RDBAgentMemory.content.ilike(pattern),
    )


def _make_search_filter(query: str) -> sa.ColumnElement[bool]:
    """Build case-insensitive AND search filters from whitespace terms."""
    term_filters = [_make_term_filter(term) for term in _split_search_terms(query)]
    if not term_filters:
        return sa.false()
    return sa.and_(*term_filters)


def _make_search_scope_filter(
    *,
    user_id: str | None,
    include_agent_scope: bool,
) -> sa.ColumnElement[bool]:
    """Build a scope filter for runtime memory search."""
    if user_id is None:
        return RDBAgentMemory.user_id.is_(None)
    if include_agent_scope:
        return sa.or_(
            RDBAgentMemory.user_id.is_(None),
            RDBAgentMemory.user_id == user_id,
        )
    return RDBAgentMemory.user_id == user_id


class MemoryRepository:
    """Memory CRUD repository."""

    async def create(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        user_id: str | None,
        create: MemoryCreate,
    ) -> Memory:
        """Create a memory without upsert semantics.

        :param session: Database session
        :param agent_id: Agent ID
        :param user_id: User ID (None=agent scope)
        :param create: Create data
        :return: Created Memory
        """
        rdb = RDBAgentMemory(
            agent_id=agent_id,
            user_id=user_id,
            scope=create.scope.value,
            type=create.type,
            name=create.name,
            description=create.description,
            content=create.content,
        )
        session.add(rdb)
        await session.flush()
        return self._build(rdb)

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

    async def get_by_id(
        self,
        session: AsyncSession,
        memory_id: str,
    ) -> Memory | None:
        """Fetch memory by ID.

        :param session: Database session
        :param memory_id: Memory ID
        :return: Memory or None
        """
        rdb = await session.get(RDBAgentMemory, memory_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def list(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        user_id: str | None,
        type: str | None = None,
    ) -> list[Memory]:
        """Fetch full memory list for one exact scope.

        :param session: Database session
        :param agent_id: Agent ID
        :param user_id: User ID (None=agent scope)
        :param type: Type to filter (optional)
        :return: Memory list
        """
        stmt = sa.select(RDBAgentMemory).where(RDBAgentMemory.agent_id == agent_id)
        if user_id is None:
            stmt = stmt.where(RDBAgentMemory.user_id.is_(None))
        else:
            stmt = stmt.where(RDBAgentMemory.user_id == user_id)

        if type is not None:
            stmt = stmt.where(RDBAgentMemory.type == type)

        stmt = stmt.order_by(RDBAgentMemory.type, RDBAgentMemory.name).limit(100)

        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._build(r) for r in rows]

    async def search_full(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        user_id: str | None,
        query: str,
        type: str | None = None,
    ) -> list[Memory]:
        """Search full memory rows for one exact scope.

        :param session: Database session
        :param agent_id: Agent ID
        :param user_id: User ID (None=agent scope)
        :param query: Whitespace-separated search terms; all terms must match
        :param type: Type to filter (optional)
        :return: Memory list
        """
        search_filter = _make_search_filter(query)
        stmt = sa.select(RDBAgentMemory).where(
            RDBAgentMemory.agent_id == agent_id,
            search_filter,
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
        return [self._build(r) for r in rows]

    async def update_by_id(
        self,
        session: AsyncSession,
        memory_id: str,
        update: MemoryUpdate,
    ) -> Memory | None:
        """Update memory by ID.

        :param session: Database session
        :param memory_id: Memory ID
        :param update: Partial update data
        :return: Updated Memory or None when absent
        """
        rdb = await session.get(RDBAgentMemory, memory_id)
        if rdb is None:
            return None

        if "type" in update:
            rdb.type = update["type"]
        if "name" in update:
            rdb.name = update["name"]
        if "description" in update:
            rdb.description = update["description"]
        if "content" in update:
            rdb.content = update["content"]

        await session.flush()
        await session.refresh(rdb)
        return self._build(rdb)

    async def delete_by_id(
        self,
        session: AsyncSession,
        memory_id: str,
    ) -> bool:
        """Delete memory by ID.

        :param session: Database session
        :param memory_id: Memory ID
        :return: Deletion flag (True=existed, False=absent)
        """
        result = await session.execute(
            sa.delete(RDBAgentMemory).where(RDBAgentMemory.id == memory_id)
        )
        return result.rowcount > 0  # pyright: ignore[reportAttributeAccessIssue]  # SQLAlchemy CursorResult.rowcount returns int at runtime but is inferred as generic Result type

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
        include_agent_scope: bool,
        query: str,
    ) -> list[MemorySummary]:
        """Search memory using case-insensitive all-term matching.

        :param session: Database session
        :param agent_id: Agent ID
        :param user_id: User ID (None=agent scope only)
        :param include_agent_scope: Include agent scope with the user's scope
        :param query: Whitespace-separated search terms; all terms must match
        :return: MemorySummary list
        """
        search_filter = _make_search_filter(query)
        scope_filter = _make_search_scope_filter(
            user_id=user_id,
            include_agent_scope=include_agent_scope,
        )

        stmt = (
            sa.select(RDBAgentMemory)
            .where(
                RDBAgentMemory.agent_id == agent_id,
                scope_filter,
                search_filter,
            )
            .order_by(RDBAgentMemory.type, RDBAgentMemory.name)
            .limit(50)
        )

        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [self._build_summary(r) for r in rows]

    async def search_partial(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        user_id: str | None,
        include_agent_scope: bool,
        query: str,
    ) -> list[MemorySearchMatch]:
        """Search memories matching any query term, ranked by matched term count.

        :param session: Database session
        :param agent_id: Agent ID
        :param user_id: User ID (None=agent scope only)
        :param include_agent_scope: Include agent scope with the user's scope
        :param query: Whitespace-separated search terms
        :return: Ranked partial search matches
        """
        terms = _split_search_terms(query)
        if not terms:
            return []

        term_filters = [_make_term_filter(term) for term in terms]
        matched_terms: sa.ColumnElement[int] = sa.literal(0)
        for term_filter in term_filters:
            matched_terms = matched_terms + sa.case((term_filter, 1), else_=0)
        matched_terms_label = matched_terms.label("matched_terms")

        scope_filter = _make_search_scope_filter(
            user_id=user_id,
            include_agent_scope=include_agent_scope,
        )

        stmt = (
            sa.select(RDBAgentMemory, matched_terms_label)
            .where(
                RDBAgentMemory.agent_id == agent_id,
                scope_filter,
                sa.or_(*term_filters),
            )
            .order_by(
                matched_terms_label.desc(),
                RDBAgentMemory.type,
                RDBAgentMemory.name,
            )
            .limit(_PARTIAL_SEARCH_LIMIT)
        )

        result = await session.execute(stmt)
        rows = result.all()
        return [
            MemorySearchMatch(
                name=rdb.name,
                type=rdb.type,
                description=rdb.description,
                matched_terms=match_count,
                total_terms=len(terms),
            )
            for rdb, match_count in rows
        ]

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
