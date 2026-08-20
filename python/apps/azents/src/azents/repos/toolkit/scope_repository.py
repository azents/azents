"""Toolkit scope repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from azcommon.sqlalchemy.postgres import is_constrained_by
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.toolkit import RDBToolkitScope

from .data import DuplicateScope, ToolkitScope, ToolkitScopeCreate


class ToolkitScopeRepository:
    """ToolkitScope repository."""

    async def create(
        self,
        session: AsyncSession,
        create: ToolkitScopeCreate,
    ) -> Result[ToolkitScope, DuplicateScope]:
        """Create ToolkitScope.

        :param session: Database session
        :param create: Create data
        :return: Created ToolkitScope or error
        """
        try:
            rdb_scope = RDBToolkitScope(
                toolkit_id=create.toolkit_id,
                scope_type=create.scope_type,
                scope_id=create.scope_id,
            )
            session.add(rdb_scope)
            await session.flush()
            return Success(self._build(rdb_scope))
        except IntegrityError as e:
            await session.rollback()
            if is_constrained_by(e, RDBToolkitScope.UQ_TOOLKIT_SCOPE):
                return Failure(
                    DuplicateScope(
                        toolkit_id=create.toolkit_id,
                        scope_type=create.scope_type,
                        scope_id=create.scope_id,
                    )
                )
            raise

    async def list_by_toolkit(
        self, session: AsyncSession, toolkit_id: str
    ) -> list[ToolkitScope]:
        """Fetch all Scopes of Toolkit.

        :param session: Database session
        :param toolkit_id: Toolkit ID
        :return: ToolkitScope list
        """
        result = await session.execute(
            sa.select(RDBToolkitScope)
            .where(RDBToolkitScope.toolkit_id == toolkit_id)
            .order_by(RDBToolkitScope.created_at.asc())
        )
        return [self._build(rdb) for rdb in result.scalars().all()]

    async def get_by_id(
        self, session: AsyncSession, scope_id: str
    ) -> ToolkitScope | None:
        """Fetch ToolkitScope by ID.

        :param session: Database session
        :param scope_id: Scope ID
        :return: ToolkitScope or None
        """
        rdb = await session.get(RDBToolkitScope, scope_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def delete_by_id(self, session: AsyncSession, scope_id: str) -> None:
        """Delete ToolkitScope by ID.

        :param session: Database session
        :param scope_id: Scope ID
        """
        await session.execute(
            sa.delete(RDBToolkitScope).where(RDBToolkitScope.id == scope_id)
        )

    def _build(self, rdb: RDBToolkitScope) -> ToolkitScope:
        """Convert RDB model to domain model."""
        return ToolkitScope(
            id=rdb.id,
            toolkit_id=rdb.toolkit_id,
            scope_type=rdb.scope_type,
            scope_id=rdb.scope_id,
            created_at=rdb.created_at,
        )
