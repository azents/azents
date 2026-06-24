"""Session repository."""

import datetime
from typing import Any, cast

import sqlalchemy as sa
from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.session import RDBSession

from .data import NotFound, Session, SessionCreate, TokenMatch


class SessionRepository:
    """Session CRUD repository."""

    async def create(self, session: AsyncSession, create: SessionCreate) -> Session:
        """Create Session.

        :param session: Database session
        :param create: Create data
        :return: Created Session
        """
        rdb_session = RDBSession(
            user_id=create.user_id,
            refresh_token=create.refresh_token,
            expires_at=create.expires_at,
            max_expires_at=create.max_expires_at,
            user_agent=create.user_agent,
            ip_address=create.ip_address,
        )
        session.add(rdb_session)
        await session.flush()
        return Session.from_rdb(rdb_session)

    async def get(self, session: AsyncSession, session_id: str) -> Session | None:
        """Fetch Session by ID.

        :param session: Database session
        :param session_id: Session ID
        :return: Session or None
        """
        rdb_session = await session.get(RDBSession, session_id)
        if rdb_session is None:
            return None
        return Session.from_rdb(rdb_session)

    async def get_by_refresh_token(
        self, session: AsyncSession, refresh_token: str
    ) -> tuple[Session, TokenMatch] | None:
        """Fetch Session by refresh token, current or previous token.

        :param session: Database session
        :param refresh_token: Refresh token
        :return: (Session, TokenMatch) tuple or None
        """
        # Fetch by current token
        result = await session.execute(
            sa.select(RDBSession).where(RDBSession.refresh_token == refresh_token)
        )
        rdb_session = result.scalar_one_or_none()
        if rdb_session is not None:
            return (Session.from_rdb(rdb_session), TokenMatch.CURRENT)

        # Fetch by previous token (grace period)
        result = await session.execute(
            sa.select(RDBSession).where(RDBSession.prev_refresh_token == refresh_token)
        )
        rdb_session = result.scalar_one_or_none()
        if rdb_session is not None:
            return (Session.from_rdb(rdb_session), TokenMatch.PREVIOUS)

        return None

    async def revoke(
        self, session: AsyncSession, session_id: str
    ) -> Result[Session, NotFound]:
        """Revoke Session.

        :param session: Database session
        :param session_id: Session ID
        :return: Revoked Session or error
        """
        now = tznow()
        result = await session.execute(
            sa.update(RDBSession)
            .where(RDBSession.id == session_id)
            .values(revoked_at=now)
            .returning(RDBSession)
        )
        rdb_session = result.scalar_one_or_none()
        if rdb_session is None:
            return Failure(NotFound(id=session_id))

        return Success(Session.from_rdb(rdb_session))

    async def revoke_all_by_user(
        self,
        session: AsyncSession,
        user_id: str,
        *,
        except_session_id: str | None = None,
    ) -> int:
        """Revoke all Sessions for User.

        :param session: Database session
        :param user_id: User ID
        :param except_session_id: Session ID to exclude from revocation
        :return: Revoked Session count
        """
        now = tznow()
        query = (
            sa.update(RDBSession)
            .where(
                sa.and_(
                    RDBSession.user_id == user_id,
                    RDBSession.revoked_at.is_(None),
                )
            )
            .values(revoked_at=now)
        )

        if except_session_id is not None:
            query = query.where(RDBSession.id != except_session_id)

        cursor_result = cast(CursorResult[Any], await session.execute(query))
        return cursor_result.rowcount or 0

    async def rotate_refresh_token(
        self,
        session: AsyncSession,
        session_id: str,
        current_refresh_token: str,
        new_refresh_token: str,
        new_expires_at: datetime.datetime,
    ) -> Result[Session, NotFound]:
        """Rotate refresh token and update expiration time.

        Move current token to prev and set new token (atomic). Include
        current_refresh_token in WHERE clause so only one concurrent request succeeds.

        :param session: Database session
        :param session_id: Session ID
        :param current_refresh_token: Current refresh token (for optimistic locking)
        :param new_refresh_token: New refresh token
        :param new_expires_at: New expiration time
        :return: Updated Session or error
        """
        now = tznow()

        # Check max_expires_at
        rdb_session = await session.get(RDBSession, session_id)
        if rdb_session is None:
            return Failure(NotFound(id=session_id))

        # Apply max_expires_at limit
        actual_expires_at = new_expires_at
        if rdb_session.max_expires_at is not None:
            actual_expires_at = min(new_expires_at, rdb_session.max_expires_at)

        # Atomic update: current token -> prev, set new token
        result = await session.execute(
            sa.update(RDBSession)
            .where(
                RDBSession.id == session_id,
                RDBSession.refresh_token == current_refresh_token,
            )
            .values(
                prev_refresh_token=current_refresh_token,
                refresh_token=new_refresh_token,
                refresh_token_created_at=now,
                expires_at=actual_expires_at,
                last_used_at=now,
            )
            .returning(RDBSession)
        )
        updated_session = result.scalar_one_or_none()

        if updated_session is not None:
            return Success(Session.from_rdb(updated_session))

        # Failed due to concurrent request: refetch latest session
        # After UPDATE, object in identity map is expired, so explicitly issue
        # async SELECT with refresh
        rdb_session = await session.get(RDBSession, session_id)
        if rdb_session is None:
            return Failure(NotFound(id=session_id))
        await session.refresh(rdb_session)

        return Success(Session.from_rdb(rdb_session))

    async def update_last_used(
        self, session: AsyncSession, session_id: str
    ) -> Result[Session, NotFound]:
        """Update Session last used time.

        :param session: Database session
        :param session_id: Session ID
        :return: Updated Session or error
        """
        now = tznow()
        result = await session.execute(
            sa.update(RDBSession)
            .where(RDBSession.id == session_id)
            .values(last_used_at=now)
            .returning(RDBSession)
        )
        rdb_session = result.scalar_one_or_none()
        if rdb_session is None:
            return Failure(NotFound(id=session_id))

        return Success(Session.from_rdb(rdb_session))

    async def delete(self, session: AsyncSession, session_id: str) -> None:
        """Delete Session.

        :param session: Database session
        :param session_id: Session ID
        """
        await session.execute(sa.delete(RDBSession).where(RDBSession.id == session_id))
