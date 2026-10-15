"""Database integration for explicit Workspace environment delegation."""

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
    StoredRuntimeEnvironmentValue,
)
from azents.core.workspace_environment import WorkspaceEnvironmentEntryEdit
from azents.rdb.models.workspace_environment import RDBWorkspaceEnvironmentVariable
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_runtime_environment import AgentRuntimeEnvironmentRepository
from azents.repos.agent_runtime_environment_test import _edit, _seed
from azents.repos.workspace_environment import WorkspaceEnvironmentRepository


def _shared(
    name: str, value: str, identity: str | None = None
) -> WorkspaceEnvironmentEntryEdit:
    return WorkspaceEnvironmentEntryEdit(
        id=identity,
        name=name,
        value=ReplacementRuntimeEnvironmentValue(
            type="replace", value=SecretStr(value)
        ),
    )


@pytest.mark.asyncio
async def test_opt_in_lifecycle_isolation_precedence_and_stale_identity(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    await _seed(rdb_session_manager)
    local = AgentRuntimeEnvironmentRepository(
        session_manager=rdb_session_manager,
        read_session_manager=rdb_session_manager,
        cipher=CredentialCipher(Fernet.generate_key().decode()),
        admin_repository=AgentAdminRepository(),
    )
    shared = WorkspaceEnvironmentRepository(local)
    owner = WorkspaceUserRole.OWNER
    auth = {"workspace_id": "env-ws", "workspace_user_id": "member", "role": owner}
    before = await shared.agent_settings("env-a", selected_ids=None, **auth)
    assert isinstance(before, Success) and before.value.selected_ids == []
    saved = await shared.replace(
        "env-ws",
        edits=[_shared("TOKEN", "first-secret"), _shared("OTHER", "other")],
        role=WorkspaceUserRole.MANAGER,
    )
    assert isinstance(saved, Success)
    token = next(entry for entry in saved.value.entries if entry.name == "TOKEN")
    other = next(entry for entry in saved.value.entries if entry.name == "OTHER")
    assert "first-secret" not in saved.value.model_dump_json()
    async with rdb_session_manager() as session:
        row = await session.read_session.get(RDBWorkspaceEnvironmentVariable, token.id)
        assert row is not None and "first-secret" not in row.encrypted_value
    assert await local.read_values("env-a") == {}
    selected = await shared.agent_settings("env-a", selected_ids=[token.id], **auth)
    assert isinstance(selected, Success)
    assert await local.read_values("env-a") == {"TOKEN": "first-secret"}
    assert await local.read_values("env-b") == {}
    assert await shared.agent_settings(
        "env-a",
        selected_ids=[other.id],
        workspace_id="env-ws",
        workspace_user_id="ordinary",
        role=WorkspaceUserRole.MANAGER,
    ) == Failure(RuntimeEnvironmentAccessError.DENIED)
    assert await shared.replace(
        "env-ws", edits=[], role=WorkspaceUserRole.MEMBER
    ) == Failure(RuntimeEnvironmentAccessError.DENIED)
    changed = await shared.replace(
        "env-ws",
        edits=[_shared("TOKEN", "next-secret", token.id), _shared("NEW", "new-secret")],
        role=owner,
    )
    assert isinstance(changed, Success)
    assert await local.read_values("env-a") == {"TOKEN": "next-secret"}
    with pytest.raises(InvalidRuntimeEnvironment):
        await shared.agent_settings("env-a", selected_ids=[other.id], **auth)
    await local.replace("env-a", edits=[_edit("TOKEN", "local-secret")], **auth)
    assert await local.read_values("env-a") == {"TOKEN": "local-secret"}
    projection = await shared.agent_settings("env-a", selected_ids=None, **auth)
    assert isinstance(projection, Success) and projection.value.overridden_names == [
        "TOKEN"
    ]
    await local.replace("env-a", edits=[], **auth)
    assert await local.read_values("env-a") == {"TOKEN": "next-secret"}
    await shared.agent_settings("env-a", selected_ids=[], **auth)
    assert await local.read_values("env-a") == {}
    await shared.agent_settings("env-a", selected_ids=[token.id], **auth)
    renamed = await shared.replace(
        "env-ws",
        edits=[
            WorkspaceEnvironmentEntryEdit(
                id=token.id,
                name="RENAMED",
                value=StoredRuntimeEnvironmentValue(type="stored", name="TOKEN"),
            )
        ],
        role=owner,
    )
    assert isinstance(renamed, Success) and renamed.value.entries[0].id != token.id
    assert await local.read_values("env-a") == {}
    await shared.replace("env-ws", edits=[], role=owner)
    recreated = await shared.replace(
        "env-ws", edits=[_shared("TOKEN", "new-identity")], role=owner
    )
    assert isinstance(recreated, Success) and recreated.value.entries[0].id != token.id
    with pytest.raises(InvalidRuntimeEnvironment):
        await shared.agent_settings("env-a", selected_ids=[token.id], **auth)
    with pytest.raises(InvalidRuntimeEnvironment):
        await shared.replace(
            "env-ws", edits=[_shared("TOKEN", "stale-secret", token.id)], role=owner
        )
    assert await local.read_values("env-a") == {}
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.text(
                "INSERT INTO workspaces (id,name,handle) "
                "VALUES ('other-ws','Other','other-ws')"
            )
        )
    foreign = await shared.replace(
        "other-ws", edits=[_shared("FOREIGN", "secret")], role=owner
    )
    assert isinstance(foreign, Success)
    with pytest.raises(InvalidRuntimeEnvironment):
        await shared.agent_settings(
            "env-a", selected_ids=[foreign.value.entries[0].id], **auth
        )
    assert await shared.agent_settings(
        "env-a",
        selected_ids=[],
        workspace_id="other-ws",
        workspace_user_id="member",
        role=owner,
    ) == Failure(RuntimeEnvironmentAccessError.NOT_FOUND)
