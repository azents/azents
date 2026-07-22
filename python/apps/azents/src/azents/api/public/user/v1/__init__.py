"""User v1 Public API.

Endpoint for retrieving the current user information.
"""

from textwrap import dedent
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException

from azents.core.auth.deps import CurrentUser, get_current_user
from azents.repos.user.data import NotFound, UserUpdate
from azents.services.system_user_role.service import SystemUserRoleService
from azents.services.user import UserService
from azents.utils.fastapi.route import RouteMounter

from .data import MeResponse, MySystemRolesResponse, UpdateMyUserRequest

router = APIRouter()


@router.get("/me")
async def me(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    user_service: Annotated[UserService, Depends()],
) -> MeResponse:
    """Return the currently authenticated user's information."""
    user = await user_service.get(current_user.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    return MeResponse(
        email=user.primary_email,
        locale=user.locale,
        created_at=user.created_at,
    )


@router.patch("/me")
async def update_me(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    user_service: Annotated[UserService, Depends()],
    *,
    request_body: UpdateMyUserRequest,
) -> MeResponse:
    """Update the currently authenticated user's account settings."""
    result = await user_service.update(
        current_user.user_id,
        UserUpdate(locale=request_body.locale),
    )
    match result:
        case Success(user):
            return MeResponse(
                email=user.primary_email,
                locale=user.locale,
                created_at=user.created_at,
            )
        case Failure(error):
            match error:
                case NotFound():
                    raise HTTPException(status_code=404, detail="User not found.")
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/me/system-roles")
async def get_my_system_roles(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    system_role_service: Annotated[SystemUserRoleService, Depends()],
) -> MySystemRolesResponse:
    """Return system roles assigned to the current User."""
    output = await system_role_service.get_current_roles(current_user.user_id)
    return MySystemRolesResponse(roles=output.roles)


def mount(mounter: RouteMounter) -> None:
    """Mount the User v1 routes."""
    mounter(
        router,
        prefix="/user/v1",
        tag="User v1",
        description=dedent(
            """
            User API (Public)

            Endpoint for retrieving the current user information.
            """
        ),
    )
