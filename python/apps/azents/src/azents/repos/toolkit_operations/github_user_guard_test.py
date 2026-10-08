"""Current-row protection and token capture during concurrent Toolkit mutations."""

import asyncio
import dataclasses
import json
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.crypto import CredentialCipher
from azents.core.github_user_oauth import (
    GitHubUserConnectionStatus,
    GitHubUserErrorCode,
    GitHubUserOAuthError,
    GitHubUserRegistration,
    GitHubUserRevocation,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.github_user_oauth import RDBGitHubUserConnection
from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.github_user_oauth.payloads import encode_registration
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.data import ToolkitConfig, ToolkitUpdate
from azents.repos.toolkit_operations.github_user_guard import (
    capture_user_toolkit_delete,
    guard_user_registration_update,
)
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_option_dicts,
)


@dataclasses.dataclass(frozen=True)
class _GuardDatabase:
    manager: SessionManager[WriteSession]
    owned_toolkit_id: str
    shared_toolkit_id: str


@pytest_asyncio.fixture
async def guard_database(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> AsyncIterator[_GuardDatabase]:
    """Use committed transactions to exercise retained ORM identity maps."""
    del latest_db_schema
    manager = create_read_write_session_manager(rdb_engine)
    async with manager() as session:
        workspace = RDBWorkspace(
            name="Toolkit guard", handle="guard-" + uuid4().hex[:8]
        )
        session.write_session.add(workspace)
        await session.write_session.flush()
        selection = make_test_model_selection().model_dump(mode="json")
        agent = RDBAgent(
            workspace_id=workspace.id,
            name="Toolkit owner",
            model_selection=selection,
            lightweight_model_selection=selection,
            selectable_model_options=make_test_selectable_model_option_dicts(
                model_selection=selection,
                lightweight_model_selection=selection,
            ),
            main_model_label="default",
            lightweight_model_label="default",
        )
        session.write_session.add(agent)
        await session.write_session.flush()
        toolkits = [
            RDBToolkitConfig(
                workspace_id=workspace.id,
                owner_agent_id=owner,
                toolkit_type="github",
                slug="github",
                name="GitHub user",
                config={"github_auth_type": "pat"},
            )
            for owner in (agent.id, None)
        ]
        session.write_session.add_all(toolkits)
        await session.write_session.flush()
        state = _GuardDatabase(manager, toolkits[0].id, toolkits[1].id)
        workspace_id, agent_id = workspace.id, agent.id
    try:
        yield state
    finally:
        async with manager() as session:
            await session.write_session.execute(
                sa.delete(RDBToolkitConfig).where(
                    RDBToolkitConfig.workspace_id == workspace_id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == agent_id)
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
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
    manager = guard_database.manager
    toolkit_id = (
        guard_database.owned_toolkit_id if owned else guard_database.shared_toolkit_id
    )
    cipher = CredentialCipher(Fernet.generate_key().decode())
    repository = ToolkitRepository(cipher)
    async with manager() as session:
        await session.write_session.execute(
            sa.update(RDBToolkitConfig)
            .where(RDBToolkitConfig.id == toolkit_id)
            .values(
                encrypted_credentials=cipher.encrypt(
                    json.dumps({"type": "pat", "token": "old-pat"})
                )
            )
        )
    read_old, new_activated = asyncio.Event(), asyncio.Event()

    async def mutation(
        session: WriteSession, old: ToolkitConfig
    ) -> tuple[GitHubUserRevocation, ...]:
        if deleting:
            revocations = await capture_user_toolkit_delete(
                session, old, repository=repository
            )
            await repository.delete_by_id(session, toolkit_id)
            return revocations
        update = ToolkitUpdate(
            config={"github_auth_type": "pat"},
            credentials=json.dumps({"type": "pat", "token": "old-pat"}),
        )
        await guard_user_registration_update(
            session, old, update, repository=repository
        )
        await repository.update_by_id(session, toolkit_id, update)
        return ()

    async def execute(
        session: WriteSession, old: ToolkitConfig
    ) -> tuple[GitHubUserRevocation, ...]:
        if deleting:
            return await mutation(session, old)
        with pytest.raises(GitHubUserOAuthError) as caught:
            await mutation(session, old)
        assert caught.value.code is GitHubUserErrorCode.STALE
        return ()

    async def stale_mutation() -> tuple[GitHubUserRevocation, ...]:
        if hold_orm:
            async with manager() as session:
                held = await session.read_session.get(RDBToolkitConfig, toolkit_id)
                assert held is not None and held.config["github_auth_type"] == "pat"
                old = await repository.get_by_id(session, toolkit_id)
                assert old is not None
                read_old.set()
                await new_activated.wait()
                result = await execute(session, old)
                assert held.config["github_auth_type"] == "github_app_user"
                return result
        async with manager() as session:
            old = await repository.get_by_id(session, toolkit_id)
            assert old is not None and old.config["github_auth_type"] == "pat"
        read_old.set()
        await new_activated.wait()
        async with manager() as session:
            return await execute(session, old)

    stale = asyncio.create_task(stale_mutation())
    await read_old.wait()
    registration = GitHubUserRegistration(
        source="byoa_user",
        app_id="123",
        client_id="Iv1.user",
        client_secret="app-secret",
        toolkit_revision=1,
        platform_generation=None,
    )
    async with manager() as session:
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
        connection = RDBGitHubUserConnection(
            toolkit_id=toolkit_id,
            app_id="123",
            account_id=42,
            account_login="execution-user",
            account_avatar_url=None,
            encrypted_access_token=cipher.encrypt("new-current-token"),
            encrypted_registration=encode_registration(registration, cipher),
            status=GitHubUserConnectionStatus.CONNECTED,
            failure_reason=None,
        )
        session.write_session.add(connection)
        await session.write_session.flush()
        connection_id = connection.id
    new_activated.set()
    revocations = await stale
    async with manager() as session:
        current = await repository.get_by_id(session, toolkit_id)
        if deleting:
            assert current is None
            assert len(revocations) == 1
            assert revocations[0].access_token == "new-current-token"
            assert revocations[0].registration.client_secret == "app-secret"
        else:
            assert (
                current is not None
                and current.config["github_auth_type"] == "github_app_user"
            )
            assert (
                await session.read_session.scalar(
                    sa.select(RDBGitHubUserConnection.id).where(
                        RDBGitHubUserConnection.toolkit_id == toolkit_id
                    )
                )
                == connection_id
            )
