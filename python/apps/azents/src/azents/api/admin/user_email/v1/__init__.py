"""UserEmail v1 Admin API.

User email management endpoints.
"""

from textwrap import dedent
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, status

from azents.repos.user_email.data import DuplicateEmail, UserEmailCreate
from azents.services.user_email import UserEmailService
from azents.utils.fastapi.route import RouteMounter

from .data import UserEmailCreateRequest, UserEmailListResponse, UserEmailResponse

router = APIRouter()


@router.get("/emails")
async def list_emails(
    user_email_service: Annotated[UserEmailService, Depends()],
    *,
    offset: int = 0,
    limit: int = 50,
) -> UserEmailListResponse:
    """List all UserEmail records."""
    result = await user_email_service.list_all(offset=offset, limit=limit)
    return UserEmailListResponse(
        items=[UserEmailResponse.convert_from(e) for e in result.items],
        total=result.total,
    )


@router.get("/users/{user_id}/emails")
async def list_emails_by_user(
    user_email_service: Annotated[UserEmailService, Depends()],
    *,
    user_id: str,
) -> UserEmailListResponse:
    """List UserEmail records by User ID."""
    result = await user_email_service.list_by_user(user_id)
    return UserEmailListResponse(
        items=[UserEmailResponse.convert_from(e) for e in result.items],
        total=result.total,
    )


@router.post("/users/{user_id}/emails", status_code=status.HTTP_201_CREATED)
async def create_email(
    user_email_service: Annotated[UserEmailService, Depends()],
    request: UserEmailCreateRequest,
    *,
    user_id: str,
) -> UserEmailResponse:
    """Create a UserEmail."""
    result = await user_email_service.create(
        UserEmailCreate(user_id=user_id, email=request.email),
    )
    match result:
        case Success(value):
            return UserEmailResponse.convert_from(value)
        case Failure(error):
            match error:
                case DuplicateEmail():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Email is already in use.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.delete("/emails/{email_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_email(
    user_email_service: Annotated[UserEmailService, Depends()],
    *,
    email_id: str,
) -> None:
    """Delete a UserEmail."""
    await user_email_service.delete(email_id)


def mount(mounter: RouteMounter) -> None:
    """Mount UserEmail v1 Admin routes."""
    mounter(
        router,
        prefix="/user-email/v1",
        tag="UserEmail v1",
        description=dedent(
            """
            UserEmail API (Admin)

            User email management CRUD endpoints.
            """
        ),
    )
