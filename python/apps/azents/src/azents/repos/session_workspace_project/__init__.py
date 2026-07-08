"""Session Workspace Project repository."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import (
    RDBSessionAgentContext,
    RDBSessionAgentContextProject,
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
        context_id = await self._get_context_id_by_session_id(
            session,
            session_id=create.session_id,
        )
        rdb = RDBSessionAgentContextProject(
            session_agent_context_id=context_id,
            path=create.path,
        )
        session.add(rdb)
        await session.flush()
        await session.refresh(rdb)
        return self._build_project(rdb, session_id=create.session_id)

    async def get_project_by_id(
        self,
        session: AsyncSession,
        project_id: str,
    ) -> SessionWorkspaceProject | None:
        """Fetch Project by ID."""
        result = await session.execute(
            sa.select(
                RDBSessionAgentContextProject,
                RDBSessionAgent.agent_session_id,
            )
            .join(
                RDBSessionAgentContext,
                RDBSessionAgentContext.id
                == RDBSessionAgentContextProject.session_agent_context_id,
            )
            .join(
                RDBSessionAgent,
                RDBSessionAgent.id == RDBSessionAgentContext.root_session_agent_id,
            )
            .where(RDBSessionAgentContextProject.id == project_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        rdb, session_id = row
        return self._build_project(rdb, session_id=session_id)

    async def get_project_by_path(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        path: str,
    ) -> SessionWorkspaceProject | None:
        """Fetch Project by AgentSession and path."""
        context_id = await self._get_context_id_by_session_id(
            session,
            session_id=session_id,
        )
        result = await session.execute(
            sa.select(RDBSessionAgentContextProject).where(
                RDBSessionAgentContextProject.session_agent_context_id == context_id,
                RDBSessionAgentContextProject.path == path,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_project(rdb, session_id=session_id)

    async def list_projects(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> list[SessionWorkspaceProject]:
        """Fetch Project list of AgentSession ordered by path."""
        context_id = await self._get_context_id_by_session_id(
            session,
            session_id=session_id,
        )
        result = await session.execute(
            sa.select(RDBSessionAgentContextProject)
            .where(RDBSessionAgentContextProject.session_agent_context_id == context_id)
            .order_by(RDBSessionAgentContextProject.path)
        )
        return [
            self._build_project(rdb, session_id=session_id) for rdb in result.scalars()
        ]

    async def delete_project(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        session_id: str,
    ) -> bool:
        """Delete Project row."""
        context_id = await self._get_context_id_by_session_id(
            session,
            session_id=session_id,
        )
        result = await session.execute(
            sa.delete(RDBSessionAgentContextProject).where(
                RDBSessionAgentContextProject.id == project_id,
                RDBSessionAgentContextProject.session_agent_context_id == context_id,
            )
        )
        await session.flush()
        return result.rowcount > 0  # pyright: ignore[reportAttributeAccessIssue]  # SQLAlchemy CursorResult.rowcount returns int at runtime.

    async def _get_context_id_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> str:
        """Fetch SessionAgentContext ID for an AgentSession."""
        result = await session.execute(
            sa.select(RDBSessionAgent.context_id).where(
                RDBSessionAgent.agent_session_id == session_id,
            )
        )
        context_id = result.scalar_one_or_none()
        if context_id is None:
            raise ValueError("SessionAgentContext not found for AgentSession")
        return context_id

    def _build_project(
        self,
        rdb: RDBSessionAgentContextProject,
        *,
        session_id: str,
    ) -> SessionWorkspaceProject:
        """Convert RDB Project row to domain model."""
        return SessionWorkspaceProject(
            id=rdb.id,
            session_id=session_id,
            session_agent_context_id=rdb.session_agent_context_id,
            path=rdb.path,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
