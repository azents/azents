"""Security v1 Public API.

Security settings and step-up authentication endpoints.
"""

from textwrap import dedent
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, Response, status

from azents.core.auth.deps import CurrentUser, get_current_user, get_elevated_user
from azents.services.security import SecurityService
from azents.services.security.data import (
    ElevateWithEmailInput,
    ElevateWithPasswordInput,
    GetAuthMethodsInput,
    InvalidElevationCode,
    InvalidPassword,
    LastCredentialRemovalDenied,
    PasswordNotSet,
    RemovePasswordInput,
    SendElevationCodeInput,
    SetPasswordInput,
    UserNotFound,
    WeakPassword,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    ElevateResponse,
    ElevateWithEmailRequest,
    ElevateWithPasswordRequest,
    GetAuthMethodsResponse,
    SendElevationCodeResponse,
    SetPasswordRequest,
)

router = APIRouter()


@router.get("/auth-methods")
async def get_auth_methods(
    security_service: Annotated[SecurityService, Depends()],
    current_user: Annotated[CurrentUser, Depends(get_elevated_user)],
) -> GetAuthMethodsResponse:
    """List available authentication methods."""
    result = await security_service.get_auth_methods(
        GetAuthMethodsInput(user_id=current_user.user_id)
    )
    match result:
        case Success(value):
            return GetAuthMethodsResponse.convert_from(value)
        case Failure(error):
            match error:
                case UserNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="User not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/elevation-methods")
async def get_elevation_methods(
    security_service: Annotated[SecurityService, Depends()],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> GetAuthMethodsResponse:
    """List authentication methods available for elevation without elevation."""
    result = await security_service.get_elevation_methods(
        GetAuthMethodsInput(user_id=current_user.user_id)
    )
    match result:
        case Success(value):
            return GetAuthMethodsResponse.convert_from(value)
        case Failure(error):
            match error:
                case UserNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="User not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post("/elevate/send-code")
async def send_elevation_code(
    security_service: Annotated[SecurityService, Depends()],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> SendElevationCodeResponse:
    """Send an email OTP for step-up authentication."""
    result = await security_service.send_elevation_code(
        SendElevationCodeInput(user_id=current_user.user_id)
    )
    match result:
        case Success(value):
            return SendElevationCodeResponse.convert_from(value)
        case Failure(error):
            match error:
                case UserNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="User not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post("/elevate/email")
async def elevate_with_email(
    security_service: Annotated[SecurityService, Depends()],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    request_body: ElevateWithEmailRequest,
) -> ElevateResponse:
    """Perform step-up authentication with email OTP."""
    result = await security_service.elevate_with_email(
        ElevateWithEmailInput(
            user_id=current_user.user_id,
            session_id=current_user.session_id,
            code=request_body.code,
            csrf_token=request_body.csrf_token,
        )
    )
    match result:
        case Success(value):
            return ElevateResponse.convert_from(value)
        case Failure(error):
            match error:
                case InvalidElevationCode():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid elevation code.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post("/elevate/password")
async def elevate_with_password(
    security_service: Annotated[SecurityService, Depends()],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    request_body: ElevateWithPasswordRequest,
) -> ElevateResponse:
    """Perform step-up authentication with password."""
    result = await security_service.elevate_with_password(
        ElevateWithPasswordInput(
            user_id=current_user.user_id,
            session_id=current_user.session_id,
            password=request_body.password,
        )
    )
    match result:
        case Success(value):
            return ElevateResponse.convert_from(value)
        case Failure(error):
            match error:
                case InvalidPassword():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid password.",
                    )
                case PasswordNotSet():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Password is not configured.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def set_password(
    security_service: Annotated[SecurityService, Depends()],
    current_user: Annotated[CurrentUser, Depends(get_elevated_user)],
    request_body: SetPasswordRequest,
) -> Response:
    """Set or change password."""
    result = await security_service.set_password(
        SetPasswordInput(
            user_id=current_user.user_id,
            password=request_body.password,
        )
    )
    match result:
        case Success():
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        case Failure(error):
            match error:
                case WeakPassword(message=message):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=message,
                    )
                case UserNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="User not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.delete("/password", status_code=status.HTTP_204_NO_CONTENT)
async def remove_password(
    security_service: Annotated[SecurityService, Depends()],
    current_user: Annotated[CurrentUser, Depends(get_elevated_user)],
) -> Response:
    """Delete password."""
    result = await security_service.remove_password(
        RemovePasswordInput(user_id=current_user.user_id)
    )
    match result:
        case Success():
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        case Failure(error):
            match error:
                case PasswordNotSet():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Password is not configured.",
                    )
                case LastCredentialRemovalDenied():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Cannot remove the last valid credential.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


def mount(mounter: RouteMounter) -> None:
    """Mount Security v1 routes."""
    mounter(
        router,
        prefix="/security/v1",
        tag="Security v1",
        description=dedent(
            """
            Security API (Public)

            Security settings and step-up authentication endpoints.
            """
        ),
    )
