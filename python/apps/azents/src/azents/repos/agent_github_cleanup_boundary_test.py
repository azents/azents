"""Agent decommission captures transient revocation facts in its local write."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.crypto import CredentialCipher
from azents.core.github_user_oauth import (
    GitHubUserConnectionStatus,
    GitHubUserRegistration,
    GitHubUserRevocation,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.github_user_oauth import RDBGitHubUserConnection
from azents.rdb.models.toolkit import RDBAgentToolkit, RDBToolkitConfig
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_decommission import AgentDecommissionRepository
from azents.repos.agent_operations import AgentOperationsRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.github_user_oauth.guards import capture_and_clear_agent_user_tokens
from azents.repos.github_user_oauth.payloads import encode_registration
from azents.repos.runtime_profile.availability import (
    RuntimeProfileAvailabilityRepository,
)
from azents.repos.runtime_profile.repository import RuntimeProfileRepository
from azents.repos.workspace_model_settings import WorkspaceModelSettingsRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_option_dicts,
)


@pytest.mark.parametrize("known_token", [True, False])
async def test_capture_completes_with_local_decommission_before_provider_effects(
    monkeypatch: pytest.MonkeyPatch, known_token: bool
) -> None:
    raw = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(raw)
    cipher = CredentialCipher(Fernet.generate_key().decode())
    active = False
    captured = False
    target = GitHubUserRevocation(
        registration=GitHubUserRegistration(
            source="byoa_user",
            app_id="123",
            client_id="client-123",
            client_secret="private-client-secret",
            toolkit_revision=1,
            platform_generation=None,
        ),
        access_token="private-owned-token",
    )
    revocations = (target,) if known_token else ()

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        nonlocal active
        active = True
        try:
            yield session
        finally:
            active = False

    async def capture(
        current: WriteSession, *, agent_id: str, cipher: CredentialCipher
    ) -> tuple[GitHubUserRevocation, ...]:
        nonlocal captured
        assert active and current is session and agent_id == "agent-1"
        assert cipher is repository.credential_cipher
        captured = True
        return revocations

    capture_mock = AsyncMock(side_effect=capture)
    monkeypatch.setattr(
        "azents.repos.agent_operations.capture_and_clear_agent_user_tokens",
        capture_mock,
    )
    agents = AsyncMock(spec=AgentRepository)
    jobs = AsyncMock(spec=AgentDecommissionRepository)
    retention = AsyncMock(spec=ArchivedSessionRetentionRepository)
    retention.get_settings.return_value = SimpleNamespace(
        archived_session_retention_days=30
    )

    async def mark(current: WriteSession, agent_id: str) -> object:
        assert active and captured and current is session and agent_id == "agent-1"
        return SimpleNamespace(id=agent_id, workspace_id="workspace-1")

    agents.mark_decommissioning.side_effect = mark
    repository = AgentOperationsRepository(
        session_manager=manager,
        credential_cipher=cipher,
        agent_repository=agents,
        admin_repository=AsyncMock(spec=AgentAdminRepository),
        workspace_model_settings_repository=AsyncMock(
            spec=WorkspaceModelSettingsRepository
        ),
        workspace_user_repository=AsyncMock(spec=WorkspaceUserRepository),
        agent_decommission_repository=jobs,
        archived_session_retention_repository=retention,
        agent_session_repository=AsyncMock(spec=AgentSessionRepository),
        runtime_profile_repository=AsyncMock(spec=RuntimeProfileRepository),
        runtime_profile_availability_repository=AsyncMock(
            spec=RuntimeProfileAvailabilityRepository
        ),
    )
    result = await repository.request_decommission(
        agent_id="agent-1", workspace_user_id="member-1"
    )
    assert result.success and not active
    assert result.value.github_user_revocations == revocations
    assert "private-owned-token" not in repr(result.value)
    assert "private-client-secret" not in repr(result.value)
    capture_mock.assert_awaited_once_with(session, agent_id="agent-1", cipher=cipher)
    jobs.create_or_get.assert_awaited_once_with(
        session,
        agent_id="agent-1",
        workspace_id="workspace-1",
        requested_by_workspace_user_id="member-1",
    )


async def test_parent_capture_leaves_shared_and_other_agent_tokens_untouched(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Real SQL parent cleanup follows ownership rather than shared attachment."""
    cipher = CredentialCipher(Fernet.generate_key().decode())
    registration = GitHubUserRegistration(
        source="byoa_user",
        app_id="123",
        client_id="client-123",
        client_secret="current-client-secret",
        toolkit_revision=1,
        platform_generation=None,
    )
    async with rdb_session_manager() as session:
        workspace = RDBWorkspace(name="Parent capture", handle="parent-capture")
        session.write_session.add(workspace)
        await session.write_session.flush()
        selection = make_test_model_selection().model_dump(mode="json")
        agents = [
            RDBAgent(
                workspace_id=workspace.id,
                name=name,
                model_selection=selection,
                lightweight_model_selection=selection,
                selectable_model_options=make_test_selectable_model_option_dicts(
                    model_selection=selection,
                    lightweight_model_selection=selection,
                ),
                main_model_label="default",
                lightweight_model_label="default",
            )
            for name in ("Deleting Agent", "Other Agent")
        ]
        session.write_session.add_all(agents)
        await session.write_session.flush()
        deleting, other = agents
        toolkits = [
            RDBToolkitConfig(
                workspace_id=workspace.id,
                owner_agent_id=owner,
                toolkit_type="github",
                slug="github",
                name="GitHub user connection",
                config={"github_auth_type": "github_app_user"},
                encrypted_credentials=cipher.encrypt(
                    json.dumps(
                        {
                            "type": "github_app_user",
                            "app_id": "123",
                            "private_key": "private-key-for-registration",
                            "client_id": "client-123",
                            "client_secret": "current-client-secret",
                        }
                    )
                ),
            )
            for owner in (deleting.id, None, other.id)
        ]
        session.write_session.add_all(toolkits)
        await session.write_session.flush()
        owned, shared, other_owned = toolkits
        session.write_session.add(
            RDBAgentToolkit(
                agent_id=deleting.id, toolkit_id=shared.id, toolkit_type="github"
            )
        )
        for toolkit, token in zip(
            toolkits, ("owned-token", "shared-token", "other-agent-token"), strict=True
        ):
            session.write_session.add(
                RDBGitHubUserConnection(
                    toolkit_id=toolkit.id,
                    app_id="123",
                    account_id=42,
                    account_login="execution-account",
                    account_avatar_url=None,
                    encrypted_access_token=cipher.encrypt(token),
                    encrypted_registration=encode_registration(registration, cipher),
                    status=GitHubUserConnectionStatus.CONNECTED,
                    failure_reason=None,
                )
            )
        await session.write_session.flush()
        deleting_id = deleting.id
        owned_id, shared_id, other_id = owned.id, shared.id, other_owned.id
    async with rdb_session_manager() as session:
        captured = await capture_and_clear_agent_user_tokens(
            session, agent_id=deleting_id, cipher=cipher
        )
        assert len(captured) == 1 and captured[0].access_token == "owned-token"
        assert captured[0].registration.client_secret == "current-client-secret"
        assert "owned-token" not in repr(captured)
        assert "current-client-secret" not in repr(captured)
    async with rdb_session_manager() as session:
        remaining = (
            await session.read_session.scalars(
                sa.select(RDBGitHubUserConnection).where(
                    RDBGitHubUserConnection.toolkit_id.in_(
                        (owned_id, shared_id, other_id)
                    )
                )
            )
        ).all()
        assert {row.toolkit_id for row in remaining} == {shared_id, other_id}
        assert {cipher.decrypt(row.encrypted_access_token) for row in remaining} == {
            "shared-token",
            "other-agent-token",
        }
