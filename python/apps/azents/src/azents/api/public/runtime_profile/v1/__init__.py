"""Workspace Runtime Profile v1 Public API."""

from textwrap import dedent
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.permissions import Permission, Permissions
from azents.services.runtime_profile_workspace.service import (
    RuntimeProfileWorkspaceService,
    RuntimeProfileWorkspaceUnavailable,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    SelectableInfrastructureProfileListResponse,
    SelectableInfrastructureProfileResponse,
    WorkspaceRuntimeProfileCreateRequest,
    WorkspaceRuntimeProfileDefaultReplaceRequest,
    WorkspaceRuntimeProfileDefaultResponse,
    WorkspaceRuntimeProfileListResponse,
    WorkspaceRuntimeProfileReplaceRequest,
    WorkspaceRuntimeProfileResponse,
)

router = APIRouter()


@router.get("/workspaces/{handle}/default")
async def get_workspace_runtime_profile_default(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeProfileWorkspaceService, Depends()],
) -> WorkspaceRuntimeProfileDefaultResponse:
    """Get the Workspace Runtime Profile default and its current availability."""
    _require_permission(member, Permissions.RUNTIME_PROFILES_READ)
    try:
        projection = await service.get_default(member.workspace_id)
    except RuntimeProfileWorkspaceUnavailable as error:
        _raise_unavailable(error)
    return WorkspaceRuntimeProfileDefaultResponse.convert_from(projection)


@router.put("/workspaces/{handle}/default")
async def replace_workspace_runtime_profile_default(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeProfileWorkspaceService, Depends()],
    request_body: WorkspaceRuntimeProfileDefaultReplaceRequest,
) -> WorkspaceRuntimeProfileDefaultResponse:
    """Set or clear the Workspace default with optimistic version fencing."""
    _require_permission(member, Permissions.RUNTIME_PROFILES_WRITE)
    try:
        projection = await service.replace_default(
            member.workspace_id,
            expected_version=request_body.expected_version,
            runtime_profile_id=request_body.runtime_profile_id,
        )
    except RuntimeProfileWorkspaceUnavailable as error:
        _raise_unavailable(error)
    return WorkspaceRuntimeProfileDefaultResponse.convert_from(projection)


@router.get("/workspaces/{handle}/infrastructure-profiles")
async def list_selectable_infrastructure_profiles(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeProfileWorkspaceService, Depends()],
) -> SelectableInfrastructureProfileListResponse:
    """List exact Provider infrastructure Profiles selectable by the Workspace."""
    _require_permission(member, Permissions.RUNTIME_PROFILES_READ)
    profiles = await service.list_selectable_infrastructure(member.workspace_id)
    return SelectableInfrastructureProfileListResponse(
        items=[
            SelectableInfrastructureProfileResponse.convert_from(profile)
            for profile in profiles
        ]
    )


@router.get("/workspaces/{handle}/profiles")
async def list_workspace_runtime_profiles(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeProfileWorkspaceService, Depends()],
    *,
    include_disabled: bool = False,
) -> WorkspaceRuntimeProfileListResponse:
    """List Workspace-owned Runtime Profiles with current availability."""
    _require_permission(member, Permissions.RUNTIME_PROFILES_READ)
    profiles = await service.list_profiles(
        member.workspace_id,
        include_disabled=include_disabled,
    )
    return WorkspaceRuntimeProfileListResponse(
        items=[
            WorkspaceRuntimeProfileResponse.convert_from(profile)
            for profile in profiles
        ]
    )


@router.post(
    "/workspaces/{handle}/profiles",
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_runtime_profile(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeProfileWorkspaceService, Depends()],
    request_body: WorkspaceRuntimeProfileCreateRequest,
) -> WorkspaceRuntimeProfileResponse:
    """Create one complete Workspace Runtime choice."""
    _require_permission(member, Permissions.RUNTIME_PROFILES_WRITE)
    try:
        profile = await service.create_profile(
            member.workspace_id,
            infrastructure_profile_id=request_body.infrastructure_profile_id,
            display_name=request_body.display_name,
            description=request_body.description,
            lifecycle=request_body.lifecycle,
            policy=request_body.policy,
            actor_workspace_user_id=member.workspace_user_id,
        )
    except RuntimeProfileWorkspaceUnavailable as error:
        _raise_unavailable(error)
    return WorkspaceRuntimeProfileResponse.convert_from(profile)


@router.get("/workspaces/{handle}/profiles/{profile_id}")
async def get_workspace_runtime_profile(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeProfileWorkspaceService, Depends()],
    *,
    profile_id: str,
) -> WorkspaceRuntimeProfileResponse:
    """Inspect one exact Workspace-owned Runtime Profile."""
    _require_permission(member, Permissions.RUNTIME_PROFILES_READ)
    try:
        profile = await service.get_profile(member.workspace_id, profile_id)
    except RuntimeProfileWorkspaceUnavailable as error:
        _raise_unavailable(error)
    return WorkspaceRuntimeProfileResponse.convert_from(profile)


@router.put("/workspaces/{handle}/profiles/{profile_id}")
async def replace_workspace_runtime_profile(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[RuntimeProfileWorkspaceService, Depends()],
    request_body: WorkspaceRuntimeProfileReplaceRequest,
    *,
    profile_id: str,
) -> WorkspaceRuntimeProfileResponse:
    """Replace one Workspace Profile with optimistic version fencing."""
    _require_permission(member, Permissions.RUNTIME_PROFILES_WRITE)
    try:
        profile = await service.replace_profile(
            member.workspace_id,
            profile_id,
            expected_version=request_body.expected_version,
            infrastructure_profile_id=request_body.infrastructure_profile_id,
            display_name=request_body.display_name,
            description=request_body.description,
            lifecycle=request_body.lifecycle,
            policy=request_body.policy,
            actor_workspace_user_id=member.workspace_user_id,
        )
    except RuntimeProfileWorkspaceUnavailable as error:
        _raise_unavailable(error)
    return WorkspaceRuntimeProfileResponse.convert_from(profile)


def _require_permission(member: WorkspaceMember, permission: Permission) -> None:
    if not member.has_permission(permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace Runtime Profile permission is required.",
        )


def _raise_unavailable(error: RuntimeProfileWorkspaceUnavailable) -> NoReturn:
    if error.code in {
        "workspace_not_found",
        "profile_not_found",
        "infrastructure_profile_not_found",
    }:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": error.code},
        ) from None
    if error.code in {
        "profile_document_invalid",
        "workspace_policy_invalid",
    }:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": error.code},
        ) from None
    detail: dict[str, object] = {"code": error.code}
    if error.current_profile is not None:
        detail["current_version"] = error.current_profile.version
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=detail,
    ) from None


def mount(mounter: RouteMounter) -> None:
    """Mount Workspace Runtime Profile routes."""
    mounter(
        router,
        prefix="/runtime-profile/v1",
        tag="Runtime Profile v1",
        description=dedent(
            """
            Runtime Profile API (Public)

            Workspace-owned complete Runtime choices and selectable Provider
            infrastructure Profiles.
            """
        ),
    )
