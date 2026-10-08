"""WorkspaceInvitation service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.auth.deps import CurrentUser, WorkspaceMember
from azents.core.email.service import EmailService
from azents.core.enums import InvitationStatus, SignupTokenDeliveryMethod
from azents.repos.workspace_invitation.data import WorkspaceInvitationCreate
from azents.repos.workspace_invitation.operation_data import (
    AlreadyMember as RepositoryAlreadyMember,
)
from azents.repos.workspace_invitation.operation_data import (
    AlreadyProcessed as RepositoryAlreadyProcessed,
)
from azents.repos.workspace_invitation.operation_data import (
    InvitationNotFound as RepositoryInvitationNotFound,
)
from azents.repos.workspace_invitation.operations import (
    WorkspaceInvitationOperationRepository,
)
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
    """Orchestrate completed invitation operations and post-commit delivery."""

    operation_repo: Annotated[WorkspaceInvitationOperationRepository, Depends()]
    email_service: Annotated[EmailService, Depends()]
    signup_token_service: Annotated[SignupTokenService, Depends()]

    async def create(
        self, member: WorkspaceMember, invitation_input: CreateInvitationInput
    ) -> Result[InvitationOutput, AlreadyMember]:
        """Create or re-invite, then deliver after the database transaction closes."""
        email = invitation_input.email.lower().strip()
        result = await self.operation_repo.create(
            WorkspaceInvitationCreate(
                workspace_id=member.workspace_id,
                email=email,
                role=invitation_input.role,
                invited_by=member.workspace_user_id,
            )
        )
        match result:
            case Failure(RepositoryAlreadyMember(email=existing_email)):
                return Failure(AlreadyMember(email=existing_email))
            case Success(value):
                created = value
            case _:
                assert_never(result)
        workspace = await self.operation_repo.get_workspace(member.workspace_id)
        workspace_name = workspace.name if workspace else "Workspace"
        signup_url = None
        if created.needs_signup_token and self.email_service.configured:
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
            to_email=email, workspace_name=workspace_name, signup_url=signup_url
        )
        return Success(InvitationOutput.convert_from(created.invitation))

    async def list_received(
        self, current_user: CurrentUser
    ) -> ReceivedInvitationListOutput:
        """Fetch owned pending invitations with detached Workspace information."""
        received = await self.operation_repo.list_received(current_user.user_id)
        return ReceivedInvitationListOutput(
            items=[
                ReceivedInvitationOutput(
                    id=item.invitation.id,
                    workspace_id=item.invitation.workspace_id,
                    workspace_name=item.workspace.name,
                    workspace_handle=item.workspace.handle,
                    email=item.invitation.email,
                    role=item.invitation.role,
                    status=item.invitation.status,
                    created_at=item.invitation.created_at,
                )
                for item in received
            ]
        )

    async def accept(
        self, current_user: CurrentUser, invitation_id: str
    ) -> Result[AcceptDeclineOutput, InvitationNotFound | AlreadyProcessed]:
        """Accept an owned pending invitation and create membership atomically."""
        return await self._process(
            current_user, invitation_id, InvitationStatus.ACCEPTED
        )

    async def decline(
        self, current_user: CurrentUser, invitation_id: str
    ) -> Result[AcceptDeclineOutput, InvitationNotFound | AlreadyProcessed]:
        """Decline an owned pending invitation."""
        return await self._process(
            current_user, invitation_id, InvitationStatus.DECLINED
        )

    async def _process(
        self, current_user: CurrentUser, invitation_id: str, status: InvitationStatus
    ) -> Result[AcceptDeclineOutput, InvitationNotFound | AlreadyProcessed]:
        """Convert the completed repository outcome to the existing service contract."""
        result = await self.operation_repo.process(
            user_id=current_user.user_id, invitation_id=invitation_id, status=status
        )
        match result:
            case Success():
                return Success(AcceptDeclineOutput(id=invitation_id, status=status))
            case Failure(error):
                match error:
                    case RepositoryInvitationNotFound(invitation_id=missing_id):
                        return Failure(InvitationNotFound(invitation_id=missing_id))
                    case RepositoryAlreadyProcessed(
                        invitation_id=processed_id, status=processed_status
                    ):
                        return Failure(
                            AlreadyProcessed(
                                invitation_id=processed_id, status=processed_status
                            )
                        )
                    case _:
                        assert_never(error)
            case _:
                assert_never(result)

    async def list_by_workspace_handle(
        self, handle: str
    ) -> Result[InvitationListOutput, WorkspaceNotFound]:
        """Fetch Workspace invitations by handle."""
        result = await self.operation_repo.list_by_workspace_handle(handle)
        match result:
            case Success(value):
                return Success(
                    InvitationListOutput(
                        items=[
                            InvitationOutput.convert_from(item) for item in value.items
                        ]
                    )
                )
            case Failure(error):
                return Failure(WorkspaceNotFound(handle=error.handle))
            case _:
                assert_never(result)

    async def list_by_workspace(self, workspace_id: str) -> InvitationListOutput:
        """Fetch all invitations in a Workspace."""
        invitations = await self.operation_repo.list_by_workspace(workspace_id)
        return InvitationListOutput(
            items=[InvitationOutput.convert_from(item) for item in invitations.items]
        )

    async def delete(self, invitation_id: str) -> None:
        """Delete an invitation through a completed operation."""
        await self.operation_repo.delete(invitation_id)

    async def get_my_invitation(
        self, current_user: CurrentUser, workspace_handle: str
    ) -> Result[InvitationOutput | None, WorkspaceNotFound]:
        """Fetch the owned pending invitation for a Workspace."""
        result = await self.operation_repo.get_my_invitation(
            user_id=current_user.user_id, workspace_handle=workspace_handle
        )
        match result:
            case Success(value):
                return Success(
                    None if value is None else InvitationOutput.convert_from(value)
                )
            case Failure(error):
                return Failure(WorkspaceNotFound(handle=error.handle))
            case _:
                assert_never(result)
