"""Assembled GitHub setup verification and reviewed final-settings publication."""

from typing import Annotated, Literal
from urllib.parse import parse_qs, urlsplit

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentsadminclient.api.system_settings_v1_api import SystemSettingsV1Api
from azentsadminclient.models.platform_git_hub_app_patch_request import (
    PlatformGitHubAppPatchRequest,
)
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_model_selection_input import (
    AgentModelSelectionInput,
)
from azentspublicclient.models.agent_type import AgentType
from pydantic import Field, StrictStr

from support.observations import ExtensionObservation
from support.utils import single_candidate_model_options, unique
from tests.required.admin.test_03_system_settings import (
    _generate_private_key,
    _replace_secret,
)
from tests.required.public.test_agent_execution_persistence import (
    auth_headers,
)
from tests.required.public.test_github_user_toolkit import (
    _Connect,
    _Created,
    _CreationReview,
    _GitHubConfig,
    _operation,
    _ProxyEvidence,
    _response,
    _scenario,
)
from tests.required.public.test_runtime_optional_capability import _create_workspace

E2E_PLANNER_FALLBACK_WEIGHT = 25.0


class _UserIdentity(ExtensionObservation):
    type: Literal["user"]
    login: StrictStr


class _AppIdentity(ExtensionObservation):
    type: Literal["app"]
    app_id: StrictStr
    name: StrictStr


class _Installation(ExtensionObservation):
    installation_id: StrictStr
    account_login: StrictStr | None
    status: Literal["ready", "denied", "unavailable"]


class _Connectivity(ExtensionObservation):
    status: Literal["ready", "failed"]


class _Verification(ExtensionObservation):
    identity: Annotated[_UserIdentity | _AppIdentity, Field(discriminator="type")]
    installations: list[_Installation]
    connectivity: _Connectivity


class _AppMetadata(ExtensionObservation):
    app_id: StrictStr
    name: StrictStr


class _AppOutput(ExtensionObservation):
    app: _AppMetadata | None


class _OAuthUrl(ExtensionObservation):
    oauth_url: StrictStr


class _Toolkit(ExtensionObservation):
    toolkit_type: StrictStr


class _ToolkitPage(ExtensionObservation):
    items: list[_Toolkit]


class _AgentToolkit(ExtensionObservation):
    toolkit: _Toolkit


class _AgentToolkitPage(ExtensionObservation):
    items: list[_AgentToolkit]


class _PublishedToolkit(ExtensionObservation):
    name: StrictStr
    config: _GitHubConfig


def _management_base(
    server: str,
    handle: str,
    token: str,
    client: azentspublicclient.ApiClient,
    model_selection: AgentModelSelectionInput,
    *,
    agent_owned: bool,
) -> str:
    base = f"{server}/toolkit/v1/workspaces/{handle}"
    if not agent_owned:
        return base
    agent = AgentV1Api(client).agent_v1_create_agent(
        handle,
        AgentCreateRequest(
            name="GitHub Wizard API Agent",
            type=AgentType.PUBLIC,
            selectable_model_options=single_candidate_model_options(model_selection),
            main_model_label="default",
            lightweight_model_label="default",
        ),
        _headers=auth_headers(token),
    )
    return base + f"/agents/{agent.id}"


def _assert_no_github_toolkits(base: str, token: str, *, agent_owned: bool) -> None:
    """Observe the exact originating management scope before publication."""
    response = requests.get(
        base + "/toolkit-configs", headers=auth_headers(token), timeout=10
    )
    if agent_owned:
        page = _response(response, _AgentToolkitPage, label="Agent Toolkit management")
        assert all(item.toolkit.toolkit_type != "github" for item in page.items)
    else:
        shared = _response(response, _ToolkitPage, label="Shared Toolkit management")
        assert all(item.toolkit_type != "github" for item in shared.items)


