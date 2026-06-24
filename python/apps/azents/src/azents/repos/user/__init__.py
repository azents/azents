"""User repository."""

import datetime

import sqlalchemy as sa
from azcommon.uuid import uuid7
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from azents.rdb.models.user import RDBUser
from azents.rdb.models.user_email import RDBUserEmail

from .data import User, UserCreate, UserList


class UserRepository:
    """User CRUD repository."""

    async def create(self, session: AsyncSession, create: UserCreate) -> User:
        """Create User together with primary UserEmail.

        :param session: Database session
        :param create: Create data including email
        :return: Created User
        """
        return await self._create(
            session,
            create,
            primary_email_verified_at=None,
        )

    async def create_with_verified_primary_email(
        self,
        session: AsyncSession,
        create: UserCreate,
        *,
        verified_at: datetime.datetime,
    ) -> User:
        """Create User with verified primary email.

        :param session: Database session
        :param create: Create data
        :param verified_at: Primary email verification completion time
        :return: Created User
        """
        return await self._create(
            session,
            create,
            primary_email_verified_at=verified_at,
        )

    async def get(self, session: AsyncSession, user_id: str) -> User | None:
        """Fetch User by ID.

        :param session: Database session
        :param user_id: User ID
        :return: User or None
        """
        result = await session.execute(
            sa.select(RDBUser, RDBUserEmail.email)
            .join(RDBUserEmail, RDBUserEmail.id == RDBUser.primary_email_id)
            .where(RDBUser.id == user_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return self._build(row[0], primary_email=row[1])

    async def get_by_email(self, session: AsyncSession, email: str) -> User | None:
        """Fetch User by email.

        :param session: Database session
        :param email: Email address
        :return: User or None
        """
        primary = aliased(RDBUserEmail)
        result = await session.execute(
            sa.select(RDBUser, primary.email)
            .join(RDBUserEmail, RDBUserEmail.user_id == RDBUser.id)
            .join(primary, primary.id == RDBUser.primary_email_id)
            .where(RDBUserEmail.email == email)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return self._build(row[0], primary_email=row[1])

    async def count(self, session: AsyncSession) -> int:
        """Fetch total User count.

        :param session: Database session
        :return: Total User count
        """
        result = await session.execute(sa.select(sa.func.count()).select_from(RDBUser))
        return result.scalar() or 0

    async def list_all(
        self,
        session: AsyncSession,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> UserList:
        """Fetch all Users.

        :param session: Database session
        :param offset: Record count to skip
        :param limit: Maximum record count to return
        :return: User list
        """
        count_result = await session.execute(
            sa.select(sa.func.count()).select_from(RDBUser)
        )
        total = count_result.scalar() or 0

        result = await session.execute(
            sa.select(RDBUser, RDBUserEmail.email)
            .join(RDBUserEmail, RDBUserEmail.id == RDBUser.primary_email_id)
            .order_by(RDBUser.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = result.all()
        return UserList(
            items=[self._build(row[0], primary_email=row[1]) for row in rows],
            total=total,
        )

    async def delete(self, session: AsyncSession, user_id: str) -> None:
        """Delete User.

        :param session: Database session
        :param user_id: User ID
        """
        await session.execute(sa.delete(RDBUser).where(RDBUser.id == user_id))

    async def _create(
        self,
        session: AsyncSession,
        create: UserCreate,
        *,
        primary_email_verified_at: datetime.datetime | None,
    ) -> User:
        """Create User together with primary UserEmail."""
        # Create User with temporary email ID (resolve circular FK)
        temp_email_id = uuid7().hex
        rdb_user = RDBUser(primary_email_id=temp_email_id)
        session.add(rdb_user)
        await session.flush()

        rdb_user_email = RDBUserEmail(
            user_id=rdb_user.id,
            email=create.email,
            verified_at=primary_email_verified_at,
        )
        session.add(rdb_user_email)
        await session.flush()

        await session.execute(
            sa.update(RDBUser)
            .where(RDBUser.id == rdb_user.id)
            .values(primary_email_id=rdb_user_email.id)
        )
        await session.flush()

        await session.refresh(rdb_user)
        return self._build(rdb_user, primary_email=create.email)

    def _build(self, rdb_user: RDBUser, *, primary_email: str) -> User:
        """Convert RDBUser to domain User."""
        return User(
            id=rdb_user.id,
            primary_email_id=rdb_user.primary_email_id,
            primary_email=primary_email,
            created_at=rdb_user.created_at,
            updated_at=rdb_user.updated_at,
        )
