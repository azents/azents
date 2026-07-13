"""SystemUserRoleRepository tests."""

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import SystemUserRole
from azents.repos.system_user_role.data import SystemUserRoleAssignmentCreate
from azents.repos.system_user_role.repository import SystemUserRoleRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate


class TestSystemUserRoleRepository:
    """SystemUserRoleRepository tests."""

    async def test_assignment_lifecycle(self, rdb_session: AsyncSession) -> None:
        """Create, query, list, count, and delete one assignment."""
        user_repo = UserRepository()
        role_repo = SystemUserRoleRepository()
        granter = await user_repo.create(
            rdb_session,
            UserCreate(email="granter@example.com"),
        )
        target = await user_repo.create(
            rdb_session,
            UserCreate(email="target@example.com"),
        )

        await role_repo.acquire_mutation_lock(rdb_session)
        created = await role_repo.create(
            rdb_session,
            SystemUserRoleAssignmentCreate(
                user_id=target.id,
                role=SystemUserRole.SYSTEM_ADMIN,
                granted_by_user_id=granter.id,
            ),
        )

        assert created.user_id == target.id
        assert created.granted_by_user_id == granter.id
        assert await role_repo.has_role(
            rdb_session,
            target.id,
            SystemUserRole.SYSTEM_ADMIN,
        )
        assert (
            await role_repo.count_by_role(
                rdb_session,
                SystemUserRole.SYSTEM_ADMIN,
            )
            == 1
        )
        assert (await role_repo.list_by_user(rdb_session, target.id)) == [created]
        listed = await role_repo.list_all(rdb_session)
        assert listed.total == 1
        assert listed.items == [created]

        assert await role_repo.delete(
            rdb_session,
            target.id,
            SystemUserRole.SYSTEM_ADMIN,
        )
        assert not await role_repo.has_role(
            rdb_session,
            target.id,
            SystemUserRole.SYSTEM_ADMIN,
        )
