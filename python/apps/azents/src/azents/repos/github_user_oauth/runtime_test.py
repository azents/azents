"""PostgreSQL current user execution authority and exact late-failure fences."""

import dataclasses
import json
from unittest.mock import create_autospec

import pytest
import sqlalchemy as sa

from azents.core.enums import AgentLifecycleStatus, AgentSessionStatus
from azents.core.github_user_oauth import (
    GitHubUserConnectionStatus,
    GitHubUserOAuthError,
)
from azents.core.github_user_runtime import GitHubUserExecutionContext
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.github_user_oauth import RDBGitHubUserConnection
from azents.rdb.models.toolkit import RDBAgentToolkit, RDBToolkitConfig
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.github_user_oauth.operations_test import (
    _harness,
    _review,
    _save_credentials,
)
from azents.repos.github_user_oauth.runtime import GitHubUserRuntimeOperationRepository
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.github_user_oauth.runtime import GitHubUserRuntimeService
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_selectable_model_option_dicts,
)


@dataclasses.dataclass(frozen=True)
class _RuntimeFixture:
    repository: GitHubUserRuntimeOperationRepository
    service: GitHubUserRuntimeService
    context: GitHubUserExecutionContext
    connection_id: str


async def _runtime_fixture(
    manager: SessionManager[WriteSession], *, owned: bool
) -> _RuntimeFixture:
    setup = await _harness(manager)
    await _save_credentials(manager, setup, app_id="123", client_id="Iv1.client")
    attempt = await _review(setup, "current-token")
    result = await setup.repository.confirm(
        requester=setup.requester,
        attempt_id=attempt.id,
        registration=setup.registration,
    )
    selection = make_test_model_selection().model_dump(mode="json")
    async with manager() as session:
        agent = RDBAgent(
            workspace_id=setup.requester.workspace_id,
            name="Executing Agent",
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
        executing = RDBAgentSession(
            workspace_id=setup.requester.workspace_id,
            agent_id=agent.id,
            lifecycle_root_session_id=None,
            current_model_target_label=None,
            applied_model_target_label=None,
            current_model_selection=None,
            current_model_settings=None,
            current_reasoning_effort=None,
            applied_reasoning_effort=None,
            current_enabled_execution_options=[],
            applied_enabled_execution_options=[],
            current_effective_context_window_tokens=None,
            current_effective_auto_compaction_threshold_tokens=None,
            current_inference_resolved_at=None,
        )
        session.write_session.add(executing)
        if owned:
            await session.write_session.execute(
                sa.update(RDBToolkitConfig)
                .where(RDBToolkitConfig.id == setup.requester.toolkit_id)
                .values(owner_agent_id=agent.id)
            )
        else:
            session.write_session.add(
                RDBAgentToolkit(
                    agent_id=agent.id,
                    toolkit_id=setup.requester.toolkit_id,
                    toolkit_type="github",
                )
            )
        await session.write_session.flush()
        context = GitHubUserExecutionContext(
            workspace_id=setup.requester.workspace_id,
            agent_id=agent.id,
            session_id=executing.id,
            toolkit_id=setup.requester.toolkit_id,
            source="byoa_user",
            app_id="123",
            client_id="Iv1.client",
        )
    repository = GitHubUserRuntimeOperationRepository(
        session_manager=manager,
        toolkit_repository=setup.repository.toolkit_repository,
        cipher=setup.cipher,
    )
    service = GitHubUserRuntimeService(
        repository=repository,
        platform_runtime=create_autospec(
            PlatformGitHubAppRuntimeService, instance=True
        ),
    )
    return _RuntimeFixture(repository, service, context, result.connection.id)


@pytest.mark.parametrize("owned", [False, True])
async def test_runtime_uses_delegated_account_without_manager_login(
    rdb_session_manager: SessionManager[WriteSession], owned: bool
) -> None:
    h = await _runtime_fixture(rdb_session_manager, owned=owned)
    current = await h.service.current_connection(h.context)
    assert current.access_token == "current-token"
    assert current.account_login == "connected-user"
    assert h.context.session_id != "s" * 32  # Setup's authentication Session.
    assert not hasattr(h.context, "user_id")
    assert current.id == h.connection_id


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize(
    "field",
    ["workspace_id", "agent_id", "session_id", "toolkit_id", "app_id", "client_id"],
)
async def test_runtime_rejects_wrong_resolved_context(
    rdb_session_manager: SessionManager[WriteSession], owned: bool, field: str
) -> None:
    h = await _runtime_fixture(rdb_session_manager, owned=owned)
    wrong = dataclasses.replace(h.context, **{field: "wrong-identity"})
    with pytest.raises(GitHubUserOAuthError):
        await h.service.current_connection(wrong)


@pytest.mark.parametrize(
    "change",
    [
        "toolkit_disabled",
        "agent_disabled",
        "agent_decommission",
        "session_archived",
        "detached",
        "disconnected",
        "app_changed",
        "mode_changed",
        "reconnect_required",
    ],
)
async def test_current_mutation_blocks_later_credentials(
    rdb_session_manager: SessionManager[WriteSession], change: str
) -> None:
    h = await _runtime_fixture(rdb_session_manager, owned=False)
    await h.service.current_connection(h.context)
    async with rdb_session_manager() as session:
        match change:
            case "toolkit_disabled":
                await session.write_session.execute(
                    sa.update(RDBToolkitConfig)
                    .where(RDBToolkitConfig.id == h.context.toolkit_id)
                    .values(enabled=False)
                )
            case "agent_disabled":
                await session.write_session.execute(
                    sa.update(RDBAgent)
                    .where(RDBAgent.id == h.context.agent_id)
                    .values(enabled=False)
                )
            case "agent_decommission":
                await session.write_session.execute(
                    sa.update(RDBAgent)
                    .where(RDBAgent.id == h.context.agent_id)
                    .values(lifecycle_status=AgentLifecycleStatus.DECOMMISSIONING)
                )
            case "session_archived":
                await session.write_session.execute(
                    sa.update(RDBAgentSession)
                    .where(RDBAgentSession.id == h.context.session_id)
                    .values(status=AgentSessionStatus.ARCHIVED)
                )
            case "detached":
                await session.write_session.execute(
                    sa.delete(RDBAgentToolkit).where(
                        RDBAgentToolkit.toolkit_id == h.context.toolkit_id
                    )
                )
            case "disconnected":
                await session.write_session.execute(
                    sa.delete(RDBGitHubUserConnection).where(
                        RDBGitHubUserConnection.toolkit_id == h.context.toolkit_id
                    )
                )
            case "app_changed":
                await session.write_session.execute(
                    sa.update(RDBToolkitConfig)
                    .where(RDBToolkitConfig.id == h.context.toolkit_id)
                    .values(
                        encrypted_credentials=h.repository.cipher.encrypt(
                            json.dumps(
                                {
                                    "type": "github_app_user",
                                    "app_id": "999",
                                    "client_id": "other-client",
                                    "client_secret": "other-secret",
                                    "private_key": "other-key",
                                }
                            )
                        )
                    )
                )
            case "mode_changed":
                await session.write_session.execute(
                    sa.update(RDBToolkitConfig)
                    .where(RDBToolkitConfig.id == h.context.toolkit_id)
                    .values(config={"github_auth_type": "pat"})
                )
            case "reconnect_required":
                await session.write_session.execute(
                    sa.update(RDBGitHubUserConnection)
                    .where(RDBGitHubUserConnection.toolkit_id == h.context.toolkit_id)
                    .values(status=GitHubUserConnectionStatus.RECONNECT_REQUIRED)
                )
    with pytest.raises(GitHubUserOAuthError):
        await h.service.current_connection(h.context)


async def test_late_authentication_failure_cannot_invalidate_replacement(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _runtime_fixture(rdb_session_manager, owned=False)
    async with rdb_session_manager() as session:
        previous = await session.write_session.get(
            RDBGitHubUserConnection, h.connection_id
        )
        assert previous is not None
        replacement = RDBGitHubUserConnection(
            toolkit_id=previous.toolkit_id,
            app_id=previous.app_id,
            account_id=previous.account_id,
            account_login=previous.account_login,
            account_avatar_url=previous.account_avatar_url,
            encrypted_access_token=h.repository.cipher.encrypt("replacement-token"),
            encrypted_registration=previous.encrypted_registration,
            status=GitHubUserConnectionStatus.CONNECTED,
            failure_reason=None,
        )
        await session.write_session.delete(previous)
        await session.write_session.flush()
        session.write_session.add(replacement)
    await h.service.authentication_failed(h.context, connection_id=h.connection_id)
    current = await h.service.current_connection(h.context)
    assert current.id != h.connection_id
    assert current.access_token == "replacement-token"
    assert current.status is GitHubUserConnectionStatus.CONNECTED
    await h.service.authentication_failed(h.context, connection_id=current.id)
    with pytest.raises(GitHubUserOAuthError):
        await h.service.current_connection(h.context)


async def test_runtime_current_opt_in_controls_new_environment_only(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    h = await _runtime_fixture(rdb_session_manager, owned=False)
    assert await h.service.runtime_environment(h.context) == {}
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBToolkitConfig)
            .where(RDBToolkitConfig.id == h.context.toolkit_id)
            .values(
                config={
                    "github_auth_type": "github_app_user",
                    "inject_runtime_environment": True,
                }
            )
        )
    handed_off = await h.service.runtime_environment(h.context)
    assert handed_off == {"GH_TOKEN": "current-token", "GITHUB_TOKEN": "current-token"}
    async with rdb_session_manager() as session:
        await session.write_session.execute(
            sa.update(RDBToolkitConfig)
            .where(RDBToolkitConfig.id == h.context.toolkit_id)
            .values(
                config={
                    "github_auth_type": "github_app_user",
                    "inject_runtime_environment": False,
                }
            )
        )
    assert await h.service.runtime_environment(h.context) == {}
    assert (
        handed_off["GH_TOKEN"] == "current-token"
    )  # Existing copies are not recalled.
