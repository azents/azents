"""UserEmail service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.user_email import DuplicateEmail, UserEmailCreate
from azents.repos.user_email.operations import UserEmailOperationRepository

from .data import UserEmailListOutput, UserEmailOutput


@dataclasses.dataclass
class UserEmailService:
    """UserEmail CRUD service."""

    repository: Annotated[
        UserEmailOperationRepository, Depends(UserEmailOperationRepository)
    ]

    async def create(
        self, create: UserEmailCreate
    ) -> Result[UserEmailOutput, DuplicateEmail]:
        """Create UserEmail.

        :param create: Create data
        :return: Created UserEmail or duplicate email error
        """
        result = await self.repository.create(create)

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
        email = await self.repository.get(email_id)
        if email is None:
            return None
        return UserEmailOutput.convert_from(email)

    async def list_by_user(self, user_id: str) -> UserEmailListOutput:
        """Fetch UserEmail list by User ID.

        :param user_id: User ID
        :return: UserEmail list
        """
        result = await self.repository.list_by_user(user_id)
        return UserEmailListOutput(
            items=[UserEmailOutput.convert_from(e) for e in result.items],
            total=result.total,
        )

    async def list_all(
        self, *, offset: int = 0, limit: int = 50
    ) -> UserEmailListOutput:
        """Fetch all UserEmail list.

        :param offset: Record count to skip
        :param limit: Maximum record count to return
        :return: UserEmail list
        """
        result = await self.repository.list_all(offset=offset, limit=limit)
        return UserEmailListOutput(
            items=[UserEmailOutput.convert_from(e) for e in result.items],
            total=result.total,
        )

    async def delete(self, email_id: str) -> None:
        """Delete UserEmail.

        :param email_id: UserEmail ID
        """
        await self.repository.delete(email_id)
