"""User v1 Public API.

Endpoint for retrieving the current user information.
"""

from textwrap import dedent
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from azents.core.auth.deps import CurrentUser, get_current_user
from azents.services.user import UserService
from azents.utils.fastapi.route import RouteMounter

from .data import MeResponse

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
        created_at=user.created_at,
    )


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
