"""UserEmail service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.user_email import UserEmailRepository
from azents.repos.user_email.data import DuplicateEmail, UserEmailCreate

from .data import UserEmailListOutput, UserEmailOutput


@dataclasses.dataclass
class UserEmailService:
    """UserEmail CRUD service."""

    user_email_repository: Annotated[UserEmailRepository, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def create(
        self, create: UserEmailCreate
    ) -> Result[UserEmailOutput, DuplicateEmail]:
        """Create UserEmail.

        :param create: Create data
        :return: Created UserEmail or duplicate email error
        """
        async with self.session_manager() as session:
            result = await self.user_email_repository.create(session, create)

        match result:
            case Success(value):
                return Success(UserEmailOutput.convert_from(value))
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(result)

    async def get(self, email_id: str) -> UserEmailOutput | None:
        """Fetch UserEmail by ID.

        :param email_id: UserEmail ID
        :return: UserEmail or None
        """
        async with self.session_manager() as session:
            email = await self.user_email_repository.get(session, email_id)
        if email is None:
            return None
        return UserEmailOutput.convert_from(email)

    async def list_by_user(self, user_id: str) -> UserEmailListOutput:
        """Fetch UserEmail list by User ID.

        :param user_id: User ID
        :return: UserEmail list
        """
        async with self.session_manager() as session:
            items = await self.user_email_repository.list_by_user(session, user_id)
        return UserEmailListOutput(
            items=[UserEmailOutput.convert_from(e) for e in items],
            total=len(items),
        )

    async def list_all(
        self, *, offset: int = 0, limit: int = 50
    ) -> UserEmailListOutput:
        """Fetch all UserEmail list.

        :param offset: Record count to skip
        :param limit: Maximum record count to return
        :return: UserEmail list
        """
        async with self.session_manager() as session:
            result = await self.user_email_repository.list_all(
                session, offset=offset, limit=limit
            )
        return UserEmailListOutput(
            items=[UserEmailOutput.convert_from(e) for e in result.items],
            total=result.total,
        )

    async def delete(self, email_id: str) -> None:
        """Delete UserEmail.

        :param email_id: UserEmail ID
        """
        async with self.session_manager() as session:
            await self.user_email_repository.delete(session, email_id)
