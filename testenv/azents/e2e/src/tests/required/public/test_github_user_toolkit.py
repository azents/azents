"""Credential-free GitHub user setup, delegated Worker execution and local cleanup."""

import json
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
from azentspublicclient.api.toolkit_v1_api import ToolkitV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_runtime_capability import AgentRuntimeCapability
from azentspublicclient.models.agent_toolkit_attach_request import (
    AgentToolkitAttachRequest,
)
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.toolkit_config_create_request import (
    ToolkitConfigCreateRequest,
)
from azentspublicclient.models.toolkit_config_update_request import (
    ToolkitConfigUpdateRequest,
)

from support.runtime_profiles import start_and_wait_for_agent_runtime
from support.utils import single_candidate_model_options, unique
from tests.required.admin.test_03_system_settings import (
    _generate_private_key,
    _replace_secret,
)
from tests.required.public.test_agent_execution_persistence import (
    auth_headers,
    json_object_payload,
)
from tests.required.public.test_brave_search import (
    _tool_events,
    _wait_for_terminal_session,
)
from tests.required.public.test_per_prompt_inference_profile import (
    _create_profile_session,
)
from tests.required.public.test_runtime_optional_capability import (
    _create_workspace,
    _invite_member,
)

E2E_PLANNER_FALLBACK_WEIGHT = 45.0


def _scenario(proxy_url: str, scenario: str) -> None:
    response = requests.post(
        proxy_url + "/__testenv/scenario", json={"scenario": scenario}, timeout=5
    )
    response.raise_for_status()


def _operation(
    base: str, token: str, operation: str, *, body: dict[str, object] | None
) -> dict[str, object]:
    response = requests.post(
        base + "/" + operation, headers=auth_headers(token), json=body, timeout=15
    )
    response.raise_for_status()
    return (
        {}
        if response.status_code == 204
        else json_object_payload(response.json(), label="GitHub user operation")
    )


def _connect(base: str, token: str, label: str) -> dict[str, object]:
    prepared = _operation(base, token, "connect", body=None)
    authorization_url = prepared["authorization_url"]
    assert isinstance(authorization_url, str)
    state = parse_qs(urlsplit(authorization_url).query)["state"][0]
    reviewed = _operation(
        base,
        token,
        "exchange",
        body={"code": f"e2e-user-{label}-{unique()}", "state": state},
    )
    assert reviewed["account_login"] in {"connected-user", "replacement-user"}
    assert "access_token" not in json.dumps(reviewed)
    return reviewed


def _status(base: str, token: str) -> dict[str, object]:
    response = requests.get(base + "/status", headers=auth_headers(token), timeout=10)
    response.raise_for_status()
    return json_object_payload(response.json(), label="GitHub user status")


