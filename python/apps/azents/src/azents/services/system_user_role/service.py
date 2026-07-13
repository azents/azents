"""Instance-wide User role service."""

import dataclasses
import logging
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import SystemUserRole
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.system_user_role.data import (
    LastSystemAdmin,
    SystemRoleAssignmentNotFound,
    SystemUserNotFound,
    SystemUserRoleAssignmentCreate,
)
from azents.repos.system_user_role.repository import SystemUserRoleRepository
from azents.repos.user import UserRepository

from .data import (
    CurrentSystemRolesOutput,
    SystemUserRoleAssignmentListOutput,
    SystemUserRoleAssignmentOutput,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class SystemUserRoleService:
    """Manage instance-wide User role assignments."""

    system_role_repository: Annotated[SystemUserRoleRepository, Depends()]
    user_repository: Annotated[UserRepository, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def has_role(self, user_id: str, role: SystemUserRole) -> bool:
        """Return whether a User has a system role.

        :param user_id: User ID
        :param role: System role
        :return: Whether the assignment exists
        """
        async with self.session_manager() as session:
            return await self.system_role_repository.has_role(session, user_id, role)

    async def get_current_roles(self, user_id: str) -> CurrentSystemRolesOutput:
        """Return system roles assigned to one User.

        :param user_id: User ID
        :return: Current role projection
        """
        async with self.session_manager() as session:
            assignments = await self.system_role_repository.list_by_user(
                session,
                user_id,
            )
        return CurrentSystemRolesOutput(
            roles=[assignment.role for assignment in assignments]
        )

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> SystemUserRoleAssignmentListOutput:
        """List all system role assignments.

        :param offset: Record count to skip
        :param limit: Maximum record count
        :return: Assignment list
        """
        async with self.session_manager() as session:
            assignments = await self.system_role_repository.list_all(
                session,
                offset=offset,
                limit=limit,
            )
        return SystemUserRoleAssignmentListOutput(
            items=[
                SystemUserRoleAssignmentOutput.convert_from(assignment)
                for assignment in assignments.items
            ],
            total=assignments.total,
        )

    async def grant(
        self,
        user_id: str,
        role: SystemUserRole,
        *,
        granted_by_user_id: str | None,
        source: str,
    ) -> Result[SystemUserRoleAssignmentOutput, SystemUserNotFound]:
        """Grant a system role to an existing User.

        :param user_id: Target User ID
        :param role: System role
        :param granted_by_user_id: Granting User ID or None for operator authority
        :param source: Audit source
        :return: Assignment or target-not-found error
        """
        async with self.session_manager() as session:
            await self.system_role_repository.acquire_mutation_lock(session)
            user = await self.user_repository.get(session, user_id)
            if user is None:
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

        logger.info(
            "System role granted",
            extra={
                "target_user_id": user_id,
                "role": role.value,
                "granted_by_user_id": granted_by_user_id,
                "source": source,
                "assignment_created": existing is None,
            },
        )
        return Success(SystemUserRoleAssignmentOutput.convert_from(assignment))

    async def grant_by_email(
        self,
        email: str,
        role: SystemUserRole,
        *,
        source: str,
    ) -> Result[SystemUserRoleAssignmentOutput, SystemUserNotFound]:
        """Grant a system role to a User resolved by exact normalized email.

        :param email: Exact User email
        :param role: System role
        :param source: Audit source
        :return: Assignment or target-not-found error
        """
        normalized_email = email.strip().lower()
        async with self.session_manager() as session:
            user = await self.user_repository.get_by_email(session, normalized_email)
        if user is None:
            return Failure(SystemUserNotFound(user_id=normalized_email))
        return await self.grant(
            user.id,
            role,
            granted_by_user_id=None,
            source=source,
        )

    async def revoke(
        self,
        user_id: str,
        role: SystemUserRole,
        *,
        revoked_by_user_id: str,
    ) -> Result[None, SystemRoleAssignmentNotFound | LastSystemAdmin]:
        """Revoke a system role while preserving the final-admin invariant.

        :param user_id: Target User ID
        :param role: System role
        :param revoked_by_user_id: Acting User ID
        :return: Success or invariant/not-found error
        """
        async with self.session_manager() as session:
            await self.system_role_repository.acquire_mutation_lock(session)
            assignment = await self.system_role_repository.get(session, user_id, role)
            if assignment is None:
                return Failure(SystemRoleAssignmentNotFound(user_id=user_id, role=role))
            if role is SystemUserRole.SYSTEM_ADMIN:
                count = await self.system_role_repository.count_by_role(session, role)
                if count <= 1:
                    logger.warning(
                        "Final system administrator revocation denied",
                        extra={
                            "target_user_id": user_id,
                            "revoked_by_user_id": revoked_by_user_id,
                        },
                    )
                    return Failure(LastSystemAdmin(user_id=user_id))
            deleted = await self.system_role_repository.delete(session, user_id, role)
            if not deleted:
                return Failure(SystemRoleAssignmentNotFound(user_id=user_id, role=role))

        logger.info(
            "System role revoked",
            extra={
                "target_user_id": user_id,
                "role": role.value,
                "revoked_by_user_id": revoked_by_user_id,
            },
        )
        return Success(None)

    async def require_system_admin(self, user_id: str) -> bool:
        """Return whether a User is a system administrator.

        :param user_id: User ID
        :return: Whether the User is a system administrator
        """
        return await self.has_role(user_id, SystemUserRole.SYSTEM_ADMIN)
