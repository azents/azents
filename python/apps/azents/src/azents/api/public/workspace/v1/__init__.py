"""Workspace v1 Public API.

Workspace lookup/create endpoints.
"""

from textwrap import dedent
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, status

from azents.core.auth.deps import CurrentUser, get_current_user
from azents.repos.workspace.data import HandleConflict
from azents.services.workspace import WorkspaceService
from azents.services.workspace.data import (
    BootstrapNotAvailable,
    CreateWithOwnerInput,
    WeakBootstrapPassword,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    BootstrapFirstOwnerRequest,
    BootstrapFirstOwnerResponse,
    BootstrapStatusResponse,
    CreateWorkspaceRequest,
    CreateWorkspaceResponse,
    WorkspaceListResponse,
    WorkspaceResponse,
)

router = APIRouter()


@router.get("/bootstrap/status")
async def get_bootstrap_status(
    workspace_service: Annotated[WorkspaceService, Depends()],
) -> BootstrapStatusResponse:
    """Get whether first owner bootstrap is available.

    This endpoint is intentionally public because it is available only before
    the first user exists and is gated by server-side bootstrap invariants.
    """
    output = await workspace_service.get_bootstrap_status()
    return BootstrapStatusResponse.model_validate(output.model_dump())


@router.post("/bootstrap/first-owner", status_code=status.HTTP_201_CREATED)
async def bootstrap_first_owner(
    workspace_service: Annotated[WorkspaceService, Depends()],
    request_body: BootstrapFirstOwnerRequest,
) -> BootstrapFirstOwnerResponse:
    """Create the first Owner and Workspace.

    This endpoint is intentionally public because normal authentication cannot
    exist before the first user. The service allows it only when user count is
    zero and first-owner bootstrap is enabled.
    """
    result = await workspace_service.bootstrap_first_owner(request_body)
    match result:
        case Success(value):
            return BootstrapFirstOwnerResponse.model_validate(value.model_dump())
        case Failure(error):
            match error:
                case BootstrapNotAvailable():
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="First owner bootstrap is not available.",
                    )
                case HandleConflict():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Workspace handle already exists.",
                    )
                case WeakBootstrapPassword(message):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=message,
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/workspaces/{handle}")
async def get_workspace_by_handle(
    workspace_service: Annotated[WorkspaceService, Depends()],
    *,
    handle: str,
) -> WorkspaceResponse:
    """Get a Workspace by handle."""
    workspace = await workspace_service.get_by_handle(handle)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return WorkspaceResponse.convert_from(workspace)


@router.get("/workspaces")
async def list_workspaces(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    workspace_service: Annotated[WorkspaceService, Depends()],
) -> WorkspaceListResponse:
    """List Workspaces the current user belongs to."""
    workspaces = await workspace_service.list_by_user(current_user.user_id)
    return WorkspaceListResponse(
        items=[WorkspaceResponse.convert_from(w) for w in workspaces.items]
    )


@router.post("/workspaces", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    workspace_service: Annotated[WorkspaceService, Depends()],
    request_body: CreateWorkspaceRequest,
) -> CreateWorkspaceResponse:
    """Create a Workspace and register the current user as Owner."""
    result = await workspace_service.create_with_owner(
        CreateWithOwnerInput(
            user_id=current_user.user_id,
            workspace_name=request_body.workspace_name,
            workspace_handle=request_body.workspace_handle,
            owner_name=request_body.owner_name,
            locale=request_body.locale,
        )
    )
    match result:
        case Success(value):
            return CreateWorkspaceResponse.convert_from(value)
        case Failure(error):
            match error:
                case HandleConflict():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Handle already in use.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


def mount(mounter: RouteMounter) -> None:
    """Mount Workspace v1 routes."""
    mounter(
        router,
        prefix="/workspace/v1",
        tag="Workspace v1",
        description=dedent(
            """
            Workspace API (Public)

            Workspace lookup/create endpoints.
            """
        ),
    )
