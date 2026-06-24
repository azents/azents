"""WorkspaceJoinRequest repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from azcommon.uuid import uuid7
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import JoinRequestStatus
from azents.rdb.models.workspace_join_request import RDBWorkspaceJoinRequest

from .data import (
    NotFound,
    WorkspaceJoinRequest,
    WorkspaceJoinRequestCreate,
    WorkspaceJoinRequestList,
    WorkspaceJoinRequestUpdate,
)


class WorkspaceJoinRequestRepository:
    """WorkspaceJoinRequest CRUD repository."""

    async def create_or_rerequest(
        self, session: AsyncSession, create: WorkspaceJoinRequestCreate
    ) -> WorkspaceJoinRequest:
        """Create or re-request join request (PostgreSQL ON CONFLICT).

        - Existing request absent: create new (status=pending)
        - Existing request present: update to pending + update message

        pending validation is handled in service layer.

        :param session: Database session
        :param create: Create data
        :return: Join request
        """
        message = create.get("message")
        stmt = insert(RDBWorkspaceJoinRequest).values(
            id=uuid7().hex,
            workspace_id=create["workspace_id"],
            user_id=create["user_id"],
            message=message,
            status=JoinRequestStatus.PENDING,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_workspace_join_requests_workspace_user",
            set_={
                "status": JoinRequestStatus.PENDING,
                "message": message,
                "updated_at": sa.func.now(),
            },
        ).returning(RDBWorkspaceJoinRequest)
        result = await session.execute(stmt)
        rdb = result.scalar_one()
        return self._build(rdb)

    async def get(
        self, session: AsyncSession, join_request_id: str
    ) -> WorkspaceJoinRequest | None:
        """Fetch join request by ID.

        :param session: Database session
        :param join_request_id: Join request ID
        :return: Join request or None
        """
        rdb = await session.get(RDBWorkspaceJoinRequest, join_request_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def get_by_workspace_and_user(
        self, session: AsyncSession, workspace_id: str, user_id: str
    ) -> WorkspaceJoinRequest | None:
        """Workspace ID + User Fetch join request by ID.

        :param session: Database session
        :param workspace_id: Workspace ID
        :param user_id: User ID
        :return: Join request or None
        """
        result = await session.execute(
            sa.select(RDBWorkspaceJoinRequest).where(
                RDBWorkspaceJoinRequest.workspace_id == workspace_id,
                RDBWorkspaceJoinRequest.user_id == user_id,
            )
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        return self._build(rdb)

    async def list_by_workspace(
        self,
        session: AsyncSession,
        workspace_id: str,
        *,
        status: JoinRequestStatus | None = None,
    ) -> WorkspaceJoinRequestList:
        """Fetch join request list for workspace.

        :param session: Database session
        :param workspace_id: Workspace ID
        :param status: Status to filter (all when None)
        :return: Join request list
        """
        stmt = sa.select(RDBWorkspaceJoinRequest).where(
            RDBWorkspaceJoinRequest.workspace_id == workspace_id
        )
        if status is not None:
            stmt = stmt.where(RDBWorkspaceJoinRequest.status == status)
        stmt = stmt.order_by(RDBWorkspaceJoinRequest.created_at.desc())

        result = await session.execute(stmt)
        items = result.scalars().all()
        return WorkspaceJoinRequestList(
            items=[self._build(r) for r in items],
            total=len(items),
        )

    async def update(
        self,
        session: AsyncSession,
        join_request_id: str,
        update: WorkspaceJoinRequestUpdate,
    ) -> Result[WorkspaceJoinRequest, NotFound]:
        """Update join request.

        :param session: Database session
        :param join_request_id: Join request ID
        :param update: Update data
        :return: Updated join request or error
        """
        if not update:
            existing = await self.get(session, join_request_id)
            if existing is None:
                return Failure(NotFound(join_request_id=join_request_id))
            return Success(existing)

        result = await session.execute(
            sa.update(RDBWorkspaceJoinRequest)
            .where(RDBWorkspaceJoinRequest.id == join_request_id)
            .values(**update)
            .returning(RDBWorkspaceJoinRequest)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return Failure(NotFound(join_request_id=join_request_id))
        return Success(self._build(rdb))

    async def delete(self, session: AsyncSession, join_request_id: str) -> None:
        """Delete join request.

        :param session: Database session
        :param join_request_id: Join request ID
        """
        await session.execute(
            sa.delete(RDBWorkspaceJoinRequest).where(
                RDBWorkspaceJoinRequest.id == join_request_id
            )
        )

    def _build(self, rdb: RDBWorkspaceJoinRequest) -> WorkspaceJoinRequest:
        """Convert RDBWorkspaceJoinRequest to domain model."""
        return WorkspaceJoinRequest(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            user_id=rdb.user_id,
            message=rdb.message,
            status=rdb.status,
            last_notified_at=rdb.last_notified_at,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
