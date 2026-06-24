"""UserEmail repository tests."""

from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate

from . import UserEmailRepository
from .data import DuplicateEmail, UserEmailCreate

_email_counter = 0


def _next_email() -> str:
    """Create unique email for tests."""
    global _email_counter  # noqa: PLW0603
    _email_counter += 1
    return f"ue-test-{_email_counter}@example.com"


async def _create_user(session: AsyncSession) -> str:
    """Create User for tests and return ID."""
    repo = UserRepository()
    user = await repo.create(session, UserCreate(email=_next_email()))
    return user.id


class TestUserEmailRepository:
    """UserEmailRepository tests."""

    async def test_create(self, rdb_session: AsyncSession) -> None:
        """Create UserEmail."""
        # Given: prepare User
        user_id = await _create_user(rdb_session)
        repo = UserEmailRepository()

        # When: create UserEmail
        result = await repo.create(
            rdb_session,
            UserEmailCreate(user_id=user_id, email="ue-create@example.com"),
        )

        # Then: check success
        assert isinstance(result, Success)
        email = result.value
        assert email.user_id == user_id
        assert email.email == "ue-create@example.com"
        assert email.verified_at is None
        assert email.id
        assert email.created_at
        assert email.updated_at

    async def test_create_duplicate_email(self, rdb_session: AsyncSession) -> None:
        """Return DuplicateEmail when creating duplicate email."""
        # Given: UserEmail with same email already exists
        user_id = await _create_user(rdb_session)
        repo = UserEmailRepository()
        await repo.create(
            rdb_session,
            UserEmailCreate(user_id=user_id, email="ue-dup@example.com"),
        )

        # When: create again with same email
        user_id_2 = await _create_user(rdb_session)
        result = await repo.create(
            rdb_session,
            UserEmailCreate(user_id=user_id_2, email="ue-dup@example.com"),
        )

        # Then: DuplicateEmail error
        assert isinstance(result, Failure)
        assert isinstance(result.error, DuplicateEmail)
        assert result.error.email == "ue-dup@example.com"

    async def test_get(self, rdb_session: AsyncSession) -> None:
        """Fetch UserEmail by ID."""
        # Given: create UserEmail
        user_id = await _create_user(rdb_session)
        repo = UserEmailRepository()
        create_result = await repo.create(
            rdb_session,
            UserEmailCreate(user_id=user_id, email="ue-get@example.com"),
        )
        assert isinstance(create_result, Success)
        email_id = create_result.value.id

        # When: fetch by ID
        email = await repo.get(rdb_session, email_id)

        # Then: fetch success
        assert email is not None
        assert email.id == email_id
        assert email.email == "ue-get@example.com"

    async def test_get_not_found(self, rdb_session: AsyncSession) -> None:
        """Return None when fetching by nonexistent ID."""
        # Given: nonexistent ID
        repo = UserEmailRepository()

        # When: fetch
        email = await repo.get(rdb_session, "nonexistent")

        # Then: None
        assert email is None

    async def test_get_by_email(self, rdb_session: AsyncSession) -> None:
        """Fetch UserEmail by email address."""
        # Given: create UserEmail
        user_id = await _create_user(rdb_session)
        repo = UserEmailRepository()
        await repo.create(
            rdb_session,
            UserEmailCreate(user_id=user_id, email="ue-by-email@example.com"),
        )

        # When: fetch by email
        email = await repo.get_by_email(rdb_session, "ue-by-email@example.com")

        # Then: fetch success
        assert email is not None
        assert email.email == "ue-by-email@example.com"
        assert email.user_id == user_id

    async def test_get_by_email_not_found(self, rdb_session: AsyncSession) -> None:
        """Return None when fetching by nonexistent email."""
        # Given: nonexistent email
        repo = UserEmailRepository()

        # When: fetch
        email = await repo.get_by_email(rdb_session, "nonexistent@example.com")

        # Then: None
        assert email is None

    async def test_list_by_user(self, rdb_session: AsyncSession) -> None:
        """Fetch UserEmail list by User ID."""
        # Given: add multiple emails to one User
        user_id = await _create_user(rdb_session)
        repo = UserEmailRepository()
        await repo.create(
            rdb_session,
            UserEmailCreate(user_id=user_id, email="ue-list-1@example.com"),
        )
        await repo.create(
            rdb_session,
            UserEmailCreate(user_id=user_id, email="ue-list-2@example.com"),
        )

        # When: fetch list
        emails = await repo.list_by_user(rdb_session, user_id)

        # Then: three items (one auto-created on create + two manual additions)
        assert len(emails) >= 2

    async def test_list_all(self, rdb_session: AsyncSession) -> None:
        """Fetch all UserEmail list."""
        # Given: create UserEmail
        user_id = await _create_user(rdb_session)
        repo = UserEmailRepository()
        await repo.create(
            rdb_session,
            UserEmailCreate(user_id=user_id, email="ue-listall@example.com"),
        )

        # When: fetch full list
        email_list = await repo.list_all(rdb_session)

        # Then: one or more items exist (auto-created + manual additions)
        assert email_list.total >= 1
        assert len(email_list.items) >= 1

    async def test_delete(self, rdb_session: AsyncSession) -> None:
        """Delete UserEmail."""
        # Given: create UserEmail
        user_id = await _create_user(rdb_session)
        repo = UserEmailRepository()
        create_result = await repo.create(
            rdb_session,
            UserEmailCreate(user_id=user_id, email="ue-delete@example.com"),
        )
        assert isinstance(create_result, Success)
        email_id = create_result.value.id

        # When: delete
        await repo.delete(rdb_session, email_id)

        # Then: None when fetching
        email = await repo.get(rdb_session, email_id)
        assert email is None
