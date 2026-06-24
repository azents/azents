"""User repository tests."""

from sqlalchemy.ext.asyncio import AsyncSession

from . import UserRepository
from .data import UserCreate


class TestUserRepository:
    """UserRepository tests."""

    async def test_create(self, rdb_session: AsyncSession) -> None:
        """Create User + UserEmail."""
        # Given: prepare create data
        repo = UserRepository()

        # When: create User
        user = await repo.create(rdb_session, UserCreate(email="gu-test@example.com"))

        # Then: check success
        assert user.id
        assert user.primary_email_id
        assert user.primary_email == "gu-test@example.com"
        assert user.created_at
        assert user.updated_at

    async def test_get(self, rdb_session: AsyncSession) -> None:
        """Fetch User by ID."""
        # Given: create User
        repo = UserRepository()
        created = await repo.create(rdb_session, UserCreate(email="gu-get@example.com"))

        # When: fetch by ID
        user = await repo.get(rdb_session, created.id)

        # Then: fetch success
        assert user is not None
        assert user.id == created.id
        assert user.primary_email_id == created.primary_email_id
        assert user.primary_email == "gu-get@example.com"

    async def test_get_not_found(self, rdb_session: AsyncSession) -> None:
        """Return None when fetching by nonexistent ID."""
        # Given: nonexistent ID
        repo = UserRepository()

        # When: fetch
        user = await repo.get(rdb_session, "nonexistent")

        # Then: None
        assert user is None

    async def test_get_by_email(self, rdb_session: AsyncSession) -> None:
        """Fetch User by email."""
        # Given: create User
        repo = UserRepository()
        created = await repo.create(
            rdb_session, UserCreate(email="gu-by-email@example.com")
        )

        # When: fetch by email
        user = await repo.get_by_email(rdb_session, "gu-by-email@example.com")

        # Then: fetch success
        assert user is not None
        assert user.id == created.id
        assert user.primary_email == "gu-by-email@example.com"

    async def test_get_by_email_not_found(self, rdb_session: AsyncSession) -> None:
        """Return None when fetching by nonexistent email."""
        # Given: nonexistent email
        repo = UserRepository()

        # When: fetch
        user = await repo.get_by_email(rdb_session, "nonexistent@example.com")

        # Then: None
        assert user is None

    async def test_list_all(self, rdb_session: AsyncSession) -> None:
        """Fetch all User list."""
        # Given: create multiple Users
        repo = UserRepository()
        await repo.create(rdb_session, UserCreate(email="gu-list-1@example.com"))
        await repo.create(rdb_session, UserCreate(email="gu-list-2@example.com"))

        # When: fetch list
        user_list = await repo.list_all(rdb_session)

        # Then: two or more users exist
        assert user_list.total >= 2
        assert len(user_list.items) >= 2

    async def test_list_all_pagination(self, rdb_session: AsyncSession) -> None:
        """Paginate all User list."""
        # Given: create User
        repo = UserRepository()
        await repo.create(rdb_session, UserCreate(email="gu-page-1@example.com"))
        await repo.create(rdb_session, UserCreate(email="gu-page-2@example.com"))
        await repo.create(rdb_session, UserCreate(email="gu-page-3@example.com"))

        # When: fetch with limit=1
        user_list = await repo.list_all(rdb_session, limit=1)

        # Then: return only one item, total is full count
        assert len(user_list.items) == 1
        assert user_list.total >= 3

    async def test_delete(self, rdb_session: AsyncSession) -> None:
        """Delete User."""
        # Given: create User
        repo = UserRepository()
        created = await repo.create(
            rdb_session, UserCreate(email="gu-delete@example.com")
        )

        # When: delete
        await repo.delete(rdb_session, created.id)

        # Then: None when fetching
        user = await repo.get(rdb_session, created.id)
        assert user is None
