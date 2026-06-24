"""Auth v1 Public API.

Authentication endpoints based on email verification codes.
"""

from textwrap import dedent
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from azents.core.auth.deps import CurrentUser, get_current_user
from azents.core.config import AuthConfig
from azents.core.deps import get_auth_config
from azents.core.email.service import EmailService
from azents.services.auth import AuthService
from azents.services.auth.data import (
    InvalidCredentials,
    InvalidRefreshToken,
    InvalidVerificationCode,
    LoginMethodsInput,
    LogoutInput,
    PasswordLoginInput,
    RefreshTokenInput,
    RegistrationRequired,
    SendCodeInput,
    VerifyCodeInput,
)
from azents.services.password_reset_token import PasswordResetTokenService
from azents.services.password_reset_token.data import (
    InvalidPasswordResetToken,
    PreviewPasswordResetTokenInput,
    RedeemPasswordResetTokenInput,
    WeakResetPassword,
)
from azents.services.signup_token import SignupTokenService
from azents.services.signup_token.data import (
    InvalidSignupToken,
    PreviewSignupTokenInput,
    RedeemSignupTokenInput,
    SignupEmailDeliveryUnavailable,
    SignupTokenEmailAlreadyRegistered,
    SignupTokenEmailMismatch,
    WeakSignupPassword,
)
from azents.utils.fastapi.route import RouteMounter

from .data import (
    LoginMethodsResponse,
    PasswordLoginRequest,
    PasswordLoginResponse,
    PreviewPasswordResetTokenRequest,
    PreviewPasswordResetTokenResponse,
    PreviewSignupTokenRequest,
    PreviewSignupTokenResponse,
    RedeemPasswordResetTokenRequest,
    RedeemPasswordResetTokenResponse,
    RedeemSignupTokenRequest,
    RedeemSignupTokenResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    RequestSignupEmailRequest,
    RequestSignupEmailResponse,
    SendCodeRequest,
    SendCodeResponse,
    SignupStatusResponse,
    VerifyCodeRequest,
    VerifyCodeResponse,
)

router = APIRouter()


@router.post("/email/send-code")
async def send_code(
    auth_service: Annotated[AuthService, Depends()],
    request_body: SendCodeRequest,
) -> SendCodeResponse:
    """Send an email verification code."""
    output = await auth_service.send_code(SendCodeInput(email=request_body.email))
    return SendCodeResponse.convert_from(output)


@router.post("/email/verify")
async def verify_code(
    auth_service: Annotated[AuthService, Depends()],
    request_body: VerifyCodeRequest,
    request: Request,
) -> VerifyCodeResponse:
    """Verify an authentication code and issue a JWT."""
    input_data = VerifyCodeInput(
        email=request_body.email,
        code=request_body.code,
        csrf_token=request_body.csrf_token,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    result = await auth_service.verify_code(input_data)
    match result:
        case Success(value):
            return VerifyCodeResponse.convert_from(value)
        case Failure(error):
            match error:
                case InvalidVerificationCode():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid verification code.",
                    )
                case RegistrationRequired():
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Signup token is required.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/signup/status")
async def get_signup_status(
    auth_config: Annotated[AuthConfig, Depends(get_auth_config)],
    email_service: Annotated[EmailService, Depends()],
) -> SignupStatusResponse:
    """Return whether signup UX can be shown."""
    return SignupStatusResponse(
        email_signup_available=(
            auth_config.registration_mode == "signup_token" and email_service.configured
        )
    )


@router.post("/signup/email")
async def request_signup_email(
    signup_token_service: Annotated[SignupTokenService, Depends()],
    request_body: RequestSignupEmailRequest,
) -> RequestSignupEmailResponse:
    """Send a signup link by email."""
    result = await signup_token_service.create_email_delivery_token(request_body.email)
    match result:
        case Success():
            return RequestSignupEmailResponse(sent=True)
        case Failure(error):
            match error:
                case SignupEmailDeliveryUnavailable():
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Signup email delivery is not configured.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post("/signup-tokens/preview")
async def preview_signup_token(
    signup_token_service: Annotated[SignupTokenService, Depends()],
    request_body: PreviewSignupTokenRequest,
) -> PreviewSignupTokenResponse:
    """Check signup token status."""
    output = await signup_token_service.preview(
        PreviewSignupTokenInput(token=request_body.token)
    )
    return PreviewSignupTokenResponse.convert_from(output)


