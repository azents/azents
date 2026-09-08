"""Completed Email Verification operation repository tests."""

import asyncio
import datetime

import pytest
from azcommon.datetime import tznow
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session import SessionManager
from azents.repos.email_verification import EmailVerificationRepository
from azents.repos.email_verification.data import (
    AlreadyVerified,
    EmailVerification,
    EmailVerificationCreate,
    Expired,
    NotFound,
)

from . import EmailVerificationOperationRepository
from .data import EmailVerificationVerify


def _future() -> datetime.datetime:
    """Return a verification expiry in the future."""
    return tznow() + datetime.timedelta(minutes=10)


def _past() -> datetime.datetime:
    """Return a verification expiry in the past."""
    return tznow() - datetime.timedelta(minutes=10)


class _DeliveryInsertFailure(Exception):
    """Fail after stale-record deletion to prove operation rollback."""


class _FailingDeliveryRepository(EmailVerificationRepository):
    """Raise during the delivery insert after the inherited stale deletion."""

    async def create(
        self,
        session: AsyncSession,
        create: EmailVerificationCreate,
    ) -> EmailVerification:
        """Fail the insert portion of the delivery operation."""
        del session, create
        raise _DeliveryInsertFailure()


class _BarrierEmailVerificationRepository(EmailVerificationRepository):
    """Synchronize two reads before their conditional verification updates."""

    def __init__(self, barrier: asyncio.Barrier) -> None:
        self.barrier = barrier

    async def get_by_email_and_csrf(
        self,
        session: AsyncSession,
        email: str,
        csrf_token: str,
    ) -> EmailVerification | None:
        """Read both contenders before either conditional update runs."""
        verification = await super().get_by_email_and_csrf(
            session,
            email,
            csrf_token,
        )
        await self.barrier.wait()
        return verification


def _operation_repository(
    session_manager: SessionManager[AsyncSession],
    *,
    email_verification_repository: EmailVerificationRepository | None = None,
) -> EmailVerificationOperationRepository:
    """Create the operation repository using the test transaction factory."""
    return EmailVerificationOperationRepository(
        email_verification_repository=email_verification_repository
        or EmailVerificationRepository(),
        session_manager=session_manager,
    )


async def test_create_delivery_record_rolls_back_stale_deletion_on_insert_failure(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A failed insert preserves the stale row deleted by the same operation."""
    email = "rollback-delivery@example.com"
    primitive = EmailVerificationRepository()
    async with rdb_session_manager() as session:
        stale = await primitive.create(
            session,
            EmailVerificationCreate(
                email=email,
                code="STALE1",
                csrf_token="csrf-stale",
                expires_at=_past(),
            ),
        )

    repository = _operation_repository(
        rdb_session_manager,
        email_verification_repository=_FailingDeliveryRepository(),
    )

    with pytest.raises(_DeliveryInsertFailure):
        await repository.create_delivery_record(
            create=EmailVerificationCreate(
                email=email,
                code="FRESH1",
                csrf_token="csrf-fresh",
                expires_at=_future(),
            )
        )

    async with rdb_session_manager() as session:
        preserved = await primitive.get(session, stale.id)
    assert preserved is not None


async def test_verify_and_mark_rejects_expiry_and_csrf(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Expiry and CSRF validation fail without marking the record verified."""
    email = "verification-rejection@example.com"
    repository = _operation_repository(rdb_session_manager)
    expired = await repository.create_delivery_record(
        create=EmailVerificationCreate(
            email=email,
            code="EXPIRE",
            csrf_token="csrf-expired",
            expires_at=_past(),
        )
    )

    expired_result = await repository.verify_and_mark(
        verification=EmailVerificationVerify(
            email=email,
            csrf_token=expired.csrf_token,
            code=expired.code,
        )
    )
    csrf_result = await repository.verify_and_mark(
        verification=EmailVerificationVerify(
            email=email,
            csrf_token="wrong-csrf",
            code=expired.code,
        )
    )

    assert isinstance(expired_result, Failure)
    assert isinstance(expired_result.error, Expired)
    assert isinstance(csrf_result, Failure)
    assert isinstance(csrf_result.error, NotFound)
    persisted = await repository.get(verification_id=expired.id)
    assert persisted is not None
    assert persisted.verified_at is None


async def test_verify_and_mark_allows_one_concurrent_winner(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Two simultaneous verification attempts cannot both mark one record."""
    email = "verification-race@example.com"
    setup_repository = _operation_repository(rdb_session_manager)
    created = await setup_repository.create_delivery_record(
        create=EmailVerificationCreate(
            email=email,
            code="RACE01",
            csrf_token="csrf-race",
            expires_at=_future(),
        )
    )
    repository = _operation_repository(
        rdb_session_manager,
        email_verification_repository=_BarrierEmailVerificationRepository(
            asyncio.Barrier(2)
        ),
    )
    verification = EmailVerificationVerify(
        email=email,
        csrf_token=created.csrf_token,
        code=created.code,
    )

    first, second = await asyncio.gather(
        repository.verify_and_mark(verification=verification),
        repository.verify_and_mark(verification=verification),
    )

    results = (first, second)
    assert sum(isinstance(result, Success) for result in results) == 1
    failures = [result for result in results if isinstance(result, Failure)]
    assert len(failures) == 1
    assert isinstance(failures[0].error, AlreadyVerified)
    persisted = await setup_repository.get(verification_id=created.id)
    assert persisted is not None
    assert persisted.verified_at is not None