@pytest.mark.parametrize("agent_owned", [False, True])
def test_setup_verifies_actual_pat_and_app_targets_without_publication(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    github_validation_proxy_url: str,
    agent_owned: bool,
) -> None:
    _scenario(github_validation_proxy_url, "user_success")
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=False,
    )
    base = _management_base(
        azents_public_server_url,
        workspace.handle,
        workspace.token,
        public_api_client,
        workspace.model_selection,
        agent_owned=agent_owned,
    )
    pat = _operation(
        base + "/github",
        workspace.token,
        "setup-verification",
        model=_Verification,
        body={
            "github_auth_type": "pat",
            "token": "synthetic-pat",
            "transport": {"toolsets": ["users", "repos"], "timeout": 5},
        },
    )
    identity = pat.identity
    assert isinstance(identity, _UserIdentity) and identity.login == "connected-user"
    assert "synthetic-pat" not in pat.model_dump_json(exclude_unset=True)
    app = _operation(
        base + "/github",
        workspace.token,
        "setup-verification",
        model=_Verification,
        body={
            "github_auth_type": "github_app",
            "app_id": "123",
            "private_key": _generate_private_key(),
            "installation_ids": ["501", "502", "504"],
            "transport": {"toolsets": ["users", "repos"], "timeout": 5},
        },
    )
    app_identity = app.identity
    assert isinstance(app_identity, _AppIdentity)
    assert app_identity.app_id == "123"
    assert app_identity.name == "Azents Test App"
    targets = {item.installation_id: item for item in app.installations}
    assert targets["501"].account_login == "connected-user"
    assert targets["502"].account_login == "research-team"
    assert targets["504"].status == "denied"
    assert "synthetic-installation" not in app.model_dump_json(exclude_unset=True)
    _assert_no_github_toolkits(base, workspace.token, agent_owned=agent_owned)


@pytest.mark.parametrize("agent_owned", [False, True])
def test_creation_publishes_only_reviewed_post_authorization_settings(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    github_validation_proxy_url: str,
    agent_owned: bool,
) -> None:
    _scenario(github_validation_proxy_url, "user_success")
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=False,
    )
    base = _management_base(
        azents_public_server_url,
        workspace.handle,
        workspace.token,
        public_api_client,
        workspace.model_selection,
        agent_owned=agent_owned,
    )
    creation = base + "/github-user-creations"
    headers = auth_headers(workspace.token)
    initial: dict[str, object] = {
        "toolkit_type": "github",
        "name": "Initial authorization defaults",
        "slug": "github_wizard_" + unique(),
        "config": {
            "github_auth_type": "github_app_user",
            "toolsets": ["users"],
            "inject_runtime_environment": False,
        },
        "credentials": {
            "type": "github_app_user",
            "app_id": "123",
            "client_id": "Iv1.azents-test",
            "private_key": _generate_private_key(),
            "client_secret": "synthetic-client-secret",
        },
        "enabled": True,
        "always_expose_tools": False,
    }
    connected = _operation(
        creation, workspace.token, "connect", body=initial, model=_Connect
    )
    authorization_url = connected.authorization_url
    state = parse_qs(urlsplit(authorization_url).query)["state"][0]
    review = _operation(
        creation,
        workspace.token,
        "exchange",
        body={"code": "e2e-user-wizard-" + unique(), "state": state},
        model=_CreationReview,
    )
    attempt = review.candidate.attempt_id
    app_response = requests.get(
        creation + f"/{attempt}/app", headers=headers, timeout=10
    )
    metadata = _response(app_response, _AppOutput, label="Candidate metadata")
    assert metadata.app is not None
    assert metadata.app.name == "Azents Test App"
    settings = {
        "name": "Reviewed final Wizard settings",
        "slug": initial["slug"],
        "description": "Selected after GitHub authorization",
        "prompt": None,
        "enabled": True,
        "always_expose_tools": True,
        "toolsets": ["repos", "issues"],
        "timeout": 17,
        "inject_runtime_environment": True,
        "runtime_risk_acknowledged": True,
    }
    rejected = requests.post(
        creation + "/confirm",
        headers=headers,
        json={
            "attempt_id": attempt,
            "settings": {**settings, "github_auth_type": "pat"},
        },
        timeout=15,
    )
    assert rejected.status_code == 422
    live = requests.get(creation + f"/{attempt}", headers=headers, timeout=10)
    live.raise_for_status()
    _assert_no_github_toolkits(base, workspace.token, agent_owned=agent_owned)
    published = _operation(
        creation,
        workspace.token,
        "confirm",
        body={"attempt_id": attempt, "settings": settings},
        model=_Created,
    )
    toolkit_id = published.toolkit_id
    saved = requests.get(
        base + f"/toolkit-configs/{toolkit_id}", headers=headers, timeout=10
    )
    saved_payload = _response(saved, _PublishedToolkit, label="Published Toolkit")
    config = saved_payload.config
    assert saved_payload.name == settings["name"]
    assert config.github_auth_type == "github_app_user"
    assert config.toolsets == settings["toolsets"]
    assert config.timeout == 17
    assert config.inject_runtime_environment is True
    assert "runtime_risk_acknowledged" not in config.model_dump(exclude_unset=True)
    assert "synthetic-token" not in saved_payload.model_dump_json(exclude_unset=True)


