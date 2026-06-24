"""EmailVerification repository."""

from typing import Any, cast

import sqlalchemy as sa
from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.email_verification import RDBEmailVerification

from .data import (
    AlreadyVerified,
    EmailVerification,
    EmailVerificationCreate,
    EmailVerificationList,
    NotFound,
)


class EmailVerificationRepository:
    """EmailVerification CRUD repository."""

    async def create(
        self,
        session: AsyncSession,
        create: EmailVerificationCreate,
    ) -> EmailVerification:
        """Create verification record.

        :param session: Database session
        :param create: Create data
        :return: Created EmailVerification
        """
        rdb_verification = RDBEmailVerification(
            email=create.email,
            code=create.code,
            csrf_token=create.csrf_token,
            expires_at=create.expires_at,
        )
        session.add(rdb_verification)
        await session.flush()
        return self._build(rdb_verification)

    async def get(
        self, session: AsyncSession, verification_id: str
    ) -> EmailVerification | None:
        """Fetch verification record by ID.

        :param session: Database session
        :param verification_id: Verification ID
        :return: EmailVerification or None
        """
        rdb = await session.get(RDBEmailVerification, verification_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_by_email_and_csrf(
        self, session: AsyncSession, email: str, csrf_token: str
    ) -> EmailVerification | None:
        """Fetch by email + CSRF token.

        :param session: Database session
        :param email: Email address
        :param csrf_token: CSRF token
        :return: EmailVerification or None
        """
        result = await session.execute(
            sa.select(RDBEmailVerification).where(
                RDBEmailVerification.email == email,
                RDBEmailVerification.csrf_token == csrf_token,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def mark_verified(
        self, session: AsyncSession, verification_id: str
    ) -> Result[EmailVerification, NotFound | AlreadyVerified]:
        """Mark as verification complete.

        :param session: Database session
        :param verification_id: Verification ID
        :return: Updated EmailVerification or error
        """
        rdb = await session.get(RDBEmailVerification, verification_id)
        if rdb is None:
            return Failure(NotFound(verification_id=verification_id))
        if rdb.verified_at is not None:
            return Failure(AlreadyVerified(verification_id=verification_id))
        now = tznow()
        result = await session.execute(
            sa.update(RDBEmailVerification)
            .where(RDBEmailVerification.id == verification_id)
            .values(verified_at=now)
            .returning(RDBEmailVerification)
        )
        updated = result.scalar_one()
        return Success(self._build(updated))

    async def delete_stale_by_email(self, session: AsyncSession, email: str) -> int:
        """Delete stale verification records for email, either unverified or expired.

        :param session: Database session
        :param email: Email address
        :return: Deleted record count
        """
        now = tznow()
        result = await session.execute(
            sa.delete(RDBEmailVerification).where(
                RDBEmailVerification.email == email,
                sa.or_(
                    RDBEmailVerification.verified_at.is_not(None),
                    RDBEmailVerification.expires_at < now,
                ),
            )
        )
        cursor = cast(CursorResult[Any], result)
        return cursor.rowcount or 0

    async def list_all(
        self,
        session: AsyncSession,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> EmailVerificationList:
        """Fetch all verification records.

        :param session: Database session
        :param offset: Record count to skip
        :param limit: Maximum record count to return
        :return: EmailVerification list
        """
        count_result = await session.execute(
            sa.select(sa.func.count()).select_from(RDBEmailVerification)
        )
        total = count_result.scalar() or 0

        result = await session.execute(
            sa.select(RDBEmailVerification)
            .order_by(RDBEmailVerification.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = [self._build(rdb) for rdb in result.scalars().all()]
        return EmailVerificationList(items=items, total=total)

    async def list_by_email(
        self,
        session: AsyncSession,
        email: str,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> EmailVerificationList:
        """Fetch verification records by email.

        :param session: Database session
        :param email: Email address
        :param offset: Record count to skip
        :param limit: Maximum record count to return
        :return: EmailVerification list
        """
        now = tznow()
        base_filter = sa.and_(
            RDBEmailVerification.email == email,
            RDBEmailVerification.expires_at >= now,
            RDBEmailVerification.verified_at.is_(None),
        )

        count_result = await session.execute(
            sa.select(sa.func.count()).select_from(
                sa.select(RDBEmailVerification).where(base_filter).subquery()
            )
        )
        total = count_result.scalar() or 0

        result = await session.execute(
            sa.select(RDBEmailVerification)
            .where(base_filter)
            .order_by(RDBEmailVerification.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = [self._build(rdb) for rdb in result.scalars().all()]
        return EmailVerificationList(items=items, total=total)

    def _build(self, rdb: RDBEmailVerification) -> EmailVerification:
        """Convert RDB model to domain model."""
        return EmailVerification(
            id=rdb.id,
            email=rdb.email,
            code=rdb.code,
            csrf_token=rdb.csrf_token,
            expires_at=rdb.expires_at,
            verified_at=rdb.verified_at,
            created_at=rdb.created_at,
        )
