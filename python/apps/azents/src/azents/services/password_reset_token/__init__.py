"""Password reset token service."""

import dataclasses
import datetime
import hashlib
import secrets
from typing import Annotated, assert_never

from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.auth.password import (
    WeakPasswordError,
    hash_password,
    validate_password_strength,
)
from azents.core.config import Config
from azents.core.deps import get_config
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.password_login.data import PasswordLoginCreate
from azents.repos.password_reset_token import PasswordResetTokenRepository
from azents.repos.password_reset_token.data import (
    PasswordResetTokenCreate,
    PasswordResetTokenRedemptionCreate,
    PasswordResetTokenUnavailable,
)
from azents.repos.session import SessionRepository
from azents.repos.user import UserRepository
from azents.repos.user_email import UserEmailRepository

from .data import (
    CreatePasswordResetTokenInput,
    InvalidPasswordResetToken,
    PasswordResetTokenListOutput,
    PasswordResetTokenOutput,
    PasswordResetTokenWithPlaintextOutput,
    PasswordResetUserNotFound,
    PreviewPasswordResetTokenInput,
    PreviewPasswordResetTokenOutput,
    RedeemPasswordResetTokenInput,
    WeakResetPassword,
)

_PASSWORD_RESET_TOKEN_BYTES = 32
_DEFAULT_PASSWORD_RESET_EXPIRE_HOURS = 24


def generate_password_reset_token() -> str:
    """Create plaintext password reset token."""
    return secrets.token_urlsafe(_PASSWORD_RESET_TOKEN_BYTES)


