"""GithubUserInstallationRepository tests."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.github_user_installation import RDBGithubUserInstallation
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate

from . import GithubUserInstallationRepository

_PLATFORM_APP_ID = "123"


async def _create_user(
    session: AsyncSession, email: str = "gh-install@example.com"
) -> str:
    """Create User for tests and return user_id."""
    repo = UserRepository()
    user = await repo.create(session, UserCreate(email=email))
    return user.id


def _make_installation(
    inst_id: int,
    login: str = "test-org",
    account_type: str = "Organization",
    avatar_url: str = "https://example.com/avatar.png",
) -> dict[str, object]:
    """Create installation dict in GitHub API format."""
    return {
        "id": inst_id,
        "account": {
            "login": login,
            "type": account_type,
            "avatar_url": avatar_url,
        },
    }


class TestGithubUserInstallationRepository:
    """GithubUserInstallationRepository tests."""

    async def test_sync_insert(self, rdb_session: AsyncSession) -> None:
        """INSERT new installation."""
        user_id = await _create_user(rdb_session)
        repo = GithubUserInstallationRepository()

        await repo.sync(
            rdb_session,
            user_id,
            _PLATFORM_APP_ID,
            [_make_installation(1001, login="my-org")],
        )

        # Then: id should be stored normally as NOT NULL
        result = await rdb_session.execute(
            select(RDBGithubUserInstallation).where(
                RDBGithubUserInstallation.user_id == user_id,
            )
        )
        row = result.scalar_one()
        assert row.id is not None
        assert len(row.id) == 32
        assert row.platform_app_id == _PLATFORM_APP_ID
        assert row.installation_id == 1001
        assert row.account_login == "my-org"
        assert row.account_type == "Organization"

    async def test_sync_upsert(self, rdb_session: AsyncSession) -> None:
        """UPDATE when synchronizing same installation again."""
        user_id = await _create_user(rdb_session, email="gh-upsert@example.com")
        repo = GithubUserInstallationRepository()

        # Given: first sync
        await repo.sync(
            rdb_session,
            user_id,
            _PLATFORM_APP_ID,
            [_make_installation(2001, login="old-name")],
        )
        result = await rdb_session.execute(
            select(RDBGithubUserInstallation).where(
                RDBGithubUserInstallation.user_id == user_id,
            )
        )
        first_row = result.scalar_one()
        original_id = first_row.id

        # When: sync again with same installation_id (login changed)
        await repo.sync(
            rdb_session,
            user_id,
            _PLATFORM_APP_ID,
            [_make_installation(2001, login="new-name")],
        )

        # Then: id is kept and account_login is updated
        rdb_session.expire_all()
        result = await rdb_session.execute(
            select(RDBGithubUserInstallation).where(
                RDBGithubUserInstallation.user_id == user_id,
            )
        )
        updated_row = result.scalar_one()
        assert updated_row.id == original_id
        assert updated_row.account_login == "new-name"

    async def test_sync_deletes_removed_installations(
        self, rdb_session: AsyncSession
    ) -> None:
        """Delete installation absent from API result."""
        user_id = await _create_user(rdb_session, email="gh-delete@example.com")
        repo = GithubUserInstallationRepository()

        # Given: sync two installations
        await repo.sync(
            rdb_session,
            user_id,
            _PLATFORM_APP_ID,
            [
                _make_installation(3001, login="org-a"),
                _make_installation(3002, login="org-b"),
            ],
        )

        # When: sync with only one remaining
        await repo.sync(
            rdb_session,
            user_id,
            _PLATFORM_APP_ID,
            [_make_installation(3001, login="org-a")],
        )

        # Then: org-b is deleted
        result = await rdb_session.execute(
            select(RDBGithubUserInstallation).where(
                RDBGithubUserInstallation.user_id == user_id,
            )
        )
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].installation_id == 3001

    async def test_sync_empty_deletes_all(self, rdb_session: AsyncSession) -> None:
        """Synchronizing empty list deletes all installations."""
        user_id = await _create_user(rdb_session, email="gh-empty@example.com")
        repo = GithubUserInstallationRepository()

        # Given: installation exists
        await repo.sync(
            rdb_session,
            user_id,
            _PLATFORM_APP_ID,
            [_make_installation(4001)],
        )

        # When: sync empty list
        await repo.sync(rdb_session, user_id, _PLATFORM_APP_ID, [])

        # Then: all deleted
        result = await rdb_session.execute(
            select(RDBGithubUserInstallation).where(
                RDBGithubUserInstallation.user_id == user_id,
            )
        )
        assert result.scalars().all() == []

    async def test_sync_multiple_installations(self, rdb_session: AsyncSession) -> None:
        """Synchronize multiple installations at once."""
        user_id = await _create_user(rdb_session, email="gh-multi@example.com")
        repo = GithubUserInstallationRepository()

        await repo.sync(
            rdb_session,
            user_id,
            _PLATFORM_APP_ID,
            [
                _make_installation(5001, login="org-1"),
                _make_installation(5002, login="org-2"),
                _make_installation(5003, login="org-3"),
            ],
        )

        # Then: all three saved with NOT NULL id
        result = await rdb_session.execute(
            select(RDBGithubUserInstallation).where(
                RDBGithubUserInstallation.user_id == user_id,
            )
        )
        rows = result.scalars().all()
        assert len(rows) == 3
        for row in rows:
            assert row.id is not None
            assert len(row.id) == 32

    async def test_sync_skips_invalid_entries(self, rdb_session: AsyncSession) -> None:
        """Skip malformed installation."""
        user_id = await _create_user(rdb_session, email="gh-invalid@example.com")
        repo = GithubUserInstallationRepository()

        await repo.sync(
            rdb_session,
            user_id,
            _PLATFORM_APP_ID,
            [
                {"id": "not-int", "account": {"login": "x", "type": "User"}},
                {"id": 6001},  # account missing
                {"id": 6002, "account": "not-dict"},
                _make_installation(6003, login="valid-org"),
            ],
        )

        # Then: save only one valid item
        result = await rdb_session.execute(
            select(RDBGithubUserInstallation).where(
                RDBGithubUserInstallation.user_id == user_id,
            )
        )
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].installation_id == 6003

    async def test_has_access(self, rdb_session: AsyncSession) -> None:
        """Check accessible installation."""
        user_id = await _create_user(rdb_session, email="gh-access@example.com")
        repo = GithubUserInstallationRepository()

        await repo.sync(
            rdb_session,
            user_id,
            _PLATFORM_APP_ID,
            [_make_installation(7001)],
        )

        assert (
            await repo.has_access(rdb_session, user_id, _PLATFORM_APP_ID, 7001) is True
        )
        assert (
            await repo.has_access(rdb_session, user_id, _PLATFORM_APP_ID, 9999) is False
        )

    async def test_has_access_different_user(self, rdb_session: AsyncSession) -> None:
        """Cannot access installation of another user."""
        user_a = await _create_user(rdb_session, email="gh-a@example.com")
        user_b = await _create_user(rdb_session, email="gh-b@example.com")
        repo = GithubUserInstallationRepository()

        await repo.sync(
            rdb_session,
            user_a,
            _PLATFORM_APP_ID,
            [_make_installation(8001)],
        )

        assert (
            await repo.has_access(rdb_session, user_a, _PLATFORM_APP_ID, 8001) is True
        )
        assert (
            await repo.has_access(rdb_session, user_b, _PLATFORM_APP_ID, 8001) is False
        )

    async def test_sync_scopes_rows_to_platform_app(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """The same installation may be synchronized by different Apps."""
        user_id = await _create_user(rdb_session, email="gh-app-scope@example.com")
        repo = GithubUserInstallationRepository()

        await repo.sync(
            rdb_session,
            user_id,
            "111",
            [_make_installation(9001)],
        )
        await repo.sync(
            rdb_session,
            user_id,
            "222",
            [_make_installation(9001)],
        )
        await repo.sync(rdb_session, user_id, "111", [])

        result = await rdb_session.execute(
            select(RDBGithubUserInstallation).where(
                RDBGithubUserInstallation.user_id == user_id,
            )
        )
        rows = result.scalars().all()
        assert len(rows) == 1
        assert rows[0].platform_app_id == "222"
        assert rows[0].installation_id == 9001
