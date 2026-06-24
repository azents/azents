"""Session Workspace Project repository."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import SessionWorkspaceProjectRegistrationRequestStatus
from azents.rdb.models.session_workspace_project import (
    RDBSessionWorkspaceProject,
    RDBSessionWorkspaceProjectRegistrationRequest,
)

from .data import (
    SessionWorkspaceProject,
    SessionWorkspaceProjectCreate,
    SessionWorkspaceProjectRegistrationRequest,
    SessionWorkspaceProjectRegistrationRequestCreate,
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
            agent_runtime_id=create.agent_runtime_id,
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
        agent_runtime_id: str,
        path: str,
    ) -> SessionWorkspaceProject | None:
        """Fetch Project by AgentRuntime and path."""
        result = await session.execute(
            sa.select(RDBSessionWorkspaceProject).where(
                RDBSessionWorkspaceProject.agent_runtime_id == agent_runtime_id,
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
        agent_runtime_id: str,
    ) -> list[SessionWorkspaceProject]:
        """Fetch Project list of AgentRuntime ordered by path."""
        result = await session.execute(
            sa.select(RDBSessionWorkspaceProject)
            .where(RDBSessionWorkspaceProject.agent_runtime_id == agent_runtime_id)
            .order_by(RDBSessionWorkspaceProject.path)
        )
        return [self._build_project(rdb) for rdb in result.scalars()]

    async def delete_project(
        self,
        session: AsyncSession,
        project_id: str,
        *,
        agent_runtime_id: str,
    ) -> bool:
        """Delete Project row."""
        result = await session.execute(
            sa.delete(RDBSessionWorkspaceProject).where(
                RDBSessionWorkspaceProject.id == project_id,
                RDBSessionWorkspaceProject.agent_runtime_id == agent_runtime_id,
            )
        )
        await session.flush()
        return result.rowcount > 0  # pyright: ignore[reportAttributeAccessIssue]  # SQLAlchemy CursorResult.rowcount returns int at runtime.

    async def create_registration_request(
        self,
        session: AsyncSession,
        create: SessionWorkspaceProjectRegistrationRequestCreate,
    ) -> SessionWorkspaceProjectRegistrationRequest:
        """Create Project registration request row."""
        rdb = RDBSessionWorkspaceProjectRegistrationRequest(
            agent_runtime_id=create.agent_runtime_id,
            path=create.path,
            reason=create.reason,
        )
        session.add(rdb)
        await session.flush()
        await session.refresh(rdb)
        return self._build_registration_request(rdb)

    async def get_registration_request_by_id(
        self,
        session: AsyncSession,
        request_id: str,
    ) -> SessionWorkspaceProjectRegistrationRequest | None:
        """Fetch Project registration request by ID."""
        rdb = await session.get(
            RDBSessionWorkspaceProjectRegistrationRequest,
            request_id,
        )
        if rdb is None:
            return None
        return self._build_registration_request(rdb)

    async def get_registration_request_by_id_for_update(
        self,
        session: AsyncSession,
        request_id: str,
    ) -> SessionWorkspaceProjectRegistrationRequest | None:
        """Fetch registration request by ID with row lock."""
        result = await session.execute(
            sa.select(RDBSessionWorkspaceProjectRegistrationRequest)
            .where(RDBSessionWorkspaceProjectRegistrationRequest.id == request_id)
            .with_for_update()
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_registration_request(rdb)

    async def get_pending_registration_request_by_path(
        self,
        session: AsyncSession,
        *,
        agent_runtime_id: str,
        path: str,
    ) -> SessionWorkspaceProjectRegistrationRequest | None:
        """Fetch pending registration request with same path."""
        result = await session.execute(
            sa.select(RDBSessionWorkspaceProjectRegistrationRequest).where(
                RDBSessionWorkspaceProjectRegistrationRequest.agent_runtime_id
                == agent_runtime_id,
                RDBSessionWorkspaceProjectRegistrationRequest.path == path,
                RDBSessionWorkspaceProjectRegistrationRequest.status
                == SessionWorkspaceProjectRegistrationRequestStatus.PENDING,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build_registration_request(rdb)

    async def list_registration_requests(
        self,
        session: AsyncSession,
        *,
        agent_runtime_id: str,
    ) -> list[SessionWorkspaceProjectRegistrationRequest]:
        """Fetch Project registration request list for AgentRuntime."""
        result = await session.execute(
            sa.select(RDBSessionWorkspaceProjectRegistrationRequest)
            .where(
                RDBSessionWorkspaceProjectRegistrationRequest.agent_runtime_id
                == agent_runtime_id
            )
            .order_by(RDBSessionWorkspaceProjectRegistrationRequest.created_at)
        )
        return [self._build_registration_request(rdb) for rdb in result.scalars()]

    async def mark_registration_request_approved(
        self,
        session: AsyncSession,
        request_id: str,
        *,
        agent_runtime_id: str,
        project_id: str,
    ) -> bool:
        """Transition Registration request to approved state."""
        result = await session.execute(
            sa.update(RDBSessionWorkspaceProjectRegistrationRequest)
            .where(
                RDBSessionWorkspaceProjectRegistrationRequest.id == request_id,
                RDBSessionWorkspaceProjectRegistrationRequest.agent_runtime_id
                == agent_runtime_id,
                RDBSessionWorkspaceProjectRegistrationRequest.status
                == SessionWorkspaceProjectRegistrationRequestStatus.PENDING,
            )
            .values(
                status=SessionWorkspaceProjectRegistrationRequestStatus.APPROVED,
                project_id=project_id,
            )
        )
        await session.flush()
        return result.rowcount > 0  # pyright: ignore[reportAttributeAccessIssue]  # SQLAlchemy CursorResult.rowcount returns int at runtime.

    async def mark_registration_request_rejected(
        self,
        session: AsyncSession,
        request_id: str,
        *,
        agent_runtime_id: str,
    ) -> bool:
        """Transition Registration request to rejected state."""
        result = await session.execute(
            sa.update(RDBSessionWorkspaceProjectRegistrationRequest)
            .where(
                RDBSessionWorkspaceProjectRegistrationRequest.id == request_id,
                RDBSessionWorkspaceProjectRegistrationRequest.agent_runtime_id
                == agent_runtime_id,
                RDBSessionWorkspaceProjectRegistrationRequest.status
                == SessionWorkspaceProjectRegistrationRequestStatus.PENDING,
            )
            .values(status=SessionWorkspaceProjectRegistrationRequestStatus.REJECTED)
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
            agent_runtime_id=rdb.agent_runtime_id,
            path=rdb.path,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    def _build_registration_request(
        self,
        rdb: RDBSessionWorkspaceProjectRegistrationRequest,
    ) -> SessionWorkspaceProjectRegistrationRequest:
        """Convert RDB registration request row to domain model."""
        return SessionWorkspaceProjectRegistrationRequest(
            id=rdb.id,
            agent_runtime_id=rdb.agent_runtime_id,
            path=rdb.path,
            reason=rdb.reason,
            status=rdb.status,
            project_id=rdb.project_id,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
