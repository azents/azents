"""Completed role operations with the existing shared mutation lock."""

import dataclasses
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.enums import SystemUserRole
from azents.core.system_user_role import (
    LastSystemAdmin,
    SystemRoleAssignmentNotFound,
    SystemUserNotFound,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
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
    """Own ordinary role reads/grants and narrowly fenced administrator removal."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
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
        """Grant by assignment uniqueness without the administrator removal gate."""
        async with self.session_manager() as session:
            if not await self.system_role_repository.admit_active_user_grant(
                session, user_id
            ):
                return Failure(SystemUserNotFound(user_id=user_id))
            await self.system_role_repository.claim_assignment_mutation(
                session, user_id, role
            )
            inserted = await self.system_role_repository.create_if_absent(
                session,
                SystemUserRoleAssignmentCreate(
                    user_id=user_id,
                    role=role,
                    granted_by_user_id=granted_by_user_id,
                ),
            )
            assignment = inserted or await self.system_role_repository.get(
                session, user_id, role
            )
            if assignment is None:
                raise RuntimeError("Role assignment disappeared during grant")
            return Success(
                SystemUserRoleGrantOutcome(
                    assignment=assignment,
                    created=inserted is not None,
                )
            )

    async def revoke(
        self, user_id: str, role: SystemUserRole
    ) -> Result[None, SystemRoleAssignmentNotFound | LastSystemAdmin]:
        """Remove an exact assignment while preserving the final administrator."""
        async with self.session_manager() as session:
            await self.system_role_repository.acquire_mutation_lock(session)
            await self.system_role_repository.claim_assignment_mutation(
                session, user_id, role
            )
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
