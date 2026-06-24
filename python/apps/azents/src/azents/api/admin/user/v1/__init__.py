"""User v1 Admin API.

User management endpoints.
"""

from textwrap import dedent
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from azents.services.user import UserService
from azents.utils.fastapi.route import RouteMounter

from .data import UserListResponse, UserResponse

router = APIRouter()


@router.get("/users")
async def list_users(
    user_service: Annotated[UserService, Depends()],
    *,
    offset: int = 0,
    limit: int = 50,
) -> UserListResponse:
    """List all Users."""
    result = await user_service.list_all(offset=offset, limit=limit)
    return UserListResponse(
        items=[UserResponse.convert_from(u) for u in result.items],
        total=result.total,
    )


@router.get("/users/{user_id}")
async def get_user(
    user_service: Annotated[UserService, Depends()],
    *,
    user_id: str,
) -> UserResponse:
    """Get a User by ID."""
    user = await user_service.get(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    return UserResponse.convert_from(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_service: Annotated[UserService, Depends()],
    *,
    user_id: str,
) -> None:
    """Delete a User."""
    await user_service.delete(user_id)


def mount(mounter: RouteMounter) -> None:
    """Mount User v1 Admin routes."""
    mounter(
        router,
        prefix="/user/v1",
        tag="User v1",
        description=dedent(
            """
            User API (Admin)

            User management CRUD endpoints.
            """
        ),
    )
