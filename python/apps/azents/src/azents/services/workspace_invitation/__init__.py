"""WorkspaceInvitation service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.auth.deps import CurrentUser, WorkspaceMember
from azents.core.email.service import EmailService
from azents.core.enums import InvitationStatus, SignupTokenDeliveryMethod
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.user_email import UserEmailRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import Workspace
from azents.repos.workspace_invitation import WorkspaceInvitationRepository
from azents.repos.workspace_invitation.data import WorkspaceInvitationCreate
from azents.repos.workspace_join_request import WorkspaceJoinRequestRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate
from azents.services.signup_token import SignupTokenService
from azents.services.signup_token.data import CreateSignupTokenInput

from .data import (
    AcceptDeclineOutput,
    AlreadyMember,
    AlreadyProcessed,
    CreateInvitationInput,
    InvitationListOutput,
    InvitationNotFound,
    InvitationOutput,
    ReceivedInvitationListOutput,
    ReceivedInvitationOutput,
    WorkspaceNotFound,
)


@dataclasses.dataclass
class WorkspaceInvitationService:
    """Workspace invitation service."""

    invitation_repo: Annotated[WorkspaceInvitationRepository, Depends()]
    workspace_repo: Annotated[WorkspaceRepository, Depends()]
    workspace_user_repo: Annotated[WorkspaceUserRepository, Depends()]
    user_email_repo: Annotated[UserEmailRepository, Depends()]
    join_request_repo: Annotated[WorkspaceJoinRequestRepository, Depends()]
    email_service: Annotated[EmailService, Depends()]
    signup_token_service: Annotated[SignupTokenService, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def create(
        self,
        member: WorkspaceMember,
        invitation_input: CreateInvitationInput,
    ) -> Result[
        InvitationOutput,
        AlreadyMember,
    ]:
        """Create or re-invite invitation and send email.

        - New invitation: create + send email
        - declined/accepted invitation: update to pending + send email
        - pending invitation: update role/invited_by + resend email

        Also supports re-invite after export/delete.

        :param member: Current workspace member (manager or above)
        :param invitation_input: Invitation create input
        :return: Invitation or error
        """
        email = invitation_input.email.lower().strip()

        needs_signup_token = False
        async with self.session_manager() as session:
            # Check whether already member
            user_email = await self.user_email_repo.get_by_email(session, email)
            if user_email is None:
                needs_signup_token = True
            else:
                existing_member = (
                    await self.workspace_user_repo.get_by_workspace_and_user(
                        session, member.workspace_id, user_email.user_id
                    )
                )
                if existing_member is not None:
                    return Failure(AlreadyMember(email=email))

                # Auto-approve if pending join request exists
                pending_jr = await self.join_request_repo.get_by_workspace_and_user(
                    session, member.workspace_id, user_email.user_id
                )
                if pending_jr is not None and pending_jr.status.value == "pending":
                    await self.workspace_user_repo.create(
                        session,
                        WorkspaceUserCreate(
                            workspace_id=member.workspace_id,
                            user_id=user_email.user_id,
                            name=email.split("@")[0],
                            role=invitation_input.role,
                        ),
                    )
                    await self.join_request_repo.delete(session, pending_jr.id)

            # Create or re-invite invitation
            invitation = await self.invitation_repo.create_or_reinvite(
                session,
                WorkspaceInvitationCreate(
                    workspace_id=member.workspace_id,
                    email=email,
                    role=invitation_input.role,
                    invited_by=member.workspace_user_id,
                ),
            )

        # Send email (invitation remains valid even on failure)
        workspace = await self._get_workspace_by_id(member.workspace_id)
        workspace_name = workspace.name if workspace else "Workspace"
        signup_url = None
        if needs_signup_token and self.email_service.configured:
            signup_token = await self.signup_token_service.create(
                CreateSignupTokenInput(
                    email=email,
                    created_by_user_id=member.user_id,
                    delivery_method=SignupTokenDeliveryMethod.EMAIL,
                    expires_at=None,
                    max_uses=None,
                )
            )
            signup_url = self.signup_token_service.build_signup_url(
                signup_token.plaintext_token
            )
        await self.email_service.send_invitation(
            to_email=email,
            workspace_name=workspace_name,
            signup_url=signup_url,
        )
        return Success(InvitationOutput.convert_from(invitation))

    async def list_received(
        self, current_user: CurrentUser
    ) -> ReceivedInvitationListOutput:
        """Fetch pending invitation list received by current user.

        :param current_user: Current authenticated user
        :return: Received invitation list (including workspace info)
        """
        async with self.session_manager() as session:
            # Fetch email list of user
            user_emails = await self.user_email_repo.list_by_user(
                session, current_user.user_id
            )
            emails = [ue.email for ue in user_emails]

            # Fetch pending invitations sent to those emails
            invitations = await self.invitation_repo.list_pending_by_emails(
                session, emails
            )

            # Return with workspace info
            items: list[ReceivedInvitationOutput] = []
            for inv in invitations.items:
                workspace = await self.workspace_repo.get_by_id(
                    session, inv.workspace_id
                )
                if workspace is not None:
                    items.append(
                        ReceivedInvitationOutput(
                            id=inv.id,
                            workspace_id=inv.workspace_id,
                            workspace_name=workspace.name,
                            workspace_handle=workspace.handle,
                            email=inv.email,
                            role=inv.role,
                            status=inv.status,
                            created_at=inv.created_at,
                        )
                    )

        return ReceivedInvitationListOutput(items=items)

    async def accept(
        self, current_user: CurrentUser, invitation_id: str
    ) -> Result[
        AcceptDeclineOutput,
        InvitationNotFound | AlreadyProcessed,
    ]:
        """Accept invitation.

        :param current_user: Current authenticated user
        :param invitation_id: Invitation ID
        :return: Accept result or error
        """
        async with self.session_manager() as session:
            invitation = await self.invitation_repo.get(session, invitation_id)
            if invitation is None:
                return Failure(InvitationNotFound(invitation_id=invitation_id))

            # Check email ownership (treat as 404 if not owned by user)
            user_emails = await self.user_email_repo.list_by_user(
                session, current_user.user_id
            )
            user_email_addresses = {ue.email for ue in user_emails}
            if invitation.email not in user_email_addresses:
                return Failure(InvitationNotFound(invitation_id=invitation_id))

            if invitation.status != InvitationStatus.PENDING:
                return Failure(
                    AlreadyProcessed(
                        invitation_id=invitation_id, status=invitation.status
                    )
                )

            # Create WorkspaceUser
            await self.workspace_user_repo.create(
                session,
                WorkspaceUserCreate(
                    workspace_id=invitation.workspace_id,
                    user_id=current_user.user_id,
                    name=invitation.email.split("@")[0],
                    role=invitation.role,
                ),
            )

            # Change invitation status
            update_result = await self.invitation_repo.update_status(
                session, invitation_id, InvitationStatus.ACCEPTED
            )

        match update_result:
            case Success():
                return Success(
                    AcceptDeclineOutput(
                        id=invitation_id, status=InvitationStatus.ACCEPTED
                    )
                )
            case Failure():
                return Failure(InvitationNotFound(invitation_id=invitation_id))
            case _:
                assert_never(update_result)

    async def decline(
        self, current_user: CurrentUser, invitation_id: str
    ) -> Result[
        AcceptDeclineOutput,
        InvitationNotFound | AlreadyProcessed,
    ]:
        """Decline invitation.

        :param current_user: Current authenticated user
        :param invitation_id: Invitation ID
        :return: Decline result or error
        """
        async with self.session_manager() as session:
            invitation = await self.invitation_repo.get(session, invitation_id)
            if invitation is None:
                return Failure(InvitationNotFound(invitation_id=invitation_id))

            # Check email ownership (treat as 404 if not owned by user)
            user_emails = await self.user_email_repo.list_by_user(
                session, current_user.user_id
            )
            user_email_addresses = {ue.email for ue in user_emails}
            if invitation.email not in user_email_addresses:
                return Failure(InvitationNotFound(invitation_id=invitation_id))

            if invitation.status != InvitationStatus.PENDING:
                return Failure(
                    AlreadyProcessed(
                        invitation_id=invitation_id, status=invitation.status
                    )
                )

            # Change invitation status
            update_result = await self.invitation_repo.update_status(
                session, invitation_id, InvitationStatus.DECLINED
            )

        match update_result:
            case Success():
                return Success(
                    AcceptDeclineOutput(
                        id=invitation_id, status=InvitationStatus.DECLINED
                    )
                )
            case Failure():
                return Failure(InvitationNotFound(invitation_id=invitation_id))
            case _:
                assert_never(update_result)

    async def list_by_workspace_handle(
        self, handle: str
    ) -> Result[InvitationListOutput, WorkspaceNotFound]:
        """Fetch workspace by handle, then return invitation list.

        :param handle: Workspace handle
        :return: Invitation list or Workspace not found error
        """
        async with self.session_manager() as session:
            workspace_id = await self.workspace_repo.resolve_id(session, handle)
        if workspace_id is None:
            return Failure(WorkspaceNotFound(handle=handle))

        return Success(await self.list_by_workspace(workspace_id))

    async def list_by_workspace(self, workspace_id: str) -> InvitationListOutput:
        """Fetch all invitations of workspace.

        :param workspace_id: Workspace ID
        :return: Invitation list
        """
        async with self.session_manager() as session:
            invitations = await self.invitation_repo.list_by_workspace(
                session, workspace_id
            )
        return InvitationListOutput(
            items=[InvitationOutput.convert_from(inv) for inv in invitations.items]
        )

    async def delete(self, invitation_id: str) -> None:
        """Delete invitation.

        :param invitation_id: Invitation ID
        """
        async with self.session_manager() as session:
            await self.invitation_repo.delete(session, invitation_id)

    async def get_my_invitation(
        self,
        current_user: CurrentUser,
        workspace_handle: str,
    ) -> Result[InvitationOutput | None, WorkspaceNotFound]:
        """Fetch my invitation for the workspace.

        :param current_user: Current authenticated user
        :param workspace_handle: Workspace handle
        :return: pending invitation or None
        """
        async with self.session_manager() as session:
            workspace_id = await self.workspace_repo.resolve_id(
                session, workspace_handle
            )
            if workspace_id is None:
                return Failure(WorkspaceNotFound(handle=workspace_handle))

            # Fetch email list of user
            user_emails = await self.user_email_repo.list_by_user(
                session, current_user.user_id
            )
            emails = [ue.email for ue in user_emails]

            # Fetch pending invitations sent to those emails
            invitations = await self.invitation_repo.list_pending_by_emails(
                session, emails
            )

        # Filter only invitations for that workspace
        for inv in invitations.items:
            if inv.workspace_id == workspace_id:
                return Success(InvitationOutput.convert_from(inv))

        return Success(None)

    async def _get_workspace_by_id(self, workspace_id: str) -> Workspace | None:
        """Fetch workspace by Workspace ID."""
        async with self.session_manager() as session:
            return await self.workspace_repo.get_by_id(session, workspace_id)