def _run(
    server: str, token: str, agent_id: str, *, kind: str, session_id: str | None
) -> list[dict[str, object]]:
    session_id = session_id or _create_profile_session(
        server_url=server, token=token, agent_id=agent_id
    )
    response = requests.post(
        f"{server}/chat/v1/sessions/{session_id}/inputs",
        headers={**auth_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": "github-user-" + unique(),
            "message": f"GitHub User Toolkit E2E {kind}",
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    response.raise_for_status()
    _wait_for_terminal_session(
        server_url=server, token=token, agent_id=agent_id, session_id=session_id
    )
    return _tool_events(server_url=server, token=token, session_id=session_id)


def _assert_runtime_result(
    events: list[dict[str, object]], *, kind: str, marker: str
) -> None:
    """Inspect command results rather than markers contained in command input."""
    results = [
        json_object_payload(event.get("payload"), label="Runtime command result")
        for event in events
        if event.get("kind") == "client_tool_result"
    ]
    result = next(
        item for item in results if item.get("call_id") == f"call_github_user_{kind}_0"
    )
    assert result["status"] == "completed"
    assert marker in json.dumps(result)
    assert "GITHUB_USER_ENV_MISMATCH" not in json.dumps(result)


@pytest.mark.parametrize("platform", [False, True])
def test_staged_account_delegated_worker_and_fail_open_disconnect(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    github_validation_proxy_url: str,
    platform: bool,
) -> None:
    """Only confirmation activates user authority; another participant uses it."""
    _scenario(github_validation_proxy_url, "user_success")
    private_key = _generate_private_key()
    if platform:
        settings = SystemSettingsV1Api(admin_api_client)
        before = settings.system_settings_v1_get_platform_github_app_setting()
        activated = settings.system_settings_v1_patch_platform_github_app_setting(
            PlatformGitHubAppPatchRequest(
                expected_version=before.admin_version,
                app_id="123",
                client_id="Iv1.azents-test",
                private_key=_replace_secret(private_key),
                client_secret=_replace_secret("synthetic-client-secret"),
            )
        )
        assert activated.effective_status == "ready"
        assert activated.candidate is None
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=platform,
    )
    headers = auth_headers(workspace.token)
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        workspace.handle,
        AgentCreateRequest(
            name="GitHub user E2E",
            selectable_model_options=single_candidate_model_options(
                workspace.model_selection
            ),
            main_model_label="default",
            lightweight_model_label="default",
            type=AgentType.PUBLIC,
            tool_search_enabled=True,
            runtime_profile_id=workspace.runtime_profile_id,
        ),
        _headers=headers,
    )
    assert agent.runtime_capability == (
        AgentRuntimeCapability.MANAGED if platform else AgentRuntimeCapability.NONE
    )
    if platform:
        start_and_wait_for_agent_runtime(
            public_api_client,
            token=workspace.token,
            workspace_handle=workspace.handle,
            agent_id=agent.id,
        )
    mode = "github_app_platform_user" if platform else "github_app_user"
    credentials: dict[str, object] = {"type": mode}
    if not platform:
        credentials.update(
            app_id="123",
            client_id="Iv1.azents-test",
            private_key=private_key,
            client_secret="synthetic-client-secret",
        )
    toolkits = ToolkitV1Api(public_api_client)
    toolkit = toolkits.toolkit_v1_create_toolkit_config(
        workspace.handle,
        ToolkitConfigCreateRequest(
            toolkit_type="github",
            slug="github_user",
            name="GitHub user E2E",
            config={"github_auth_type": mode, "toolsets": ["users", "repos"]},
            credentials=credentials,
            enabled=True,
            always_expose_tools=True,
        ),
        _headers=headers,
    )
    toolkits.toolkit_v1_attach_toolkit_to_agent(
        handle=workspace.handle,
        agent_id=agent.id,
        agent_toolkit_attach_request=AgentToolkitAttachRequest(toolkit_id=toolkit.id),
        _headers=headers,
    )
    base = (
        f"{azents_public_server_url}/toolkit/v1/workspaces/{workspace.handle}"
        f"/toolkit-configs/{toolkit.id}/github-user"
    )
    assert _status(base, workspace.token) == {"connection": None}
    reviewed = _connect(base, workspace.token, "main")
    assert _status(base, workspace.token) == {"connection": None}
    connected = _operation(
        base, workspace.token, "confirm", body={"attempt_id": reviewed["attempt_id"]}
    )
    assert connected["account_login"] == "connected-user"
    assert "access_token" not in json.dumps(connected)

    owners: dict[str, dict[str, object]] = {}
    cursor = None
    for _ in range(8):
        response = requests.get(
            base + "/access",
            headers=headers,
            params={} if cursor is None else {"cursor": cursor},
            timeout=10,
        )
        response.raise_for_status()
        page = json_object_payload(response.json(), label="GitHub access page")
        entries = page["installations"]
        assert isinstance(entries, list)
        for raw in entries:
            owner = json_object_payload(raw, label="GitHub owner")
            login = owner["account_login"]
            assert isinstance(login, str)
            owners[login] = owner
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert isinstance(cursor, str)
    else:
        raise AssertionError("Synthetic GitHub inventory did not complete pagination")
    assert {
        "connected-user",
        "research-team",
        "ops-team",
        "restricted-team",
    } <= owners.keys()
    assert owners["restricted-team"]["failure_reason"] is not None
    assert _status(base, workspace.token)["connection"] is not None

    member = _invite_member(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        workspace=workspace,
    )
    events = _run(
        azents_public_server_url,
        member.access_token,
        agent.id,
        kind="mcp",
        session_id=None,
    )
    serialized = json.dumps(events)
    assert "GITHUB_USER_E2E_COMPLETED_mcp" in serialized
    assert "connected-user" in serialized
    assert "research-team" in serialized and "ops-team" in serialized
    results = [
        json_object_payload(event.get("payload"), label="GitHub user tool result")
        for event in events
        if event.get("kind") == "client_tool_result"
    ]
    denied = next(
        item for item in results if item.get("call_id") == "call_github_user_mcp_4"
    )
    assert {f"call_github_user_mcp_{index}" for index in range(5)} <= {
        item.get("call_id") for item in results
    }
    assert denied["status"] == "failed"
    assert all(
        item["status"] == "completed"
        for item in results
        if item.get("call_id")
        in {
            "call_github_user_mcp_0",
            "call_github_user_mcp_1",
            "call_github_user_mcp_2",
            "call_github_user_mcp_3",
        }
    )
    assert _status(base, workspace.token)["connection"] is not None
    provider_state = requests.get(
        github_validation_proxy_url + "/__testenv/state", timeout=5
    ).json()
    assert provider_state["mcp_call_count"] >= 5
    assert set(provider_state["mcp_accounts"]) == {"connected-user"}

    if platform:
        off_events = _run(
            azents_public_server_url,
            member.access_token,
            agent.id,
            kind="runtime-off",
            session_id=None,
        )
        _assert_runtime_result(
            off_events, kind="runtime-off", marker="GITHUB_USER_ENV_ABSENT"
        )
        toolkits.toolkit_v1_update_toolkit_config(
            handle=workspace.handle,
            toolkit_config_id=toolkit.id,
            toolkit_config_update_request=ToolkitConfigUpdateRequest(
                config={
                    "github_auth_type": mode,
                    "toolsets": ["users", "repos"],
                    "inject_runtime_environment": True,
                }
            ),
            _headers=headers,
        )
        on_events = _run(
            azents_public_server_url,
            member.access_token,
            agent.id,
            kind="runtime-on",
            session_id=None,
        )
        _assert_runtime_result(
            on_events, kind="runtime-on", marker="GITHUB_USER_ENV_CONNECTED"
        )

    replacement = _connect(base, workspace.token, "replacement")
    assert _status(base, workspace.token)["connection"] == connected
    _scenario(github_validation_proxy_url, "user_cleanup_failure")
    active = _operation(
        base, workspace.token, "confirm", body={"attempt_id": replacement["attempt_id"]}
    )
    assert active["account_login"] == "replacement-user"
    assert active["id"] != connected["id"]
    attempted = requests.get(
        github_validation_proxy_url + "/__testenv/state", timeout=5
    ).json()
    assert attempted["revocation_request_count"] >= 1
    replaced_events = _run(
        azents_public_server_url,
        member.access_token,
        agent.id,
        kind="replacement",
        session_id=None,
    )
    assert "replacement-user" in json.dumps(replaced_events)
    if platform:
        runtime_replaced = _run(
            azents_public_server_url,
            member.access_token,
            agent.id,
            kind="runtime-replacement",
            session_id=None,
        )
        _assert_runtime_result(
            runtime_replaced,
            kind="runtime-replacement",
            marker="GITHUB_USER_ENV_REPLACEMENT",
        )
    _scenario(github_validation_proxy_url, "user_revoked")
    _run(
        azents_public_server_url,
        member.access_token,
        agent.id,
        kind="replacement",
        session_id=None,
    )
    failed_connection = json_object_payload(
        _status(base, workspace.token)["connection"],
        label="Current GitHub user authentication failure",
    )
    assert failed_connection["id"] == active["id"]
    assert failed_connection["status"] == "reconnect_required"
    _scenario(github_validation_proxy_url, "user_cleanup_failure")
    disconnected = requests.delete(base + "/connection", headers=headers, timeout=15)
    assert disconnected.status_code == 204
    assert _status(base, workspace.token) == {"connection": None}
    final = requests.get(
        github_validation_proxy_url + "/__testenv/state", timeout=5
    ).json()
    assert final["revocation_request_count"] >= 1
    # Provider failure is an attempted cleanup, not a provider-revocation claim.
    toolkits.toolkit_v1_delete_toolkit_config(
        handle=workspace.handle, toolkit_config_id=toolkit.id, _headers=headers
    )
