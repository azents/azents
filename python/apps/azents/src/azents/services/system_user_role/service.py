"""Instance-wide User role service over completed repository operations."""

import dataclasses
import logging
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.enums import SystemUserRole
from azents.core.system_user_role import (
    LastSystemAdmin,
    SystemRoleAssignmentNotFound,
    SystemUserNotFound,
)
from azents.repos.system_user_role.operations import SystemUserRoleOperationRepository

from .data import (
    CurrentSystemRolesOutput,
    SystemUserRoleAssignmentListOutput,
    SystemUserRoleAssignmentOutput,
)

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class SystemUserRoleService:
    """Project current roles and publish audit logs after completed mutations."""

    repository: Annotated[SystemUserRoleOperationRepository, Depends()]

    async def has_role(self, user_id: str, role: SystemUserRole) -> bool:
        """Return whether a User currently has one system role."""
        return await self.repository.has_role(user_id, role)

    async def get_current_roles(self, user_id: str) -> CurrentSystemRolesOutput:
        """Return roles assigned to one User."""
        assignments = await self.repository.list_by_user(user_id)
        return CurrentSystemRolesOutput(
            roles=[assignment.role for assignment in assignments]
        )

    async def list_all(
        self, *, offset: int = 0, limit: int = 50
    ) -> SystemUserRoleAssignmentListOutput:
        """List all role assignments with the existing count and order."""
        assignments = await self.repository.list_all(offset=offset, limit=limit)
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
        """Grant a role to an enabled User with current mutation authority."""
        result = await self.repository.grant(
            user_id, role, granted_by_user_id=granted_by_user_id
        )
        if isinstance(result, Failure):
            return Failure(result.error)
        outcome = result.value
        logger.info(
            "System role granted",
            extra={
                "target_user_id": user_id,
                "role": role.value,
                "granted_by_user_id": granted_by_user_id,
                "source": source,
                "assignment_created": outcome.created,
            },
        )
        return Success(SystemUserRoleAssignmentOutput.convert_from(outcome.assignment))

    async def grant_by_email(
        self, email: str, role: SystemUserRole, *, source: str
    ) -> Result[SystemUserRoleAssignmentOutput, SystemUserNotFound]:
        """Resolve exact normalized email before the separate locked grant."""
        normalized_email = email.strip().lower()
        user = await self.repository.get_user_by_email(normalized_email)
        if user is None:
            return Failure(SystemUserNotFound(user_id=normalized_email))
        return await self.grant(user.id, role, granted_by_user_id=None, source=source)

    async def revoke(
        self,
        user_id: str,
        role: SystemUserRole,
        *,
        revoked_by_user_id: str,
    ) -> Result[None, SystemRoleAssignmentNotFound | LastSystemAdmin]:
        """Revoke a role while preserving the final-administrator invariant."""
        result = await self.repository.revoke(user_id, role)
        if isinstance(result, Failure):
            if isinstance(result.error, LastSystemAdmin):
                logger.warning(
                    "Final system administrator revocation denied",
                    extra={
                        "target_user_id": user_id,
                        "revoked_by_user_id": revoked_by_user_id,
                    },
                )
            return Failure(result.error)
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
        """Return whether a User currently has system-administrator authority."""
        return await self.has_role(user_id, SystemUserRole.SYSTEM_ADMIN)