def hash_password_reset_token(token: str) -> str:
    """Hash plaintext password reset token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mask_password_reset_email(email: str) -> str:
    """Create email hint for password reset preview."""
    local, separator, domain = email.partition("@")
    if separator == "":
        return "***"
    local_hint = f"{local[:1]}***" if local else "***"
    return f"{local_hint}@{domain}"


@dataclasses.dataclass
class PasswordResetTokenService:
    """Password reset token service."""

    password_reset_token_repo: Annotated[PasswordResetTokenRepository, Depends()]
    user_repo: Annotated[UserRepository, Depends()]
    user_email_repo: Annotated[UserEmailRepository, Depends()]
    password_login_repo: Annotated[PasswordLoginRepository, Depends()]
    session_repo: Annotated[SessionRepository, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    config: Annotated[Config, Depends(get_config)]

    async def create(
        self,
        input: CreatePasswordResetTokenInput,
    ) -> Result[PasswordResetTokenWithPlaintextOutput, PasswordResetUserNotFound]:
        """Create Password reset token."""
        plaintext_token = generate_password_reset_token()
        token_hash = hash_password_reset_token(plaintext_token)
        now = tznow()
        expires_at = input.expires_at or (
            now + datetime.timedelta(hours=_DEFAULT_PASSWORD_RESET_EXPIRE_HOURS)
        )

        async with self.session_manager() as session:
            user = None
            if input.user_id is not None:
                user = await self.user_repo.get(session, input.user_id)
            elif input.email is not None:
                user = await self.user_repo.get_by_email(session, input.email)
            if user is None:
                return Failure(PasswordResetUserNotFound())

            token = await self.password_reset_token_repo.create(
                session,
                PasswordResetTokenCreate(
                    token_hash=token_hash,
                    user_id=user.id,
                    created_by_user_id=input.created_by_user_id,
                    expires_at=expires_at,
                ),
            )

        return Success(
            PasswordResetTokenWithPlaintextOutput(
                token=PasswordResetTokenOutput.convert_from(token),
                plaintext_token=plaintext_token,
                reset_url=self.build_reset_url(plaintext_token),
            )
        )

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> PasswordResetTokenListOutput:
        """Fetch Password reset token list."""
        async with self.session_manager() as session:
            result = await self.password_reset_token_repo.list_all(
                session,
                offset=offset,
                limit=limit,
            )
        return PasswordResetTokenListOutput(
            items=[
                PasswordResetTokenOutput.convert_from(token) for token in result.items
            ],
            total=result.total,
        )

    async def preview(
        self,
        input: PreviewPasswordResetTokenInput,
    ) -> PreviewPasswordResetTokenOutput:
        """Preview Password reset token status."""
        token_hash = hash_password_reset_token(input.token)
        now = tznow()
        async with self.session_manager() as session:
            token = await self.password_reset_token_repo.get_by_token_hash(
                session,
                token_hash,
            )
            if token is None:
                return PreviewPasswordResetTokenOutput(
                    valid=False,
                    email=None,
                    expires_at=None,
                )
            if token.revoked_at is not None or token.used_at is not None:
                return PreviewPasswordResetTokenOutput(
                    valid=False,
                    email=None,
                    expires_at=None,
                )
            if token.expires_at <= now:
                return PreviewPasswordResetTokenOutput(
                    valid=False,
                    email=None,
                    expires_at=None,
                )
            user = await self.user_repo.get(session, token.user_id)
            if user is None:
                return PreviewPasswordResetTokenOutput(
                    valid=False,
                    email=None,
                    expires_at=None,
                )
        return PreviewPasswordResetTokenOutput(
            valid=True,
            email=mask_password_reset_email(user.primary_email),
            expires_at=token.expires_at,
        )

    async def redeem(
        self,
        input: RedeemPasswordResetTokenInput,
    ) -> Result[None, InvalidPasswordResetToken | WeakResetPassword]:
        """Create/update password credential using Password reset token."""
        try:
            validate_password_strength(input.password)
        except WeakPasswordError as error:
            return Failure(WeakResetPassword(message=error.message))

        token_hash = hash_password_reset_token(input.token)
        now = tznow()
        password_hash = hash_password(input.password)

        async with self.session_manager() as session:
            available_result = (
                await self.password_reset_token_repo.get_available_by_token_hash(
                    session,
                    token_hash,
                    now=now,
                )
            )
            match available_result:
                case Success(token):
                    pass
                case Failure(error):
                    match error:
                        case PasswordResetTokenUnavailable():
                            return Failure(InvalidPasswordResetToken())
                        case _:
                            assert_never(error)
                case _:
                    assert_never(available_result)

            user = await self.user_repo.get(session, token.user_id)
            if user is None:
                return Failure(InvalidPasswordResetToken())

            claim_result = await self.password_reset_token_repo.claim_for_redemption(
                session,
                token_hash,
                now=now,
            )
            match claim_result:
                case Success(token):
                    pass
                case Failure(error):
                    match error:
                        case PasswordResetTokenUnavailable():
                            return Failure(InvalidPasswordResetToken())
                        case _:
                            assert_never(error)
                case _:
                    assert_never(claim_result)

            existing = await self.password_login_repo.get_by_user_id(
                session,
                token.user_id,
            )
            if existing is not None:
                update_result = await self.password_login_repo.update_password_hash(
                    session,
                    token.user_id,
                    password_hash,
                )
                match update_result:
                    case Success():
                        pass
                    case Failure():
                        return Failure(InvalidPasswordResetToken())
                    case _:
                        assert_never(update_result)
            else:
                create_result = await self.password_login_repo.create(
                    session,
                    PasswordLoginCreate(
                        user_id=token.user_id,
                        password_hash=password_hash,
                    ),
                )
                match create_result:
                    case Success():
                        pass
                    case Failure():
                        update_result = (
                            await self.password_login_repo.update_password_hash(
                                session,
                                token.user_id,
                                password_hash,
                            )
                        )
                        match update_result:
                            case Success():
                                pass
                            case Failure():
                                return Failure(InvalidPasswordResetToken())
                            case _:
                                assert_never(update_result)
                    case _:
                        assert_never(create_result)

            await self.session_repo.revoke_all_by_user(session, token.user_id)
            await self.password_reset_token_repo.create_redemption(
                session,
                PasswordResetTokenRedemptionCreate(
                    password_reset_token_id=token.id,
                    user_id=token.user_id,
                    ip_address=input.ip_address,
                    user_agent=input.user_agent,
                    redeemed_at=now,
                ),
            )
        return Success(None)

    async def revoke(self, token_id: str) -> bool:
        """Revoke Password reset token."""
        async with self.session_manager() as session:
            return await self.password_reset_token_repo.revoke(
                session,
                token_id,
                revoked_at=tznow(),
            )

    def build_reset_url(self, token: str) -> str:
        """Create Password reset URL."""
        path = f"/reset-password?token={token}"
        if self.config.web_url:
            return f"{self.config.web_url}{path}"
        return path
