"""Security service."""

import dataclasses
import datetime
from typing import Annotated, assert_never

from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.auth.jwt import create_access_token
from azents.core.auth.password import (
    WeakPasswordError,
    hash_password,
    validate_password_strength,
    verify_password,
)
from azents.core.config import AuthConfig, EmailConfig
from azents.core.deps import get_auth_config, get_email_config
from azents.core.email.service import EmailService
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.email_verification import EmailVerificationRepository
from azents.repos.email_verification.data import EmailVerificationCreate
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.password_login.data import PasswordLoginCreate
from azents.repos.user import UserRepository
from azents.services._utils import (
    DEFAULT_EXPIRE_MINUTES,
    generate_code,
    generate_csrf_token,
)
from azents.services.credential.data import CredentialType, CredentialUnavailableReason
from azents.services.credential.service import CredentialService

from .data import (
    AuthMethod,
    ElevateOutput,
    ElevateWithEmailInput,
    ElevateWithPasswordInput,
    GetAuthMethodsInput,
    GetAuthMethodsOutput,
    InvalidElevationCode,
    InvalidPassword,
    LastCredentialRemovalDenied,
    PasswordNotSet,
    RemovePasswordInput,
    SendElevationCodeInput,
    SendElevationCodeOutput,
    SetPasswordInput,
    UserNotFound,
    WeakPassword,
)


