"""Workspace repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from azcommon.sqlalchemy.postgres import is_constrained_by
from sqlalchemy.exc import IntegrityError

from azents.core.workspace import (
    HandleConflict,
    NotFound,
    WorkspaceCreate,
    WorkspaceUpdate,
)
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import ReadSession, WriteSession

from .data import (
    Workspace,
    WorkspaceList,
    WorkspaceRuntimeProfileDefaultReplace,
    WorkspaceSnapshot,
)


class WorkspaceRepository:
    """Workspace CRUD repository."""

    async def create(
        self, session: WriteSession, create: WorkspaceCreate
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
            session.write_session.add(rdb_workspace)
            await session.write_session.flush()
            return Success(self._build_workspace(rdb_workspace))
        except IntegrityError as e:
            await session.write_session.rollback()
            if is_constrained_by(e, RDBWorkspace.UQ_HANDLE):
                return Failure(HandleConflict(handle=create.handle))
            raise

    async def get_by_id(
        self, session: ReadSession, workspace_id: str
    ) -> Workspace | None:
        """Fetch Workspace by ID.

        :param session: Database session
        :param workspace_id: Workspace ID
        :return: Workspace or None
        """
        rdb_workspace = await session.read_session.get(RDBWorkspace, workspace_id)
        if rdb_workspace is None:
            return None
        return self._build_workspace(rdb_workspace)

    async def get_by_handle(
        self, session: ReadSession, handle: str
    ) -> Workspace | None:
        """Fetch Workspace by handle.

        :param session: Database session
        :param handle: Workspace handle
        :return: Workspace or None
        """
        result = await session.read_session.execute(
            sa.select(RDBWorkspace).where(RDBWorkspace.handle == handle)
        )
        rdb_workspace = result.scalar_one_or_none()
        if rdb_workspace is None:
            return None
        return self._build_workspace(rdb_workspace)

    async def get_with_id_by_handle(
        self, session: ReadSession, handle: str
    ) -> WorkspaceSnapshot | None:
        """Fetch one Workspace ID and projection from the same row read."""
        result = await session.read_session.execute(
            sa.select(RDBWorkspace).where(RDBWorkspace.handle == handle)
        )
        rdb_workspace = result.scalar_one_or_none()
        if rdb_workspace is None:
            return None
        return WorkspaceSnapshot(
            workspace_id=rdb_workspace.id,
            workspace=self._build_workspace(rdb_workspace),
        )

    async def acquire_ownership_mutation(
        self, session: WriteSession, workspace_id: str
    ) -> Workspace | None:
        """Serialize only Workspace OWNER creation/transfer through commit (E3)."""
        result = await session.write_session.execute(
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
        session: WriteSession,
        workspace_id: str,
        replacement: WorkspaceRuntimeProfileDefaultReplace,
    ) -> Workspace | None:
        """Replace the Workspace default with optimistic version fencing."""
        result = await session.write_session.execute(
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
        await session.write_session.flush()
        if rdb_workspace is None:
            return None
        return self._build_workspace(rdb_workspace)

    async def list_all(self, session: ReadSession) -> WorkspaceList:
        """Fetch all Workspaces.

        :param session: Database session
        :return: Workspace list
        """
        result = await session.read_session.execute(
            sa.select(RDBWorkspace).order_by(RDBWorkspace.created_at.desc())
        )
        rdb_workspaces = result.scalars().all()
        return WorkspaceList(items=[self._build_workspace(w) for w in rdb_workspaces])

    async def update_by_handle(
        self,
        session: WriteSession,
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
            result = await session.write_session.execute(
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
            await session.write_session.rollback()
            if is_constrained_by(e, RDBWorkspace.UQ_HANDLE):
                return Failure(HandleConflict(handle=update.get("handle", "")))
            raise

    async def resolve_id(self, session: ReadSession, handle: str) -> str | None:
        """Convert handle to internal ID.

        Return internal workspace ID for FK reference.

        :param session: Database session
        :param handle: Workspace handle
        :return: Internal Workspace ID or None
        """
        result = await session.read_session.execute(
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
