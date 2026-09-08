"""Auth service."""

import dataclasses
import datetime
from typing import Annotated, assert_never

from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.auth.jwt import create_access_token
from azents.core.auth.password import verify_password
from azents.core.config import AuthConfig, EmailConfig
from azents.core.deps import get_auth_config, get_email_config
from azents.core.email.service import EmailService
from azents.repos.auth_operation import AuthOperationRepository
from azents.repos.auth_operation.data import (
    AuthenticationUnavailable,
    PasswordCredentialLookup,
    RefreshAuthenticationSession,
    RefreshTokenRejected,
    VerifiedEmailUserResolve,
)
from azents.repos.auth_operation.data import (
    RegistrationRequired as RepositoryRegistrationRequired,
)
from azents.repos.email_verification.data import EmailVerificationCreate
from azents.repos.email_verification_operation import (
    EmailVerificationOperationRepository,
)
from azents.repos.email_verification_operation.data import EmailVerificationVerify
from azents.repos.session.data import SessionCreate
from azents.services._utils import (
    DEFAULT_EXPIRE_MINUTES,
    generate_code,
    generate_csrf_token,
    generate_refresh_token,
)
from azents.services.credential.service import CredentialService
from azents.services.runtime_terminal.invalidation import (
    RuntimeTerminalInvalidationPublisherDependency,
)

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
    email_verification_operation_repository: Annotated[
        EmailVerificationOperationRepository,
        Depends(EmailVerificationOperationRepository),
    ]
    auth_operation_repository: Annotated[
        AuthOperationRepository,
        Depends(AuthOperationRepository),
    ]
    credential_service: Annotated[CredentialService, Depends()]
    terminal_invalidation_publisher: RuntimeTerminalInvalidationPublisherDependency
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

        await self.email_verification_operation_repository.create_delivery_record(
            create=EmailVerificationCreate(
                email=input.email,
                code=code,
                csrf_token=csrf_token,
                expires_at=expires_at,
            )
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
        mark_result = (
            await self.email_verification_operation_repository.verify_and_mark(
                verification=EmailVerificationVerify(
                    email=input.email,
                    csrf_token=input.csrf_token,
                    code=input.code,
                )
            )
        )
        match mark_result:
            case Success():
                pass
            case Failure():
                return Failure(InvalidVerificationCode())
            case _:
                assert_never(mark_result)

        # Clean stale rows
        await self.email_verification_operation_repository.delete_stale_by_email(
            email=input.email
        )

        resolve_result = (
            await self.auth_operation_repository.resolve_verified_email_user(
                resolve=VerifiedEmailUserResolve(
                    email=input.email,
                    registration_open=self.auth_config.registration_mode == "open",
                )
            )
        )
        if isinstance(resolve_result, Failure):
            error = resolve_result.error
            if isinstance(error, RepositoryRegistrationRequired):
                return Failure(RegistrationRequired())
            if isinstance(error, AuthenticationUnavailable):
                return Failure(InvalidVerificationCode())
            assert_never(error)
        user_id = resolve_result.value.user_id

        # Create session
        refresh_token = generate_refresh_token()
        expires_at = tznow() + self.auth_config.refresh_token.expire_timedelta
        max_expires_at = (
            tznow() + self.auth_config.refresh_token.max_expire_timedelta
            if self.auth_config.refresh_token.max_expire_timedelta is not None
            else None
        )

        session_result = await self.auth_operation_repository.issue_session(
            create=SessionCreate(
                user_id=user_id,
                refresh_token=refresh_token,
                expires_at=expires_at,
                max_expires_at=max_expires_at,
                user_agent=input.user_agent,
                ip_address=input.ip_address,
            )
        )
        match session_result:
            case Success(db_session):
                pass
            case Failure():
                return Failure(InvalidVerificationCode())
            case _:
                assert_never(session_result)

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
        refresh_result = await self.auth_operation_repository.refresh_session(
            refresh=RefreshAuthenticationSession(
                refresh_token=input.refresh_token,
                candidate_refresh_token=generate_refresh_token(),
                rotation_period=self.auth_config.refresh_token.rotation_period,
                grace_period=self.auth_config.refresh_token.grace_period,
                expire_timedelta=self.auth_config.refresh_token.expire_timedelta,
            )
        )
        match refresh_result:
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
            case Failure(error) if isinstance(error, RefreshTokenRejected):
                return Failure(InvalidRefreshToken())
            case Failure(error):
                assert_never(error)
            case _:
                assert_never(refresh_result)

    async def logout(self, input: LogoutInput) -> Result[None, SessionNotFound]:
        """Revoke session.

        :param input: Logout input data
        :return: None on success, error on failure
        """
        result = await self.auth_operation_repository.revoke_session(
            session_id=input.session_id
        )

        match result:
            case Success():
                publisher = self.terminal_invalidation_publisher
                publish = publisher.publish_authentication_session_terminal_invalidation
                await publish(input.session_id)
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
        credential_result = (
            await self.auth_operation_repository.get_password_credential(
                lookup=PasswordCredentialLookup(email=input.email)
            )
        )
        match credential_result:
            case Success(credential):
                pass
            case Failure():
                return Failure(InvalidCredentials())
            case _:
                assert_never(credential_result)

        if not verify_password(input.password, credential.password_hash):
            return Failure(InvalidCredentials())

        refresh_token = generate_refresh_token()
        expires_at = tznow() + self.auth_config.refresh_token.expire_timedelta
        max_expires_at = (
            tznow() + self.auth_config.refresh_token.max_expire_timedelta
            if self.auth_config.refresh_token.max_expire_timedelta is not None
            else None
        )

        session_result = await self.auth_operation_repository.issue_session(
            create=SessionCreate(
                user_id=credential.user_id,
                refresh_token=refresh_token,
                expires_at=expires_at,
                max_expires_at=max_expires_at,
                user_agent=input.user_agent,
                ip_address=input.ip_address,
            )
        )
        match session_result:
            case Success(db_session):
                pass
            case Failure():
                return Failure(InvalidCredentials())
            case _:
                assert_never(session_result)

        # Create JWT access token
        access_token = create_access_token(
            config=self.auth_config.jwt,
            user_id=credential.user_id,
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
