"""Personal GitHub routes bind the current account across all setup entry points."""

from typing import NamedTuple
from unittest.mock import Mock, create_autospec

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.public.toolkit.v1.personal_github import router
from azents.core.auth.deps import CurrentUser, get_current_user
from azents.core.github_user_creation import GitHubPersonalCreationSubject
from azents.core.github_user_oauth import GitHubPersonalRequester
from azents.core.personal_toolkit import (
    PersonalToolkitAuthorityDenied,
    PersonalToolkitConfigurationConflict,
    PersonalToolkitManager,
)
from azents.services.github_user_oauth.creation import GitHubUserCreationService
from azents.services.github_user_oauth.data import GitHubUserConnectOutput
from azents.services.github_user_oauth.personal_installations import (
    PersonalGitHubInstallationsService,
)
from azents.services.github_user_oauth.service import GitHubUserOAuthService
from azents.services.github_user_oauth.setup import GitHubSetupService
from azents.services.toolkit_oauth.data import GitHubInstallationProjection


def app(oauth: Mock, creation: Mock, setup: Mock) -> FastAPI:
    result = FastAPI()
    result.include_router(router)
    result.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id="owner", session_id="login"
    )
    result.dependency_overrides[GitHubUserOAuthService] = lambda: oauth
    result.dependency_overrides[GitHubUserCreationService] = lambda: creation
    result.dependency_overrides[GitHubSetupService] = lambda: setup
    return result


class GitHubServices(NamedTuple):
    oauth: Mock
    creation: Mock
    setup: Mock


def services() -> GitHubServices:
    return GitHubServices(
        create_autospec(GitHubUserOAuthService, instance=True),
        create_autospec(GitHubUserCreationService, instance=True),
        create_autospec(GitHubSetupService, instance=True),
    )


def connect_output() -> GitHubUserConnectOutput:
    return GitHubUserConnectOutput(
        attempt_id="attempt",
        authorization_url="https://github.com/login/oauth/authorize",
        install_url="https://github.com/apps/fixture/installations/new",
    )


def test_personal_saved_connect_binds_exact_current_owner_without_workspace() -> None:
    oauth, creation, setup = services()
    oauth.connect.return_value = connect_output()
    with TestClient(app(oauth, creation, setup)) as client:
        response = client.post(
            "/personal-toolkit-configs/exact-toolkit/github-user/connect"
        )
    assert response.status_code == 200
    requester = oauth.connect.call_args.args[0]
    assert isinstance(requester, GitHubPersonalRequester)
    assert requester.user_id == "owner" and requester.owner.user_id == "owner"
    assert requester.session_id == "login" and requester.toolkit_id == "exact-toolkit"
    assert requester.workspace_id is None and requester.agent_id is None
    creation.connect.assert_not_awaited()


def test_personal_creation_uses_common_fields_without_publishing() -> None:
    oauth, creation, setup = services()
    creation.connect.return_value = connect_output()
    body = {
        "toolkit_type": "github",
        "name": "Personal GitHub",
        "config": {
            "github_auth_type": "github_app_user",
            "inject_runtime_environment": True,
        },
        "always_expose_tools": True,
    }
    with TestClient(app(oauth, creation, setup)) as client:
        response = client.post("/personal/github-user-creations/connect", json=body)
        forged = client.post(
            "/personal/github-user-creations/connect",
            json={**body, "workspace_id": "hidden-workspace"},
        )
    assert response.status_code == 200 and forged.status_code == 422
    subject, configuration = creation.connect.call_args.args
    assert isinstance(subject, GitHubPersonalCreationSubject)
    assert subject.user_id == "owner" and subject.session_id == "login"
    assert subject.owner.user_id == "owner" and subject.workspace_id is None
    assert configuration.config["inject_runtime_environment"] is True
    assert configuration.always_expose_tools
    assert "workspace_id" not in configuration.model_dump()
    creation.connect.assert_awaited_once()
    creation.confirm.assert_not_awaited()


def test_personal_callback_validation_excludes_codes_and_state() -> None:
    oauth, creation, setup = services()
    with TestClient(app(oauth, creation, setup)) as client:
        for path in [
            "/personal/github-user-creations/exchange",
            "/personal-toolkit-configs/exact-toolkit/github-user/exchange",
        ]:
            response = client.post(
                path,
                json={
                    "code": "PERSONAL-CODE-SECRET",
                    "state": ["PERSONAL-STATE-SECRET"],
                },
            )
            assert response.status_code == 422
            assert "PERSONAL-CODE-SECRET" not in response.text
            assert "PERSONAL-STATE-SECRET" not in response.text
    oauth.exchange.assert_not_awaited()
    creation.exchange.assert_not_awaited()


def test_personal_platform_routes_project_exact_account_and_common_inventory() -> None:
    oauth, creation, setup = services()
    application = app(oauth, creation, setup)
    installations = create_autospec(PersonalGitHubInstallationsService, instance=True)
    application.dependency_overrides[PersonalGitHubInstallationsService] = lambda: (
        installations
    )
    installations.install_url.return_value = (
        "https://github.com/apps/fixture/installations/new"
    )
    installations.oauth_url.return_value = (
        "https://github.com/login/oauth/authorize?state=opaque"
    )
    installations.sync.return_value = (
        GitHubInstallationProjection(
            id=42,
            account_login="fixture",
            account_type="Organization",
            account_avatar_url="https://example.test/avatar",
        ),
    )
    with TestClient(application) as client:
        install = client.get("/personal/github/platform-install-url")
        start = client.get("/personal/github/platform-oauth-url")
        synced = client.post(
            "/personal/github/platform-installations",
            json={"code": "fixture-code", "state": "fixture-state"},
        )
    assert install.status_code == start.status_code == synced.status_code == 200
    assert install.json() == {"install_url": installations.install_url.return_value}
    assert start.json() == {"oauth_url": installations.oauth_url.return_value}
    assert synced.json() == {
        "installations": [
            {
                "id": 42,
                "account_login": "fixture",
                "account_type": "Organization",
                "account_avatar_url": "https://example.test/avatar",
            }
        ]
    }
    subject = PersonalToolkitManager("owner", "login")
    installations.install_url.assert_awaited_once_with(subject)
    installations.oauth_url.assert_awaited_once_with(subject)
    installations.sync.assert_awaited_once_with(
        subject, code="fixture-code", state="fixture-state"
    )
    creation.connect.assert_not_awaited()


@pytest.mark.parametrize(
    "error,status",
    [
        (PersonalToolkitAuthorityDenied("inactive"), 401),
        (PersonalToolkitConfigurationConflict("changed"), 409),
    ],
)
def test_personal_platform_denials_and_validation_are_safe(
    error: Exception, status: int
) -> None:
    oauth, creation, setup = services()
    application = app(oauth, creation, setup)
    installations = create_autospec(PersonalGitHubInstallationsService, instance=True)
    application.dependency_overrides[PersonalGitHubInstallationsService] = lambda: (
        installations
    )
    installations.sync.side_effect = error
    with TestClient(application) as client:
        invalid = client.post(
            "/personal/github/platform-installations",
            json={"code": "PRIVATE-CODE", "state": ["PRIVATE-STATE"]},
        )
        assert invalid.status_code == 422
        assert "PRIVATE-" not in invalid.text
        installations.sync.assert_not_awaited()
        denied = client.post(
            "/personal/github/platform-installations",
            json={"code": "PRIVATE-CODE", "state": "PRIVATE-STATE"},
        )
    assert denied.status_code == status
    assert "PRIVATE-" not in denied.text
