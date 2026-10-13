"""Setup composes existing exact scope and current-user/App installation authority."""

from types import SimpleNamespace
from unittest.mock import create_autospec

import pytest

from azents.core.github_user_creation import GitHubUserCreationSubject
from azents.core.github_user_oauth import GitHubUserErrorCode, GitHubUserOAuthError
from azents.core.system_setting import SystemSettingFieldSource
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.github_user_installation import GithubUserInstallationRepository
from azents.repos.github_user_installation.repository_test import _make_installation
from azents.repos.github_user_oauth.operations import GitHubUserOAuthOperationRepository
from azents.repos.github_user_oauth.operations_test import _harness
from azents.repos.github_user_oauth.setup import GitHubSetupRepository
from azents.repos.toolkit_operations.data import PlatformToolkitAuthority
from azents.repos.toolkit_operations.repository_test import (
    _repository,
    _TrackedSessionManager,
)
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate


def _subject() -> GitHubUserCreationSubject:
    return GitHubUserCreationSubject("manager", "auth-session", "workspace", None)


def _authority() -> PlatformToolkitAuthority:
    return PlatformToolkitAuthority(
        app_id="123",
        app_id_source=SystemSettingFieldSource.ENVIRONMENT,
        user_id="manager",
        installation_ids=frozenset({501, 502}),
    )


async def test_scope_and_targets_share_one_completed_database_operation() -> None:
    manager = _TrackedSessionManager()
    operations = create_autospec(GitHubUserOAuthOperationRepository, instance=True)
    operations.session_manager = manager
    toolkit = _repository(manager)
    toolkit.github.list_accessible_installation_ids.return_value = frozenset({501, 502})
    repository = GitHubSetupRepository(operations, toolkit.repository)
    await repository.authorize_platform(_subject(), _authority())
    operations.authorize_scope_in_session.assert_awaited_once_with(
        manager.session,
        user_id="manager",
        session_id="auth-session",
        workspace_id="workspace",
        agent_id=None,
    )
    toolkit.github.list_accessible_installation_ids.assert_awaited_once_with(
        manager.session,
        user_id="manager",
        platform_app_id="123",
        installation_ids=frozenset({501, 502}),
    )
    assert manager.committed and not manager.active
    toolkit.toolkits.create.assert_not_awaited()


async def test_scope_loss_precedes_any_selected_installation_lookup() -> None:
    manager = _TrackedSessionManager()
    operations = create_autospec(GitHubUserOAuthOperationRepository, instance=True)
    operations.session_manager = manager
    operations.authorize_scope_in_session.side_effect = GitHubUserOAuthError(
        GitHubUserErrorCode.AUTHORITY, "Exact Agent management lost."
    )
    toolkit = _repository(manager)
    with pytest.raises(GitHubUserOAuthError):
        await GitHubSetupRepository(operations, toolkit.repository).authorize_platform(
            _subject(), _authority()
        )
    toolkit.github.list_accessible_installation_ids.assert_not_awaited()
    assert manager.rolled_back and not manager.active


@pytest.mark.parametrize(
    "source", [SystemSettingFieldSource.ADMIN, SystemSettingFieldSource.ENVIRONMENT]
)
@pytest.mark.parametrize(
    "scenario", ["valid", "foreign_user", "foreign_app", "removed"]
)
async def test_real_synced_installations_are_bound_to_current_user_and_app(
    rdb_session_manager: SessionManager[WriteSession],
    source: SystemSettingFieldSource,
    scenario: str,
) -> None:
    h = await _harness(rdb_session_manager)
    installations = GithubUserInstallationRepository()
    async with rdb_session_manager() as session:
        user = await UserRepository().create(
            session, UserCreate(email="setup-owner@example.com")
        )
        other = await UserRepository().create(
            session, UserCreate(email="setup-other@example.com")
        )
        await installations.sync(
            session,
            other.id if scenario == "foreign_user" else user.id,
            "999" if scenario == "foreign_app" else "123",
            [_make_installation(501), _make_installation(502)],
        )
        if scenario == "removed":
            await installations.sync(session, user.id, "123", [])
    h.auth_session.get.return_value.user_id = user.id
    subject = GitHubUserCreationSubject(
        user.id, h.requester.session_id, h.requester.workspace_id, None
    )
    authority = PlatformToolkitAuthority(
        app_id="123",
        app_id_source=source,
        user_id=user.id,
        installation_ids=frozenset({501, 502}),
    )
    toolkit = _repository(_TrackedSessionManager())
    toolkit.settings.get_current.return_value = SimpleNamespace(
        config={"app_id": "123"}
    )
    toolkit.repository.github_installation_repository = installations
    repository = GitHubSetupRepository(h.repository, toolkit.repository)
    if scenario == "valid":
        await repository.authorize_platform(subject, authority)
        async with rdb_session_manager() as session:
            await installations.sync(session, user.id, "123", [_make_installation(501)])
        with pytest.raises(GitHubUserOAuthError) as error:
            await repository.authorize_platform(subject, authority)
        assert error.value.code is GitHubUserErrorCode.AUTHORITY
    else:
        with pytest.raises(GitHubUserOAuthError) as error:
            await repository.authorize_platform(subject, authority)
        assert error.value.code is GitHubUserErrorCode.AUTHORITY
    toolkit.toolkits.create.assert_not_awaited()
