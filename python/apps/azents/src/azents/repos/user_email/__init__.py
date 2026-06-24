"""UserEmail repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from azcommon.sqlalchemy.postgres import is_constrained_by
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.user_email import RDBUserEmail

from .data import DuplicateEmail, UserEmail, UserEmailCreate, UserEmailList


class UserEmailRepository:
    """UserEmail CRUD repository."""

    async def create(
        self, session: AsyncSession, create: UserEmailCreate
    ) -> Result[UserEmail, DuplicateEmail]:
        """Create UserEmail.

        :param session: Database session
        :param create: Create data
        :return: Created UserEmail or duplicate email error
        """
        try:
            rdb_email = RDBUserEmail(
                user_id=create.user_id,
                email=create.email,
            )
            session.add(rdb_email)
            await session.flush()
            return Success(self._build(rdb_email))
        except IntegrityError as e:
            await session.rollback()
            if is_constrained_by(e, RDBUserEmail.UQ_EMAIL):
                return Failure(DuplicateEmail(email=create.email))
            raise

    async def get(self, session: AsyncSession, email_id: str) -> UserEmail | None:
        """Fetch UserEmail by ID.

        :param session: Database session
        :param email_id: UserEmail ID
        :return: UserEmail or None
        """
        rdb_email = await session.get(RDBUserEmail, email_id)
        if rdb_email is None:
            return None
        return self._build(rdb_email)

    async def get_by_email(self, session: AsyncSession, email: str) -> UserEmail | None:
        """Fetch UserEmail by email address.

        :param session: Database session
        :param email: Email address
        :return: UserEmail or None
        """
        result = await session.execute(
            sa.select(RDBUserEmail).where(RDBUserEmail.email == email)
        )
        rdb_email = result.scalar_one_or_none()
        if rdb_email is None:
            return None
        return self._build(rdb_email)

    async def list_by_user(
        self, session: AsyncSession, user_id: str
    ) -> list[UserEmail]:
        """Fetch UserEmail list by User ID.

        :param session: Database session
        :param user_id: User ID
        :return: UserEmail list
        """
        result = await session.execute(
            sa.select(RDBUserEmail)
            .where(RDBUserEmail.user_id == user_id)
            .order_by(RDBUserEmail.created_at.asc())
        )
        return [self._build(rdb) for rdb in result.scalars().all()]

    async def list_all(
        self,
        session: AsyncSession,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> UserEmailList:
        """Fetch all UserEmail list.

        :param session: Database session
        :param offset: Record count to skip
        :param limit: Maximum record count to return
        :return: UserEmail list
        """
        count_result = await session.execute(
            sa.select(sa.func.count()).select_from(RDBUserEmail)
        )
        total = count_result.scalar() or 0

        result = await session.execute(
            sa.select(RDBUserEmail)
            .order_by(RDBUserEmail.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = [self._build(rdb) for rdb in result.scalars().all()]
        return UserEmailList(items=items, total=total)

    async def delete(self, session: AsyncSession, email_id: str) -> None:
        """Delete UserEmail.

        :param session: Database session
        :param email_id: UserEmail ID
        """
        await session.execute(
            sa.delete(RDBUserEmail).where(RDBUserEmail.id == email_id)
        )

    def _build(self, rdb_email: RDBUserEmail) -> UserEmail:
        """Convert RDBUserEmail to domain UserEmail."""
        return UserEmail(
            id=rdb_email.id,
            user_id=rdb_email.user_id,
            email=rdb_email.email,
            verified_at=rdb_email.verified_at,
            created_at=rdb_email.created_at,
            updated_at=rdb_email.updated_at,
        )
