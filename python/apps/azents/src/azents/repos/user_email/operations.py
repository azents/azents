"""Completed database operations for UserEmail CRUD."""

import dataclasses
from typing import Annotated

from azcommon.result import Result
from fastapi import Depends

from azents.core.user_email import DuplicateEmail, UserEmailCreate
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.user_email import UserEmailRepository
from azents.repos.user_email.data import UserEmail, UserEmailList


@dataclasses.dataclass
class UserEmailOperationRepository:
    """Own complete UserEmail read and mutation transactions."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    user_email_repository: Annotated[UserEmailRepository, Depends(UserEmailRepository)]

    async def create(
        self, create: UserEmailCreate
    ) -> Result[UserEmail, DuplicateEmail]:
        """Create an email and finish uniqueness rollback before returning."""
        async with self.session_manager() as session:
            return await self.user_email_repository.create(session, create)

    async def get(self, email_id: str) -> UserEmail | None:
        """Return a detached email projection or None."""
        async with self.session_manager() as session:
            return await self.user_email_repository.get(session, email_id)

    async def list_by_user(self, user_id: str) -> UserEmailList:
        """Read ordered emails and their exact user-scoped count together."""
        async with self.session_manager() as session:
            items = await self.user_email_repository.list_by_user(session, user_id)
            return UserEmailList(items=items, total=len(items))

    async def list_all(self, *, offset: int, limit: int) -> UserEmailList:
        """Read the email count and ordered page in one completed operation."""
        async with self.session_manager() as session:
            return await self.user_email_repository.list_all(
                session, offset=offset, limit=limit
            )

    async def delete(self, email_id: str) -> None:
        """Delete an exact email, retaining missing-row and foreign-key behavior."""
        async with self.session_manager() as session:
            await self.user_email_repository.delete(session, email_id)
