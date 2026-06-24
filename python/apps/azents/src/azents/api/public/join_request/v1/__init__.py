"""JoinRequest v1 Public API.

Workspace join request create, list, approve, reject, mute, and delete endpoints.
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
from azents.services.workspace_join_request import (
    WorkspaceJoinRequestService,
)
from azents.services.workspace_join_request.data import (
    AlreadyMember,
    JoinRequestNotFound,
    PendingRequestExists,
    WorkspaceNotFound,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    CreateJoinRequestRequest,
    JoinRequestListResponse,
    JoinRequestResponse,
    MyJoinRequestResponse,
)

router = APIRouter()


@router.post(
    "/workspaces/{handle}/join-requests",
    status_code=status.HTTP_201_CREATED,
)
async def create_join_request(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    join_request_service: Annotated[WorkspaceJoinRequestService, Depends()],
    request_body: CreateJoinRequestRequest,
    *,
    handle: str,
) -> JoinRequestResponse:
    """Request to join a workspace.

    Any logged-in user can request this, including non-members.
    """
    result = await join_request_service.request_join(
        user_id=current_user.user_id,
        workspace_handle=handle,
        message=request_body.message,
    )
    match result:
        case Success(value):
            return JoinRequestResponse.model_validate(value, from_attributes=True)
        case Failure(error):
            match error:
                case WorkspaceNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Workspace not found.",
                    )
                case AlreadyMember():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Already a workspace member.",
                    )
                case PendingRequestExists():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="A pending join request already exists.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/workspaces/{handle}/join-requests/me")
async def get_my_join_request(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    join_request_service: Annotated[WorkspaceJoinRequestService, Depends()],
    *,
    handle: str,
) -> MyJoinRequestResponse | None:
    """Get my join request status."""
    result = await join_request_service.get_my_request(
        user_id=current_user.user_id,
        workspace_handle=handle,
    )
    match result:
        case Success(value):
            if value is None:
                return None
            return MyJoinRequestResponse.model_validate(value, from_attributes=True)
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


@router.get("/workspaces/{handle}/join-requests")
async def list_join_requests(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    join_request_service: Annotated[WorkspaceJoinRequestService, Depends()],
) -> JoinRequestListResponse:
    """List join requests for a workspace.

    Requires manager-or-higher permission.
    """
    if not member.has_permission(Permissions.WORKSPACE_JOIN_REQUESTS_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied.",
        )

    output = await join_request_service.list_by_workspace(member.workspace_id)
    return JoinRequestListResponse(
        items=[
            JoinRequestResponse.model_validate(r, from_attributes=True)
            for r in output.items
        ],
        total=output.total,
    )


@router.post("/workspaces/{handle}/join-requests/{join_request_id}/approve")
async def approve_join_request(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    join_request_service: Annotated[WorkspaceJoinRequestService, Depends()],
    *,
    join_request_id: str,
) -> None:
    """Approve a join request.

    Requires manager-or-higher permission.
    """
    if not member.has_permission(Permissions.WORKSPACE_JOIN_REQUESTS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied.",
        )

    result = await join_request_service.approve(join_request_id)
    match result:
        case Success():
            return
        case Failure(error):
            match error:
                case JoinRequestNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Join request not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post("/workspaces/{handle}/join-requests/{join_request_id}/reject")
async def reject_join_request(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    join_request_service: Annotated[WorkspaceJoinRequestService, Depends()],
    *,
    join_request_id: str,
) -> None:
    """Reject a join request.

    Requires manager-or-higher permission.
    """
    if not member.has_permission(Permissions.WORKSPACE_JOIN_REQUESTS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied.",
        )

    result = await join_request_service.reject(join_request_id)
    match result:
        case Success():
            return
        case Failure(error):
            match error:
                case JoinRequestNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Join request not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post("/workspaces/{handle}/join-requests/{join_request_id}/mute")
async def mute_join_request(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    join_request_service: Annotated[WorkspaceJoinRequestService, Depends()],
    *,
    join_request_id: str,
) -> None:
    """Mute a join request.

    Requires manager-or-higher permission. Notifications are not sent on re-request.
    """
    if not member.has_permission(Permissions.WORKSPACE_JOIN_REQUESTS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied.",
        )

    result = await join_request_service.mute(join_request_id)
    match result:
        case Success():
            return
        case Failure(error):
            match error:
                case JoinRequestNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Join request not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.delete(
    "/workspaces/{handle}/join-requests/{join_request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_join_request(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    join_request_service: Annotated[WorkspaceJoinRequestService, Depends()],
    *,
    join_request_id: str,
) -> None:
    """Delete a join request.

    Requires manager-or-higher permission. Also used to unmute.
    """
    if not member.has_permission(Permissions.WORKSPACE_JOIN_REQUESTS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied.",
        )

    await join_request_service.delete(join_request_id)


def mount(mounter: RouteMounter) -> None:
    """Mount JoinRequest v1 routes."""
    mounter(
        router,
        prefix="/join-request/v1",
        tag="Join Request v1",
        description=dedent(
            """
            Workspace Join Request API (Public)

            Workspace join request create, list, approve, reject, mute,
            and delete endpoints.
            """
        ),
    )
