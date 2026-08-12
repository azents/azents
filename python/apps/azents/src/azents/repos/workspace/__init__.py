"""Workspace repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from azcommon.sqlalchemy.postgres import is_constrained_by
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.workspace import RDBWorkspace

from .data import (
    HandleConflict,
    NotFound,
    Workspace,
    WorkspaceCreate,
    WorkspaceList,
    WorkspaceRuntimeProfileDefaultReplace,
    WorkspaceUpdate,
)


class WorkspaceRepository:
    """Workspace CRUD repository."""

    async def create(
        self, session: AsyncSession, create: WorkspaceCreate
    ) -> Result[Workspace, HandleConflict]:
        """Create Workspace.

        :param session: Database session
        :param create: Create data
        :return: Created Workspace or duplicate handle error
        """
        try:
            rdb_workspace = RDBWorkspace(
                name=create.name,
                handle=create.handle,
            )
            session.add(rdb_workspace)
            await session.flush()
            return Success(self._build_workspace(rdb_workspace))
        except IntegrityError as e:
            await session.rollback()
            if is_constrained_by(e, RDBWorkspace.UQ_HANDLE):
                return Failure(HandleConflict(handle=create.handle))
            raise

    async def get_by_id(
        self, session: AsyncSession, workspace_id: str
    ) -> Workspace | None:
        """Fetch Workspace by ID.

        :param session: Database session
        :param workspace_id: Workspace ID
        :return: Workspace or None
        """
        rdb_workspace = await session.get(RDBWorkspace, workspace_id)
        if rdb_workspace is None:
            return None
        return self._build_workspace(rdb_workspace)

    async def get_by_handle(
        self, session: AsyncSession, handle: str
    ) -> Workspace | None:
        """Fetch Workspace by handle.

        :param session: Database session
        :param handle: Workspace handle
        :return: Workspace or None
        """
        result = await session.execute(
            sa.select(RDBWorkspace).where(RDBWorkspace.handle == handle)
        )
        rdb_workspace = result.scalar_one_or_none()
        if rdb_workspace is None:
            return None
        return self._build_workspace(rdb_workspace)

    async def get_with_id_by_handle(
        self, session: AsyncSession, handle: str
    ) -> tuple[str, Workspace] | None:
        """Fetch one Workspace ID and projection from the same row read."""
        result = await session.execute(
            sa.select(RDBWorkspace).where(RDBWorkspace.handle == handle)
        )
        rdb_workspace = result.scalar_one_or_none()
        if rdb_workspace is None:
            return None
        return rdb_workspace.id, self._build_workspace(rdb_workspace)

    async def get_by_id_for_update(
        self, session: AsyncSession, workspace_id: str
    ) -> Workspace | None:
        """Fetch and lock one Workspace."""
        result = await session.execute(
            sa.select(RDBWorkspace)
            .where(RDBWorkspace.id == workspace_id)
            .with_for_update()
        )
        rdb_workspace = result.scalar_one_or_none()
        if rdb_workspace is None:
            return None
        return self._build_workspace(rdb_workspace)

    async def replace_runtime_profile_default(
        self,
        session: AsyncSession,
        workspace_id: str,
        replacement: WorkspaceRuntimeProfileDefaultReplace,
    ) -> Workspace | None:
        """Replace the Workspace default with optimistic version fencing."""
        result = await session.execute(
            sa.update(RDBWorkspace)
            .where(
                RDBWorkspace.id == workspace_id,
                RDBWorkspace.default_runtime_profile_version
                == replacement.expected_version,
            )
            .values(
                default_runtime_profile_id=replacement.runtime_profile_id,
                default_runtime_profile_version=(
                    RDBWorkspace.default_runtime_profile_version + 1
                ),
                updated_at=sa.func.now(),
            )
            .returning(RDBWorkspace)
        )
        rdb_workspace = result.scalar_one_or_none()
        await session.flush()
        if rdb_workspace is None:
            return None
        return self._build_workspace(rdb_workspace)

    async def list_all(self, session: AsyncSession) -> WorkspaceList:
        """Fetch all Workspaces.

        :param session: Database session
        :return: Workspace list
        """
        result = await session.execute(
            sa.select(RDBWorkspace).order_by(RDBWorkspace.created_at.desc())
        )
        rdb_workspaces = result.scalars().all()
        return WorkspaceList(items=[self._build_workspace(w) for w in rdb_workspaces])

    async def update_by_handle(
        self,
        session: AsyncSession,
        handle: str,
        update: WorkspaceUpdate,
    ) -> Result[Workspace, NotFound | HandleConflict]:
        """Update Workspace by handle.

        :param session: Database session
        :param handle: Workspace handle
        :param update: Update data
        :return: Updated Workspace or error
        """
        if not update:
            workspace = await self.get_by_handle(session, handle)
            if workspace is None:
                return Failure(NotFound(handle=handle))
            return Success(workspace)

        try:
            result = await session.execute(
                sa.update(RDBWorkspace)
                .where(RDBWorkspace.handle == handle)
                .values(**update)
                .returning(RDBWorkspace)
            )
            rdb_workspace = result.scalar_one_or_none()
            if rdb_workspace is None:
                return Failure(NotFound(handle=handle))

            return Success(self._build_workspace(rdb_workspace))
        except IntegrityError as e:
            await session.rollback()
            if is_constrained_by(e, RDBWorkspace.UQ_HANDLE):
                return Failure(HandleConflict(handle=update.get("handle", "")))
            raise

    async def resolve_id(self, session: AsyncSession, handle: str) -> str | None:
        """Convert handle to internal ID.

        Return internal workspace ID for FK reference.

        :param session: Database session
        :param handle: Workspace handle
        :return: Internal Workspace ID or None
        """
        result = await session.execute(
            sa.select(RDBWorkspace.id).where(RDBWorkspace.handle == handle)
        )
        return result.scalar_one_or_none()

    def _build_workspace(self, rdb_workspace: RDBWorkspace) -> Workspace:
        """Convert RDBWorkspace to domain Workspace."""
        return Workspace(
            name=rdb_workspace.name,
            handle=rdb_workspace.handle,
            default_runtime_profile_id=rdb_workspace.default_runtime_profile_id,
            default_runtime_profile_version=(
                rdb_workspace.default_runtime_profile_version
            ),
            created_at=rdb_workspace.created_at,
            updated_at=rdb_workspace.updated_at,
        )
