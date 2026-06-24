"""EmailVerification service."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.email_verification import EmailVerificationRepository

from .data import EmailVerificationListOutput, EmailVerificationOutput


@dataclasses.dataclass
class EmailVerificationService:
    """EmailVerification CRUD service."""

    email_verification_repository: Annotated[EmailVerificationRepository, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def get(self, verification_id: str) -> EmailVerificationOutput | None:
        """Fetch verification record by ID.

        :param verification_id: Verification ID
        :return: EmailVerification or None
        """
        async with self.session_manager() as session:
            verification = await self.email_verification_repository.get(
                session, verification_id
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
        repo = self.email_verification_repository
        async with self.session_manager() as session:
            verification = await repo.get_by_email_and_csrf(session, email, csrf_token)
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
        async with self.session_manager() as session:
            result = await self.email_verification_repository.list_all(
                session, offset=offset, limit=limit
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
        async with self.session_manager() as session:
            result = await self.email_verification_repository.list_by_email(
                session, email, offset=offset, limit=limit
            )
        return EmailVerificationListOutput(
            items=[EmailVerificationOutput.convert_from(v) for v in result.items],
            total=result.total,
        )
