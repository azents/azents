"""Workspace v1 Admin API.

Workspace CRUD endpoints.
"""

from textwrap import dedent
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, status

from azents.repos.workspace.data import HandleConflict, NotFound
from azents.services.workspace import WorkspaceService
from azents.services.workspace.data import (
    BootstrapNotAvailable,
    WeakBootstrapPassword,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    BootstrapFirstOwnerRequest,
    BootstrapFirstOwnerResponse,
    BootstrapStatusResponse,
    WorkspaceCreateRequest,
    WorkspaceListResponse,
    WorkspaceResponse,
    WorkspaceUpdateRequest,
)

router = APIRouter()


@router.get("/bootstrap/status")
async def get_bootstrap_status(
    workspace_service: Annotated[WorkspaceService, Depends()],
) -> BootstrapStatusResponse:
    """Get whether first owner bootstrap is available."""
    output = await workspace_service.get_bootstrap_status()
    return BootstrapStatusResponse.model_validate(output.model_dump())


@router.post("/bootstrap/first-owner", status_code=status.HTTP_201_CREATED)
async def bootstrap_first_owner(
    workspace_service: Annotated[WorkspaceService, Depends()],
    request: BootstrapFirstOwnerRequest,
) -> BootstrapFirstOwnerResponse:
    """Create the first Owner and Workspace."""
    result = await workspace_service.bootstrap_first_owner(request)
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


@router.post("/workspaces", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    workspace_service: Annotated[WorkspaceService, Depends()],
    request: WorkspaceCreateRequest,
) -> WorkspaceResponse:
    """Create a Workspace."""
    result = await workspace_service.create(request)
    match result:
        case Success(value):
            return WorkspaceResponse.convert_from(value)
        case Failure(error):
            match error:
                case HandleConflict():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Handle already exists.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/workspaces")
async def list_workspaces(
    workspace_service: Annotated[WorkspaceService, Depends()],
) -> WorkspaceListResponse:
    """List all Workspaces."""
    workspaces = await workspace_service.list_all()
    return WorkspaceListResponse(
        items=[WorkspaceResponse.convert_from(w) for w in workspaces.items]
    )


@router.get("/workspaces/{handle}")
async def get_workspace(
    workspace_service: Annotated[WorkspaceService, Depends()],
    *,
    handle: str,
) -> WorkspaceResponse:
    """Get a Workspace by handle."""
    workspace = await workspace_service.get_by_handle(handle)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return WorkspaceResponse.convert_from(workspace)


@router.patch("/workspaces/{handle}")
async def update_workspace(
    workspace_service: Annotated[WorkspaceService, Depends()],
    *,
    handle: str,
    request: WorkspaceUpdateRequest,
) -> WorkspaceResponse:
    """Update a Workspace."""
    result = await workspace_service.update_by_handle(handle, request)
    match result:
        case Success(value):
            return WorkspaceResponse.convert_from(value)
        case Failure(error):
            match error:
                case NotFound():
                    raise HTTPException(
                        status_code=404,
                        detail="Workspace not found.",
                    )
                case HandleConflict():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Handle already exists.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.delete("/workspaces/{handle}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace_service: Annotated[WorkspaceService, Depends()],
    *,
    handle: str,
) -> None:
    """Delete a Workspace."""
    await workspace_service.delete_by_handle(handle)


def mount(mounter: RouteMounter) -> None:
    """Mount Workspace v1 routes."""
    mounter(
        router,
        prefix="/workspace/v1",
        tag="Workspace v1",
        description=dedent(
            """
            Workspace API (Admin)

            Workspace CRUD endpoints.
            """
        ),
    )
