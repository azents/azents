"""Assembled GitHub setup verification and reviewed final-settings publication."""

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

from support.utils import single_candidate_model_options, unique
from tests.required.admin.test_03_system_settings import (
    _generate_private_key,
    _replace_secret,
)
from tests.required.public.test_agent_execution_persistence import (
    auth_headers,
    json_object_payload,
)
from tests.required.public.test_github_user_toolkit import _operation, _scenario
from tests.required.public.test_runtime_optional_capability import _create_workspace

E2E_PLANNER_FALLBACK_WEIGHT = 25.0


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
    response.raise_for_status()
    payload = json_object_payload(response.json(), label="Toolkit management scope")
    items = payload["items"]
    assert isinstance(items, list)
    for raw in items:
        item = json_object_payload(raw, label="Toolkit management item")
        toolkit = (
            json_object_payload(item["toolkit"], label="Agent management Toolkit")
            if agent_owned
            else item
        )
        assert toolkit["toolkit_type"] != "github"


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
        body={
            "github_auth_type": "pat",
            "token": "synthetic-pat",
            "transport": {"toolsets": ["users", "repos"], "timeout": 5},
        },
    )
    identity = json_object_payload(pat["identity"], label="Verified PAT identity")
    assert identity["type"] == "user" and identity["login"] == "connected-user"
    assert "synthetic-pat" not in str(pat)
    app = _operation(
        base + "/github",
        workspace.token,
        "setup-verification",
        body={
            "github_auth_type": "github_app",
            "app_id": "123",
            "private_key": _generate_private_key(),
            "installation_ids": ["501", "502", "504"],
            "transport": {"toolsets": ["users", "repos"], "timeout": 5},
        },
    )
    app_identity = json_object_payload(app["identity"], label="Verified App identity")
    assert app_identity["type"] == "app"
    assert app_identity["app_id"] == "123"
    assert app_identity["name"] == "Azents Test App"
    installations = app["installations"]
    assert isinstance(installations, list)
    targets = {
        item["installation_id"]: item
        for raw in installations
        for item in [json_object_payload(raw, label="Verified installation")]
    }
    assert targets["501"]["account_login"] == "connected-user"
    assert targets["502"]["account_login"] == "research-team"
    assert targets["504"]["status"] == "denied"
    assert "synthetic-installation" not in str(app)
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
    connected = _operation(creation, workspace.token, "connect", body=initial)
    authorization_url = connected["authorization_url"]
    assert isinstance(authorization_url, str)
    state = parse_qs(urlsplit(authorization_url).query)["state"][0]
    review = _operation(
        creation,
        workspace.token,
        "exchange",
        body={"code": "e2e-user-wizard-" + unique(), "state": state},
    )
    candidate = json_object_payload(review["candidate"], label="Wizard candidate")
    attempt = candidate["attempt_id"]
    assert isinstance(attempt, str)
    app_response = requests.get(
        creation + f"/{attempt}/app", headers=headers, timeout=10
    )
    app_response.raise_for_status()
    metadata = json_object_payload(app_response.json(), label="Candidate metadata")
    app = json_object_payload(metadata["app"], label="Candidate App")
    assert app["name"] == "Azents Test App"
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
    )
    toolkit_id = published["toolkit_id"]
    assert isinstance(toolkit_id, str)
    saved = requests.get(
        base + f"/toolkit-configs/{toolkit_id}", headers=headers, timeout=10
    )
    saved.raise_for_status()
    saved_payload = json_object_payload(saved.json(), label="Published Toolkit")
    config = json_object_payload(saved_payload["config"], label="Final GitHub config")
    assert saved_payload["name"] == settings["name"]
    assert config["github_auth_type"] == "github_app_user"
    assert config["toolsets"] == settings["toolsets"]
    assert config["timeout"] == 17
    assert config["inject_runtime_environment"] is True
    assert "runtime_risk_acknowledged" not in config
    assert "synthetic-token" not in str(saved_payload)


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
    before = requests.get(
        github_validation_proxy_url + "/__testenv/state", timeout=5
    ).json()
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
    after = requests.get(
        github_validation_proxy_url + "/__testenv/state", timeout=5
    ).json()
    assert after["app_request_count"] == before["app_request_count"]

    # The existing installation OAuth synchronization grants only this user's
    # selected-installation authority; verification cannot substitute App keys.
    oauth = requests.get(base + "/platform-oauth-url", headers=headers, timeout=10)
    oauth.raise_for_status()
    state = parse_qs(urlsplit(oauth.json()["oauth_url"]).query)["state"][0]
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
        body={
            "github_auth_type": "github_app_platform",
            "installation_ids": ["501", "502"],
            "transport": {"toolsets": ["repos"], "timeout": 5},
        },
    )
    permitted_identity = json_object_payload(
        permitted["identity"], label="User-admitted Platform App"
    )
    assert permitted_identity["type"] == "app"
    assert permitted_identity["app_id"] == "123"
    permitted_connectivity = json_object_payload(
        permitted["connectivity"], label="User-admitted Platform MCP"
    )
    assert permitted_connectivity["status"] == "ready"
    first = requests.get(base + "/setup-app", headers=headers, timeout=10)
    first.raise_for_status()
    first_app = json_object_payload(first.json()["app"], label="Platform App metadata")
    assert first_app["name"] == "Azents Test App"
    _scenario(github_validation_proxy_url, "user_app_renamed")
    renamed = requests.get(base + "/setup-app", headers=headers, timeout=10)
    renamed.raise_for_status()
    renamed_app = json_object_payload(
        renamed.json()["app"], label="Renamed Platform App metadata"
    )
    assert renamed_app["app_id"] == first_app["app_id"]
    assert renamed_app["name"] == "Renamed Test App"
    _scenario(github_validation_proxy_url, "user_success")
