"""Credential provider implementation."""

import dataclasses
from typing import Annotated, Protocol

from fastapi import Depends

from azents.core.credential_read import CredentialReadFact, CredentialReadKind
from azents.core.email.service import EmailService
from azents.services.credential.data import (
    CredentialSummary,
    CredentialType,
    CredentialUnavailableReason,
)


class CredentialProvider(Protocol):
    """Provider that calculates summary by Credential type."""

    credential_type: CredentialType

    @property
    def read_kind(self) -> CredentialReadKind:
        """Return the fixed database query behavior for this provider."""
        ...

    async def get_user_summary(
        self,
        *,
        fact: CredentialReadFact,
    ) -> CredentialSummary:
        """Project one completed User configuration fact."""
        ...

    async def get_login_summary(
        self,
        *,
        fact: CredentialReadFact,
    ) -> CredentialSummary:
        """Project one completed login configuration fact."""
        ...


@dataclasses.dataclass
class PasswordCredentialProvider:
    """Password credential provider."""

    credential_type: CredentialType = CredentialType.PASSWORD

    @property
    def read_kind(self) -> CredentialReadKind:
        """Keep Password query identity independent of projection attributes."""
        return CredentialReadKind.PASSWORD

    async def get_user_summary(
        self,
        *,
        fact: CredentialReadFact,
    ) -> CredentialSummary:
        """Project a completed User password fact."""
        return self._build(configured=fact.configured)

    async def get_login_summary(
        self,
        *,
        fact: CredentialReadFact,
    ) -> CredentialSummary:
        """Project a completed login password fact."""
        return self._build(configured=fact.configured)

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

    credential_type: CredentialType = CredentialType.EMAIL

    @property
    def read_kind(self) -> CredentialReadKind:
        """Keep Email query identity independent of projection attributes."""
        return CredentialReadKind.EMAIL

    async def get_user_summary(
        self,
        *,
        fact: CredentialReadFact,
    ) -> CredentialSummary:
        """Project a completed User email fact using local delivery availability."""
        return self._build(configured=fact.configured)

    async def get_login_summary(
        self,
        *,
        fact: CredentialReadFact,
    ) -> CredentialSummary:
        """Project a completed login email fact using local delivery availability."""
        return self._build(configured=fact.configured)

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
