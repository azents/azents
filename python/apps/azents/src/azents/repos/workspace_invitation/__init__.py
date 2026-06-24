"""WorkspaceInvitation repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import InvitationStatus
from azents.rdb.models.workspace_invitation import RDBWorkspaceInvitation

from .data import (
    NotFound,
    WorkspaceInvitation,
    WorkspaceInvitationCreate,
    WorkspaceInvitationList,
)


class WorkspaceInvitationRepository:
    """WorkspaceInvitation CRUD repository."""

    async def create_or_reinvite(
        self, session: AsyncSession, create: WorkspaceInvitationCreate
    ) -> WorkspaceInvitation:
        """Create or re-invite invitation.

        - Existing invitation absent: create new
        - Existing invitation present (pending/accepted/declined): update to pending

        Membership validation is handled in service layer, so re-inviting accepted
        invitations is allowed (supports re-invite after export).

        :param session: Database session
        :param create: Create data
        :return: Invitation
        """
        existing_rdb = await self._get_rdb_by_workspace_and_email(
            session, create.workspace_id, create.email
        )

        if existing_rdb is not None:
            existing_rdb.status = InvitationStatus.PENDING
            existing_rdb.role = create.role
            existing_rdb.invited_by = create.invited_by
            await session.flush()
            await session.refresh(existing_rdb)
            return self._build(existing_rdb)

        rdb_invitation = RDBWorkspaceInvitation(
            workspace_id=create.workspace_id,
            email=create.email,
            role=create.role,
            invited_by=create.invited_by,
        )
        session.add(rdb_invitation)
        await session.flush()
        return self._build(rdb_invitation)

    async def get(
        self, session: AsyncSession, invitation_id: str
    ) -> WorkspaceInvitation | None:
        """Fetch invitation by ID.

        :param session: Database session
        :param invitation_id: Invitation ID
        :return: Invitation or None
        """
        rdb = await session.get(RDBWorkspaceInvitation, invitation_id)
        if rdb is None:
            return None
        return self._build(rdb)

    async def list_by_workspace(
        self, session: AsyncSession, workspace_id: str
    ) -> WorkspaceInvitationList:
        """Fetch all invitations in workspace.

        :param session: Database session
        :param workspace_id: Workspace ID
        :return: Invitation list
        """
        result = await session.execute(
            sa.select(RDBWorkspaceInvitation)
            .where(RDBWorkspaceInvitation.workspace_id == workspace_id)
            .order_by(RDBWorkspaceInvitation.created_at.desc())
        )
        items = result.scalars().all()
        return WorkspaceInvitationList(items=[self._build(r) for r in items])

    async def list_pending_by_emails(
        self, session: AsyncSession, emails: list[str]
    ) -> WorkspaceInvitationList:
        """Fetch pending invitations by email list.

        :param session: Database session
        :param emails: Email address list
        :return: Pending invitation list
        """
        if not emails:
            return WorkspaceInvitationList(items=[])

        result = await session.execute(
            sa.select(RDBWorkspaceInvitation)
            .where(
                RDBWorkspaceInvitation.email.in_(emails),
                RDBWorkspaceInvitation.status == InvitationStatus.PENDING,
            )
            .order_by(RDBWorkspaceInvitation.created_at.desc())
        )
        items = result.scalars().all()
        return WorkspaceInvitationList(items=[self._build(r) for r in items])

    async def update_status(
        self, session: AsyncSession, invitation_id: str, status: InvitationStatus
    ) -> Result[WorkspaceInvitation, NotFound]:
        """Change invitation status.

        :param session: Database session
        :param invitation_id: Invitation ID
        :param status: Status to change
        :return: Changed invitation or error
        """
        result = await session.execute(
            sa.update(RDBWorkspaceInvitation)
            .where(RDBWorkspaceInvitation.id == invitation_id)
            .values(status=status)
            .returning(RDBWorkspaceInvitation)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return Failure(NotFound(invitation_id=invitation_id))
        return Success(self._build(rdb))

    async def delete(self, session: AsyncSession, invitation_id: str) -> None:
        """Delete invitation.

        :param session: Database session
        :param invitation_id: Invitation ID
        """
        await session.execute(
            sa.delete(RDBWorkspaceInvitation).where(
                RDBWorkspaceInvitation.id == invitation_id
            )
        )

    async def _get_rdb_by_workspace_and_email(
        self, session: AsyncSession, workspace_id: str, email: str
    ) -> RDBWorkspaceInvitation | None:
        """Fetch RDB model by workspace + email."""
        result = await session.execute(
            sa.select(RDBWorkspaceInvitation).where(
                RDBWorkspaceInvitation.workspace_id == workspace_id,
                RDBWorkspaceInvitation.email == email,
            )
        )
        return result.scalar_one_or_none()

    def _build(self, rdb: RDBWorkspaceInvitation) -> WorkspaceInvitation:
        """Convert RDBWorkspaceInvitation to domain model."""
        return WorkspaceInvitation(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            email=rdb.email,
            role=rdb.role,
            invited_by=rdb.invited_by,
            status=rdb.status,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )
