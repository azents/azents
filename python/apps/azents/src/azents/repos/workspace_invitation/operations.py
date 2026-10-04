"""Complete database operations for Workspace invitations."""

from dataclasses import dataclass
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.enums import InvitationStatus, JoinRequestStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.user_email import UserEmailRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import Workspace
from azents.repos.workspace_invitation import WorkspaceInvitationRepository
from azents.repos.workspace_invitation.data import (
    WorkspaceInvitation,
    WorkspaceInvitationCreate,
    WorkspaceInvitationList,
)
from azents.repos.workspace_invitation.operation_data import (
    AlreadyMember,
    AlreadyProcessed,
    CreatedInvitation,
    InvitationNotFound,
    ReceivedInvitation,
    WorkspaceNotFound,
)
from azents.repos.workspace_join_request import WorkspaceJoinRequestRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate


@dataclass
class WorkspaceInvitationOperationRepository:
    """Compose invitation database work without exposing live sessions."""

    invitation_repo: Annotated[WorkspaceInvitationRepository, Depends()]
    workspace_repo: Annotated[WorkspaceRepository, Depends()]
    workspace_user_repo: Annotated[WorkspaceUserRepository, Depends()]
    user_email_repo: Annotated[UserEmailRepository, Depends()]
    join_request_repo: Annotated[WorkspaceJoinRequestRepository, Depends()]
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]

    async def create(
        self, create: WorkspaceInvitationCreate
    ) -> Result[CreatedInvitation, AlreadyMember]:
        """Commit invitation and any pending-request autoapproval atomically."""
        async with self.session_manager() as session:
            user_email = await self.user_email_repo.get_by_email(session, create.email)
            if user_email is not None:
                existing_member = (
                    await self.workspace_user_repo.get_by_workspace_and_user(
                        session, create.workspace_id, user_email.user_id
                    )
                )
                if existing_member is not None:
                    return Failure(AlreadyMember(email=create.email))
                pending = await self.join_request_repo.get_by_workspace_and_user(
                    session, create.workspace_id, user_email.user_id
                )
                if pending is not None and pending.status == JoinRequestStatus.PENDING:
                    await self.workspace_user_repo.create(
                        session,
                        WorkspaceUserCreate(
                            workspace_id=create.workspace_id,
                            user_id=user_email.user_id,
                            name=create.email.split("@")[0],
                            role=create.role,
                        ),
                    )
                    await self.join_request_repo.delete(session, pending.id)
            invitation = await self.invitation_repo.create_or_reinvite(session, create)
            return Success(
                CreatedInvitation(
                    invitation=invitation, needs_signup_token=user_email is None
                )
            )

    async def list_received(self, user_id: str) -> list[ReceivedInvitation]:
        """Read pending invitations and Workspace metadata in one completed scope."""
        async with self.session_manager() as session:
            emails = await self.user_email_repo.list_by_user(session, user_id)
            invitations = await self.invitation_repo.list_pending_by_emails(
                session, [email.email for email in emails]
            )
            received: list[ReceivedInvitation] = []
            for invitation in invitations.items:
                workspace = await self.workspace_repo.get_by_id(
                    session, invitation.workspace_id
                )
                if workspace is not None:
                    received.append(
                        ReceivedInvitation(invitation=invitation, workspace=workspace)
                    )
            return received

    async def process(
        self, *, user_id: str, invitation_id: str, status: InvitationStatus
    ) -> Result[WorkspaceInvitation, InvitationNotFound | AlreadyProcessed]:
        """Validate email ownership and commit acceptance or decline."""
        async with self.session_manager() as session:
            invitation = await self.invitation_repo.get(session, invitation_id)
            if invitation is None:
                return Failure(InvitationNotFound(invitation_id=invitation_id))
            emails = await self.user_email_repo.list_by_user(session, user_id)
            if invitation.email not in {email.email for email in emails}:
                return Failure(InvitationNotFound(invitation_id=invitation_id))
            if invitation.status != InvitationStatus.PENDING:
                return Failure(
                    AlreadyProcessed(
                        invitation_id=invitation_id, status=invitation.status
                    )
                )
            if status == InvitationStatus.ACCEPTED:
                await self.workspace_user_repo.create(
                    session,
                    WorkspaceUserCreate(
                        workspace_id=invitation.workspace_id,
                        user_id=user_id,
                        name=invitation.email.split("@")[0],
                        role=invitation.role,
                    ),
                )
            result = await self.invitation_repo.update_status(
                session, invitation_id, status
            )
            match result:
                case Success(value):
                    return Success(value)
                case Failure():
                    # An absent final row must not leave a membership-only commit.
                    await session.write_session.rollback()
                    return Failure(InvitationNotFound(invitation_id=invitation_id))
                case _:
                    assert_never(result)

    async def list_by_workspace_handle(
        self, handle: str
    ) -> Result[WorkspaceInvitationList, WorkspaceNotFound]:
        """Resolve the Workspace and read invitations in one completed scope."""
        async with self.session_manager() as session:
            workspace_id = await self.workspace_repo.resolve_id(session, handle)
            if workspace_id is None:
                return Failure(WorkspaceNotFound(handle=handle))
            return Success(
                await self.invitation_repo.list_by_workspace(session, workspace_id)
            )

    async def list_by_workspace(self, workspace_id: str) -> WorkspaceInvitationList:
        """Read Workspace invitations in a completed scope."""
        async with self.session_manager() as session:
            return await self.invitation_repo.list_by_workspace(session, workspace_id)

    async def delete(self, invitation_id: str) -> None:
        """Delete an invitation in a completed transaction."""
        async with self.session_manager() as session:
            await self.invitation_repo.delete(session, invitation_id)

    async def get_my_invitation(
        self, *, user_id: str, workspace_handle: str
    ) -> Result[WorkspaceInvitation | None, WorkspaceNotFound]:
        """Resolve the Workspace and owned pending invitation together."""
        async with self.session_manager() as session:
            workspace_id = await self.workspace_repo.resolve_id(
                session, workspace_handle
            )
            if workspace_id is None:
                return Failure(WorkspaceNotFound(handle=workspace_handle))
            emails = await self.user_email_repo.list_by_user(session, user_id)
            invitations = await self.invitation_repo.list_pending_by_emails(
                session, [email.email for email in emails]
            )
            for invitation in invitations.items:
                if invitation.workspace_id == workspace_id:
                    return Success(invitation)
            return Success(None)

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        """Read detached Workspace metadata for post-commit delivery."""
        async with self.session_manager() as session:
            return await self.workspace_repo.get_by_id(session, workspace_id)