@dataclasses.dataclass
class SecurityService:
    """Security service.

    Handles auth method management, step-up auth, and password setup/deletion.
    """

    email_service: Annotated[EmailService, Depends()]
    email_verification_repo: Annotated[EmailVerificationRepository, Depends()]
    password_login_repo: Annotated[PasswordLoginRepository, Depends()]
    user_repo: Annotated[UserRepository, Depends()]
    credential_service: Annotated[CredentialService, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    auth_config: Annotated[AuthConfig, Depends(get_auth_config)]
    email_config: Annotated[EmailConfig | None, Depends(get_email_config)]

    async def get_auth_methods(
        self, input: GetAuthMethodsInput
    ) -> Result[GetAuthMethodsOutput, UserNotFound]:
        """Fetch available auth methods.

        :param input: Lookup input data
        :return: Auth method list or error
        """
        projections = await self.credential_service.get_security_projection(
            user_id=input.user_id
        )
        if projections is None:
            return Failure(UserNotFound(user_id=input.user_id))

        methods = [
            AuthMethod(
                type=projection.type.value,
                enabled=projection.enabled,
                configured=projection.configured,
                valid=projection.valid,
                can_login=projection.can_login,
                can_elevate=projection.can_elevate,
                can_remove=projection.can_remove,
                unavailable_reason=projection.unavailable_reason.value
                if projection.unavailable_reason is not None
                else None,
            )
            for projection in projections
        ]
        return Success(GetAuthMethodsOutput(methods=methods))

    async def get_elevation_methods(
        self, input: GetAuthMethodsInput
    ) -> Result[GetAuthMethodsOutput, UserNotFound]:
        """Fetch auth methods available for Elevation.

        :param input: Lookup input data
        :return: Auth method list or error
        """
        projections = await self.credential_service.get_elevation_projection(
            user_id=input.user_id
        )
        if projections is None:
            return Failure(UserNotFound(user_id=input.user_id))

        methods = [
            AuthMethod(
                type=projection.type.value,
                enabled=projection.enabled,
                configured=projection.configured,
                valid=projection.valid,
                can_login=projection.can_login,
                can_elevate=projection.can_elevate,
                can_remove=projection.can_remove,
                unavailable_reason=projection.unavailable_reason.value
                if projection.unavailable_reason is not None
                else None,
            )
            for projection in projections
        ]
        return Success(GetAuthMethodsOutput(methods=methods))

    async def send_elevation_code(
        self, input: SendElevationCodeInput
    ) -> Result[SendElevationCodeOutput, UserNotFound]:
        """Send email OTP for step-up auth.

        :param input: Send input data
        :return: Output including CSRF token or error
        """
        async with self.session_manager() as session:
            user = await self.user_repo.get(session, input.user_id)
            if user is None:
                return Failure(UserNotFound(user_id=input.user_id))

        email = user.primary_email
        code = generate_code()
        csrf_token = generate_csrf_token()
        expire_minutes = (
            self.email_config.verification_expire_minutes
            if self.email_config is not None
            else DEFAULT_EXPIRE_MINUTES
        )
        expires_at = tznow() + datetime.timedelta(minutes=expire_minutes)

        async with self.session_manager() as session:
            await self.email_verification_repo.delete_stale_by_email(session, email)
            await self.email_verification_repo.create(
                session,
                EmailVerificationCreate(
                    email=email,
                    code=code,
                    csrf_token=csrf_token,
                    expires_at=expires_at,
                ),
            )

        await self.email_service.send_verification_code(
            to_email=email,
            code=code,
            expire_minutes=expire_minutes,
        )

        return Success(SendElevationCodeOutput(csrf_token=csrf_token))

    async def elevate_with_email(
        self, input: ElevateWithEmailInput
    ) -> Result[ElevateOutput, InvalidElevationCode]:
        """Perform elevation with email OTP.

        :param input: elevation input data
        :return: elevated access token or error
        """
        # Fetch primary email of user
        async with self.session_manager() as session:
            user = await self.user_repo.get(session, input.user_id)
            if user is None:
                return Failure(InvalidElevationCode())

        email = user.primary_email

        # Verify verification code
        async with self.session_manager() as session:
            verification = await self.email_verification_repo.get_by_email_and_csrf(
                session, email, input.csrf_token
            )
            if verification is None:
                return Failure(InvalidElevationCode())

            if verification.expires_at < tznow():
                return Failure(InvalidElevationCode())

            if verification.verified_at is not None:
                return Failure(InvalidElevationCode())

            if verification.code.upper() != input.code.upper():
                return Failure(InvalidElevationCode())

            mark_result = await self.email_verification_repo.mark_verified(
                session, verification.id
            )
            match mark_result:
                case Success():
                    pass
                case Failure():
                    return Failure(InvalidElevationCode())
                case _:
                    assert_never(mark_result)

        # Clean stale rows
        async with self.session_manager() as session:
            await self.email_verification_repo.delete_stale_by_email(session, email)

        # Create elevated access token
        access_token = create_access_token(
            config=self.auth_config.jwt,
            user_id=input.user_id,
            session_id=input.session_id,
            elevated=True,
        )

        return Success(
            ElevateOutput(
                access_token=access_token,
                expires_in=self.auth_config.jwt.access_token_expire_seconds,
            )
        )

    async def elevate_with_password(
        self, input: ElevateWithPasswordInput
    ) -> Result[ElevateOutput, InvalidPassword | PasswordNotSet]:
        """Perform elevation with password.

        :param input: elevation input data
        :return: elevated access token or error
        """
        async with self.session_manager() as session:
            password_login = await self.password_login_repo.get_by_user_id(
                session, input.user_id
            )

        if password_login is None:
            return Failure(PasswordNotSet())

        if not verify_password(input.password, password_login.password_hash):
            return Failure(InvalidPassword())

        # Create elevated access token
        access_token = create_access_token(
            config=self.auth_config.jwt,
            user_id=input.user_id,
            session_id=input.session_id,
            elevated=True,
        )

        return Success(
            ElevateOutput(
                access_token=access_token,
                expires_in=self.auth_config.jwt.access_token_expire_seconds,
            )
        )

    async def set_password(
        self, input: SetPasswordInput
    ) -> Result[None, WeakPassword | UserNotFound]:
        """Set or change password.

        :param input: Password setup input data
        :return: Success or error
        """
        # Validate password strength
        try:
            validate_password_strength(input.password)
        except WeakPasswordError as e:
            return Failure(WeakPassword(message=e.message))

        password_hash = hash_password(input.password)

        async with self.session_manager() as session:
            user = await self.user_repo.get(session, input.user_id)
            if user is None:
                return Failure(UserNotFound(user_id=input.user_id))

            # upsert: update existing password if present, create if absent
            existing = await self.password_login_repo.get_by_user_id(
                session, input.user_id
            )
            if existing is not None:
                result = await self.password_login_repo.update_password_hash(
                    session, input.user_id, password_hash
                )
                match result:
                    case Success():
                        pass
                    case Failure():
                        return Failure(UserNotFound(user_id=input.user_id))
                    case _:
                        assert_never(result)
            else:
                create_result = await self.password_login_repo.create(
                    session,
                    PasswordLoginCreate(
                        user_id=input.user_id,
                        password_hash=password_hash,
                    ),
                )
                match create_result:
                    case Success():
                        pass
                    case Failure():
                        # AlreadyExists (race condition) → fallback to update
                        update_result = (
                            await self.password_login_repo.update_password_hash(
                                session, input.user_id, password_hash
                            )
                        )
                        match update_result:
                            case Success():
                                pass
                            case Failure():
                                return Failure(UserNotFound(user_id=input.user_id))
                            case _:
                                assert_never(update_result)
                    case _:
                        assert_never(create_result)

        return Success(None)

    async def remove_password(
        self, input: RemovePasswordInput
    ) -> Result[None, PasswordNotSet | LastCredentialRemovalDenied]:
        """Delete password.

        :param input: Password deletion input data
        :return: Success or error
        """
        remove_check = await self.credential_service.check_remove_allowed(
            user_id=input.user_id,
            credential_type=CredentialType.PASSWORD,
        )
        if remove_check is None:
            return Failure(PasswordNotSet())
        if not remove_check.allowed:
            if remove_check.reason == CredentialUnavailableReason.NOT_CONFIGURED:
                return Failure(PasswordNotSet())
            return Failure(LastCredentialRemovalDenied())

        async with self.session_manager() as session:
            result = await self.password_login_repo.delete_by_user_id(
                session, input.user_id
            )

        match result:
            case Success():
                return Success(None)
            case Failure():
                return Failure(PasswordNotSet())
            case _:
                assert_never(result)
