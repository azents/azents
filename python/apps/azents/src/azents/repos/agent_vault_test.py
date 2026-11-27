"""Agent Vault tests against the migrated PostgreSQL schema."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.crypto import CredentialCipher
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.agent_mutation_guard import require_active_agent
from azents.repos.agent_vault import (
    AgentVaultRepository,
    InvalidVaultEntry,
    VaultAccessDenied,
    VaultEntryConflict,
    VaultEntryMetadata,
    VaultEntryMutation,
    VaultEntryUnavailable,
    VaultManager,
)

_OWNER = VaultManager("vault-workspace", "vault-owner")
_ADMIN = VaultManager("vault-workspace", "vault-member")
_VALUE = "synthetic-vault-entry-do-not-echo"


async def _seed(manager: SessionManager[WriteSession]) -> None:
    """Create two public Agents and scoped manager identities."""
    async with manager() as session:
        db = session.write_session
        await db.execute(
            sa.text("""
                INSERT INTO workspaces (id, name, handle)
                VALUES ('vault-workspace', 'Vault', 'vault-workspace')
            """)
        )
        for user_id, role in (("vault-owner", "owner"), ("vault-member", "member")):
            user = {"uid": user_id, "email": user_id + "@example.test", "role": role}
            await db.execute(
                sa.text("INSERT INTO users (id, primary_email_id) VALUES (:uid, :uid)"),
                user,
            )
            await db.execute(
                sa.text("""
                    INSERT INTO user_emails (id, user_id, email)
                    VALUES (:uid, :uid, :email)
                """),
                user,
            )
            await db.execute(
                sa.text("""
                    INSERT INTO workspace_users (id, workspace_id, user_id, name, role)
                    VALUES (:uid, 'vault-workspace', :uid, :uid, :role)
                """),
                user,
            )
        for agent_id in ("vault-a", "vault-b"):
            await db.execute(
                sa.text("""
                    INSERT INTO agents (
                        id, workspace_id, name, model_selection,
                        lightweight_model_selection, selectable_model_options,
                        main_model_label, lightweight_model_label, type,
                        runtime_capability, enabled, memory_enabled
                    )
                    VALUES (:aid, 'vault-workspace', :aid, '{}'::jsonb, '{}'::jsonb,
                        '[{"label":"default","candidates":[{"model_selection":{},
                           "settings":{"context_window_tokens": null,
                           "max_output_tokens": null,"builtin_tools":[]}}],
                           "subagent_enabled": true,"subagent_guidance": null}]'::jsonb,
                        'default', 'default', 'public', 'managed', TRUE, TRUE)
                """),
                {"aid": agent_id},
            )
        await db.execute(
            sa.text("""
                INSERT INTO agent_admins (id, agent_id, workspace_user_id)
                VALUES ('vault-grant', 'vault-a', 'vault-member')
            """)
        )


@pytest.fixture
async def vault(
    rdb_session_manager: SessionManager[WriteSession],
) -> AgentVaultRepository:
    await _seed(rdb_session_manager)
    return AgentVaultRepository(
        session_manager=rdb_session_manager,
        read_session_manager=rdb_session_manager,
        cipher=CredentialCipher(Fernet.generate_key().decode()),
    )


@pytest.mark.asyncio
async def test_manager_metadata_isolation_and_no_value_readback(
    vault: AgentVaultRepository,
) -> None:
    assert await vault.list_entries("vault-a", manager=_ADMIN) == []
    for agent_id, manager in (("vault-a", _ADMIN), ("vault-b", _OWNER)):
        await vault.mutate_entry(
            agent_id,
            "token",
            manager=manager,
            mutation=VaultEntryMutation.CREATE,
            value=SecretStr(_VALUE + agent_id),
        )
    with pytest.raises(VaultAccessDenied, match="Agent Vault not found"):
        await vault.list_entries("vault-b", manager=_ADMIN)
    with pytest.raises(VaultAccessDenied, match="Agent Vault not found"):
        await vault.list_entries(
            "vault-a", manager=VaultManager("another-workspace", "vault-owner")
        )
    values = await vault.resolve_for_execution("vault-a", {"token"})
    assert values["token"].get_secret_value() == _VALUE + "vault-a"
    assert _VALUE not in repr(values)
    with pytest.raises(VaultEntryUnavailable):
        await vault.resolve_for_execution("vault-a", {"token", "missing"})
    async with vault.session_manager() as session:
        result = await session.write_session.execute(
            sa.text("SELECT encrypted_value FROM agent_vault_entries ORDER BY agent_id")
        )
        ciphertext = result.scalars().all()
        assert len(ciphertext) == 2
        assert all(_VALUE not in value for value in ciphertext)
        await session.write_session.execute(
            sa.text("""
                UPDATE agent_vault_entries SET encrypted_value = 'invalid'
                WHERE agent_id = 'vault-a'
            """)
        )
    assert await vault.list_entries("vault-a", manager=_ADMIN) == [
        VaultEntryMetadata("token", "vault-member")
    ]
    with pytest.raises(VaultEntryUnavailable, match="Vault entry unavailable"):
        await vault.resolve_for_execution("vault-a", {"token"})


@pytest.mark.asyncio
async def test_explicit_mutation_batch_rollback_and_agent_cascade(
    vault: AgentVaultRepository,
) -> None:
    async with vault.session_manager() as session:
        await vault.insert_from_execution_in_session(
            session, "vault-a", "TOKEN", SecretStr(_VALUE), contributor_label="Agent"
        )
    with pytest.raises(VaultEntryConflict):
        async with vault.session_manager() as session:
            await vault.insert_from_execution_in_session(
                session, "vault-a", "TOKEN", SecretStr("new"), contributor_label="Agent"
            )
    with pytest.raises(VaultEntryUnavailable):
        await vault.mutate_entry(
            "vault-a",
            "token",
            manager=_OWNER,
            mutation=VaultEntryMutation.REPLACE,
            value=SecretStr("new"),
        )
    with pytest.raises(InvalidVaultEntry):
        async with vault.session_manager() as session:
            await require_active_agent(session, agent_id="vault-a")
            await vault.apply_manager_batch_in_session(
                session,
                "vault-a",
                {"token": SecretStr("new"), "\x00": SecretStr("invalid")},
                manager=_OWNER,
                contributor_label="Contributor",
            )
    assert await vault.list_entries("vault-a", manager=_OWNER) == [
        VaultEntryMetadata("TOKEN", "Agent")
    ]
    async with vault.session_manager() as session:
        await require_active_agent(session, agent_id="vault-a")
        await vault.apply_manager_batch_in_session(
            session,
            "vault-a",
            {"TOKEN": SecretStr("changed"), "token": SecretStr("lowercase")},
            manager=_OWNER,
            contributor_label="Contributor",
        )
    entries = await vault.resolve_for_execution("vault-a", {"TOKEN", "token"})
    assert entries["TOKEN"].get_secret_value() == "changed"
    assert entries["token"].get_secret_value() == "lowercase"
    await vault.mutate_entry(
        "vault-a",
        "token",
        manager=_OWNER,
        mutation=VaultEntryMutation.DELETE,
        value=None,
    )
    with pytest.raises(VaultEntryUnavailable):
        await vault.resolve_for_execution("vault-a", {"token"})
    async with vault.session_manager() as session:
        await vault.insert_from_execution_in_session(
            session, "vault-b", "TOKEN", SecretStr("other"), contributor_label="Agent"
        )
        await session.write_session.execute(
            sa.text("DELETE FROM agents WHERE id = 'vault-a'")
        )
        result = await session.read_session.scalars(
            sa.text("SELECT agent_id FROM agent_vault_entries ORDER BY agent_id")
        )
        assert result.all() == ["vault-b"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("principal", "revoke", "batch"),
    [
        (_OWNER, "UPDATE workspace_users SET role = 'manager' WHERE id = :uid", False),
        (_ADMIN, "DELETE FROM workspace_users WHERE id = :uid", True),
    ],
)
async def test_revocation_committed_first_denies_waiting_write(
    latest_db_schema: None,
    rdb_engine: AsyncEngine,
    principal: VaultManager,
    revoke: str,
    batch: bool,
) -> None:
    """A waiting manager write must see the committed grant loss."""
    manager = create_read_write_session_manager(rdb_engine)
    await _seed(manager)
    write_started: asyncio.Queue[int] = asyncio.Queue()

    @asynccontextmanager
    async def observed_manager() -> AsyncIterator[WriteSession]:
        async with manager() as session:
            pid = await session.write_session.scalar(
                sa.select(sa.func.pg_backend_pid())
            )
            assert isinstance(pid, int)
            await write_started.put(pid)
            yield session

    vault = AgentVaultRepository(
        session_manager=observed_manager,
        read_session_manager=manager,
        cipher=CredentialCipher(Fernet.generate_key().decode()),
    )

    async def write() -> None:
        if batch:
            async with observed_manager() as session:
                await vault.apply_manager_batch_in_session(
                    session,
                    "vault-a",
                    {"token": SecretStr(_VALUE)},
                    manager=principal,
                    contributor_label="Contributor",
                )
        else:
            await vault.mutate_entry(
                "vault-a",
                "token",
                manager=principal,
                mutation=VaultEntryMutation.CREATE,
                value=SecretStr(_VALUE),
            )

    try:
        async with asyncio.TaskGroup() as tasks:
            async with manager() as revoker:
                await revoker.write_session.execute(
                    sa.text(revoke), {"uid": principal.user_id}
                )
                blocker = await revoker.write_session.scalar(
                    sa.select(sa.func.pg_backend_pid())
                )

                async def write_and_expect_denial() -> None:
                    with pytest.raises(VaultAccessDenied):
                        await write()

                tasks.create_task(write_and_expect_denial())
                async with asyncio.timeout(5):
                    blocked = await write_started.get()
                    while not await revoker.read_session.scalar(
                        sa.text("SELECT :holder = ANY(pg_blocking_pids(:waiter))"),
                        {"holder": blocker, "waiter": blocked},
                    ):
                        await asyncio.sleep(0.01)
                # Membership removal may enroll historical memory and validate
                # an Agent FK before releasing the grant row.
                agent = await revoker.read_session.scalar(
                    sa.text(
                        "SELECT id FROM agents WHERE id = 'vault-a' "
                        "FOR KEY SHARE NOWAIT"
                    )
                )
                assert agent == "vault-a"
        with pytest.raises(VaultEntryUnavailable):
            await vault.resolve_for_execution("vault-a", {"token"})
    finally:
        async with manager() as session:
            await session.write_session.execute(
                sa.text("DELETE FROM agents WHERE workspace_id = 'vault-workspace'")
            )
            await session.write_session.execute(
                sa.text("DELETE FROM workspaces WHERE id = 'vault-workspace'")
            )
            await session.write_session.execute(
                sa.text("DELETE FROM users WHERE id IN ('vault-owner', 'vault-member')")
            )
