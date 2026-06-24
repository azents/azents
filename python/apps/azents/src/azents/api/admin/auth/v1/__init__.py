"""Auth v1 Admin API.

Authentication record lookup endpoints for E2E tests.
"""

from textwrap import dedent
from typing import Annotated, assert_never

from azcommon.result import Failure, Success
from fastapi import APIRouter, Depends, HTTPException, status

from azents.core.auth.deps import CurrentUser, get_current_user_optional
from azents.services.email_verification import EmailVerificationService
from azents.services.password_reset_token import PasswordResetTokenService
from azents.services.password_reset_token.data import (
    CreatePasswordResetTokenInput,
    PasswordResetUserNotFound,
)
from azents.services.signup_token import SignupTokenService
from azents.services.signup_token.data import CreateSignupTokenInput
from azents.utils.fastapi.route import RouteMounter

from .data import (
    CreatePasswordResetTokenRequest,
    CreatePasswordResetTokenResponse,
    CreateSignupTokenRequest,
    CreateSignupTokenResponse,
    EmailVerificationListResponse,
    EmailVerificationResponse,
    PasswordResetTokenListResponse,
    PasswordResetTokenResponse,
    SignupTokenListResponse,
    SignupTokenResponse,
)

router = APIRouter()


# =============================================================================
# Email Verifications
# =============================================================================


@router.get("/email-verifications")
async def list_email_verifications(
    ev_service: Annotated[EmailVerificationService, Depends()],
    *,
    offset: int = 0,
    limit: int = 50,
) -> EmailVerificationListResponse:
    """List EmailVerification records."""
    result = await ev_service.list_all(offset=offset, limit=limit)
    return EmailVerificationListResponse(
        items=[EmailVerificationResponse.convert_from(v) for v in result.items],
        total=result.total,
    )


@router.get("/email-verifications/by-email")
async def get_email_verification_by_email(
    ev_service: Annotated[EmailVerificationService, Depends()],
    *,
    email: str,
    csrf_token: str,
) -> EmailVerificationResponse:
    """Get an EmailVerification by email and CSRF token."""
    verification = await ev_service.get_by_email_and_csrf(email, csrf_token)
    if verification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authentication record not found.",
        )
    return EmailVerificationResponse.convert_from(verification)


@router.get("/email-verifications/{verification_id}")
async def get_email_verification(
    ev_service: Annotated[EmailVerificationService, Depends()],
    *,
    verification_id: str,
) -> EmailVerificationResponse:
    """Get an EmailVerification by ID."""
    verification = await ev_service.get(verification_id)
    if verification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authentication record not found.",
        )
    return EmailVerificationResponse.convert_from(verification)


@router.get("/email-verifications/by-email/{email}")
async def list_email_verifications_by_email(
    ev_service: Annotated[EmailVerificationService, Depends()],
    *,
    email: str,
    offset: int = 0,
    limit: int = 20,
) -> EmailVerificationListResponse:
    """List active EmailVerification records by email."""
    result = await ev_service.list_by_email(email, offset=offset, limit=limit)
    return EmailVerificationListResponse(
        items=[EmailVerificationResponse.convert_from(v) for v in result.items],
        total=result.total,
    )


# =============================================================================
# Signup Tokens
# =============================================================================


@router.post("/signup-tokens")
async def create_signup_token(
    signup_token_service: Annotated[SignupTokenService, Depends()],
    current_user: Annotated[CurrentUser | None, Depends(get_current_user_optional)],
    request_body: CreateSignupTokenRequest,
) -> CreateSignupTokenResponse:
    """Create a signup token."""
    output = await signup_token_service.create(
        CreateSignupTokenInput(
            email=request_body.email,
            created_by_user_id=current_user.user_id if current_user else None,
            delivery_method=request_body.delivery_method,
            expires_at=None,
            max_uses=None,
        )
    )
    return CreateSignupTokenResponse(
        token=SignupTokenResponse.convert_from(output.token),
        plaintext_token=output.plaintext_token,
    )


@router.get("/signup-tokens")
async def list_signup_tokens(
    signup_token_service: Annotated[SignupTokenService, Depends()],
    *,
    offset: int = 0,
    limit: int = 50,
) -> SignupTokenListResponse:
    """List signup tokens."""
    output = await signup_token_service.list_all(offset=offset, limit=limit)
    return SignupTokenListResponse(
        items=[SignupTokenResponse.convert_from(token) for token in output.items],
        total=output.total,
    )


@router.delete("/signup-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_signup_token(
    signup_token_service: Annotated[SignupTokenService, Depends()],
    *,
    token_id: str,
) -> None:
    """Revoke a signup token."""
    revoked = await signup_token_service.revoke(token_id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Signup token not found.",
        )


# =============================================================================
# Password Reset Tokens
# =============================================================================


@router.post("/password-reset-tokens")
async def create_password_reset_token(
    password_reset_token_service: Annotated[PasswordResetTokenService, Depends()],
    current_user: Annotated[CurrentUser | None, Depends(get_current_user_optional)],
    request_body: CreatePasswordResetTokenRequest,
) -> CreatePasswordResetTokenResponse:
    """Create a password reset token."""
    result = await password_reset_token_service.create(
        CreatePasswordResetTokenInput(
            user_id=request_body.user_id,
            email=request_body.email,
            created_by_user_id=current_user.user_id if current_user else None,
            expires_at=None,
        )
    )
    match result:
        case Success(value):
            return CreatePasswordResetTokenResponse(
                token=PasswordResetTokenResponse.convert_from(value.token),
                plaintext_token=value.plaintext_token,
                reset_url=value.reset_url,
            )
        case Failure(error):
            match error:
                case PasswordResetUserNotFound():
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Password reset user not found.",
                    )
                case _:
                    assert_never(error)
        case _:
            assert_never(result)


@router.get("/password-reset-tokens")
async def list_password_reset_tokens(
    password_reset_token_service: Annotated[PasswordResetTokenService, Depends()],
    *,
    offset: int = 0,
    limit: int = 50,
) -> PasswordResetTokenListResponse:
    """List password reset tokens."""
    output = await password_reset_token_service.list_all(offset=offset, limit=limit)
    return PasswordResetTokenListResponse(
        items=[
            PasswordResetTokenResponse.convert_from(token) for token in output.items
        ],
        total=output.total,
    )


@router.delete(
    "/password-reset-tokens/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_password_reset_token(
    password_reset_token_service: Annotated[PasswordResetTokenService, Depends()],
    *,
    token_id: str,
) -> None:
    """Revoke a password reset token."""
    revoked = await password_reset_token_service.revoke(token_id)
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Password reset token not found.",
        )


def mount(mounter: RouteMounter) -> None:
    """Mount Auth v1 Admin routes."""
    mounter(
        router,
        prefix="/auth/v1",
        tag="Auth v1",
        description=dedent(
            """
            Auth API (Admin)

            Authentication record lookup endpoints for E2E tests.
            """
        ),
    )
