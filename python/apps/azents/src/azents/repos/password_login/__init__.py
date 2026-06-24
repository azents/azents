"""PasswordLogin repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from azcommon.sqlalchemy.postgres import is_constrained_by
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.password_login import RDBPasswordLogin

from .data import AlreadyExists, NotFound, PasswordLogin, PasswordLoginCreate


class PasswordLoginRepository:
    """PasswordLogin CRUD repository."""

    async def create(
        self, session: AsyncSession, create: PasswordLoginCreate
    ) -> Result[PasswordLogin, AlreadyExists]:
        """Create PasswordLogin.

        :param session: Database session
        :param create: Create data
        :return: Created PasswordLogin or duplicate error
        """
        try:
            rdb = RDBPasswordLogin(
                user_id=create.user_id,
                password_hash=create.password_hash,
            )
            session.add(rdb)
            await session.flush()
            return Success(self._build(rdb))
        except IntegrityError as e:
            await session.rollback()
            if is_constrained_by(e, RDBPasswordLogin.UQ_USER_ID):
                return Failure(AlreadyExists(user_id=create.user_id))
            raise

    async def get_by_user_id(
        self, session: AsyncSession, user_id: str
    ) -> PasswordLogin | None:
        """Fetch PasswordLogin by User ID.

        :param session: Database session
        :param user_id: User ID
        :return: PasswordLogin or None
        """
        result = await session.execute(
            sa.select(RDBPasswordLogin).where(RDBPasswordLogin.user_id == user_id)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def exists_for_user(self, session: AsyncSession, user_id: str) -> bool:
        """Check whether password is set for User.

        :param session: Database session
        :param user_id: User ID
        :return: Password existence flag
        """
        result = await session.execute(
            sa.select(sa.exists().where(RDBPasswordLogin.user_id == user_id))
        )
        return result.scalar() or False

    async def update_password_hash(
        self, session: AsyncSession, user_id: str, password_hash: str
    ) -> Result[PasswordLogin, NotFound]:
        """Update password hash.

        :param session: Database session
        :param user_id: User ID
        :param password_hash: New password hash
        :return: Updated PasswordLogin or error
        """
        result = await session.execute(
            sa.update(RDBPasswordLogin)
            .where(RDBPasswordLogin.user_id == user_id)
            .values(password_hash=password_hash)
            .returning(RDBPasswordLogin)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return Failure(NotFound(user_id=user_id))
        return Success(self._build(rdb))

    async def delete_by_user_id(
        self, session: AsyncSession, user_id: str
    ) -> Result[None, NotFound]:
        """Delete password for User.

        :param session: Database session
        :param user_id: User ID
        :return: Success or error
        """
        result = await session.execute(
            sa.delete(RDBPasswordLogin).where(RDBPasswordLogin.user_id == user_id)
        )
        if result.rowcount == 0:  # type: ignore[union-attr]  # CursorResult has rowcount
            return Failure(NotFound(user_id=user_id))
        return Success(None)

    def _build(self, rdb: RDBPasswordLogin) -> PasswordLogin:
        """Convert RDB model to domain model."""
        return PasswordLogin(
            id=rdb.id,
            user_id=rdb.user_id,
            password_hash=rdb.password_hash,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
