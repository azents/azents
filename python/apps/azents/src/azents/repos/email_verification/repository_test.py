"""EmailVerification repository tests."""

import datetime

from azcommon.datetime import tznow
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from . import EmailVerificationRepository
from .data import AlreadyVerified, EmailVerificationCreate, NotFound


def _future(minutes: int = 10) -> datetime.datetime:
    """Return time N minutes after current time."""
    return tznow() + datetime.timedelta(minutes=minutes)


def _past(minutes: int = 10) -> datetime.datetime:
    """Return time N minutes before current time."""
    return tznow() - datetime.timedelta(minutes=minutes)


class TestEmailVerificationRepository:
    """EmailVerificationRepository tests."""

    async def test_create(self, rdb_session: AsyncSession) -> None:
        """Create verification record."""
        # Given: prepare create data
        repo = EmailVerificationRepository()

        # When: create
        verification = await repo.create(
            rdb_session,
            EmailVerificationCreate(
                email="ev-create@example.com",
                code="ABC123",
                csrf_token="csrf-token-1",
                expires_at=_future(),
            ),
        )

        # Then: check success
        assert verification.id
        assert verification.email == "ev-create@example.com"
        assert verification.code == "ABC123"
        assert verification.csrf_token == "csrf-token-1"
        assert verification.verified_at is None
        assert verification.created_at

    async def test_get(self, rdb_session: AsyncSession) -> None:
        """Fetch verification record by ID."""
        # Given: create verification record
        repo = EmailVerificationRepository()
        created = await repo.create(
            rdb_session,
            EmailVerificationCreate(
                email="ev-get@example.com",
                code="DEF456",
                csrf_token="csrf-token-2",
                expires_at=_future(),
            ),
        )

        # When: fetch by ID
        verification = await repo.get(rdb_session, created.id)

        # Then: fetch success
        assert verification is not None
        assert verification.id == created.id
        assert verification.email == "ev-get@example.com"

    async def test_get_not_found(self, rdb_session: AsyncSession) -> None:
        """Return None when fetching by nonexistent ID."""
        # Given: nonexistent ID
        repo = EmailVerificationRepository()

        # When: fetch
        verification = await repo.get(rdb_session, "nonexistent")

        # Then: None
        assert verification is None

    async def test_get_by_email_and_csrf(self, rdb_session: AsyncSession) -> None:
        """Fetch by email + CSRF token."""
        # Given: create verification record
        repo = EmailVerificationRepository()
        created = await repo.create(
            rdb_session,
            EmailVerificationCreate(
                email="ev-csrf@example.com",
                code="GHI789",
                csrf_token="csrf-token-3",
                expires_at=_future(),
            ),
        )

        # When: fetch by email + CSRF
        verification = await repo.get_by_email_and_csrf(
            rdb_session, "ev-csrf@example.com", "csrf-token-3"
        )

        # Then: fetch success
        assert verification is not None
        assert verification.id == created.id

    async def test_get_by_email_and_csrf_not_found(
        self, rdb_session: AsyncSession
    ) -> None:
        """Return None for nonexistent email + CSRF combination."""
        # Given: nonexistent combination
        repo = EmailVerificationRepository()

        # When: fetch
        verification = await repo.get_by_email_and_csrf(
            rdb_session, "nonexistent@example.com", "wrong-csrf"
        )

        # Then: None
        assert verification is None

    async def test_mark_verified(self, rdb_session: AsyncSession) -> None:
        """Mark verification complete."""
        # Given: create unverified record
        repo = EmailVerificationRepository()
        created = await repo.create(
            rdb_session,
            EmailVerificationCreate(
                email="ev-verify@example.com",
                code="JKL012",
                csrf_token="csrf-token-4",
                expires_at=_future(),
            ),
        )

        # When: mark verification complete
        result = await repo.mark_verified(rdb_session, created.id)

        # Then: success
        assert isinstance(result, Success)
        assert result.value.verified_at is not None

    async def test_mark_verified_not_found(self, rdb_session: AsyncSession) -> None:
        """Return NotFound when verifying nonexistent record."""
        # Given: nonexistent ID
        repo = EmailVerificationRepository()

        # When: attempt verification
        result = await repo.mark_verified(rdb_session, "nonexistent")

        # Then: NotFound error
        assert isinstance(result, Failure)
        assert isinstance(result.error, NotFound)

    async def test_mark_verified_already_verified(
        self, rdb_session: AsyncSession
    ) -> None:
        """Return AlreadyVerified when re-verifying already verified record."""
        # Given: already verified record
        repo = EmailVerificationRepository()
        created = await repo.create(
            rdb_session,
            EmailVerificationCreate(
                email="ev-already@example.com",
                code="MNO345",
                csrf_token="csrf-token-5",
                expires_at=_future(),
            ),
        )
        await repo.mark_verified(rdb_session, created.id)

        # When: attempt re-verification
        result = await repo.mark_verified(rdb_session, created.id)

        # Then: AlreadyVerified error
        assert isinstance(result, Failure)
        assert isinstance(result.error, AlreadyVerified)

    async def test_delete_stale_by_email(self, rdb_session: AsyncSession) -> None:
        """Delete stale verification records."""
        # Given: create expired record and valid record
        repo = EmailVerificationRepository()
        email = "ev-stale@example.com"

        # Expired record
        await repo.create(
            rdb_session,
            EmailVerificationCreate(
                email=email,
                code="STL001",
                csrf_token="csrf-stale-1",
                expires_at=_past(),
            ),
        )
        # Valid record
        valid = await repo.create(
            rdb_session,
            EmailVerificationCreate(
                email=email,
                code="STL002",
                csrf_token="csrf-stale-2",
                expires_at=_future(),
            ),
        )

        # When: delete stale
        deleted_count = await repo.delete_stale_by_email(rdb_session, email)

        # Then: delete one expired record, valid record remains
        assert deleted_count >= 1
        remaining = await repo.get(rdb_session, valid.id)
        assert remaining is not None

    async def test_delete_stale_removes_verified(
        self, rdb_session: AsyncSession
    ) -> None:
        """Verified record is also deleted as stale."""
        # Given: verified record
        repo = EmailVerificationRepository()
        email = "ev-stale-verified@example.com"
        created = await repo.create(
            rdb_session,
            EmailVerificationCreate(
                email=email,
                code="STL003",
                csrf_token="csrf-stale-3",
                expires_at=_future(),
            ),
        )
        await repo.mark_verified(rdb_session, created.id)

        # When: delete stale
        deleted_count = await repo.delete_stale_by_email(rdb_session, email)

        # Then: delete one verified record
        assert deleted_count >= 1
        remaining = await repo.get(rdb_session, created.id)
        assert remaining is None

    async def test_list_all(self, rdb_session: AsyncSession) -> None:
        """Fetch all verification records."""
        # Given: create verification record
        repo = EmailVerificationRepository()
        await repo.create(
            rdb_session,
            EmailVerificationCreate(
                email="ev-listall@example.com",
                code="ALL001",
                csrf_token="csrf-listall",
                expires_at=_future(),
            ),
        )

        # When: fetch full list
        ev_list = await repo.list_all(rdb_session)

        # Then: one or more records exist
        assert ev_list.total >= 1
        assert len(ev_list.items) >= 1

    async def test_list_by_email(self, rdb_session: AsyncSession) -> None:
        """Fetch valid verification records by email."""
        # Given: create valid records for specific email
        repo = EmailVerificationRepository()
        email = "ev-list-email@example.com"
        await repo.create(
            rdb_session,
            EmailVerificationCreate(
                email=email,
                code="LST001",
                csrf_token="csrf-list-1",
                expires_at=_future(),
            ),
        )
        await repo.create(
            rdb_session,
            EmailVerificationCreate(
                email=email,
                code="LST002",
                csrf_token="csrf-list-2",
                expires_at=_future(),
            ),
        )

        # When: fetch list by email
        ev_list = await repo.list_by_email(rdb_session, email)

        # Then: two or more records exist
        assert ev_list.total >= 2
        assert len(ev_list.items) >= 2
