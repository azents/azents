"""Current-account management parity and post-preparation authority in PostgreSQL."""

import dataclasses
import datetime
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Success

from azents.core.personal_toolkit import (
    PersonalToolkitAccessConflict,
    PersonalToolkitAccessMutation,
    PersonalToolkitAgentIneligible,
    PersonalToolkitAuthorityDenied,
    PersonalToolkitConfigurationConflict,
    PersonalToolkitManager,
    PersonalToolkitNotFound,
    PersonalToolkitProviderAuthorityDenied,
)
from azents.core.system_setting import SystemSettingFieldSource
from azents.core.system_setting_payload import SystemSettingPayloadResolver
from azents.core.toolkit_ownership import PersonalToolkitAccessMode as Mode
from azents.engine.tools.mcp import McpToolkitProvider
from azents.rdb.models.session import RDBSession
from azents.rdb.models.user import RDBUser
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.repos.agent import AgentRepository
from azents.repos.github_user_installation import GithubUserInstallationRepository
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.session import SessionRepository
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.repos.toolkit import AgentToolkitRepository, ToolkitRepository
from azents.repos.toolkit.personal_management import PersonalToolkitManagementRepository
from azents.repos.toolkit.personal_test import Fixture, creation
from azents.repos.toolkit.personal_test import (
    fixture as fixture,  # noqa: PLC0414 -- register the shared pytest fixture
)
from azents.repos.toolkit_namespace import ToolkitNamespaceRepository
from azents.repos.toolkit_operations import ToolkitOperationsRepository
from azents.repos.toolkit_operations.data import PlatformToolkitAuthority
from azents.repos.user import UserRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.google_oauth.service import GoogleOAuthService
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.data import ToolkitConfigurationInput
from azents.services.toolkit.personal import PersonalToolkitService


@dataclasses.dataclass(frozen=True)
class Harness:
    foundation: Fixture
    subject: PersonalToolkitManager
    other: PersonalToolkitManager
    repository: PersonalToolkitManagementRepository
    common: ToolkitService
    service: PersonalToolkitService
    cleanup: AsyncMock


@pytest.fixture
async def harness(fixture: Fixture) -> AsyncIterator[Harness]:
    """Use actual narrow repositories and the existing common Provider service."""
    f = fixture
    async with f.writes() as session:
        rows = [
            RDBSession(
                user_id=user_id,
                refresh_token=uuid4().hex,
                expires_at=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(hours=1),
            )
            for user_id in [f.user_id, f.other_user_id]
        ]
        session.write_session.add_all(rows)
        await session.write_session.flush()
        subjects = [PersonalToolkitManager(row.user_id, row.id) for row in rows]
    assert f.repository.cipher is not None
    oauth = MCPOAuthConnectionRepository(f.repository.cipher)
    shared = ToolkitOperationsRepository(
        toolkit_repository=ToolkitRepository(f.repository.cipher),
        agent_toolkit_repository=AgentToolkitRepository(),
        agent_repository=AgentRepository(),
        namespace_repository=ToolkitNamespaceRepository(),
        workspace_repository=WorkspaceRepository(),
        workspace_user_repository=WorkspaceUserRepository(),
        github_installation_repository=GithubUserInstallationRepository(),
        oauth_connection_repository=oauth,
        system_setting_repository=SystemSettingRepository(),
        session_manager=f.writes,
    )
    repository = PersonalToolkitManagementRepository(
        session_manager=f.writes,
        repository=f.repository,
        user_repository=UserRepository(),
        auth_session_repository=SessionRepository(),
        shared_operations=shared,
        oauth_repository=oauth,
        setting_payloads=MagicMock(spec=SystemSettingPayloadResolver),
    )
    cleanup = AsyncMock()
    common = ToolkitService(
        operations_repository=shared,
        owned_operations=MagicMock(),
        toolkit_registry={"mcp": McpToolkitProvider()},
        github_runtime=MagicMock(),
        github_user_oauth=MagicMock(cleanup_revocations=cleanup),
    )
    yield Harness(
        f,
        subjects[0],
        subjects[1],
        repository,
        common,
        PersonalToolkitService(repository, common, MagicMock(spec=GoogleOAuthService)),
        cleanup,
    )


