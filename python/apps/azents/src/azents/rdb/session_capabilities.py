"""Repository session capabilities and PostgreSQL read/write scope factories."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.rdb.session import SessionManager


class ReadSession(Protocol):
    """Capability required by a repository read method."""

    @property
    def read_session(self) -> AsyncSession:
        """Return the session used for database reads."""
        ...


class WriteSession(ReadSession, Protocol):
    """Capability required by a repository mutation or locking method."""

    @property
    def write_session(self) -> AsyncSession:
        """Return the session used for database writes and row locks."""
        ...


class ReadOnlySession:
    """Read capability backed by a private SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        """Wrap a session; the factory sets its connection read-only mode."""
        self._session = session

    @property
    def read_session(self) -> AsyncSession:
        """Return the database read session."""
        return self._session


class ReadWriteSession:
    """Read and write capabilities backed by one private session/transaction."""

    def __init__(self, session: AsyncSession) -> None:
        """Wrap the exact session owned by the caller's transaction scope."""
        self._session = session

    @property
    def read_session(self) -> AsyncSession:
        """Use the same database session for a read within this write scope."""
        return self._session

    @property
    def write_session(self) -> AsyncSession:
        """Return the database write and row-lock session."""
        return self._session


def create_read_only_session_manager(
    engine: AsyncEngine,
) -> SessionManager[ReadOnlySession]:
    """Create read scopes with PostgreSQL-enforced read-only transactions.

    SQLAlchemy option engines share the caller's pool and restore connection
    characteristics on return. This does not select a replica or another DB role.
    Raw AsyncSession remains exposed: this is not a SQL sandbox. PostgreSQL
    read-only rejects ordinary writes and row locks, not advisory locks.
    """
    read_engine = engine.execution_options(postgresql_readonly=True)

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[ReadOnlySession]:
        async with AsyncSession(
            read_engine, expire_on_commit=False, autoflush=False
        ) as session:
            try:
                yield ReadOnlySession(session)
            except asyncio.CancelledError:
                await session.rollback()
                raise
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    return session_manager


def create_read_write_session_manager(
    engine: AsyncEngine,
) -> SessionManager[ReadWriteSession]:
    """Create write scopes compatible with explicit intermediate commits.

    Keep the existing session-manager transaction lifecycle: commit on successful
    scope exit and rollback on errors. An explicit commit followed by more SQL
    may start another transaction in the same scope, as before the capability split.
    """
    write_engine = engine.execution_options(postgresql_readonly=False)

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[ReadWriteSession]:
        async with AsyncSession(write_engine, expire_on_commit=False) as session:
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

    return session_manager
