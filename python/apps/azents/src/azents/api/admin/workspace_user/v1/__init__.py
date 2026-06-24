"""WorkspaceUser v1 Admin API.

WorkspaceUser CRUD endpoints.
"""

from textwrap import dedent
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, status

from azents.repos.workspace_user.data import NotFound, WorkspaceNotFound
from azents.services.workspace_user import WorkspaceUserService
from azents.services.workspace_user.data import (
    CannotModifyOwner,
    NotMemberOfWorkspace,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    TransferOwnershipRequest,
    WorkspaceUserCreateRequest,
    WorkspaceUserListResponse,
    WorkspaceUserResponse,
    WorkspaceUserUpdateRequest,
)

router = APIRouter()


@router.post("/workspace-users", status_code=status.HTTP_201_CREATED)
async def create_workspace_user(
    user_service: Annotated[WorkspaceUserService, Depends()],
    request: WorkspaceUserCreateRequest,
) -> WorkspaceUserResponse:
    """Create a WorkspaceUser."""
    result = await user_service.create(request)
    match result:
        case Success(value):
            return WorkspaceUserResponse.convert_from(value)
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


@router.get("/workspaces/{handle}/workspace-users")
async def list_workspace_users(
    user_service: Annotated[WorkspaceUserService, Depends()],
    *,
    handle: str,
) -> WorkspaceUserListResponse:
    """List WorkspaceUsers in a Workspace."""
    users = await user_service.list_by_workspace(handle)
    return WorkspaceUserListResponse(
        items=[WorkspaceUserResponse.convert_from(u) for u in users.items]
    )


@router.get("/workspace-users/{workspace_user_id}")
async def get_workspace_user(
    user_service: Annotated[WorkspaceUserService, Depends()],
    *,
    workspace_user_id: str,
) -> WorkspaceUserResponse:
    """Get a WorkspaceUser by ID."""
    user = await user_service.get(workspace_user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WorkspaceUser not found.",
        )
    return WorkspaceUserResponse.convert_from(user)


@router.patch("/workspace-users/{workspace_user_id}")
async def update_workspace_user(
    user_service: Annotated[WorkspaceUserService, Depends()],
    *,
    workspace_user_id: str,
    request: WorkspaceUserUpdateRequest,
) -> WorkspaceUserResponse:
    """Update a WorkspaceUser."""
    result = await user_service.update(workspace_user_id, request)
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


@router.delete(
    "/workspace-users/{workspace_user_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_workspace_user(
    user_service: Annotated[WorkspaceUserService, Depends()],
    *,
    workspace_user_id: str,
) -> None:
    """Delete a WorkspaceUser.

    Owners cannot be deleted. Transfer ownership first, then delete.
    """
    result = await user_service.delete_force(workspace_user_id)
    match result:
        case Success():
            return None
        case Failure(error):
            match error:
                case NotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="WorkspaceUser not found.",
                    )
                case CannotModifyOwner():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            "Owners cannot be deleted. Transfer ownership first, "
                            "then delete."
                        ),
                    )
                case _:
                    assert_never(error)


@router.post("/workspaces/{handle}/transfer-ownership")
async def transfer_workspace_ownership(
    user_service: Annotated[WorkspaceUserService, Depends()],
    *,
    handle: str,
    request: TransferOwnershipRequest,
) -> WorkspaceUserResponse:
    """Transfer Workspace ownership.

    Set the new Owner and demote the previous Owner to Manager.
    """
    result = await user_service.transfer_ownership_by_handle(
        handle, request.new_owner_workspace_user_id
    )
    match result:
        case Success(value):
            return WorkspaceUserResponse.convert_from(value)
        case Failure(error):
            match error:
                case WorkspaceNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Workspace not found.",
                    )
                case NotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="WorkspaceUser not found.",
                    )
                case NotMemberOfWorkspace():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Target is not a member of that Workspace.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


def mount(mounter: RouteMounter) -> None:
    """Mount WorkspaceUser v1 routes."""
    mounter(
        router,
        prefix="/workspace-user/v1",
        tag="WorkspaceUser v1",
        description=dedent(
            """
            WorkspaceUser API (Admin)

            CRUD endpoints that manage user profiles scoped to a Workspace.
            """
        ),
    )
