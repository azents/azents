"""WorkspaceUser v1 Public API.

Workspace member lookup, profile update, role change, and delete endpoints.
"""

from textwrap import dedent
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, status

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.permissions import Permissions
from azents.repos.workspace_user.data import NotFound
from azents.services.workspace_user import WorkspaceUserService
from azents.services.workspace_user.data import (
    CannotModifyOwner,
    CannotModifySelf,
    InvalidRole,
    WorkspaceUserUpdateInput,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    CurrentMemberResponse,
    UpdateMyProfileRequest,
    UpdateWorkspaceUserRoleRequest,
    WorkspaceUserListResponse,
    WorkspaceUserResponse,
)

router = APIRouter()


@router.get("/workspaces/{handle}/me")
async def get_current_member(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
) -> CurrentMemberResponse:
    """Return the current user's workspace member information."""
    return CurrentMemberResponse(
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )


@router.get("/workspaces/{handle}/me/profile")
async def get_my_profile(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    user_service: Annotated[WorkspaceUserService, Depends()],
) -> WorkspaceUserResponse:
    """Return the current user's workspace profile."""
    workspace_user = await user_service.get(member.workspace_user_id)
    if workspace_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WorkspaceUser not found.",
        )
    return WorkspaceUserResponse.convert_from(workspace_user)


@router.patch("/workspaces/{handle}/me/profile")
async def update_my_profile(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    user_service: Annotated[WorkspaceUserService, Depends()],
    *,
    request_body: UpdateMyProfileRequest,
) -> WorkspaceUserResponse:
    """Update the current user's workspace profile.

    Name and similar workspace profile fields can be changed.
    """
    update_data = WorkspaceUserUpdateInput()
    if request_body.name is not None:
        update_data["name"] = request_body.name

    result = await user_service.update(member.workspace_user_id, update_data)
    match result:
        case Success(value):
            return WorkspaceUserResponse.convert_from(value)
        case Failure(error):
            match error:
                case NotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="WorkspaceUser not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/workspaces/{handle}/workspace-users")
async def list_workspace_users(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    user_service: Annotated[WorkspaceUserService, Depends()],
    *,
    handle: str,
) -> WorkspaceUserListResponse:
    """List workspace members.

    Requires member read permission.
    """
    if not member.has_permission(Permissions.WORKSPACE_USERS_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No member read permission.",
        )

    users = await user_service.list_by_workspace(handle)
    return WorkspaceUserListResponse(
        items=[WorkspaceUserResponse.convert_from(u) for u in users.items]
    )


@router.patch("/workspaces/{handle}/workspace-users/{workspace_user_id}")
async def update_workspace_user_role(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    user_service: Annotated[WorkspaceUserService, Depends()],
    *,
    workspace_user_id: str,
    request_body: UpdateWorkspaceUserRoleRequest,
) -> WorkspaceUserResponse:
    """Change a workspace member role.

    Requires member management permission.
    """
    if not member.has_permission(Permissions.WORKSPACE_USERS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No member management permission.",
        )

    result = await user_service.update_role(
        member.workspace_user_id, workspace_user_id, request_body.role
    )
    match result:
        case Success(value):
            return WorkspaceUserResponse.convert_from(value)
        case Failure(error):
            match error:
                case NotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="WorkspaceUser not found.",
                    )
                case CannotModifySelf():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot change your own role.",
                    )
                case CannotModifyOwner():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot change the Owner role.",
                    )
                case InvalidRole():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot change a role to Owner.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.delete(
    "/workspaces/{handle}/workspace-users/{workspace_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_workspace_user(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    user_service: Annotated[WorkspaceUserService, Depends()],
    *,
    workspace_user_id: str,
) -> None:
    """Delete a workspace member.

    Requires member management permission.
    """
    if not member.has_permission(Permissions.WORKSPACE_USERS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No member management permission.",
        )

    result = await user_service.delete(member.workspace_user_id, workspace_user_id)
    match result:
        case Success():
            return None
        case Failure(error):
            match error:
                case CannotModifySelf():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot delete yourself.",
                    )
                case CannotModifyOwner():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Cannot delete the Owner.",
                    )
                case NotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="WorkspaceUser not found.",
                    )
                case _:
                    assert_never(error)


def mount(mounter: RouteMounter) -> None:
    """Mount WorkspaceUser v1 routes."""
    mounter(
        router,
        prefix="/workspace-user/v1",
        tag="WorkspaceUser v1",
        description=dedent(
            """
            WorkspaceUser API (Public)

            Workspace member lookup, role change, and delete endpoints.
            """
        ),
    )