def config() -> ToolkitConfigurationInput:
    """An ordinary MCP setup including the shared fields and presentation options."""
    return ToolkitConfigurationInput(
        toolkit_type="mcp",
        slug="personal",
        name="Personal MCP",
        description="Description",
        prompt="Use this connection",
        config={"server_url": "https://mcp.test", "auth_type": "none"},
        enabled=True,
        always_expose_tools=True,
    )


async def test_personal_crud_requires_only_owner_not_workspace_role(
    harness: Harness,
) -> None:
    """A Member can manage User-global connections across ordinary Agent contexts."""
    h = harness
    result = await h.service.create(h.subject, config())
    assert isinstance(result, Success)
    toolkit = result.value
    assert toolkit.owner.user_id == h.subject.user_id
    assert toolkit.access_mode is Mode.ALL and toolkit.selected_agent_ids == ()
    assert toolkit.readiness == "ready" and toolkit.always_expose_tools
    assert toolkit.config == config().config and toolkit.prompt == config().prompt
    assert len(await h.service.list(h.subject)) == 1
    assert await h.service.list(h.other) == []
    for action in (h.service.get, h.service.delete):
        with pytest.raises(PersonalToolkitNotFound):
            await action(h.other, toolkit.id)
    with pytest.raises(PersonalToolkitNotFound):
        await h.service.update(h.other, toolkit.id, {"name": "Foreign"})
    updated = await h.service.update(
        h.subject,
        toolkit.id,
        {"name": "Renamed", "enabled": False, "always_expose_tools": False},
    )
    assert isinstance(updated, Success)
    assert updated.value.id == toolkit.id and updated.value.name == "Renamed"
    assert (
        updated.value.readiness == "disabled" and not updated.value.always_expose_tools
    )
    assert (
        updated.value.prompt == config().prompt
        and updated.value.config == config().config
    )
    await h.service.delete(h.subject, toolkit.id)
    assert await h.service.list(h.subject) == []
    h.cleanup.assert_awaited_once_with(())


async def test_policy_editors_share_authority_without_agent_admin(
    harness: Harness,
) -> None:
    """Both editors share expected-mode/delta authority and reject foreign edits."""
    h = harness
    toolkit = (
        await h.repository.create(h.subject, creation(), platform_authority=None)
    ).toolkit
    eligible = await h.service.eligible_agents(h.subject)
    assert {entry.agent_id for entry in eligible} == set(h.foundation.agent_ids[:3])
    assert len({entry.workspace_id for entry in eligible}) == 2
    choices = await h.service.agent_connections(h.subject, h.foundation.agent_ids[0])
    assert [entry.id for entry in choices] == [toolkit.id]
    mutation = PersonalToolkitAccessMutation(
        toolkit.id, None, frozenset(), frozenset([h.foundation.agent_ids[0]]), Mode.ALL
    )
    [saved] = await h.service.mutate_access(
        h.subject, [mutation], agent_id=h.foundation.agent_ids[0]
    )
    assert saved.mode is Mode.SELECTED and set(saved.selected_agent_ids) == set(
        h.foundation.agent_ids[1:3]
    )
    with pytest.raises(PersonalToolkitAccessConflict):
        await h.service.mutate_access(h.subject, [mutation], agent_id=None)
    with pytest.raises(PersonalToolkitAgentIneligible):
        await h.service.mutate_access(
            h.subject,
            [dataclasses.replace(mutation, expected_mode=Mode.SELECTED)],
            agent_id=h.foundation.agent_ids[1],
        )
    with pytest.raises(PersonalToolkitAgentIneligible):
        await h.service.agent_connections(h.other, h.foundation.agent_ids[0])
    current = await h.service.get(h.subject, toolkit.id)
    assert (
        current.access_mode is Mode.SELECTED
        and current.selected_agent_ids == saved.selected_agent_ids
    )


