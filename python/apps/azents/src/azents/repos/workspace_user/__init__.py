"""WorkspaceUser repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import WorkspaceUserRole
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser

from .data import (
    NotFound,
    WorkspaceNotFound,
    WorkspaceUser,
    WorkspaceUserCreate,
    WorkspaceUserList,
    WorkspaceUserUpdate,
)


class WorkspaceUserRepository:
    """WorkspaceUser CRUD repository."""

    async def create(
        self, session: AsyncSession, create: WorkspaceUserCreate
    ) -> Result[WorkspaceUser, WorkspaceNotFound]:
        """Create WorkspaceUser.

        :param session: Database session
        :param create: Create data
        :return: Created WorkspaceUser or error
        """
        workspace = await session.get(RDBWorkspace, create.workspace_id)
        if workspace is None:
            return Failure(WorkspaceNotFound(workspace_id=create.workspace_id))

        rdb_workspace_user = RDBWorkspaceUser(
            workspace_id=create.workspace_id,
            user_id=create.user_id,
            name=create.name,
            role=create.role,
        )
        session.add(rdb_workspace_user)
        await session.flush()
        return Success(self._build_workspace_user(rdb_workspace_user))

    async def get(
        self, session: AsyncSession, workspace_user_id: str
    ) -> WorkspaceUser | None:
        """Fetch WorkspaceUser by ID.

        :param session: Database session
        :param workspace_user_id: WorkspaceUser ID
        :return: WorkspaceUser or None
        """
        rdb_workspace_user = await session.get(RDBWorkspaceUser, workspace_user_id)
        if rdb_workspace_user is None:
            return None
        return self._build_workspace_user(rdb_workspace_user)

    async def list_by_workspace(
        self, session: AsyncSession, workspace_id: str
    ) -> WorkspaceUserList:
        """Fetch WorkspaceUsers in Workspace.

        :param session: Database session
        :param workspace_id: Workspace ID
        :return: WorkspaceUser list
        """
        result = await session.execute(
            sa.select(RDBWorkspaceUser)
            .where(RDBWorkspaceUser.workspace_id == workspace_id)
            .order_by(RDBWorkspaceUser.created_at.desc())
        )
        rdb_workspace_users = result.scalars().all()
        return WorkspaceUserList(
            items=[self._build_workspace_user(u) for u in rdb_workspace_users]
        )

    async def update(
        self,
        session: AsyncSession,
        workspace_user_id: str,
        update: WorkspaceUserUpdate,
    ) -> Result[WorkspaceUser, NotFound]:
        """Update WorkspaceUser.

        :param session: Database session
        :param workspace_user_id: WorkspaceUser ID
        :param update: Update data
        :return: Updated WorkspaceUser or error
        """
        if not update:
            workspace_user = await self.get(session, workspace_user_id)
            if workspace_user is None:
                return Failure(NotFound(workspace_user_id=workspace_user_id))
            return Success(workspace_user)

        result = await session.execute(
            sa.update(RDBWorkspaceUser)
            .where(RDBWorkspaceUser.id == workspace_user_id)
            .values(**update)
            .returning(RDBWorkspaceUser)
        )
        rdb_workspace_user = result.scalar_one_or_none()
        if rdb_workspace_user is None:
            return Failure(NotFound(workspace_user_id=workspace_user_id))

        return Success(self._build_workspace_user(rdb_workspace_user))

    async def update_role(
        self,
        session: AsyncSession,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[WorkspaceUser, NotFound]:
        """Change role of WorkspaceUser.

        :param session: Database session
        :param workspace_user_id: WorkspaceUser ID
        :param role: Role to change
        :return: Updated WorkspaceUser or error
        """
        result = await session.execute(
            sa.update(RDBWorkspaceUser)
            .where(RDBWorkspaceUser.id == workspace_user_id)
            .values(role=role)
            .returning(RDBWorkspaceUser)
        )
        rdb_workspace_user = result.scalars().first()
        if rdb_workspace_user is None:
            return Failure(NotFound(workspace_user_id=workspace_user_id))
        return Success(self._build_workspace_user(rdb_workspace_user))

    async def get_by_workspace_and_user(
        self, session: AsyncSession, workspace_id: str, user_id: str
    ) -> WorkspaceUser | None:
        """Workspace ID + User Fetch WorkspaceUser by ID.

        :param session: Database session
        :param workspace_id: Workspace ID
        :param user_id: User ID
        :return: WorkspaceUser or None
        """
        result = await session.execute(
            sa.select(RDBWorkspaceUser).where(
                RDBWorkspaceUser.workspace_id == workspace_id,
                RDBWorkspaceUser.user_id == user_id,
            )
        )
        rdb_workspace_user = result.scalar_one_or_none()
        if rdb_workspace_user is None:
            return None
        return self._build_workspace_user(rdb_workspace_user)

    async def lock_by_workspace_and_user(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceUser | None:
        """Lock one Workspace membership for transactional authorization."""
        result = await session.execute(
            sa.select(RDBWorkspaceUser)
            .where(
                RDBWorkspaceUser.workspace_id == workspace_id,
                RDBWorkspaceUser.user_id == user_id,
            )
            .with_for_update()
        )
        rdb_workspace_user = result.scalar_one_or_none()
        if rdb_workspace_user is None:
            return None
        return self._build_workspace_user(rdb_workspace_user)

    async def list_by_user(
        self, session: AsyncSession, user_id: str
    ) -> WorkspaceUserList:
        """User Fetch WorkspaceUser by ID.

        :param session: Database session
        :param user_id: User ID
        :return: WorkspaceUser list
        """
        result = await session.execute(
            sa.select(RDBWorkspaceUser)
            .where(RDBWorkspaceUser.user_id == user_id)
            .order_by(RDBWorkspaceUser.created_at.desc())
        )
        rdb_workspace_users = result.scalars().all()
        return WorkspaceUserList(
            items=[self._build_workspace_user(u) for u in rdb_workspace_users]
        )

    async def get_owner_by_workspace(
        self, session: AsyncSession, workspace_id: str
    ) -> WorkspaceUser | None:
        """Fetch Owner of Workspace.

        :param session: Database session
        :param workspace_id: Workspace ID
        :return: Owner WorkspaceUser or None
        """
        result = await session.execute(
            sa.select(RDBWorkspaceUser).where(
                RDBWorkspaceUser.workspace_id == workspace_id,
                RDBWorkspaceUser.role == WorkspaceUserRole.OWNER,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_workspace_user(rdb)

    async def delete(self, session: AsyncSession, workspace_user_id: str) -> None:
        """Delete WorkspaceUser.

        :param session: Database session
        :param workspace_user_id: WorkspaceUser ID
        """
        await session.execute(
            sa.delete(RDBWorkspaceUser).where(RDBWorkspaceUser.id == workspace_user_id)
        )

    def _build_workspace_user(
        self, rdb_workspace_user: RDBWorkspaceUser
    ) -> WorkspaceUser:
        """Convert RDBWorkspaceUser to domain WorkspaceUser."""
        return WorkspaceUser(
            id=rdb_workspace_user.id,
            workspace_id=rdb_workspace_user.workspace_id,
            user_id=rdb_workspace_user.user_id,
            name=rdb_workspace_user.name,
            role=rdb_workspace_user.role,
            created_at=rdb_workspace_user.created_at,
            updated_at=rdb_workspace_user.updated_at,
        )
