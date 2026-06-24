"""Credential provider implementation."""

import dataclasses
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.email.service import EmailService
from azents.repos.password_login import PasswordLoginRepository
from azents.repos.user import UserRepository
from azents.repos.user_email import UserEmailRepository
from azents.services.credential.data import (
    CredentialSummary,
    CredentialType,
    CredentialUnavailableReason,
)


class CredentialProvider(Protocol):
    """Provider that calculates summary by Credential type."""

    credential_type: CredentialType

    async def get_user_summary(
        self,
        session: AsyncSession,
        *,
        user_id: str,
    ) -> CredentialSummary:
        """Return credential summary by User."""
        ...

    async def get_login_summary(
        self,
        session: AsyncSession,
        *,
        email: str,
    ) -> CredentialSummary:
        """Return credential summary by login input email."""
        ...


@dataclasses.dataclass
class PasswordCredentialProvider:
    """Password credential provider."""

    password_login_repo: PasswordLoginRepository = dataclasses.field(
        default_factory=PasswordLoginRepository
    )
    user_repo: UserRepository = dataclasses.field(default_factory=UserRepository)

    credential_type: CredentialType = CredentialType.PASSWORD

    async def get_user_summary(
        self,
        session: AsyncSession,
        *,
        user_id: str,
    ) -> CredentialSummary:
        """Return password credential summary by User."""
        configured = await self.password_login_repo.exists_for_user(session, user_id)
        return self._build(configured=configured)

    async def get_login_summary(
        self,
        session: AsyncSession,
        *,
        email: str,
    ) -> CredentialSummary:
        """Return password credential summary by login input email."""
        user = await self.user_repo.get_by_email(session, email)
        if user is None:
            return self._build(configured=False)
        configured = await self.password_login_repo.exists_for_user(session, user.id)
        return self._build(configured=configured)

    def _build(self, *, configured: bool) -> CredentialSummary:
        """Create Password credential summary."""
        return CredentialSummary(
            type=CredentialType.PASSWORD,
            configured=configured,
            valid=configured,
            can_login=configured,
            can_elevate=configured,
            can_remove=configured,
            unavailable_reason=None
            if configured
            else CredentialUnavailableReason.NOT_CONFIGURED,
        )


@dataclasses.dataclass
class EmailCredentialProvider:
    """Email credential provider."""

    email_service: EmailService
    user_email_repo: UserEmailRepository = dataclasses.field(
        default_factory=UserEmailRepository
    )
    user_repo: UserRepository = dataclasses.field(default_factory=UserRepository)

    credential_type: CredentialType = CredentialType.EMAIL

    async def get_user_summary(
        self,
        session: AsyncSession,
        *,
        user_id: str,
    ) -> CredentialSummary:
        """Return email credential summary by User."""
        user = await self.user_repo.get(session, user_id)
        if user is None:
            return self._build(configured=False)
        emails = await self.user_email_repo.list_by_user(session, user_id)
        configured = any(email.verified_at is not None for email in emails)
        return self._build(configured=configured)

    async def get_login_summary(
        self,
        session: AsyncSession,
        *,
        email: str,
    ) -> CredentialSummary:
        """Return email credential summary by login input email."""
        user_email = await self.user_email_repo.get_by_email(session, email)
        configured = user_email is not None and user_email.verified_at is not None
        return self._build(configured=configured)

    def _build(self, *, configured: bool) -> CredentialSummary:
        """Create Email credential summary."""
        if not configured:
            return CredentialSummary(
                type=CredentialType.EMAIL,
                configured=False,
                valid=False,
                can_login=False,
                can_elevate=False,
                can_remove=False,
                unavailable_reason=CredentialUnavailableReason.NOT_CONFIGURED,
            )
        if not self.email_service.configured:
            return CredentialSummary(
                type=CredentialType.EMAIL,
                configured=True,
                valid=False,
                can_login=False,
                can_elevate=False,
                can_remove=False,
                unavailable_reason=CredentialUnavailableReason.SMTP_NOT_CONFIGURED,
            )
        return CredentialSummary(
            type=CredentialType.EMAIL,
            configured=True,
            valid=True,
            can_login=True,
            can_elevate=True,
            can_remove=False,
            unavailable_reason=None,
        )


def get_credential_providers(
    email_service: Annotated[EmailService, Depends()],
) -> list[CredentialProvider]:
    """Return Credential provider list."""
    return [
        PasswordCredentialProvider(),
        EmailCredentialProvider(email_service=email_service),
    ]
