"""Invitation v1 Public API.

Workspace invitation create, received-list, accept, and reject endpoints.
"""

from textwrap import dedent
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, status

from azents.core.auth.deps import (
    CurrentUser,
    WorkspaceMember,
    get_current_user,
    get_workspace_member,
)
from azents.core.auth.permissions import Permissions
from azents.services.workspace_invitation import WorkspaceInvitationService
from azents.services.workspace_invitation.data import (
    AlreadyMember,
    AlreadyProcessed,
    CreateInvitationInput,
    InvitationNotFound,
    WorkspaceNotFound,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    AcceptDeclineResponse,
    CreateInvitationRequest,
    InvitationListResponse,
    InvitationResponse,
    ReceivedInvitationListResponse,
    ReceivedInvitationResponse,
)

router = APIRouter()


@router.post(
    "/workspaces/{handle}/invitations",
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    invitation_service: Annotated[WorkspaceInvitationService, Depends()],
    request_body: CreateInvitationRequest,
) -> InvitationResponse:
    """Invite a user to a workspace.

    Requires manager-or-higher permission. Handles new invitations, re-inviting
    rejected invitations, and resending emails for pending invitations.
    """
    if not member.has_permission(Permissions.WORKSPACE_INVITATIONS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No invitation permission.",
        )

    result = await invitation_service.create(
        member=member,
        invitation_input=CreateInvitationInput(
            email=request_body.email,
            role=request_body.role,
        ),
    )
    match result:
        case Success(value):
            return InvitationResponse.convert_from(value)
        case Failure(error):
            match error:
                case AlreadyMember():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Already a workspace member.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/workspaces/{handle}/invitations/me")
async def get_my_invitation(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    invitation_service: Annotated[WorkspaceInvitationService, Depends()],
    *,
    handle: str,
) -> InvitationResponse | None:
    """Get my invitation for the workspace.

    Non-members can also call this.
    """
    result = await invitation_service.get_my_invitation(current_user, handle)
    match result:
        case Success(value):
            if value is None:
                return None
            return InvitationResponse.convert_from(value)
        case Failure(error):
            match error:
                case WorkspaceNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Workspace not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/invitations/received")
async def list_received_invitations(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    invitation_service: Annotated[WorkspaceInvitationService, Depends()],
) -> ReceivedInvitationListResponse:
    """List pending invitations received by the current user."""
    output = await invitation_service.list_received(current_user)
    return ReceivedInvitationListResponse(
        items=[ReceivedInvitationResponse.convert_from(item) for item in output.items]
    )


@router.post("/invitations/{invitation_id}/accept")
async def accept_invitation(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    invitation_service: Annotated[WorkspaceInvitationService, Depends()],
    *,
    invitation_id: str,
) -> AcceptDeclineResponse:
    """Accept an invitation."""
    result = await invitation_service.accept(current_user, invitation_id)
    match result:
        case Success(value):
            return AcceptDeclineResponse.convert_from(value)
        case Failure(error):
            match error:
                case InvitationNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Invitation not found.",
                    )
                case AlreadyProcessed():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Invitation is already processed.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post("/invitations/{invitation_id}/decline")
async def decline_invitation(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    invitation_service: Annotated[WorkspaceInvitationService, Depends()],
    *,
    invitation_id: str,
) -> AcceptDeclineResponse:
    """Reject an invitation."""
    result = await invitation_service.decline(current_user, invitation_id)
    match result:
        case Success(value):
            return AcceptDeclineResponse.convert_from(value)
        case Failure(error):
            match error:
                case InvitationNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Invitation not found.",
                    )
                case AlreadyProcessed():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Invitation is already processed.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/workspaces/{handle}/invitations")
async def list_workspace_invitations(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    invitation_service: Annotated[WorkspaceInvitationService, Depends()],
) -> InvitationListResponse:
    """List invitations for a workspace.

    Requires manager-or-higher permission.
    """
    if not member.has_permission(Permissions.WORKSPACE_INVITATIONS_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No invitation read permission.",
        )

    invitations = await invitation_service.list_by_workspace(member.workspace_id)
    return InvitationListResponse(
        items=[InvitationResponse.convert_from(inv) for inv in invitations.items]
    )


@router.delete(
    "/workspaces/{handle}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_invitation(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    invitation_service: Annotated[WorkspaceInvitationService, Depends()],
    *,
    invitation_id: str,
) -> None:
    """Cancel an invitation.

    Requires manager-or-higher permission.
    """
    if not member.has_permission(Permissions.WORKSPACE_INVITATIONS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No invitation cancel permission.",
        )

    await invitation_service.delete(invitation_id)


def mount(mounter: RouteMounter) -> None:
    """Mount Invitation v1 routes."""
    mounter(
        router,
        prefix="/invitation/v1",
        tag="Invitation v1",
        description=dedent(
            """
            Workspace Invitation API (Public)

            Workspace invitation create, received-list, accept, and reject endpoints.
            """
        ),
    )
