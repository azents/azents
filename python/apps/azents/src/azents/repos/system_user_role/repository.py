"""System User role repository."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import SystemUserRole
from azents.rdb.models.system_user_role import RDBSystemUserRole

from .data import (
    SystemUserRoleAssignment,
    SystemUserRoleAssignmentCreate,
    SystemUserRoleAssignmentList,
)

_SYSTEM_ROLE_MUTATION_LOCK_ID = 0x617A656E7473


class SystemUserRoleRepository:
    """Instance-wide User role assignment repository."""

    async def acquire_mutation_lock(self, session: AsyncSession) -> None:
        """Serialize system role mutations for final-admin enforcement.

        :param session: Database session
        """
        await session.execute(
            sa.select(sa.func.pg_advisory_xact_lock(_SYSTEM_ROLE_MUTATION_LOCK_ID))
        )

    async def get(
        self,
        session: AsyncSession,
        user_id: str,
        role: SystemUserRole,
    ) -> SystemUserRoleAssignment | None:
        """Fetch one role assignment.

        :param session: Database session
        :param user_id: Assigned User ID
        :param role: System role
        :return: Assignment or None
        """
        rdb_assignment = await session.get(RDBSystemUserRole, (user_id, role))
        if rdb_assignment is None:
            return None
        return self._build(rdb_assignment)

    async def has_role(
        self,
        session: AsyncSession,
        user_id: str,
        role: SystemUserRole,
    ) -> bool:
        """Return whether a User has a system role.

        :param session: Database session
        :param user_id: User ID
        :param role: System role
        :return: Whether assignment exists
        """
        result = await session.execute(
            sa.select(sa.literal(True)).where(
                sa.exists().where(
                    RDBSystemUserRole.user_id == user_id,
                    RDBSystemUserRole.role == role,
                )
            )
        )
        return result.scalar_one_or_none() is True

    async def list_by_user(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> list[SystemUserRoleAssignment]:
        """List assignments for a User.

        :param session: Database session
        :param user_id: User ID
        :return: Role assignments
        """
        result = await session.execute(
            sa.select(RDBSystemUserRole)
            .where(RDBSystemUserRole.user_id == user_id)
            .order_by(RDBSystemUserRole.role)
        )
        return [self._build(item) for item in result.scalars().all()]

    async def list_all(
        self,
        session: AsyncSession,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> SystemUserRoleAssignmentList:
        """List all system role assignments.

        :param session: Database session
        :param offset: Record count to skip
        :param limit: Maximum record count
        :return: Assignment list
        """
        total_result = await session.execute(
            sa.select(sa.func.count()).select_from(RDBSystemUserRole)
        )
        result = await session.execute(
            sa.select(RDBSystemUserRole)
            .order_by(RDBSystemUserRole.granted_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return SystemUserRoleAssignmentList(
            items=[self._build(item) for item in result.scalars().all()],
            total=total_result.scalar_one(),
        )

    async def count_by_role(
        self,
        session: AsyncSession,
        role: SystemUserRole,
    ) -> int:
        """Count assignments for a role.

        :param session: Database session
        :param role: System role
        :return: Assignment count
        """
        result = await session.execute(
            sa.select(sa.func.count())
            .select_from(RDBSystemUserRole)
            .where(RDBSystemUserRole.role == role)
        )
        return result.scalar_one()

    async def create(
        self,
        session: AsyncSession,
        create: SystemUserRoleAssignmentCreate,
    ) -> SystemUserRoleAssignment:
        """Create a role assignment.

        :param session: Database session
        :param create: Assignment data
        :return: Created assignment
        """
        rdb_assignment = RDBSystemUserRole(
            user_id=create.user_id,
            role=create.role,
            granted_by_user_id=create.granted_by_user_id,
        )
        session.add(rdb_assignment)
        await session.flush()
        await session.refresh(rdb_assignment)
        return self._build(rdb_assignment)

    async def delete(
        self,
        session: AsyncSession,
        user_id: str,
        role: SystemUserRole,
    ) -> bool:
        """Delete a role assignment.

        :param session: Database session
        :param user_id: Assigned User ID
        :param role: System role
        :return: Whether an assignment was deleted
        """
        result = await session.execute(
            sa.delete(RDBSystemUserRole)
            .where(
                RDBSystemUserRole.user_id == user_id,
                RDBSystemUserRole.role == role,
            )
            .returning(RDBSystemUserRole.user_id)
        )
        return result.scalar_one_or_none() is not None

    def _build(self, assignment: RDBSystemUserRole) -> SystemUserRoleAssignment:
        """Convert a database assignment to a domain model."""
        return SystemUserRoleAssignment.model_validate(
            assignment,
            from_attributes=True,
        )
