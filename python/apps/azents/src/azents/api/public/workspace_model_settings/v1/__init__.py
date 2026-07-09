"""Workspace model settings v1 Public API."""

from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, status

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.services.workspace_model_settings import WorkspaceModelSettingsService
from azents.services.workspace_model_settings.data import (
    DefaultModelCannotBeCleared,
    InvalidSelectableModelOptions,
    ModelSelectionNotFound,
    WorkspaceModelSettingsUpdateInput,
)
from azents.utils.fastapi.route import RouteMounter

from .data import WorkspaceModelSettingsResponse, WorkspaceModelSettingsUpdateRequest

router = APIRouter()


@router.get("/workspaces/{handle}")
async def get_workspace_model_settings(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[WorkspaceModelSettingsService, Depends()],
) -> WorkspaceModelSettingsResponse:
    """Get the workspace default model settings."""
    output = await service.get(member.workspace_id)
    return WorkspaceModelSettingsResponse.convert_from(output)


@router.put("/workspaces/{handle}")
async def update_workspace_model_settings(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[WorkspaceModelSettingsService, Depends()],
    *,
    request_body: WorkspaceModelSettingsUpdateRequest,
) -> WorkspaceModelSettingsResponse:
    """Update the workspace default model settings."""
    result = await service.update(
        member.workspace_id,
        WorkspaceModelSettingsUpdateInput(
            default_model_selection=request_body.default_model_selection,
            default_lightweight_model_selection=(
                request_body.default_lightweight_model_selection
            ),
            default_selectable_model_options=(
                request_body.default_selectable_model_options
            ),
            default_main_model_label=request_body.default_main_model_label,
            default_lightweight_model_label=(
                request_body.default_lightweight_model_label
            ),
        ),
    )
    match result:
        case Success(value):
            return WorkspaceModelSettingsResponse.convert_from(value)
        case Failure(error):
            match error:
                case ModelSelectionNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Selected model was not found.",
                    )
                case DefaultModelCannotBeCleared():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Workspace default model cannot be cleared once set.",
                    )
                case InvalidSelectableModelOptions(errors=errors):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "message": "Invalid selectable model options.",
                            "errors": errors,
                        },
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


def mount(mounter: RouteMounter) -> None:
    """Mount the Workspace model settings v1 routes."""
    mounter(
        router,
        prefix="/workspace-model-settings/v1",
        tag="Workspace Model Settings v1",
        description="Workspace model settings API (Public)",
    )
