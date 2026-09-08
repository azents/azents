"""Completed database operations for Email Verification."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.datetime import tznow
from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.email_verification import EmailVerificationRepository
from azents.repos.email_verification.data import (
    AlreadyVerified,
    EmailVerification,
    EmailVerificationCreate,
    EmailVerificationList,
    Expired,
    NotFound,
)

from .data import EmailVerificationVerify, InvalidCode


@dataclasses.dataclass
class EmailVerificationOperationRepository:
    """Own completed database-only Email Verification operations."""

    email_verification_repository: Annotated[
        EmailVerificationRepository, Depends(EmailVerificationRepository)
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def create_delivery_record(
        self,
        *,
        create: EmailVerificationCreate,
    ) -> EmailVerification:
        """Atomically remove stale records and create one delivery record."""
        async with self.session_manager() as session:
            await self.email_verification_repository.delete_stale_by_email(
                session,
                create.email,
            )
            return await self.email_verification_repository.create(session, create)

    async def verify_and_mark(
        self,
        *,
        verification: EmailVerificationVerify,
    ) -> Result[
        EmailVerification,
        NotFound | Expired | AlreadyVerified | InvalidCode,
    ]:
        """Atomically validate and conditionally mark one verification record."""
        async with self.session_manager() as session:
            current = await self.email_verification_repository.get_by_email_and_csrf(
                session,
                verification.email,
                verification.csrf_token,
            )
            if current is None:
                return Failure(NotFound(verification_id=""))
            if current.expires_at < tznow():
                return Failure(Expired(verification_id=current.id))
            if current.verified_at is not None:
                return Failure(AlreadyVerified(verification_id=current.id))
            if current.code.upper() != verification.code.upper():
                return Failure(InvalidCode())
            mark_result = await self.email_verification_repository.mark_verified(
                session,
                current.id,
            )
            match mark_result:
                case Success(value):
                    return Success(value)
                case Failure(error) if isinstance(error, (NotFound, AlreadyVerified)):
                    return Failure(error)
                case Failure(error):
                    assert_never(error)

    async def delete_stale_by_email(self, *, email: str) -> int:
        """Delete stale verification records in a completed operation."""
        async with self.session_manager() as session:
            return await self.email_verification_repository.delete_stale_by_email(
                session,
                email,
            )

    async def get(self, *, verification_id: str) -> EmailVerification | None:
        """Fetch a verification record in a completed read operation."""
        async with self.session_manager() as session:
            return await self.email_verification_repository.get(
                session,
                verification_id,
            )

    async def get_by_email_and_csrf(
        self,
        *,
        email: str,
        csrf_token: str,
    ) -> EmailVerification | None:
        """Fetch a verification record by email and CSRF token."""
        async with self.session_manager() as session:
            return await self.email_verification_repository.get_by_email_and_csrf(
                session,
                email,
                csrf_token,
            )

    async def list_all(
        self,
        *,
        offset: int,
        limit: int,
    ) -> EmailVerificationList:
        """List verification records in a completed read operation."""
        async with self.session_manager() as session:
            return await self.email_verification_repository.list_all(
                session,
                offset=offset,
                limit=limit,
            )

    async def list_by_email(
        self,
        *,
        email: str,
        offset: int,
        limit: int,
    ) -> EmailVerificationList:
        """List active email verification records in a completed read operation."""
        async with self.session_manager() as session:
            return await self.email_verification_repository.list_by_email(
                session,
                email,
                offset=offset,
                limit=limit,
            )
