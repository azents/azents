"""System User role repository."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from azents.core.enums import SystemUserRole
from azents.rdb.models.system_user_role import RDBSystemUserRole
from azents.rdb.models.user import RDBUser
from azents.rdb.session_capabilities import ReadSession, WriteSession

from .data import (
    SystemUserRoleAssignment,
    SystemUserRoleAssignmentCreate,
    SystemUserRoleAssignmentList,
)

_SYSTEM_ROLE_MUTATION_LOCK_ID = 0x617A656E7473


class SystemUserRoleRepository:
    """Instance-wide User role assignment repository."""

    async def acquire_mutation_lock(self, session: WriteSession) -> None:
        """Serialize only final-administrator removal and account deletion (E3).

        :param session: Database session
        """
        await session.write_session.execute(
            sa.select(sa.func.pg_advisory_xact_lock(_SYSTEM_ROLE_MUTATION_LOCK_ID))
        )

    async def get(
        self,
        session: ReadSession,
        user_id: str,
        role: SystemUserRole,
    ) -> SystemUserRoleAssignment | None:
        """Fetch one role assignment.

        :param session: Database session
        :param user_id: Assigned User ID
        :param role: System role
        :return: Assignment or None
        """
        rdb_assignment = await session.read_session.get(
            RDBSystemUserRole, (user_id, role)
        )
        if rdb_assignment is None:
            return None
        return self._build(rdb_assignment)

    async def has_role(
        self,
        session: ReadSession,
        user_id: str,
        role: SystemUserRole,
    ) -> bool:
        """Return whether a User has a system role.

        :param session: Database session
        :param user_id: User ID
        :param role: System role
        :return: Whether assignment exists
        """
        result = await session.read_session.execute(
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
        session: ReadSession,
        user_id: str,
    ) -> list[SystemUserRoleAssignment]:
        """List assignments for a User.

        :param session: Database session
        :param user_id: User ID
        :return: Role assignments
        """
        result = await session.read_session.execute(
            sa.select(RDBSystemUserRole)
            .where(RDBSystemUserRole.user_id == user_id)
            .order_by(RDBSystemUserRole.role)
        )
        return [self._build(item) for item in result.scalars().all()]

    async def list_all(
        self,
        session: ReadSession,
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
        total_result = await session.read_session.execute(
            sa.select(sa.func.count()).select_from(RDBSystemUserRole)
        )
        result = await session.read_session.execute(
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
        session: ReadSession,
        role: SystemUserRole,
    ) -> int:
        """Count assignments for a role.

        :param session: Database session
        :param role: System role
        :return: Assignment count
        """
        result = await session.read_session.execute(
            sa.select(sa.func.count())
            .select_from(RDBSystemUserRole)
            .join(RDBUser, RDBUser.id == RDBSystemUserRole.user_id)
            .where(RDBSystemUserRole.role == role, RDBUser.access_disabled_at.is_(None))
        )
        return result.scalar_one()

    async def create(
        self,
        session: WriteSession,
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
        session.write_session.add(rdb_assignment)
        await session.write_session.flush()
        await session.write_session.refresh(rdb_assignment)
        return self._build(rdb_assignment)

    async def claim_assignment_mutation(
        self,
        session: WriteSession,
        user_id: str,
        role: SystemUserRole,
    ) -> None:
        """Coordinate only grant/revoke of this exact assignment result (E3)."""
        key = f"system-role-assignment:{user_id}:{role.value}"
        await session.write_session.execute(
            sa.select(sa.func.pg_advisory_xact_lock(sa.func.hashtextextended(key, 0)))
        )

    async def admit_active_user_grant(
        self, session: WriteSession, user_id: str
    ) -> bool:
        """Fence actual role issuance against concurrent disable-and-role-sweep (E3)."""
        row = await session.write_session.scalar(
            sa.select(RDBUser.id)
            .where(RDBUser.id == user_id, RDBUser.access_disabled_at.is_(None))
            .with_for_update(read=True)
        )
        return row is not None

    async def create_if_absent(
        self, session: WriteSession, create: SystemUserRoleAssignmentCreate
    ) -> SystemUserRoleAssignment | None:
        """Use assignment uniqueness for ordinary grants, without a revoke gate."""
        row = await session.write_session.scalar(
            insert(RDBSystemUserRole)
            .values(
                user_id=create.user_id,
                role=create.role,
                granted_by_user_id=create.granted_by_user_id,
            )
            .on_conflict_do_nothing(
                index_elements=[RDBSystemUserRole.user_id, RDBSystemUserRole.role]
            )
            .returning(RDBSystemUserRole)
        )
        return None if row is None else self._build(row)

    async def delete(
        self,
        session: WriteSession,
        user_id: str,
        role: SystemUserRole,
    ) -> bool:
        """Delete a role assignment.

        :param session: Database session
        :param user_id: Assigned User ID
        :param role: System role
        :return: Whether an assignment was deleted
        """
        result = await session.write_session.execute(
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
