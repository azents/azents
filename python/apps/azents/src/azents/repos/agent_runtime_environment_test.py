"""PostgreSQL environment encryption, isolation and management integration tests."""

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Success
from cryptography.fernet import Fernet
from pydantic import SecretStr

from azents.core.crypto import CredentialCipher
from azents.core.enums import WorkspaceUserRole
from azents.core.runtime_environment import (
    InvalidRuntimeEnvironment,
    ReplacementRuntimeEnvironmentValue,
    RuntimeEnvironmentAccessError,
    RuntimeEnvironmentEntryEdit,
    StoredRuntimeEnvironmentValue,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_runtime_environment import AgentRuntimeEnvironmentRepository


async def _seed(manager: SessionManager[WriteSession]) -> None:
    async with manager() as session:
        await session.write_session.execute(
            sa.text(
                "INSERT INTO workspaces (id, name, handle) "
                "VALUES ('env-ws', 'Environment', 'env-ws')"
            )
        )
        for agent_id in ("env-a", "env-b"):
            await session.write_session.execute(
                sa.text("""
                INSERT INTO agents (id, workspace_id, name, model_selection,
                    lightweight_model_selection, selectable_model_options,
                    main_model_label, lightweight_model_label, type, runtime_capability,
                    enabled, memory_enabled)
                VALUES (:agent_id, 'env-ws', :agent_id, '{}'::jsonb,
                    '{}'::jsonb,
                    '[{"label":"default","candidates":[{"model_selection":{},
                        "settings":{"context_window_tokens": null,
                        "max_output_tokens": null,"builtin_tools": []}}],
                        "subagent_enabled": true,"subagent_guidance": null}]'::jsonb,
                    'default', 'default', 'public', 'managed',
                    TRUE, TRUE)
            """),
                {"agent_id": agent_id},
            )


def _edit(name: str, value: str) -> RuntimeEnvironmentEntryEdit:
    return RuntimeEnvironmentEntryEdit(
        name=name,
        value=ReplacementRuntimeEnvironmentValue(
            type="replace", value=SecretStr(value)
        ),
    )


@pytest.mark.asyncio
async def test_encrypted_retention_rename_isolation_authority_and_delete(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    await _seed(rdb_session_manager)
    cipher = CredentialCipher(Fernet.generate_key().decode())
    repository = AgentRuntimeEnvironmentRepository(
        session_manager=rdb_session_manager,
        read_session_manager=rdb_session_manager,
        cipher=cipher,
        admin_repository=AgentAdminRepository(),
    )
    auth = {
        "workspace_id": "env-ws",
        "workspace_user_id": "member",
        "role": WorkspaceUserRole.OWNER,
    }
    result = await repository.replace(
        "env-a",
        edits=[_edit("API_TOKEN", "not-a-real-secret"), _edit("REMOVE", "removed")],
        **auth,
    )
    assert isinstance(result, Success)
    assert result.value.names == ["API_TOKEN", "REMOVE"]
    assert "not-a-real-secret" not in repr(result)
    async with rdb_session_manager() as session:
        stored = (
            await session.read_session.execute(
                sa.text(
                    "SELECT encrypted_runtime_environment FROM agents WHERE id='env-a'"
                )
            )
        ).scalar_one()
        assert isinstance(stored, str)
        assert "not-a-real-secret" not in stored
        assert "not-a-real-secret" in cipher.decrypt(stored)
    assert await repository.read_values("env-a") == {
        "API_TOKEN": "not-a-real-secret",
        "REMOVE": "removed",
    }
    assert await repository.read_values("env-b") == {}
    assert await repository.read_values("missing") == {}
    result = await repository.get("env-a", **auth)
    assert isinstance(result, Success) and result.value.can_manage
    await repository.replace(
        "env-a",
        edits=[
            RuntimeEnvironmentEntryEdit(
                name="RENAMED",
                value=StoredRuntimeEnvironmentValue(type="stored", name="API_TOKEN"),
            )
        ],
        **auth,
    )
    assert await repository.read_values("env-a") == {"RENAMED": "not-a-real-secret"}
    with pytest.raises(InvalidRuntimeEnvironment):
        await repository.replace(
            "env-a",
            edits=[
                RuntimeEnvironmentEntryEdit(
                    name="A",
                    value=StoredRuntimeEnvironmentValue(type="stored", name="MISSING"),
                )
            ],
            **auth,
        )
    assert await repository.read_values("env-a") == {"RENAMED": "not-a-real-secret"}
    denied = await repository.replace(
        "env-a",
        edits=[],
        workspace_id="env-ws",
        workspace_user_id="ordinary-member",
        role=WorkspaceUserRole.MEMBER,
    )
    assert denied == Failure(RuntimeEnvironmentAccessError.DENIED)
    mismatch = await repository.replace(
        "env-a",
        edits=[],
        workspace_id="other-ws",
        workspace_user_id="member",
        role=WorkspaceUserRole.OWNER,
    )
    assert mismatch == Failure(RuntimeEnvironmentAccessError.NOT_FOUND)
    visible = await repository.get(
        "env-a",
        workspace_id="env-ws",
        workspace_user_id="ordinary-member",
        role=WorkspaceUserRole.MEMBER,
    )
    assert isinstance(visible, Success) and not visible.value.can_manage
    await repository.replace("env-a", edits=[], **auth)
    assert await repository.read_values("env-a") == {}
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.text(
                "UPDATE agents SET runtime_capability='none', type='private' "
                "WHERE id='env-a'"
            )
        )
    hidden = await repository.get(
        "env-a",
        workspace_id="env-ws",
        workspace_user_id="ordinary-member",
        role=WorkspaceUserRole.MEMBER,
    )
    assert hidden == Failure(RuntimeEnvironmentAccessError.NOT_FOUND)
    assert await repository.read_values("env-a") == {}