@pytest.mark.parametrize(
    "invalid", ["foreign_session", "revoked", "expired", "disabled", "missing_session"]
)
async def test_exact_current_account_rechecked_in_completed_operations(
    harness: Harness, invalid: str
) -> None:
    """Authenticated route state cannot outlive the current canonical Auth Session."""
    h = harness
    toolkit = (
        await h.repository.create(h.subject, creation(), platform_authority=None)
    ).toolkit
    subject = h.subject
    async with h.foundation.writes() as session:
        if invalid == "foreign_session":
            subject = PersonalToolkitManager(h.subject.user_id, h.other.session_id)
        elif invalid == "missing_session":
            subject = PersonalToolkitManager(h.subject.user_id, uuid4().hex)
        elif invalid == "disabled":
            await session.write_session.execute(
                sa.update(RDBUser)
                .where(RDBUser.id == subject.user_id)
                .values(access_disabled_at=sa.func.now())
            )
        else:
            patch = (
                {"revoked_at": sa.func.now()}
                if invalid == "revoked"
                else {
                    "expires_at": datetime.datetime.now(datetime.UTC)
                    - datetime.timedelta(seconds=1)
                }
            )
            await session.write_session.execute(
                sa.update(RDBSession)
                .where(RDBSession.id == subject.session_id)
                .values(**patch)
            )
    for action in [
        lambda: h.repository.list(subject),
        lambda: h.repository.get(subject, toolkit.id),
        lambda: h.repository.eligible_agents(subject),
        lambda: h.repository.create(subject, creation(), platform_authority=None),
    ]:
        with pytest.raises(PersonalToolkitAuthorityDenied):
            await action()


async def test_auth_revoked_during_external_preparation_prevents_creation(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Provider I/O occurs outside DB, followed by a new exact account admission."""
    h = harness

    async def revoke(toolkit_type: str, credentials: dict[str, object] | None) -> None:
        del toolkit_type, credentials
        async with h.foundation.writes() as session:
            await session.write_session.execute(
                sa.update(RDBSession)
                .where(RDBSession.id == h.subject.session_id)
                .values(revoked_at=sa.func.now())
            )

    monkeypatch.setattr(h.common, "_validate_provider_credentials", revoke)
    with pytest.raises(PersonalToolkitAuthorityDenied):
        await h.service.create(h.subject, config())
    assert await h.foundation.operations.list_personal(user_id=h.subject.user_id) == []


async def test_prepared_edit_rejects_concurrent_source_change(harness: Harness) -> None:
    """Prepared edits cannot overwrite a newer connection using stale inputs."""
    h = harness
    snapshot = await h.repository.create(h.subject, creation(), platform_authority=None)
    await h.foundation.operations.update(
        user_id=h.subject.user_id,
        toolkit_id=snapshot.toolkit.id,
        update={"name": "Concurrent"},
    )
    with pytest.raises(PersonalToolkitConfigurationConflict):
        await h.repository.update(
            h.subject,
            snapshot.toolkit.id,
            {"name": "Stale"},
            expected_revision=snapshot.toolkit.revision,
            slug_reset_canonical_name=None,
            platform_authority=None,
        )
    current = await h.repository.get(h.subject, snapshot.toolkit.id)
    assert current.toolkit.name == "Concurrent"


async def test_platform_registration_revalidated_in_personal_write(
    harness: Harness,
) -> None:
    """Prepared Platform metadata cannot replace current DB registration authority."""
    h = harness
    authority = PlatformToolkitAuthority(
        app_id="missing-app",
        app_id_source=SystemSettingFieldSource.ADMIN,
        user_id=h.subject.user_id,
        installation_ids=frozenset(),
    )
    with pytest.raises(PersonalToolkitProviderAuthorityDenied):
        await h.repository.create(h.subject, creation(), platform_authority=authority)
    with pytest.raises(PersonalToolkitProviderAuthorityDenied):
        await h.repository.create(
            h.subject,
            creation(),
            platform_authority=dataclasses.replace(authority, user_id=h.other.user_id),
        )
    assert await h.service.list(h.subject) == []


async def test_workspace_membership_not_required_for_personal_crud(
    harness: Harness,
) -> None:
    """Ownership stays User-global after Workspace memberships disappear."""
    h = harness
    async with h.foundation.writes() as session:
        await session.write_session.execute(
            sa.delete(RDBWorkspaceUser).where(
                RDBWorkspaceUser.user_id == h.subject.user_id
            )
        )
    result = await h.service.create(h.subject, config())
    assert isinstance(result, Success)
    assert await h.service.eligible_agents(h.subject) == []
    assert len(await h.service.list(h.subject)) == 1
    with pytest.raises(PersonalToolkitAgentIneligible):
        await h.service.agent_connections(h.subject, h.foundation.agent_ids[0])
