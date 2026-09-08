"""Security service."""

import dataclasses
import datetime
from typing import Annotated, assert_never

from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from fastapi import Depends

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
from azents.repos.email_verification.data import EmailVerificationCreate
from azents.repos.email_verification_operation import (
    EmailVerificationOperationRepository,
)
from azents.repos.email_verification_operation.data import EmailVerificationVerify
from azents.repos.security_operation import (
    PasswordRemovalOutcome,
    SecurityOperationRepository,
)
from azents.services._utils import (
    DEFAULT_EXPIRE_MINUTES,
    generate_code,
    generate_csrf_token,
)
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
    email_verification_operation_repository: Annotated[
        EmailVerificationOperationRepository,
        Depends(EmailVerificationOperationRepository),
    ]
    operation_repository: Annotated[SecurityOperationRepository, Depends()]
    credential_service: Annotated[CredentialService, Depends()]
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
        user = await self.operation_repository.get_user(input.user_id)
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

        await self.email_verification_operation_repository.create_delivery_record(
            create=EmailVerificationCreate(
                email=email,
                code=code,
                csrf_token=csrf_token,
                expires_at=expires_at,
            )
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
        user = await self.operation_repository.get_user(input.user_id)
        if user is None:
            return Failure(InvalidElevationCode())

        email = user.primary_email

        mark_result = (
            await self.email_verification_operation_repository.verify_and_mark(
                verification=EmailVerificationVerify(
                    email=email,
                    csrf_token=input.csrf_token,
                    code=input.code,
                )
            )
        )
        match mark_result:
            case Success():
                pass
            case Failure():
                return Failure(InvalidElevationCode())
            case _:
                assert_never(mark_result)

        # Clean stale rows
        await self.email_verification_operation_repository.delete_stale_by_email(
            email=email
        )

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
        password_login = await self.operation_repository.get_password(input.user_id)

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

        if not await self.operation_repository.set_password(
            input.user_id, password_hash
        ):
            return Failure(UserNotFound(user_id=input.user_id))
        return Success(None)

    async def remove_password(
        self, input: RemovePasswordInput
    ) -> Result[None, PasswordNotSet | LastCredentialRemovalDenied]:
        """Delete password.

        :param input: Password deletion input data
        :return: Success or error
        """
        outcome = await self.operation_repository.remove_password(
            input.user_id,
            email_available=self.email_service.configured,
        )
        match outcome:
            case PasswordRemovalOutcome.REMOVED:
                return Success(None)
            case PasswordRemovalOutcome.NOT_SET:
                return Failure(PasswordNotSet())
            case PasswordRemovalOutcome.LAST_CREDENTIAL:
                return Failure(LastCredentialRemovalDenied())
            case _:
                assert_never(outcome)
