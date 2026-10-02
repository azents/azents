"""Completed role operations with the existing shared mutation lock."""

import dataclasses
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import SystemUserRole
from azents.core.system_user_role import (
    LastSystemAdmin,
    SystemRoleAssignmentNotFound,
    SystemUserNotFound,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.system_user_role.data import (
    SystemUserRoleAssignment,
    SystemUserRoleAssignmentCreate,
    SystemUserRoleAssignmentList,
)
from azents.repos.system_user_role.operation_data import SystemUserRoleGrantOutcome
from azents.repos.system_user_role.repository import SystemUserRoleRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import User


@dataclasses.dataclass
class SystemUserRoleOperationRepository:
    """Own role reads and grants/revocations under one advisory lock."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    system_role_repository: Annotated[SystemUserRoleRepository, Depends()]
    user_repository: Annotated[UserRepository, Depends()]

    async def has_role(self, user_id: str, role: SystemUserRole) -> bool:
        """Read one current role assignment."""
        async with self.session_manager() as session:
            return await self.system_role_repository.has_role(session, user_id, role)

    async def list_by_user(self, user_id: str) -> list[SystemUserRoleAssignment]:
        """Read current User roles in their existing order."""
        async with self.session_manager() as session:
            return await self.system_role_repository.list_by_user(session, user_id)

    async def list_all(
        self, *, offset: int, limit: int
    ) -> SystemUserRoleAssignmentList:
        """Read role count and page in one completed transaction."""
        async with self.session_manager() as session:
            return await self.system_role_repository.list_all(
                session, offset=offset, limit=limit
            )

    async def get_user_by_email(self, email: str) -> User | None:
        """Read exact email before grant's authority revalidation."""
        async with self.session_manager() as session:
            return await self.user_repository.get_by_email(session, email)

    async def grant(
        self,
        user_id: str,
        role: SystemUserRole,
        *,
        granted_by_user_id: str | None,
    ) -> Result[SystemUserRoleGrantOutcome, SystemUserNotFound]:
        """Validate enabled User and create or retain a role under one lock."""
        async with self.session_manager() as session:
            await self.system_role_repository.acquire_mutation_lock(session)
            user = await self.user_repository.get(session, user_id)
            if user is None or user.access_disabled_at is not None:
                return Failure(SystemUserNotFound(user_id=user_id))
            existing = await self.system_role_repository.get(session, user_id, role)
            assignment = existing or await self.system_role_repository.create(
                session,
                SystemUserRoleAssignmentCreate(
                    user_id=user_id,
                    role=role,
                    granted_by_user_id=granted_by_user_id,
                ),
            )
            return Success(
                SystemUserRoleGrantOutcome(
                    assignment=assignment, created=existing is None
                )
            )

    async def revoke(
        self, user_id: str, role: SystemUserRole
    ) -> Result[None, SystemRoleAssignmentNotFound | LastSystemAdmin]:
        """Remove an exact assignment while preserving the final administrator."""
        async with self.session_manager() as session:
            await self.system_role_repository.acquire_mutation_lock(session)
            assignment = await self.system_role_repository.get(session, user_id, role)
            if assignment is None:
                return Failure(SystemRoleAssignmentNotFound(user_id=user_id, role=role))
            if role is SystemUserRole.SYSTEM_ADMIN:
                count = await self.system_role_repository.count_by_role(session, role)
                if count <= 1:
                    return Failure(LastSystemAdmin(user_id=user_id))
            deleted = await self.system_role_repository.delete(session, user_id, role)
            if not deleted:
                return Failure(SystemRoleAssignmentNotFound(user_id=user_id, role=role))
            return Success(None)
