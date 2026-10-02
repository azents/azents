"""Completed User operations and atomic account-deletion authority."""

import dataclasses
import datetime
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import SystemUserRole
from azents.core.system_user_role import LastSystemAdmin
from azents.core.user import UserDeletionStatus, UserUpdate
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.owner_lifecycle import OwnerLifecycleRepository
from azents.repos.session import SessionRepository
from azents.repos.system_user_role.repository import SystemUserRoleRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import User, UserCreate, UserList


@dataclasses.dataclass
class UserOperationRepository:
    """Own User reads/writes and the complete disable-and-revoke transaction."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    user_repository: Annotated[UserRepository, Depends()]
    system_role_repository: Annotated[SystemUserRoleRepository, Depends()]
    session_repository: Annotated[SessionRepository, Depends()]
    owner_lifecycle_repository: Annotated[OwnerLifecycleRepository, Depends()]

    async def create(self, create: UserCreate) -> User:
        """Create User and its primary email in one completed transaction."""
        async with self.session_manager() as session:
            return await self.user_repository.create(session, create)

    async def get(self, user_id: str) -> User | None:
        """Return one detached User."""
        async with self.session_manager() as session:
            return await self.user_repository.get(session, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Return the exact-email User snapshot."""
        async with self.session_manager() as session:
            return await self.user_repository.get_by_email(session, email)

    async def update(self, user_id: str, update: UserUpdate) -> User | None:
        """Apply the existing partial update in one completed transaction."""
        async with self.session_manager() as session:
            return await self.user_repository.update(session, user_id, update)

    async def list_all(self, *, offset: int, limit: int) -> UserList:
        """Read User count and page together."""
        async with self.session_manager() as session:
            return await self.user_repository.list_all(
                session, offset=offset, limit=limit
            )

    async def delete(
        self,
        user_id: str,
        *,
        disabled_at: datetime.datetime,
    ) -> Result[UserDeletionStatus, LastSystemAdmin]:
        """Atomically disable, remove roles, revoke Sessions and schedule purge."""
        async with self.session_manager() as session:
            await self.system_role_repository.acquire_mutation_lock(session)
            system_admin = await self.system_role_repository.get(
                session, user_id, SystemUserRole.SYSTEM_ADMIN
            )
            if system_admin is not None:
                count = await self.system_role_repository.count_by_role(
                    session, SystemUserRole.SYSTEM_ADMIN
                )
                if count <= 1:
                    return Failure(LastSystemAdmin(user_id=user_id))
            user = await self.user_repository.get(session, user_id)
            if user is None:
                return Success(UserDeletionStatus.MISSING)
            await self.user_repository.disable_access(
                session, user_id, disabled_at=disabled_at
            )
            for role in SystemUserRole:
                await self.system_role_repository.delete(session, user_id, role)
            await self.session_repository.revoke_all_by_user(session, user_id)
            await self.owner_lifecycle_repository.create_or_get_account_purge(
                session, user_id=user_id
            )
            return Success(UserDeletionStatus.ACCEPTED)
