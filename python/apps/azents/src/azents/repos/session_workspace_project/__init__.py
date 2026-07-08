"""Session Workspace Project repository."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.session_workspace_project import (
    RDBSessionWorkspaceProject,
)

from .data import (
    SessionWorkspaceProject,
    SessionWorkspaceProjectCreate,
)


class SessionWorkspaceProjectRepository:
    """Session Workspace Project CRUD repository."""

    async def create_project(
        self,
        session: AsyncSession,
        create: SessionWorkspaceProjectCreate,
    ) -> SessionWorkspaceProject:
        """Create Project row."""
        rdb = RDBSessionWorkspaceProject(
            session_id=create.session_id,
            path=create.path,
        )
        session.add(rdb)
        await session.flush()
        await session.refresh(rdb)
        return self._build_project(rdb)

    async def get_project_by_id(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> SessionWorkspaceProject | None:
        """Fetch Project by ID."""
        rdb = await session.get(RDBSessionWorkspaceProject, project_id)
        if rdb is None:
            return None
        return self._build_project(rdb)

    async def get_project_by_path(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        path: str,
    ) -> SessionWorkspaceProject | None:
        """Fetch Project by AgentSession and path."""
        result = await session.execute(
            sa.select(RDBSessionWorkspaceProject).where(
                RDBSessionWorkspaceProject.session_id == session_id,
                RDBSessionWorkspaceProject.path == path,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_project(rdb)

    async def list_projects(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> list[SessionWorkspaceProject]:
        """Fetch Project list of AgentSession ordered by path."""
        result = await session.execute(
            sa.select(RDBSessionWorkspaceProject)
            .where(RDBSessionWorkspaceProject.session_id == session_id)
            .order_by(RDBSessionWorkspaceProject.path)
        )
        return [self._build_project(rdb) for rdb in result.scalars()]

    async def delete_project(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        session_id: str,
    ) -> bool:
        """Delete Project row."""
        result = await session.execute(
            sa.delete(RDBSessionWorkspaceProject).where(
                RDBSessionWorkspaceProject.id == project_id,
                RDBSessionWorkspaceProject.session_id == session_id,
            )
        )
        await session.flush()
        return result.rowcount > 0  # pyright: ignore[reportAttributeAccessIssue]  # SQLAlchemy CursorResult.rowcount returns int at runtime.

    def _build_project(
        self,
        rdb: RDBSessionWorkspaceProject,
    ) -> SessionWorkspaceProject:
        """Convert RDB Project row to domain model."""
        return SessionWorkspaceProject(
            id=rdb.id,
            session_id=rdb.session_id,
            path=rdb.path,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
