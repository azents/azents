"""User service."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate

from .data import UserListOutput, UserOutput


@dataclasses.dataclass
class UserService:
    """User CRUD service."""

    user_repository: Annotated[UserRepository, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def create(self, create: UserCreate) -> UserOutput:
        """Create User.

        :param create: Create data
        :return: Created User
        """
        async with self.session_manager() as session:
            user = await self.user_repository.create(session, create)
        return UserOutput.convert_from(user)

    async def get(self, user_id: str) -> UserOutput | None:
        """Fetch User by ID.

        :param user_id: User ID
        :return: User or None
        """
        async with self.session_manager() as session:
            user = await self.user_repository.get(session, user_id)
        if user is None:
            return None
        return UserOutput.convert_from(user)

    async def get_by_email(self, email: str) -> UserOutput | None:
        """Fetch User by email.

        :param email: Email address
        :return: User or None
        """
        async with self.session_manager() as session:
            user = await self.user_repository.get_by_email(session, email)
        if user is None:
            return None
        return UserOutput.convert_from(user)

    async def list_all(self, *, offset: int = 0, limit: int = 50) -> UserListOutput:
        """Fetch all Users.

        :param offset: Record count to skip
        :param limit: Maximum record count to return
        :return: User list
        """
        async with self.session_manager() as session:
            result = await self.user_repository.list_all(
                session, offset=offset, limit=limit
            )
        return UserListOutput(
            items=[UserOutput.convert_from(u) for u in result.items],
            total=result.total,
        )

    async def delete(self, user_id: str) -> None:
        """Delete User.

        :param user_id: User ID
        """
        async with self.session_manager() as session:
            await self.user_repository.delete(session, user_id)
