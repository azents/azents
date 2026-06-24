"""Invitation v1 Admin API.

Workspace invitation lookup/delete endpoints.
"""

from textwrap import dedent
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, status

from azents.services.workspace_invitation import WorkspaceInvitationService
from azents.services.workspace_invitation.data import WorkspaceNotFound
from azents.utils.fastapi.route import RouteMounter

from .data import InvitationListResponse, InvitationResponse

router = APIRouter()


@router.get("/workspaces/{handle}/invitations")
async def list_workspace_invitations(
    invitation_service: Annotated[WorkspaceInvitationService, Depends()],
    *,
    handle: str,
) -> InvitationListResponse:
    """List workspace invitations."""
    result = await invitation_service.list_by_workspace_handle(handle)
    match result:
        case Success(invitations):
            return InvitationListResponse(
                items=[
                    InvitationResponse.convert_from(inv) for inv in invitations.items
                ]
            )
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


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invitation(
    invitation_service: Annotated[WorkspaceInvitationService, Depends()],
    *,
    invitation_id: str,
) -> None:
    """Delete an invitation, cancelling it."""
    await invitation_service.delete(invitation_id)


def mount(mounter: RouteMounter) -> None:
    """Mount Invitation v1 routes."""
    mounter(
        router,
        prefix="/invitation/v1",
        tag="Invitation v1",
        description=dedent(
            """
            Workspace Invitation API (Admin)

            Workspace invitation lookup/delete endpoints.
            """
        ),
    )
