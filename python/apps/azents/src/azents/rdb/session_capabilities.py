"""Opt-in Read/Write Session foundation prototype; existing DI stays unchanged."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ReadOnlySession:
    """Read capability; the factory enforces PostgreSQL transaction read-only."""

    read_session: AsyncSession


@dataclass(frozen=True)
class ReadWriteSession:
    """Read and write capabilities sharing one session and transaction."""

    read_session: AsyncSession

    @property
    def write_session(self) -> AsyncSession:
        """Use the exact same session for reads, writes and row locks."""
        return self.read_session


def create_read_only_session_manager(
    engine: AsyncEngine,
) -> SessionManager[ReadOnlySession]:
    """Create opt-in read scopes with DB-enforced read-only transactions.

    The option engine shares the caller's pool; SQLAlchemy restores connection
    characteristics on return. It does not imply a separate replica or DB role.
    Raw AsyncSession remains exposed, so the Protocol is not a SQL sandbox.
    PostgreSQL read-only rejects ordinary writes and row locks, not advisory locks.
    """
    read_engine = engine.execution_options(postgresql_readonly=True)

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[ReadOnlySession]:
        async with (
            AsyncSession(
                read_engine, expire_on_commit=False, autoflush=False
            ) as session,
            session.begin(),
        ):
            yield ReadOnlySession(read_session=session)

    return session_manager


def create_read_write_session_manager(
    engine: AsyncEngine,
) -> SessionManager[ReadWriteSession]:
    """Create write scopes that also satisfy read-method contracts.

    The scope owns commit on success and rollback on failure or cancellation.
    Repository methods use attributes instead of ending the caller's transaction.
    """
    write_engine = engine.execution_options(postgresql_readonly=False)

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[ReadWriteSession]:
        async with (
            AsyncSession(write_engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            yield ReadWriteSession(read_session=session)

    return session_manager
