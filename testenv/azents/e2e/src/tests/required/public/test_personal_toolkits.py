"""Workspace-bound personal ownership, policy and Worker effects through real APIs."""

from urllib.parse import parse_qs, urlsplit

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.chat_event_response import ChatEventResponse
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.personal_toolkit_list_response import (
    PersonalToolkitListResponse,
)
from azentspublicclient.models.personal_toolkit_response import PersonalToolkitResponse
from azentspublicclient.models.secrets import Secrets

from support.observations import ToolResultObservation
from support.runtime_profiles import (
    create_workspace_runtime_profile,
    start_and_wait_for_agent_runtime,
)
from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    single_candidate_model_options,
    unique,
)
from tests.required.admin.test_03_system_settings import _generate_private_key
from tests.required.public.test_agent_execution_persistence import auth_headers
from tests.required.public.test_brave_search import (
    _tool_events,
    _wait_for_terminal_session,
)
from tests.required.public.test_github_user_toolkit import (
    _assert_runtime_result,
    _Connect,
    _Created,
    _CreationReview,
    _operation,
    _ProxyEvidence,
    _response,
    _scenario,
)
from tests.required.public.test_github_user_toolkit import (
    _run as _run_team,
)
from tests.required.public.test_toolkit import _add_member
from tests.required.public.test_user_sessions import _write_user_first_message


def _run_user(
    server: str, token: str, agent_id: str, *, kind: str
) -> list[ChatEventResponse]:
    """Exercise a canonical User root rather than the Team-session test helper."""
    created = _write_user_first_message(
        server_url=server,
        token=token,
        agent_id=agent_id,
        message=f"GitHub User Toolkit E2E {kind}",
        client_request_id="personal-" + unique(),
    )
    _wait_for_terminal_session(
        server_url=server,
        token=token,
        agent_id=agent_id,
        session_id=created.session_id,
    )
    return _tool_events(server_url=server, token=token, session_id=created.session_id)


def _assert_connected_result(events: list[ChatEventResponse]) -> None:
    """Inspect the Provider result rather than a marker in model input arguments."""
    results = [
        ToolResultObservation.model_validate(event.payload)
        for event in events
        if event.kind == "client_tool_result"
    ]
    result = next(
        item for item in results if item.call_id == "call_github_user_personal_0"
    )
    assert result.status == "completed"
    assert "connected-user" in result.model_dump_json(exclude_unset=True)


def _personal_connection(
    server: str, token: str, handle: str
) -> PersonalToolkitResponse:
    """Publish through exact personal setup review and explicit confirmation."""
    base = f"{server}/toolkit/v1/workspaces/{handle}"
    creation = base + "/personal/github-user-creations"
    connected = _operation(
        creation,
        token,
        "connect",
        body={
            "toolkit_type": "github",
            "slug": "github_user",
            "name": "Same personal connection",
            "config": {
                "github_auth_type": "github_app_user",
                "toolsets": ["users", "repos"],
                "inject_runtime_environment": True,
            },
            "credentials": {
                "type": "github_app_user",
                "app_id": "123",
                "client_id": "Iv1.azents-test",
                "private_key": _generate_private_key(),
                "client_secret": "synthetic-client-secret",
            },
            "always_expose_tools": True,
        },
        model=_Connect,
    )
    state = parse_qs(urlsplit(connected.authorization_url).query)["state"][0]
    review = _operation(
        creation,
        token,
        "exchange",
        body={"code": "e2e-user-create-" + unique(), "state": state},
        model=_CreationReview,
    )
    created = _operation(
        creation,
        token,
        "confirm",
        body={
            "attempt_id": review.candidate.attempt_id,
            "settings": {
                "name": "Same personal connection",
                "slug": "github_user",
                "description": None,
                "prompt": None,
                "enabled": True,
                "always_expose_tools": True,
                "toolsets": ["users", "repos"],
                "timeout": 30,
                "inject_runtime_environment": True,
                "runtime_risk_acknowledged": True,
            },
        },
        model=_Created,
    )
    return _response(
        requests.get(
            base + "/personal-toolkit-configs/" + created.toolkit_id,
            headers=auth_headers(token),
            timeout=10,
        ),
        PersonalToolkitResponse,
        label="Personal connection",
    )


def _list(server: str, token: str, handle: str) -> PersonalToolkitListResponse:
    return _response(
        requests.get(
            f"{server}/toolkit/v1/workspaces/{handle}/personal-toolkit-configs",
            headers=auth_headers(token),
            timeout=10,
        ),
        PersonalToolkitListResponse,
        label="Scoped personal list",
    )


