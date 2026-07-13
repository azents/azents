"""User service."""

import dataclasses
import logging
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import SystemUserRole
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.system_user_role.data import LastSystemAdmin
from azents.repos.system_user_role.repository import SystemUserRoleRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate

from .data import UserListOutput, UserOutput

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class UserService:
    """User CRUD service."""

    user_repository: Annotated[UserRepository, Depends()]
    system_role_repository: Annotated[SystemUserRoleRepository, Depends()]
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

    async def delete(self, user_id: str) -> Result[None, LastSystemAdmin]:
        """Delete User while preserving the final system administrator.

        :param user_id: User ID
        :return: Success or final-admin invariant error
        """
        async with self.session_manager() as session:
            await self.system_role_repository.acquire_mutation_lock(session)
            system_admin = await self.system_role_repository.get(
                session,
                user_id,
                SystemUserRole.SYSTEM_ADMIN,
            )
            if system_admin is not None:
                count = await self.system_role_repository.count_by_role(
                    session,
                    SystemUserRole.SYSTEM_ADMIN,
                )
                if count <= 1:
                    logger.warning(
                        "Final system administrator deletion denied",
                        extra={"target_user_id": user_id},
                    )
                    return Failure(LastSystemAdmin(user_id=user_id))
            await self.user_repository.delete(session, user_id)
        return Success(None)
