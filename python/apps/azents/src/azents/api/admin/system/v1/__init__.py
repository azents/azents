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
from azents.services.system_user_role.service import SystemUserRoleService
from azents.utils.fastapi.route import RouteMounter

from .data import (
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
