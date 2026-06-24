"""Auth service."""

import dataclasses
import datetime
from typing import Annotated, assert_never

from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.auth.jwt import create_access_token
from azents.core.auth.password import verify_password
from azents.core.config import AuthConfig, EmailConfig
from azents.core.deps import get_auth_config, get_email_config
from azents.core.email.service import EmailService
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.email_verification import EmailVerificationRepository
from azents.repos.email_verification.data import EmailVerificationCreate
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.session import SessionRepository
from azents.repos.session.data import SessionCreate, TokenMatch
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.user_email import UserEmailRepository
from azents.services._utils import (
    DEFAULT_EXPIRE_MINUTES,
    generate_code,
    generate_csrf_token,
    generate_refresh_token,
)
from azents.services.credential.service import CredentialService

from .data import (
    InvalidCredentials,
    InvalidRefreshToken,
    InvalidVerificationCode,
    LoginMethodsInput,
    LoginMethodsOutput,
    LogoutInput,
    PasswordLoginInput,
    PasswordLoginOutput,
    RefreshTokenInput,
    RefreshTokenOutput,
    RegistrationRequired,
    SendCodeInput,
    SendCodeOutput,
    SessionNotFound,
    VerifyCodeInput,
    VerifyCodeOutput,
)


@dataclasses.dataclass
class AuthService:
    """Integrated auth service.

    Handles email verification code send/verify, session management, and token refresh.
    """

    email_service: Annotated[EmailService, Depends()]
    email_verification_repo: Annotated[EmailVerificationRepository, Depends()]
    user_repo: Annotated[UserRepository, Depends()]
    user_email_repo: Annotated[UserEmailRepository, Depends()]
    password_login_repo: Annotated[PasswordLoginRepository, Depends()]
    session_repo: Annotated[SessionRepository, Depends()]
    credential_service: Annotated[CredentialService, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    auth_config: Annotated[AuthConfig, Depends(get_auth_config)]
    email_config: Annotated[EmailConfig | None, Depends(get_email_config)]

    async def send_code(self, input: SendCodeInput) -> SendCodeOutput:
        """Send email verification code.

        :param input: Send input data
        :return: Output including CSRF token
        """
        code = generate_code()
        csrf_token = generate_csrf_token()
        expire_minutes = (
            self.email_config.verification_expire_minutes
            if self.email_config is not None
            else DEFAULT_EXPIRE_MINUTES
        )
        expires_at = tznow() + datetime.timedelta(minutes=expire_minutes)

        async with self.session_manager() as session:
            # Clean stale verification records for this email
            await self.email_verification_repo.delete_stale_by_email(
                session, input.email
            )
            await self.email_verification_repo.create(
                session,
                EmailVerificationCreate(
                    email=input.email,
                    code=code,
                    csrf_token=csrf_token,
                    expires_at=expires_at,
                ),
            )

        await self.email_service.send_verification_code(
            to_email=input.email,
            code=code,
            expire_minutes=expire_minutes,
        )

        return SendCodeOutput(csrf_token=csrf_token)

    async def verify_code(
        self, input: VerifyCodeInput
    ) -> Result[VerifyCodeOutput, InvalidVerificationCode | RegistrationRequired]:
        """Verify verification code and create session.

        Automatically create User + UserEmail for a new email.

        :param input: Verification input data
        :return: Tokens on success, error on failure
        """
        # Verify verification code
        async with self.session_manager() as session:
            verification = await self.email_verification_repo.get_by_email_and_csrf(
                session, input.email, input.csrf_token
            )
            if verification is None:
                return Failure(InvalidVerificationCode())

            # Check expiration
            if verification.expires_at < tznow():
                return Failure(InvalidVerificationCode())

            # Already verified
            if verification.verified_at is not None:
                return Failure(InvalidVerificationCode())

            # Compare code (case-insensitive)
            if verification.code.upper() != input.code.upper():
                return Failure(InvalidVerificationCode())

            # Mark verified
            mark_result = await self.email_verification_repo.mark_verified(
                session, verification.id
            )
            match mark_result:
                case Success():
                    pass
                case Failure():
                    return Failure(InvalidVerificationCode())
                case _:
                    assert_never(mark_result)

        # Clean stale rows
        async with self.session_manager() as session:
            await self.email_verification_repo.delete_stale_by_email(
                session, input.email
            )

        # Fetch or automatically create User
        async with self.session_manager() as session:
            user_email = await self.user_email_repo.get_by_email(session, input.email)

            if user_email is None:
                if self.auth_config.registration_mode != "open":
                    return Failure(RegistrationRequired())
                user = await self.user_repo.create(
                    session,
                    UserCreate(email=input.email),
                )
                user_id = user.id
            else:
                user_id = user_email.user_id

        # Create session
        refresh_token = generate_refresh_token()
        expires_at = tznow() + self.auth_config.refresh_token.expire_timedelta
        max_expires_at = (
            tznow() + self.auth_config.refresh_token.max_expire_timedelta
            if self.auth_config.refresh_token.max_expire_timedelta is not None
            else None
        )

        async with self.session_manager() as session:
            db_session = await self.session_repo.create(
                session,
                SessionCreate(
                    user_id=user_id,
                    refresh_token=refresh_token,
                    expires_at=expires_at,
                    max_expires_at=max_expires_at,
                    user_agent=input.user_agent,
                    ip_address=input.ip_address,
                ),
            )

        # Create JWT access token
        access_token = create_access_token(
            config=self.auth_config.jwt,
            user_id=user_id,
            session_id=db_session.id,
        )

        return Success(
            VerifyCodeOutput(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in=self.auth_config.jwt.access_token_expire_seconds,
            )
        )

    async def refresh_token(
        self, input: RefreshTokenInput
    ) -> Result[RefreshTokenOutput, InvalidRefreshToken]:
        """Refresh refresh token.

        :param input: Refresh input data
        :return: New tokens on success, error on failure
        """
        async with self.session_manager() as session:
            result = await self.session_repo.get_by_refresh_token(
                session, input.refresh_token
            )
            if result is None:
                return Failure(InvalidRefreshToken())

            db_session, token_match = result

            # Revoked session
            if db_session.is_revoked:
                return Failure(InvalidRefreshToken())

            # Expired session
            if db_session.is_expired:
                return Failure(InvalidRefreshToken())

            # Check grace period for previous token
            if token_match == TokenMatch.PREVIOUS:
                grace_period = self.auth_config.refresh_token.grace_period
                if (tznow() - db_session.refresh_token_created_at) > grace_period:
                    return Failure(InvalidRefreshToken())

                # Previous token within grace period -> return current session as-is
                access_token = create_access_token(
                    config=self.auth_config.jwt,
                    user_id=db_session.user_id,
                    session_id=db_session.id,
                )
                return Success(
                    RefreshTokenOutput(
                        access_token=access_token,
                        refresh_token=db_session.refresh_token,
                        expires_in=self.auth_config.jwt.access_token_expire_seconds,
                    )
                )

            # Current token -> check rotation interval
            rotation_period = self.auth_config.refresh_token.rotation_period
            if (tznow() - db_session.refresh_token_created_at) < rotation_period:
                # Below rotation interval -> return existing token as-is
                access_token = create_access_token(
                    config=self.auth_config.jwt,
                    user_id=db_session.user_id,
                    session_id=db_session.id,
                )
                return Success(
                    RefreshTokenOutput(
                        access_token=access_token,
                        refresh_token=db_session.refresh_token,
                        expires_in=self.auth_config.jwt.access_token_expire_seconds,
                    )
                )

            # Refresh token rotation
            new_refresh_token = generate_refresh_token()
            new_expires_at = tznow() + self.auth_config.refresh_token.expire_timedelta

            rotate_result = await self.session_repo.rotate_refresh_token(
                session,
                db_session.id,
                db_session.refresh_token,
                new_refresh_token,
                new_expires_at,
            )

        match rotate_result:
            case Success(updated_session):
                access_token = create_access_token(
                    config=self.auth_config.jwt,
                    user_id=updated_session.user_id,
                    session_id=updated_session.id,
                )
                return Success(
                    RefreshTokenOutput(
                        access_token=access_token,
                        refresh_token=updated_session.refresh_token,
                        expires_in=self.auth_config.jwt.access_token_expire_seconds,
                    )
                )
            case Failure():
                return Failure(InvalidRefreshToken())
            case _:
                assert_never(rotate_result)

    async def logout(self, input: LogoutInput) -> Result[None, SessionNotFound]:
        """Revoke session.

        :param input: Logout input data
        :return: None on success, error on failure
        """
        async with self.session_manager() as session:
            result = await self.session_repo.revoke(session, input.session_id)

        match result:
            case Success():
                return Success(None)
            case Failure():
                return Failure(SessionNotFound(session_id=input.session_id))
            case _:
                assert_never(result)

    async def login_with_password(
        self, input: PasswordLoginInput
    ) -> Result[PasswordLoginOutput, InvalidCredentials]:
        """Log in with password.

        Fetch user by email, then verify password and create session.

        :param input: Password login input data
        :return: Tokens on success, error on failure
        """
        # Fetch user by email
        async with self.session_manager() as session:
            user = await self.user_repo.get_by_email(session, input.email)
            if user is None:
                return Failure(InvalidCredentials())

            # Check password
            password_login = await self.password_login_repo.get_by_user_id(
                session, user.id
            )
            if password_login is None:
                return Failure(InvalidCredentials())

        if not verify_password(input.password, password_login.password_hash):
            return Failure(InvalidCredentials())

        # Create session
        refresh_token = generate_refresh_token()
        expires_at = tznow() + self.auth_config.refresh_token.expire_timedelta
        max_expires_at = (
            tznow() + self.auth_config.refresh_token.max_expire_timedelta
            if self.auth_config.refresh_token.max_expire_timedelta is not None
            else None
        )

        async with self.session_manager() as session:
            db_session = await self.session_repo.create(
                session,
                SessionCreate(
                    user_id=user.id,
                    refresh_token=refresh_token,
                    expires_at=expires_at,
                    max_expires_at=max_expires_at,
                    user_agent=input.user_agent,
                    ip_address=input.ip_address,
                ),
            )

        # Create JWT access token
        access_token = create_access_token(
            config=self.auth_config.jwt,
            user_id=user.id,
            session_id=db_session.id,
        )

        return Success(
            PasswordLoginOutput(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in=self.auth_config.jwt.access_token_expire_seconds,
            )
        )

    async def get_login_methods(self, input: LoginMethodsInput) -> LoginMethodsOutput:
        """Fetch login methods available for email.

        :param input: Login method lookup input data
        :return: Login method information
        """
        projection = await self.credential_service.get_login_projection(
            email=input.email
        )
        return LoginMethodsOutput(
            has_password=projection.has_password,
            email_available=projection.email_available,
        )