def test_personal_workspace_policy_and_worker_isolation(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    github_validation_proxy_url: str,
) -> None:
    """One User's two Workspaces stay independent through publication and effects."""
    server = azents_public_server_url
    _scenario(github_validation_proxy_url, "user_success")
    token, _, _ = authenticate_user(public_api_client, admin_api_client)
    headers = auth_headers(token)
    handles = ["personal-a-" + unique(), "personal-b-" + unique()]
    agents: list[str] = []
    for handle in handles:
        WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
            CreateWorkspaceRequest(
                workspace_name="Personal scope",
                workspace_handle=handle,
                owner_name="Owner",
            ),
            _headers=headers,
        )
        integration = LLMProviderIntegrationV1Api(
            public_api_client
        ).llm_provider_integration_v1_create_integration(
            handle=handle,
            llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
                provider=LLMProvider.OPENAI,
                name="__testenv_model_listing:deterministic-success",
                secrets=Secrets(ApiKeySecrets(api_key="sk-personal-fixture")),
            ),
            _headers=headers,
        )
        selection = model_selection_from_first_candidate(
            server, token, handle, integration.id
        )
        profile_id = create_workspace_runtime_profile(
            public_api_client,
            token=token,
            workspace_handle=handle,
            provider_id="system-docker",
        )
        agent = AgentV1Api(public_api_client).agent_v1_create_agent(
            handle,
            AgentCreateRequest(
                name="Same Agent",
                selectable_model_options=single_candidate_model_options(selection),
                main_model_label="default",
                lightweight_model_label="default",
                type=AgentType.PUBLIC,
                tool_search_enabled=True,
                runtime_profile_id=profile_id,
            ),
            _headers=headers,
        )
        agents.append(agent.id)
        start_and_wait_for_agent_runtime(
            public_api_client, token=token, workspace_handle=handle, agent_id=agent.id
        )
    a, b = handles
    agent_a, agent_b = agents
    connection_a = _personal_connection(server, token, a)
    assert connection_a.access_mode == "all"
    assert [item.id for item in _list(server, token, a).items] == [connection_a.id]
    assert _list(server, token, b).items == []
    foreign = (
        f"{server}/toolkit/v1/workspaces/{b}/personal-toolkit-configs/{connection_a.id}"
    )
    for method in ["GET", "DELETE", "PATCH"]:
        response = requests.request(
            method,
            foreign,
            headers=headers,
            json={"name": "Cross scope"} if method == "PATCH" else None,
            timeout=10,
        )
        assert response.status_code == 404
    events = _run_user(server, token, agent_a, kind="personal")
    _assert_connected_result(events)
    _assert_runtime_result(
        _run_user(server, token, agent_a, kind="runtime-on"),
        kind="runtime-on",
        marker="GITHUB_USER_ENV_CONNECTED",
    )
    before = _response(
        requests.get(github_validation_proxy_url + "/__testenv/state", timeout=5),
        _ProxyEvidence,
        label="Provider before denial",
    )
    assert before.mcp_call_count >= 1
    _run_team(server, token, agent_a, kind="personal", session_id=None)
    _run_user(server, token, agent_b, kind="personal")
    _assert_runtime_result(
        _run_user(server, token, agent_b, kind="runtime-off"),
        kind="runtime-off",
        marker="GITHUB_USER_ENV_ABSENT",
    )
    after = _response(
        requests.get(github_validation_proxy_url + "/__testenv/state", timeout=5),
        _ProxyEvidence,
        label="Provider after denial",
    )
    assert after.mcp_call_count == before.mcp_call_count
    member_token = _add_member(
        public_api_client, admin_api_client, owner_token=token, handle=a
    )
    assert _list(server, member_token, a).items == []
    denied = requests.get(
        f"{server}/toolkit/v1/workspaces/{a}/personal-toolkit-configs/{connection_a.id}",
        headers=auth_headers(member_token),
        timeout=10,
    )
    assert denied.status_code == 404
    _run_user(server, member_token, agent_a, kind="personal")
    member_denied = _response(
        requests.get(github_validation_proxy_url + "/__testenv/state", timeout=5),
        _ProxyEvidence,
        label="Provider after foreign User",
    )
    assert member_denied.mcp_call_count == after.mcp_call_count
    policy = (
        f"{server}/toolkit/v1/workspaces/{a}"
        f"/personal-toolkit-configs/{connection_a.id}/agent-access"
    )
    restricted = requests.patch(
        policy,
        headers=headers,
        json={
            "expected_mode": "all",
            "mode": None,
            "allow_agent_ids": [],
            "restrict_agent_ids": [agent_a],
        },
        timeout=10,
    )
    restricted.raise_for_status()
    _run_user(server, token, agent_a, kind="personal")
    _assert_runtime_result(
        _run_user(server, token, agent_a, kind="runtime-off"),
        kind="runtime-off",
        marker="GITHUB_USER_ENV_ABSENT",
    )
    withdrawn = _response(
        requests.get(github_validation_proxy_url + "/__testenv/state", timeout=5),
        _ProxyEvidence,
        label="Provider after restriction",
    )
    assert withdrawn.mcp_call_count == after.mcp_call_count
    connection_b = _personal_connection(server, token, b)
    assert connection_b.github_user_connection is not None
    assert connection_a.github_user_connection is not None
    assert (
        connection_b.github_user_connection.id != connection_a.github_user_connection.id
    )
    assert connection_b.id != connection_a.id
    assert connection_b.owner.workspace_id != connection_a.owner.workspace_id
    assert connection_b.access_mode == "all"
    assert _list(server, token, a).items[0].access_mode == "selected"
    assert [item.id for item in _list(server, token, b).items] == [connection_b.id]
    restored = requests.patch(
        policy,
        headers=headers,
        json={
            "expected_mode": "selected",
            "mode": None,
            "allow_agent_ids": [agent_a],
            "restrict_agent_ids": [],
        },
        timeout=10,
    )
    restored.raise_for_status()
    recovered = _run_user(server, token, agent_a, kind="personal")
    _assert_connected_result(recovered)
