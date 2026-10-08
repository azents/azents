"""Current-row protection against stale pre-authorization Toolkit mutations."""

import asyncio
import dataclasses
import json
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.crypto import CredentialCipher
from azents.core.github_user_oauth import GitHubUserErrorCode, GitHubUserOAuthError
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.github_user_oauth import RDBGitHubUserConnection
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.github_user_oauth.parent_guards_test import (
    _connection,
    _ParentRows,
    _parents,
)
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.data import ToolkitConfig, ToolkitUpdate
from azents.repos.toolkit_operations.github_user_guard import (
    guard_user_registration_update,
    guard_user_toolkit_delete,
)


@dataclasses.dataclass(frozen=True)
class _GuardDatabase:
    manager: SessionManager[WriteSession]
    parents: _ParentRows


@pytest_asyncio.fixture
async def guard_database(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> AsyncIterator[_GuardDatabase]:
    """Use separately committed transactions, not a shared savepoint connection."""
    del latest_db_schema
    manager = create_read_write_session_manager(rdb_engine)
    parents = await _parents(manager)
    try:
        yield _GuardDatabase(manager, parents)
    finally:
        async with manager() as session:
            await session.write_session.execute(
                sa.delete(RDBGitHubUserConnection).where(
                    RDBGitHubUserConnection.toolkit_id.in_(
                        (
                            parents.owned_toolkit_id,
                            parents.shared_toolkit_id,
                            parents.other_owned_toolkit_id,
                        )
                    )
                )
            )
            await session.write_session.execute(
                sa.delete(RDBAgent).where(
                    RDBAgent.id.in_((parents.agent_id, parents.other_agent_id))
                )
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == parents.workspace_id)
            )


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("deleting", [False, True])
@pytest.mark.parametrize("hold_orm", [False, True])
async def test_stale_pat_mutation_rereads_activated_user_registration(
    guard_database: _GuardDatabase,
    owned: bool,
    deleting: bool,
    hold_orm: bool,
) -> None:
    rdb_session_manager = guard_database.manager
    parents = guard_database.parents
    toolkit_id = parents.owned_toolkit_id if owned else parents.shared_toolkit_id
    cipher = CredentialCipher(Fernet.generate_key().decode())
    repository = ToolkitRepository(cipher)
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBToolkitConfig)
            .where(RDBToolkitConfig.id == toolkit_id)
            .values(
                config={"github_auth_type": "pat"},
                encrypted_credentials=cipher.encrypt(
                    json.dumps({"type": "pat", "token": "old-pat"})
                ),
            )
        )
    read_old = asyncio.Event()
    new_activated = asyncio.Event()

    async def mutation(session: WriteSession, old: ToolkitConfig) -> None:
        if deleting:
            await guard_user_toolkit_delete(session, old, repository=repository)
        else:
            update = ToolkitUpdate(
                config={"github_auth_type": "pat"},
                credentials=json.dumps({"type": "pat", "token": "old-pat"}),
            )
            await guard_user_registration_update(
                session, old, update, repository=repository
            )
            await repository.update_by_id(session, toolkit_id, update)

    async def stale_mutation() -> GitHubUserOAuthError:
        if hold_orm:
            async with rdb_session_manager() as session:
                held = await session.read_session.get(RDBToolkitConfig, toolkit_id)
                assert held is not None and held.config["github_auth_type"] == "pat"
                old = await repository.get_by_id(session, toolkit_id)
                assert old is not None
                read_old.set()
                await new_activated.wait()
                with pytest.raises(GitHubUserOAuthError) as caught:
                    await mutation(session, old)
                # The lock explicitly populated this same retained ORM instance.
                assert held.config["github_auth_type"] == "github_app_user"
                return caught.value
        async with rdb_session_manager() as session:
            old = await repository.get_by_id(session, toolkit_id)
            assert old is not None and old.config["github_auth_type"] == "pat"
        read_old.set()
        await new_activated.wait()
        with pytest.raises(GitHubUserOAuthError) as caught:
            async with rdb_session_manager() as session:
                await mutation(session, old)
        return caught.value

    stale = asyncio.create_task(stale_mutation())
    await read_old.wait()
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBToolkitConfig)
            .where(RDBToolkitConfig.id == toolkit_id)
            .values(
                config={"github_auth_type": "github_app_user"},
                encrypted_credentials=cipher.encrypt(
                    json.dumps(
                        {
                            "type": "github_app_user",
                            "app_id": "123",
                            "client_id": "Iv1.user",
                            "private_key": "app-key",
                            "client_secret": "app-secret",
                        }
                    )
                ),
            )
        )
    connection_id = await _connection(rdb_session_manager, toolkit_id)
    new_activated.set()
    error = await stale
    assert error.code is GitHubUserErrorCode.CLEANUP_REQUIRED
    async with rdb_session_manager() as session:
        current = await repository.get_by_id(session, toolkit_id)
        assert current is not None
        assert current.config["github_auth_type"] == "github_app_user"
        assert (
            await session.read_session.scalar(
                sa.select(RDBGitHubUserConnection.id).where(
                    RDBGitHubUserConnection.toolkit_id == toolkit_id
                )
            )
            == connection_id
        )
