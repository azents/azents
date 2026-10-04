"""Password reset token service."""

import dataclasses
import datetime
import hashlib
import secrets
from typing import Annotated

from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.auth.password import (
    WeakPasswordError,
    hash_password,
    validate_password_strength,
)
from azents.core.config import Config
from azents.core.deps import get_config
from azents.repos.password_reset_token.operations import (
    PasswordResetOperationRepository,
    ResetRedemption,
)
from azents.services.runtime_terminal.invalidation import (
    RuntimeTerminalInvalidationPublisherDependency,
)

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

    operation_repository: Annotated[PasswordResetOperationRepository, Depends()]
    terminal_invalidation_publisher: RuntimeTerminalInvalidationPublisherDependency
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

        token = await self.operation_repository.create(
            user_id=input.user_id,
            email=input.email,
            token_hash=token_hash,
            created_by_user_id=input.created_by_user_id,
            expires_at=expires_at,
        )
        if token is None:
            return Failure(PasswordResetUserNotFound())

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
        result = await self.operation_repository.list_all(offset=offset, limit=limit)
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
        preview = await self.operation_repository.preview(
            token_hash=token_hash, now=now
        )
        if preview is None:
            return PreviewPasswordResetTokenOutput(
                valid=False, email=None, expires_at=None
            )
        return PreviewPasswordResetTokenOutput(
            valid=True,
            email=mask_password_reset_email(preview.email),
            expires_at=preview.expires_at,
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

        user_id = await self.operation_repository.redeem(
            command=ResetRedemption(
                token_hash=token_hash,
                password_hash=password_hash,
                now=now,
                ip_address=input.ip_address,
                user_agent=input.user_agent,
            )
        )
        if user_id is None:
            return Failure(InvalidPasswordResetToken())
        await self.terminal_invalidation_publisher.publish_user_terminal_invalidation(
            user_id
        )
        return Success(None)

    async def revoke(self, token_id: str) -> bool:
        """Revoke Password reset token."""
        return await self.operation_repository.revoke(token_id=token_id)

    def build_reset_url(self, token: str) -> str:
        """Create Password reset URL."""
        path = f"/reset-password?token={token}"
        if self.config.web_url:
            return f"{self.config.web_url}{path}"
        return path
