"""Function-owned test transactions with independently scoped ORM savepoints."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession


@asynccontextmanager
async def rollback_session_manager(
    engine: AsyncEngine,
) -> AsyncIterator[SessionManager[WriteSession]]:
    """Commit each ORM context while retaining a final outer test rollback."""
    async with engine.connect() as connection:
        transaction = await connection.begin()

        @asynccontextmanager
        async def session_manager() -> AsyncIterator[WriteSession]:
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            ) as session:
                try:
                    yield ReadWriteSession(session)
                except asyncio.CancelledError:
                    await session.rollback()
                    raise
                except Exception:
                    await session.rollback()
                    raise
                else:
                    await session.commit()

        try:
            yield session_manager
        finally:
            await transaction.rollback()