@router.post("/signup-tokens/redeem")
async def redeem_signup_token(
    signup_token_service: Annotated[SignupTokenService, Depends()],
    request_body: RedeemSignupTokenRequest,
    request: Request,
) -> RedeemSignupTokenResponse:
    """Create an account from a signup token and issue a JWT."""
    result = await signup_token_service.redeem(
        RedeemSignupTokenInput(
            token=request_body.token,
            email=request_body.email,
            password=request_body.password,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    )
    match result:
        case Success(value):
            return RedeemSignupTokenResponse.convert_from(value)
        case Failure(error):
            match error:
                case InvalidSignupToken():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid signup token.",
                    )
                case SignupTokenEmailMismatch():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Signup token email does not match.",
                    )
                case SignupTokenEmailAlreadyRegistered():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Email is already registered.",
                    )
                case WeakSignupPassword(message):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=message,
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post("/password-reset-tokens/preview")
async def preview_password_reset_token(
    password_reset_token_service: Annotated[PasswordResetTokenService, Depends()],
    request_body: PreviewPasswordResetTokenRequest,
) -> PreviewPasswordResetTokenResponse:
    """Check password reset token status."""
    output = await password_reset_token_service.preview(
        PreviewPasswordResetTokenInput(token=request_body.token)
    )
    return PreviewPasswordResetTokenResponse.convert_from(output)


@router.post("/password-reset-tokens/redeem")
async def redeem_password_reset_token(
    password_reset_token_service: Annotated[PasswordResetTokenService, Depends()],
    request_body: RedeemPasswordResetTokenRequest,
    request: Request,
) -> RedeemPasswordResetTokenResponse:
    """Set a password from a password reset token."""
    result = await password_reset_token_service.redeem(
        RedeemPasswordResetTokenInput(
            token=request_body.token,
            password=request_body.password,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    )
    match result:
        case Success():
            return RedeemPasswordResetTokenResponse(success=True)
        case Failure(error):
            match error:
                case InvalidPasswordResetToken():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Invalid password reset token.",
                    )
                case WeakResetPassword(message):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=message,
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post("/token/refresh")
async def refresh_token(
    auth_service: Annotated[AuthService, Depends()],
    request_body: RefreshTokenRequest,
) -> RefreshTokenResponse:
    """Issue new tokens from a refresh token."""
    result = await auth_service.refresh_token(
        RefreshTokenInput(refresh_token=request_body.refresh_token)
    )
    match result:
        case Success(value):
            return RefreshTokenResponse.convert_from(value)
        case Failure(error):
            match error:
                case InvalidRefreshToken():
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid refresh token.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    auth_service: Annotated[AuthService, Depends()],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> Response:
    """Revoke the current session."""
    await auth_service.logout(LogoutInput(session_id=current_user.session_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/login/password")
async def login_with_password(
    auth_service: Annotated[AuthService, Depends()],
    request_body: PasswordLoginRequest,
    request: Request,
) -> PasswordLoginResponse:
    """Log in with email and password."""
    result = await auth_service.login_with_password(
        PasswordLoginInput(
            email=request_body.email,
            password=request_body.password,
            user_agent=request.headers.get("user-agent"),
            ip_address=request.client.host if request.client else None,
        )
    )
    match result:
        case Success(value):
            return PasswordLoginResponse.convert_from(value)
        case Failure(error):
            match error:
                case InvalidCredentials():
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid email or password.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/login/methods")
async def get_login_methods(
    auth_service: Annotated[AuthService, Depends()],
    email: str,
) -> LoginMethodsResponse:
    """Get available login methods for an email."""
    output = await auth_service.get_login_methods(LoginMethodsInput(email=email))
    return LoginMethodsResponse(
        has_password=output.has_password,
        email_available=output.email_available,
    )


def mount(mounter: RouteMounter) -> None:
    """Mount Auth v1 routes."""
    mounter(
        router,
        prefix="/auth/v1",
        tag="Auth v1",
        description=dedent(
            """
            Auth API (Public)

            Authentication endpoints based on email verification codes.
            """
        ),
    )
