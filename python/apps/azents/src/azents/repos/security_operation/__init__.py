"""Completed database operations for Security service credentials."""

import dataclasses
import enum
from typing import Annotated

import sqlalchemy as sa
from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.models.password_login import RDBPasswordLogin
from azents.rdb.models.user_email import RDBUserEmail
from azents.rdb.session import SessionManager
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.password_login.data import PasswordLogin
from azents.repos.user import UserRepository
from azents.repos.user.data import User


class PasswordRemovalOutcome(enum.StrEnum):
    """Final password removal decision inside its owning DB transaction."""

    REMOVED = "removed"
    NOT_SET = "not_set"
    LAST_CREDENTIAL = "last_credential"


@dataclasses.dataclass
class SecurityOperationRepository:
    """Own Security reads and final password mutations without external effects."""

    user_repository: Annotated[UserRepository, Depends()]
    password_repository: Annotated[PasswordLoginRepository, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def get_user(self, user_id: str) -> User | None:
        """Return a detached User before email delivery or OTP verification."""
        async with self.session_manager() as session:
            return await self.user_repository.get(session, user_id)

    async def get_password(self, user_id: str) -> PasswordLogin | None:
        """Return the hash before the service performs password verification."""
        async with self.session_manager() as session:
            return await self.password_repository.get_by_user_id(session, user_id)

    async def set_password(self, user_id: str, password_hash: str) -> bool:
        """Atomically upsert a precomputed hash for an existing User."""
        async with self.session_manager() as session:
            if await self.user_repository.get(session, user_id) is None:
                return False
            await session.execute(
                insert(RDBPasswordLogin)
                .values(id=uuid7().hex, user_id=user_id, password_hash=password_hash)
                .on_conflict_do_update(
                    constraint=RDBPasswordLogin.UQ_USER_ID,
                    set_={"password_hash": password_hash, "updated_at": sa.func.now()},
                )
            )
            return True

    async def remove_password(
        self,
        user_id: str,
        *,
        email_available: bool,
    ) -> PasswordRemovalOutcome:
        """Recheck verified email eligibility in the final DELETE statement."""
        async with self.session_manager() as session:
            if await self.user_repository.get(session, user_id) is None:
                return PasswordRemovalOutcome.NOT_SET
            if email_available:
                verified_email = sa.exists().where(
                    RDBUserEmail.user_id == user_id,
                    RDBUserEmail.verified_at.is_not(None),
                )
                deleted = await session.scalar(
                    sa.delete(RDBPasswordLogin)
                    .where(RDBPasswordLogin.user_id == user_id, verified_email)
                    .returning(RDBPasswordLogin.id)
                )
                if deleted is not None:
                    return PasswordRemovalOutcome.REMOVED
            if not await self.password_repository.exists_for_user(session, user_id):
                return PasswordRemovalOutcome.NOT_SET
            return PasswordRemovalOutcome.LAST_CREDENTIAL
