"""Rollback protects local credentials without depending on provider cleanup."""

from unittest.mock import create_autospec

import pytest
import sqlalchemy as sa
from alembic.config import Config as AlembicConfig
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection

from azents.consts import PROJECT_ROOT
from azents.core.config import Config
from azents.core.github_user_auth import GitHubUserProviderError
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.github_user_oauth.operations import GitHubUserOAuthOperationRepository
from azents.repos.github_user_oauth.operations_test import _harness, _review, _start
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.github_user_oauth.provider import GitHubUserProvider
from azents.services.github_user_oauth.service import GitHubUserOAuthService


def _downgrade(connection: Connection) -> None:
    config = AlembicConfig(PROJECT_ROOT / "db-schemas" / "rdb" / "alembic.ini")
    revision = ScriptDirectory.from_config(config).get_revision("8c432dfdd6c6")
    assert revision is not None
    with Operations.context(MigrationContext.configure(connection)):
        revision.module.downgrade()


@pytest.mark.parametrize("active", [False, True])
async def test_downgrade_preserves_known_credentials_until_local_removal(
    rdb_session_manager: SessionManager[WriteSession], active: bool
) -> None:
    """Active and reviewed token material survives a refused downgrade."""
    h = await _harness(rdb_session_manager)
    attempt = await _review(h, "known-token")
    if active:
        await h.repository.confirm(
            requester=h.requester, attempt_id=attempt.id, registration=h.registration
        )
    async with rdb_session_manager() as session:
        connection = await session.write_session.connection()
        with pytest.raises(RuntimeError, match="local GitHub user credentials"):
            await connection.run_sync(_downgrade)
    if active:
        current = (await h.repository.read_context(requester=h.requester)).connection
        assert current is not None and current.access_token == "known-token"
    else:
        review = await h.repository.read_review(
            requester=h.requester, attempt_id=attempt.id
        )
        assert review.candidate is not None
        assert review.candidate.access_token == "known-token"

    revocations = await h.repository.disconnect(
        requester=h.requester, registration=h.registration
    )
    provider = create_autospec(GitHubUserProvider, instance=True)
    provider.revoke.side_effect = GitHubUserProviderError(
        reason="provider_unavailable", status_code=503
    )
    cleanup = GitHubUserOAuthService(
        repository=create_autospec(GitHubUserOAuthOperationRepository, instance=True),
        config=Config.model_construct(),
        platform_runtime=create_autospec(
            PlatformGitHubAppRuntimeService, instance=True
        ),
        provider=provider,
    )
    await cleanup.cleanup_revocations(revocations)
    provider.revoke.assert_awaited_once()
    async with rdb_session_manager() as session:
        connection = await session.write_session.connection()
        await connection.run_sync(_downgrade)
        assert (
            await session.read_session.scalar(
                sa.text("SELECT to_regclass('github_user_oauth_connections')")
            )
            is None
        )
        assert (
            await session.read_session.scalar(
                sa.text("SELECT to_regclass('github_user_oauth_attempts')")
            )
            is None
        )


async def test_downgrade_allows_setup_without_known_token(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A pending setup is not retained as a cleanup receipt or rollback gate."""
    h = await _harness(rdb_session_manager)
    await _start(h, "not-issued")
    async with rdb_session_manager() as session:
        connection = await session.write_session.connection()
        await connection.run_sync(_downgrade)
        assert (
            await session.read_session.scalar(
                sa.text("SELECT to_regclass('github_user_oauth_attempts')")
            )
            is None
        )
