"""System v1 Admin API."""

from textwrap import dedent
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, status

from azents.core.auth.deps import SystemAdmin, get_system_admin
from azents.core.enums import SystemUserRole
from azents.repos.system_user_role.data import (
    LastSystemAdmin,
    SystemRoleAssignmentNotFound,
    SystemUserNotFound,
)
from azents.services.archived_session_retention import (
    ArchivedSessionRetentionService,
    RetentionApplicationInProgress,
    RetentionRevisionConflict,
)
from azents.services.system_user_role.service import SystemUserRoleService
from azents.utils.fastapi.route import RouteMounter

from .data import (
    ArchiveRetentionApplicationResponse,
    ArchiveRetentionPreviewRequest,
    ArchiveRetentionPreviewResponse,
    FileLifecycleSettingsResponse,
    FileLifecycleSettingsUpdateRequest,
    FileLifecycleSettingsUpdateResponse,
    SystemAdminMeResponse,
    SystemUserRoleAssignmentListResponse,
    SystemUserRoleAssignmentResponse,
)

router = APIRouter()


@router.get("/me")
async def get_system_admin_me(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
) -> SystemAdminMeResponse:
    """Return the current system administrator."""
    return SystemAdminMeResponse(
        user_id=system_admin.user_id,
        roles=[SystemUserRole.SYSTEM_ADMIN],
    )


@router.get("/settings/file-lifecycle")
async def get_file_lifecycle_settings(
    _system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    retention_service: Annotated[ArchivedSessionRetentionService, Depends()],
) -> FileLifecycleSettingsResponse:
    """Return instance-wide archive retention settings."""
    state = await retention_service.get_settings_state()
    return FileLifecycleSettingsResponse.from_domain(state)


@router.post("/settings/file-lifecycle/archive-retention/preview")
async def preview_archive_retention_update(
    request: ArchiveRetentionPreviewRequest,
    _system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    retention_service: Annotated[ArchivedSessionRetentionService, Depends()],
) -> ArchiveRetentionPreviewResponse:
    """Preview applying one retention value to existing archives."""
    preview = await retention_service.preview(request.archived_session_retention_days)
    return ArchiveRetentionPreviewResponse.from_domain(preview)


@router.patch("/settings/file-lifecycle")
async def update_file_lifecycle_settings(
    request: FileLifecycleSettingsUpdateRequest,
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    retention_service: Annotated[ArchivedSessionRetentionService, Depends()],
) -> FileLifecycleSettingsUpdateResponse:
    """Update archive retention settings with optimistic concurrency."""
    try:
        result = await retention_service.update_settings(
            expected_revision=request.expected_revision,
            retention_days=request.archived_session_retention_days,
            application_scope=request.application_scope,
            user_id=system_admin.user_id,
        )
    except RetentionRevisionConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "retention_revision_conflict",
                "message": "File lifecycle settings changed. Reload and try again.",
            },
        ) from error
    except RetentionApplicationInProgress as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "retention_application_in_progress",
                "message": "An archive retention recalculation is already running.",
            },
        ) from error
    return FileLifecycleSettingsUpdateResponse.from_domain(result)


@router.get("/settings/file-lifecycle/retention-applications/{application_id}")
async def get_archive_retention_application(
    application_id: str,
    _system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    retention_service: Annotated[ArchivedSessionRetentionService, Depends()],
) -> ArchiveRetentionApplicationResponse:
    """Return durable existing-archive recalculation progress."""
    application = await retention_service.get_application(application_id=application_id)
    if application is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Retention application not found.",
        )
    return ArchiveRetentionApplicationResponse.from_domain(application)


@router.get("/role-assignments")
async def list_system_role_assignments(
    _system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    system_role_service: Annotated[SystemUserRoleService, Depends()],
    *,
    offset: int = 0,
    limit: int = 50,
) -> SystemUserRoleAssignmentListResponse:
    """List instance-wide role assignments."""
    output = await system_role_service.list_all(offset=offset, limit=limit)
    return SystemUserRoleAssignmentListResponse(
        items=[
            SystemUserRoleAssignmentResponse.convert_output(item)
            for item in output.items
        ],
        total=output.total,
    )


@router.put("/users/{user_id}/roles/system_admin")
async def grant_system_admin(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    system_role_service: Annotated[SystemUserRoleService, Depends()],
    *,
    user_id: str,
) -> SystemUserRoleAssignmentResponse:
    """Grant system administrator authority to an existing User."""
    result = await system_role_service.grant(
        user_id,
        SystemUserRole.SYSTEM_ADMIN,
        granted_by_user_id=system_admin.user_id,
        source="admin_api",
    )
    match result:
        case Success(value):
            return SystemUserRoleAssignmentResponse.convert_output(value)
        case Failure(SystemUserNotFound()):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )
        case _:
            assert_never(result)


@router.delete(
    "/users/{user_id}/roles/system_admin",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_system_admin(
    system_admin: Annotated[SystemAdmin, Depends(get_system_admin)],
    system_role_service: Annotated[SystemUserRoleService, Depends()],
    *,
    user_id: str,
) -> None:
    """Revoke system administrator authority from a User."""
    result = await system_role_service.revoke(
        user_id,
        SystemUserRole.SYSTEM_ADMIN,
        revoked_by_user_id=system_admin.user_id,
    )
    match result:
        case Success():
            return
        case Failure(error):
            match error:
                case SystemRoleAssignmentNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="System role assignment not found.",
                    )
                case LastSystemAdmin():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "last_system_admin",
                            "message": (
                                "The final system administrator cannot be revoked."
                            ),
                        },
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


def mount(mounter: RouteMounter) -> None:
    """Mount System v1 Admin routes."""
    mounter(
        router,
        prefix="/system/v1",
        tag="System v1",
        description=dedent(
            """
            System API (Admin)

            Instance-wide administrator role management.
            """
        ),
    )
