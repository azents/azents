"""EmailVerification service."""

import dataclasses
from typing import Annotated

from fastapi import Depends

from azents.repos.email_verification_operation import (
    EmailVerificationOperationRepository,
)

from .data import EmailVerificationListOutput, EmailVerificationOutput


@dataclasses.dataclass
class EmailVerificationService:
    """EmailVerification CRUD service."""

    email_verification_operation_repository: Annotated[
        EmailVerificationOperationRepository,
        Depends(EmailVerificationOperationRepository),
    ]

    async def get(self, verification_id: str) -> EmailVerificationOutput | None:
        """Fetch verification record by ID.

        :param verification_id: Verification ID
        :return: EmailVerification or None
        """
        verification = await self.email_verification_operation_repository.get(
            verification_id=verification_id
        )
        if verification is None:
            return None
        return EmailVerificationOutput.convert_from(verification)

    async def get_by_email_and_csrf(
        self, email: str, csrf_token: str
    ) -> EmailVerificationOutput | None:
        """Fetch by email + CSRF token.

        :param email: Email address
        :param csrf_token: CSRF token
        :return: EmailVerification or None
        """
        verification = (
            await self.email_verification_operation_repository.get_by_email_and_csrf(
                email=email,
                csrf_token=csrf_token,
            )
        )
        if verification is None:
            return None
        return EmailVerificationOutput.convert_from(verification)

    async def list_all(
        self, *, offset: int = 0, limit: int = 50
    ) -> EmailVerificationListOutput:
        """Fetch all verification record list.

        :param offset: Record count to skip
        :param limit: Maximum record count to return
        :return: EmailVerification list
        """
        result = await self.email_verification_operation_repository.list_all(
            offset=offset,
            limit=limit,
        )
        return EmailVerificationListOutput(
            items=[EmailVerificationOutput.convert_from(v) for v in result.items],
            total=result.total,
        )

    async def list_by_email(
        self, email: str, *, offset: int = 0, limit: int = 20
    ) -> EmailVerificationListOutput:
        """Fetch active verification record list by email.

        :param email: Email address
        :param offset: Record count to skip
        :param limit: Maximum record count to return
        :return: EmailVerification list
        """
        result = await self.email_verification_operation_repository.list_by_email(
            email=email,
            offset=offset,
            limit=limit,
        )
        return EmailVerificationListOutput(
            items=[EmailVerificationOutput.convert_from(v) for v in result.items],
            total=result.total,
        )