@pytest.mark.parametrize("agent_owned", [False, True])
def test_platform_app_name_is_current_provider_metadata(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    github_validation_proxy_url: str,
    agent_owned: bool,
) -> None:
    _scenario(github_validation_proxy_url, "user_success")
    admin = SystemSettingsV1Api(admin_api_client)
    current = admin.system_settings_v1_get_platform_github_app_setting()
    admin.system_settings_v1_patch_platform_github_app_setting(
        PlatformGitHubAppPatchRequest(
            expected_version=current.admin_version,
            app_id="123",
            client_id="Iv1.azents-test",
            private_key=_replace_secret(_generate_private_key()),
            client_secret=_replace_secret("synthetic-client-secret"),
        )
    )
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=False,
    )
    base = (
        _management_base(
            azents_public_server_url,
            workspace.handle,
            workspace.token,
            public_api_client,
            workspace.model_selection,
            agent_owned=agent_owned,
        )
        + "/github"
    )
    headers = auth_headers(workspace.token)
    before = _response(
        requests.get(github_validation_proxy_url + "/__testenv/state", timeout=5),
        _ProxyEvidence,
        label="App verification evidence",
    )
    unlinked = requests.post(
        base + "/setup-verification",
        headers=headers,
        json={
            "github_auth_type": "github_app_platform",
            "installation_ids": ["501"],
            "transport": {"toolsets": ["repos"], "timeout": 5},
        },
        timeout=10,
    )
    assert unlinked.status_code in {400, 403}
    after = _response(
        requests.get(github_validation_proxy_url + "/__testenv/state", timeout=5),
        _ProxyEvidence,
        label="App verification evidence",
    )
    assert after.app_request_count == before.app_request_count

    # The existing installation OAuth synchronization grants only this user's
    # selected-installation authority; verification cannot substitute App keys.
    oauth = requests.get(base + "/platform-oauth-url", headers=headers, timeout=10)
    state = parse_qs(
        urlsplit(_response(oauth, _OAuthUrl, label="Platform OAuth").oauth_url).query
    )["state"][0]
    synchronized = requests.post(
        base + "/platform-installations",
        headers=headers,
        json={"code": "e2e-user-installations-" + unique(), "state": state},
        timeout=15,
    )
    synchronized.raise_for_status()
    permitted = _operation(
        base,
        workspace.token,
        "setup-verification",
        model=_Verification,
        body={
            "github_auth_type": "github_app_platform",
            "installation_ids": ["501", "502"],
            "transport": {"toolsets": ["repos"], "timeout": 5},
        },
    )
    permitted_identity = permitted.identity
    assert isinstance(permitted_identity, _AppIdentity)
    assert permitted_identity.app_id == "123"
    assert permitted.connectivity.status == "ready"
    first = requests.get(base + "/setup-app", headers=headers, timeout=10)
    first_app = _response(first, _AppOutput, label="Platform App metadata").app
    assert first_app is not None
    assert first_app.name == "Azents Test App"
    _scenario(github_validation_proxy_url, "user_app_renamed")
    renamed = requests.get(base + "/setup-app", headers=headers, timeout=10)
    renamed_app = _response(
        renamed, _AppOutput, label="Renamed Platform App metadata"
    ).app
    assert renamed_app is not None
    assert renamed_app.app_id == first_app.app_id
    assert renamed_app.name == "Renamed Test App"
    _scenario(github_validation_proxy_url, "user_success")
