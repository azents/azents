"""GitHubPATRepository tests."""

from datetime import UTC, datetime, timedelta

from azcommon.result import Success
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.repos.github_pat import GitHubPATRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate

_TOKEN = "example-github-pat-token"
_USERNAME = "octocat"
_TEST_KEY = Fernet.generate_key().decode()


def _make_repo() -> GitHubPATRepository:
    return GitHubPATRepository(CredentialCipher(_TEST_KEY))


async def _create_workspace(session: AsyncSession) -> str:
    """Create Workspace for tests and return ID."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session, WorkspaceCreate(name="GitHub PAT test WS", handle="gh-pat-ws")
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, "gh-pat-ws")
    assert workspace_id is not None
    return workspace_id


async def _create_user(session: AsyncSession, email: str = "gh-pat@example.com") -> str:
    """Create User for tests and return user_id."""
    repo = UserRepository()
    user = await repo.create(session, UserCreate(email=email))
    return user.id


class TestGitHubPATRepositoryUpsert:
    """upsert tests."""

    async def test_insert(self, rdb_session: AsyncSession) -> None:
        """Create new PAT."""
        ws_id = await _create_workspace(rdb_session)
        user_id = await _create_user(rdb_session)
        repo = _make_repo()

        pat = await repo.upsert(
            rdb_session,
            workspace_id=ws_id,
            user_id=user_id,
            token=_TOKEN,
            github_username=_USERNAME,
            display_hint="token-hint",
        )

        assert pat.workspace_id == ws_id
        assert pat.user_id == user_id
        assert pat.token == _TOKEN
        assert pat.github_username == _USERNAME
        assert pat.display_hint == "token-hint"
        assert pat.expires_at is None

    async def test_upsert_updates_existing(self, rdb_session: AsyncSession) -> None:
        """Update existing PAT for same workspace+user combination."""
        ws_id = await _create_workspace(rdb_session)
        user_id = await _create_user(rdb_session)
        repo = _make_repo()

        await repo.upsert(
            rdb_session,
            workspace_id=ws_id,
            user_id=user_id,
            token=_TOKEN,
            github_username=_USERNAME,
            display_hint="token-hint",
        )

        new_token = "example-github-pat-token-updated"
        pat = await repo.upsert(
            rdb_session,
            workspace_id=ws_id,
            user_id=user_id,
            token=new_token,
            github_username="newuser",
            display_hint="token-hint-updated",
        )

        assert pat.token == new_token
        assert pat.github_username == "newuser"
        assert pat.display_hint == "token-hint-updated"

    async def test_upsert_with_expires_at(self, rdb_session: AsyncSession) -> None:
        """Store expiration date of Fine-grained PAT."""
        ws_id = await _create_workspace(rdb_session)
        user_id = await _create_user(rdb_session)
        repo = _make_repo()

        expires = datetime.now(UTC) + timedelta(days=90)
        pat = await repo.upsert(
            rdb_session,
            workspace_id=ws_id,
            user_id=user_id,
            token=_TOKEN,
            expires_at=expires,
        )

        assert pat.expires_at is not None
        assert abs((pat.expires_at - expires).total_seconds()) < 1


class TestGitHubPATRepositoryGet:
    """Fetch tests."""

    async def test_get_existing(self, rdb_session: AsyncSession) -> None:
        """Fetch registered PAT."""
        ws_id = await _create_workspace(rdb_session)
        user_id = await _create_user(rdb_session)
        repo = _make_repo()

        await repo.upsert(
            rdb_session,
            workspace_id=ws_id,
            user_id=user_id,
            token=_TOKEN,
            github_username=_USERNAME,
        )

        pat = await repo.get_by_workspace_and_user(rdb_session, ws_id, user_id)

        assert pat is not None
        assert pat.token == _TOKEN
        assert pat.github_username == _USERNAME

    async def test_get_nonexistent(self, rdb_session: AsyncSession) -> None:
        """Return None when fetching unregistered PAT."""
        repo = _make_repo()
        pat = await repo.get_by_workspace_and_user(
            rdb_session, "ws_nonexistent", "usr_nonexistent"
        )
        assert pat is None


class TestGitHubPATRepositoryStatus:
    """Status fetch tests."""

    async def test_status_registered(self, rdb_session: AsyncSession) -> None:
        """Fetch status of registered PAT."""
        ws_id = await _create_workspace(rdb_session)
        user_id = await _create_user(rdb_session)
        repo = _make_repo()

        await repo.upsert(
            rdb_session,
            workspace_id=ws_id,
            user_id=user_id,
            token=_TOKEN,
            github_username=_USERNAME,
            display_hint="token-hint",
        )

        status = await repo.get_status_by_workspace_and_user(
            rdb_session, ws_id, user_id
        )

        assert status.registered is True
        assert status.github_username == _USERNAME
        assert status.display_hint == "token-hint"

    async def test_status_not_registered(self, rdb_session: AsyncSession) -> None:
        """Fetch unregistered status."""
        repo = _make_repo()
        status = await repo.get_status_by_workspace_and_user(
            rdb_session, "ws_nonexistent", "usr_nonexistent"
        )

        assert status.registered is False
        assert status.github_username is None


class TestGitHubPATRepositoryDelete:
    """Delete tests."""

    async def test_delete_existing(self, rdb_session: AsyncSession) -> None:
        """Delete registered PAT."""
        ws_id = await _create_workspace(rdb_session)
        user_id = await _create_user(rdb_session)
        repo = _make_repo()

        await repo.upsert(
            rdb_session,
            workspace_id=ws_id,
            user_id=user_id,
            token=_TOKEN,
        )

        await repo.delete_by_workspace_and_user(rdb_session, ws_id, user_id)

        pat = await repo.get_by_workspace_and_user(rdb_session, ws_id, user_id)
        assert pat is None

    async def test_delete_nonexistent(self, rdb_session: AsyncSession) -> None:
        """Deleting nonexistent PAT completes without error."""
        repo = _make_repo()
        await repo.delete_by_workspace_and_user(
            rdb_session, "ws_nonexistent", "usr_nonexistent"
        )


class TestGitHubPATRepositoryTokenStore:
    """PerUserTokenStore protocol implementation tests."""

    async def test_get_token(self, rdb_session: AsyncSession) -> None:
        """Fetch decrypted token with get_token."""
        ws_id = await _create_workspace(rdb_session)
        user_id = await _create_user(rdb_session)
        repo = _make_repo()

        await repo.upsert(
            rdb_session,
            workspace_id=ws_id,
            user_id=user_id,
            token=_TOKEN,
        )

        token = await repo.get_token(rdb_session, ws_id, user_id)
        assert token == _TOKEN

    async def test_get_token_nonexistent(self, rdb_session: AsyncSession) -> None:
        """get_token returns None when unregistered."""
        repo = _make_repo()
        token = await repo.get_token(rdb_session, "ws_nonexistent", "usr_nonexistent")
        assert token is None

    async def test_delete_token(self, rdb_session: AsyncSession) -> None:
        """Delete PAT with delete_token."""
        ws_id = await _create_workspace(rdb_session)
        user_id = await _create_user(rdb_session)
        repo = _make_repo()

        await repo.upsert(
            rdb_session,
            workspace_id=ws_id,
            user_id=user_id,
            token=_TOKEN,
        )

        await repo.delete_token(rdb_session, ws_id, user_id)

        token = await repo.get_token(rdb_session, ws_id, user_id)
        assert token is None
