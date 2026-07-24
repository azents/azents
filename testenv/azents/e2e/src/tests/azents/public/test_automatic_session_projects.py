"""Automatic-session Project policy and root-session E2E journeys."""

from __future__ import annotations

import hashlib
import hmac
import json
import shlex
import time
from dataclasses import dataclass
from typing import cast

import azentsadminclient
import azentspublicclient
import docker as docker_py
import pytest
import requests
from azentspublicclient.api.agent_runtime_v1_api import AgentRuntimeV1Api
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.external_channel_v1_api import ExternalChannelV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.automatic_session_projects_replace_request import (
    AutomaticSessionProjectsReplaceRequest,
)
from azentspublicclient.models.automatic_session_projects_response import (
    AutomaticSessionProjectsResponse,
)
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.external_channel_decision_input import (
    ExternalChannelDecisionInput,
)
from azentspublicclient.models.external_channel_transport import (
    ExternalChannelTransport,
)
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from azentspublicclient.models.slack_connection_credentials import (
    SlackConnectionCredentials,
)
from azentspublicclient.models.slack_connection_setup_request import (
    SlackConnectionSetupRequest,
)
from docker.models.containers import Container as DockerPyContainer
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait
from testcontainers.core.container import DockerContainer

from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    unique,
    wait_until,
)

_SLACK_APP_ID = "A-E2E"
_SLACK_TEAM_ID = "T-E2E"
_SLACK_CHANNEL_ID = "C-E2E"
_SLACK_BOT_TOKEN = "xoxb-e2e-private"
_SLACK_SIGNING_SECRET = "e2e-signing-private"


@dataclass(frozen=True)
class _Setup:
    token: str
    handle: str
    agent_id: str


def _headers(token: str) -> dict[str, str]:
    """Return bearer authentication headers."""
    return {"Authorization": f"Bearer {token}"}


def _create_runtime_agent(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
    *,
    runtime_provider_id: str,
) -> _Setup:
    """Create an Agent configured with the deterministic Docker Runtime Provider."""
    suffix = unique()
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"automatic-projects-{suffix}@example.com",
    )
    handle = f"automatic-projects-{suffix}"
    headers = _headers(token)
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Automatic Projects {suffix}",
            workspace_handle=handle,
            owner_name=f"Owner {suffix}",
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
            secrets=Secrets(ApiKeySecrets(api_key="sk-automatic-projects")),
        ),
        _headers=headers,
    )
    model_selection = model_selection_from_first_candidate(
        server_url,
        token,
        handle,
        integration.id,
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=handle,
        agent_create_request=AgentCreateRequest(
            name=f"Automatic Projects Agent {suffix}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
            runtime_provider_id=runtime_provider_id,
            shell_enabled=True,
        ),
        _headers=headers,
    )
    return _Setup(token=token, handle=handle, agent_id=agent.id)


def _runtime_container(agent_id: str) -> DockerPyContainer:
    """Return the one Runtime container for an Agent."""
    client = docker_py.from_env()
    containers = client.containers.list(
        all=True,
        filters={"label": f"azents/agent-id={agent_id}"},
    )
    if len(containers) != 1:
        names = [container.name for container in containers]
        raise AssertionError(
            f"expected one Runtime container for {agent_id}, found {names!r}"
        )
    return containers[0]


def _runtime_exec(container: DockerPyContainer, command: str) -> str:
    """Run a bounded shell command in the Agent Runtime."""
    result = container.exec_run(["sh", "-lc", command])
    output = result.output.decode(errors="replace")
    if result.exit_code != 0:
        raise AssertionError(
            f"Runtime command failed with exit {result.exit_code}: {command}\n{output}"
        )
    return output


def _seed_projects(agent_id: str, suffix: str) -> list[str]:
    """Create three disposable existing Project directories in the Runtime."""
    paths = [f"/workspace/agent/automatic-project-{suffix}-{name}" for name in "abc"]
    command = "set -eu; " + "; ".join(f"mkdir -p {shlex.quote(path)}" for path in paths)
    _runtime_exec(_runtime_container(agent_id), command)
    return paths


def _remove_project(agent_id: str, path: str) -> None:
    """Remove one disposable Project directory through the Runtime boundary."""
    _runtime_exec(_runtime_container(agent_id), f"rm -rf -- {shlex.quote(path)}")


def _get_policy(
    *,
    public_api_client: azentspublicclient.ApiClient,
    setup: _Setup,
) -> AutomaticSessionProjectsResponse:
    """Read the Agent automatic-session Project policy."""
    return AgentV1Api(public_api_client).agent_v1_get_automatic_session_projects(
        agent_id=setup.agent_id,
        handle=setup.handle,
        _headers=_headers(setup.token),
    )


def _replace_policy(
    *,
    public_api_client: azentspublicclient.ApiClient,
    setup: _Setup,
    revision: int,
    paths: list[str],
) -> AutomaticSessionProjectsResponse:
    """Replace the complete Agent automatic-session Project policy."""
    return AgentV1Api(public_api_client).agent_v1_replace_automatic_session_projects(
        agent_id=setup.agent_id,
        handle=setup.handle,
        automatic_session_projects_replace_request=(
            AutomaticSessionProjectsReplaceRequest(
                expected_revision=revision,
                project_paths=paths,
            )
        ),
        _headers=_headers(setup.token),
    )


def _session_projects(
    *,
    public_url: str,
    setup: _Setup,
    session_id: str,
) -> list[str]:
    """Return registered Project paths for one root Session."""
    response = requests.get(
        f"{public_url}/chat/v1/agents/{setup.agent_id}/sessions/{session_id}/projects",
        headers=_headers(setup.token),
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    items = payload.get("items")
    if not isinstance(items, list):
        raise AssertionError(
            f"Session Project response did not include items: {payload!r}"
        )
    paths: list[str] = []
    for item in cast(list[object], items):
        if not isinstance(item, dict):
            raise AssertionError(f"Invalid Session Project item: {item!r}")
        project_item = cast(dict[str, object], item)
        path = project_item.get("path")
        if not isinstance(path, str):
            raise AssertionError(f"Invalid Session Project item: {item!r}")
        paths.append(path)
    return paths


def _team_primary_session(*, public_url: str, setup: _Setup) -> str:
    """Ensure and return the Agent team-primary Session."""
    response = requests.get(
        f"{public_url}/chat/v1/agents/{setup.agent_id}/team-primary-session",
        headers=_headers(setup.token),
        timeout=10,
    )
    response.raise_for_status()
    session_id = response.json().get("id")
    if not isinstance(session_id, str):
        raise AssertionError(
            f"Team-primary response did not include id: {response.text}"
        )
    return session_id


def _explicit_session(
    *,
    public_url: str,
    setup: _Setup,
    paths: list[str],
) -> str:
    """Create a non-primary Session with explicit Project intent."""
    response = requests.post(
        f"{public_url}/chat/v1/agents/{setup.agent_id}/sessions",
        headers={**_headers(setup.token), "Content-Type": "application/json"},
        json={"existing_project_paths": paths, "setup_actions": []},
        timeout=10,
    )
    response.raise_for_status()
    session_id = response.json().get("id")
    if not isinstance(session_id, str):
        raise AssertionError(
            f"Explicit Session response did not include id: {response.text}"
        )
    return session_id


def _prepare_runtime_workspace(
    *,
    public_api_client: azentspublicclient.ApiClient,
    public_url: str,
    setup: _Setup,
) -> list[str]:
    """Ensure a Runtime exists without consuming the team-primary producer."""
    _explicit_session(public_url=public_url, setup=setup, paths=[])
    runtime_api = AgentRuntimeV1Api(public_api_client)
    runtime_api.agent_runtime_v1_start_agent_runtime(
        agent_id=setup.agent_id,
        handle=setup.handle,
        _headers=_headers(setup.token),
    )
    deadline = time.monotonic() + 120
    last_state: object | None = None
    while time.monotonic() < deadline:
        state = runtime_api.agent_runtime_v1_observe_agent_runtime(
            agent_id=setup.agent_id,
            handle=setup.handle,
            _headers=_headers(setup.token),
        )
        last_state = state
        if state.state.actions.use_runner:
            return _seed_projects(setup.agent_id, unique())
        time.sleep(1)
    raise AssertionError(f"Runtime Runner did not become ready: {last_state!r}")


def _run_message(
    *,
    public_url: str,
    setup: _Setup,
    session_id: str,
    message: str,
) -> None:
    """Send one deterministic chat input to a Session."""
    response = requests.post(
        f"{public_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**_headers(setup.token), "Content-Type": "application/json"},
        json={
            "agent_id": setup.agent_id,
            "client_request_id": f"automatic-projects-{unique()}",
            "message": message,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
            },
        },
        timeout=10,
    )
    response.raise_for_status()


def _subagent_tree(
    *,
    public_url: str,
    setup: _Setup,
    session_id: str,
) -> dict[str, object]:
    """Fetch the public Subagent Tree projection."""
    response = requests.get(
        f"{public_url}/chat/v1/agents/{setup.agent_id}/sessions/{session_id}/subagents/tree",
        headers=_headers(setup.token),
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError(
            f"Subagent tree response is not an object: {response.text}"
        )
    return cast(dict[str, object], payload)


def _list_sessions(*, public_url: str, setup: _Setup) -> list[str]:
    """Return all root Session IDs visible for an Agent."""
    response = requests.get(
        f"{public_url}/chat/v1/agents/{setup.agent_id}/sessions",
        headers=_headers(setup.token),
        timeout=10,
    )
    response.raise_for_status()
    items = response.json().get("items")
    if not isinstance(items, list):
        raise AssertionError(
            f"Session list response did not include items: {response.text}"
        )
    session_ids: list[str] = []
    for item in cast(list[object], items):
        if not isinstance(item, dict):
            continue
        session_id = cast(dict[str, object], item).get("id")
        if isinstance(session_id, str):
            session_ids.append(session_id)
    return session_ids


def _signed_headers(body: bytes) -> dict[str, str]:
    """Sign a deterministic Slack callback body."""
    timestamp = str(int(time.time()))
    signature = hmac.new(
        _SLACK_SIGNING_SECRET.encode(),
        b"v0:" + timestamp.encode() + b":" + body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Slack-Request-Timestamp": timestamp,
        "X-Slack-Signature": f"v0={signature}",
    }


def _provider_state(slack_provider_fake_url: str) -> dict[str, object]:
    """Read the sanitized fake Slack state."""
    response = requests.get(
        f"{slack_provider_fake_url}/__testenv/state",
        timeout=5,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError(f"Fake Slack state is not an object: {payload!r}")
    return cast(dict[str, object], payload)


def _login_main_web(
    driver: WebDriver,
    *,
    main_web_url: str,
    email: str,
) -> None:
    """Log in through the real Main Web password flow."""
    driver.delete_all_cookies()
    driver.get(f"{main_web_url}/login")
    wait = WebDriverWait(driver, 30)
    email_input = wait.until(ec.element_to_be_clickable((By.NAME, "email")))
    email_input.send_keys(email, Keys.ENTER)
    wait.until(ec.url_contains("/login/password"))
    password_input = wait.until(ec.element_to_be_clickable((By.NAME, "password")))
    password_input.send_keys("TestPass123!", Keys.ENTER)
    wait.until(ec.url_contains("/workspaces"))


def _approval_request_id(slack_provider_fake_url: str) -> str:
    """Return the latest captured approval request ID."""
    deliveries = _provider_state(slack_provider_fake_url).get("deliveries")
    if not isinstance(deliveries, list):
        return ""
    for item in reversed(cast(list[object], deliveries)):
        if not isinstance(item, dict):
            continue
        delivery = cast(dict[str, object], item)
        request_id = delivery.get("approval_request_id")
        if isinstance(request_id, str):
            return request_id
    return ""


def _restart_runtime_provider(container: DockerContainer) -> None:
    """Restart the shared Runtime Provider and wait for a new registration."""
    marker = "Runtime Provider registered"
    stdout, stderr = container.get_logs()
    prior_registrations = (
        stdout.decode(errors="replace") + stderr.decode(errors="replace")
    ).count(marker)
    container.start()

    def registered_again() -> bool:
        if container.get_wrapped_container().status == "exited":
            raise AssertionError("Runtime Provider exited while restarting")
        current_stdout, current_stderr = container.get_logs()
        registrations = (
            current_stdout.decode(errors="replace")
            + current_stderr.decode(errors="replace")
        ).count(marker)
        return registrations > prior_registrations

    wait_until(
        registered_again,
        timeout=60,
        interval=1,
        message="Runtime Provider did not register after restart",
    )


@pytest.mark.runtime_provider
def test_automatic_session_projects_policy_and_explicit_precedence(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    runtime_provider_resource_id: str,
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """Apply defaults to automatic roots while preserving explicit intent."""
    del azents_runtime_provider_docker_container
    setup = _create_runtime_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_provider_id=runtime_provider_resource_id,
    )
    paths = _prepare_runtime_workspace(
        public_api_client=public_api_client,
        public_url=azents_public_server_url,
        setup=setup,
    )

    initial = _get_policy(public_api_client=public_api_client, setup=setup)
    assert initial.project_paths == []
    saved = _replace_policy(
        public_api_client=public_api_client,
        setup=setup,
        revision=initial.revision,
        paths=[paths[1], paths[0]],
    )
    assert saved.revision == initial.revision + 1
    assert saved.project_paths == [paths[1], paths[0]]

    primary_session_id = _team_primary_session(
        public_url=azents_public_server_url,
        setup=setup,
    )
    assert _session_projects(
        public_url=azents_public_server_url,
        setup=setup,
        session_id=primary_session_id,
    ) == [paths[1], paths[0]]

    empty_session_id = _explicit_session(
        public_url=azents_public_server_url,
        setup=setup,
        paths=[],
    )
    assert (
        _session_projects(
            public_url=azents_public_server_url,
            setup=setup,
            session_id=empty_session_id,
        )
        == []
    )

    explicit_session_id = _explicit_session(
        public_url=azents_public_server_url,
        setup=setup,
        paths=[paths[2]],
    )
    assert _session_projects(
        public_url=azents_public_server_url,
        setup=setup,
        session_id=explicit_session_id,
    ) == [paths[2]]


@pytest.mark.runtime_provider
def test_automatic_session_projects_revision_missing_path_and_clear(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    runtime_provider_resource_id: str,
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """Reject invalid complete replacements without changing the prior policy."""
    del azents_runtime_provider_docker_container
    setup = _create_runtime_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_provider_id=runtime_provider_resource_id,
    )
    paths = _prepare_runtime_workspace(
        public_api_client=public_api_client,
        public_url=azents_public_server_url,
        setup=setup,
    )
    saved = _replace_policy(
        public_api_client=public_api_client,
        setup=setup,
        revision=_get_policy(public_api_client=public_api_client, setup=setup).revision,
        paths=[paths[0], paths[1]],
    )
    _remove_project(setup.agent_id, paths[1])

    endpoint = (
        f"{azents_public_server_url}/agent/v1/workspaces/{setup.handle}"
        f"/agents/{setup.agent_id}/automatic-session-projects"
    )
    invalid = requests.put(
        endpoint,
        headers={**_headers(setup.token), "Content-Type": "application/json"},
        json={
            "expected_revision": saved.revision,
            "project_paths": [paths[0], paths[1]],
        },
        timeout=10,
    )
    assert invalid.status_code == 400, invalid.text
    current = _get_policy(public_api_client=public_api_client, setup=setup)
    assert current.revision == saved.revision
    assert current.project_paths == saved.project_paths

    stale = requests.put(
        endpoint,
        headers={**_headers(setup.token), "Content-Type": "application/json"},
        json={"expected_revision": saved.revision - 1, "project_paths": [paths[0]]},
        timeout=10,
    )
    assert stale.status_code == 409, stale.text
    assert _get_policy(
        public_api_client=public_api_client, setup=setup
    ).project_paths == [
        paths[0],
        paths[1],
    ]

    cleared = _replace_policy(
        public_api_client=public_api_client,
        setup=setup,
        revision=saved.revision,
        paths=[],
    )
    assert cleared.revision == saved.revision + 1
    assert cleared.project_paths == []


@pytest.mark.runtime_provider
def test_automatic_session_projects_runtime_unavailable_and_clear(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    runtime_provider_resource_id: str,
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """Keep non-empty validation dependent on Runtime while allowing clear."""
    setup = _create_runtime_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_provider_id=runtime_provider_resource_id,
    )
    paths = _prepare_runtime_workspace(
        public_api_client=public_api_client,
        public_url=azents_public_server_url,
        setup=setup,
    )
    saved = _replace_policy(
        public_api_client=public_api_client,
        setup=setup,
        revision=_get_policy(public_api_client=public_api_client, setup=setup).revision,
        paths=[paths[0]],
    )

    azents_runtime_provider_docker_container.stop()
    time.sleep(2)
    try:
        endpoint = (
            f"{azents_public_server_url}/agent/v1/workspaces/{setup.handle}"
            f"/agents/{setup.agent_id}/automatic-session-projects"
        )
        unavailable = requests.put(
            endpoint,
            headers={**_headers(setup.token), "Content-Type": "application/json"},
            json={"expected_revision": saved.revision, "project_paths": [paths[1]]},
            timeout=20,
        )
        assert unavailable.status_code == 409, unavailable.text
        detail = unavailable.json().get("detail")
        if not isinstance(detail, dict):
            raise AssertionError(
                f"Runtime-unavailable response lacked detail: {unavailable.text}"
            )
        assert (
            cast(dict[str, object], detail).get("code")
            == "automatic_session_projects_runtime_unavailable"
        )

        cleared = requests.put(
            endpoint,
            headers={**_headers(setup.token), "Content-Type": "application/json"},
            json={"expected_revision": saved.revision, "project_paths": []},
            timeout=10,
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["project_paths"] == []
    finally:
        _restart_runtime_provider(azents_runtime_provider_docker_container)


@pytest.mark.runtime_provider
def test_external_channel_allow_and_granted_binding_snapshot_projects(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    runtime_provider_resource_id: str,
    azents_runtime_provider_docker_container: DockerContainer,
    azents_engine_worker_container: DockerContainer,
    slack_provider_fake_url: str,
) -> None:
    """Allow and an already-granted initial binding snapshot current policies."""
    del azents_runtime_provider_docker_container, azents_engine_worker_container
    requests.post(
        f"{slack_provider_fake_url}/__testenv/reset",
        timeout=5,
    ).raise_for_status()
    setup = _create_runtime_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_provider_id=runtime_provider_resource_id,
    )
    paths = _prepare_runtime_workspace(
        public_api_client=public_api_client,
        public_url=azents_public_server_url,
        setup=setup,
    )
    policy = _get_policy(public_api_client=public_api_client, setup=setup)
    first_policy = _replace_policy(
        public_api_client=public_api_client,
        setup=setup,
        revision=policy.revision,
        paths=paths[:2],
    )
    root_timestamp = f"{int(time.time()) - 60}.000100"
    requests.post(
        f"{slack_provider_fake_url}/__testenv/configure",
        json={
            "history_pages": [
                [
                    {
                        "user": "U-AUTOMATIC-PROJECTS",
                        "ts": root_timestamp,
                        "text": "<@B-E2E> automatic projects",
                    }
                ]
            ],
        },
        timeout=5,
    ).raise_for_status()

    external_api = ExternalChannelV1Api(public_api_client)
    external_api.external_channel_v1_setup_slack_connection(
        agent_id=setup.agent_id,
        handle=setup.handle,
        slack_connection_setup_request=SlackConnectionSetupRequest(
            app_id=_SLACK_APP_ID,
            transport=ExternalChannelTransport.HTTP,
            credentials=SlackConnectionCredentials(
                bot_token=_SLACK_BOT_TOKEN,
                signing_secret=_SLACK_SIGNING_SECRET,
                app_token=None,
            ),
        ),
        _headers=_headers(setup.token),
    )
    callback_url = f"{azents_public_server_url}/external-channel/v1/slack/events"
    body = json.dumps(
        {
            "type": "event_callback",
            "event_id": f"Ev-{unique()}",
            "event_time": int(time.time()),
            "api_app_id": _SLACK_APP_ID,
            "team_id": _SLACK_TEAM_ID,
            "event": {
                "type": "app_mention",
                "channel": _SLACK_CHANNEL_ID,
                "channel_type": "channel",
                "user": "U-AUTOMATIC-PROJECTS",
                "text": "<@B-E2E> automatic projects",
                "ts": root_timestamp,
            },
        },
        separators=(",", ":"),
    ).encode()
    response = requests.post(
        callback_url,
        data=body,
        headers=_signed_headers(body),
        timeout=10,
    )
    assert response.status_code == 200, response.text
    request_id = wait_until(
        lambda: _approval_request_id(slack_provider_fake_url),
        timeout=15,
        interval=0.2,
        message="Automatic Projects approval was not delivered",
    )
    decided = external_api.external_channel_v1_decide_approval_request(
        access_request_id=request_id,
        external_channel_decision_input=ExternalChannelDecisionInput(
            decision="allow_agent",
            summary="Automatic projects E2E",
        ),
        _headers=_headers(setup.token),
    )
    session_id = decided.agent_session_id
    assert isinstance(session_id, str)
    assert (
        _session_projects(
            public_url=azents_public_server_url,
            setup=setup,
            session_id=session_id,
        )
        == paths[:2]
    )

    changed_policy = _replace_policy(
        public_api_client=public_api_client,
        setup=setup,
        revision=first_policy.revision,
        paths=[paths[2]],
    )
    second_timestamp = f"{int(time.time()) - 30}.000200"
    requests.post(
        f"{slack_provider_fake_url}/__testenv/configure",
        json={
            "history_pages": [
                [
                    {
                        "user": "U-AUTOMATIC-PROJECTS",
                        "ts": second_timestamp,
                        "text": "<@B-E2E> automatic projects second",
                    }
                ]
            ]
        },
        timeout=5,
    ).raise_for_status()
    second_body = json.dumps(
        {
            "type": "event_callback",
            "event_id": f"Ev-{unique()}",
            "event_time": int(time.time()),
            "api_app_id": _SLACK_APP_ID,
            "team_id": _SLACK_TEAM_ID,
            "event": {
                "type": "app_mention",
                "channel": "C-E2E-SECOND",
                "channel_type": "channel",
                "user": "U-AUTOMATIC-PROJECTS",
                "text": "<@B-E2E> automatic projects second",
                "ts": second_timestamp,
            },
        },
        separators=(",", ":"),
    ).encode()
    second_response = requests.post(
        callback_url,
        data=second_body,
        headers=_signed_headers(second_body),
        timeout=10,
    )
    assert second_response.status_code == 200, second_response.text

    def new_snapshot_session() -> str | None:
        for candidate in _list_sessions(
            public_url=azents_public_server_url,
            setup=setup,
        ):
            if candidate == session_id:
                continue
            if (
                _session_projects(
                    public_url=azents_public_server_url,
                    setup=setup,
                    session_id=candidate,
                )
                == changed_policy.project_paths
            ):
                return candidate
        return None

    second_session_id = cast(
        str,
        wait_until(
            new_snapshot_session,
            timeout=20,
            interval=0.5,
            message="Second automatic External Channel Session was not created",
        ),
    )
    assert (
        _session_projects(
            public_url=azents_public_server_url,
            setup=setup,
            session_id=session_id,
        )
        == paths[:2]
    )
    assert _session_projects(
        public_url=azents_public_server_url,
        setup=setup,
        session_id=second_session_id,
    ) == [paths[2]]
    assert _approval_request_id(slack_provider_fake_url) == request_id


@pytest.mark.runtime_provider
def test_subagent_reuses_root_project_context_without_duplicates(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    runtime_provider_resource_id: str,
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """Spawning a child leaves the root Session Project registry unchanged."""
    del azents_runtime_provider_docker_container
    setup = _create_runtime_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_provider_id=runtime_provider_resource_id,
    )
    paths = _prepare_runtime_workspace(
        public_api_client=public_api_client,
        public_url=azents_public_server_url,
        setup=setup,
    )
    policy = _get_policy(public_api_client=public_api_client, setup=setup)
    _replace_policy(
        public_api_client=public_api_client,
        setup=setup,
        revision=policy.revision,
        paths=paths[:2],
    )
    root_session_id = _team_primary_session(
        public_url=azents_public_server_url,
        setup=setup,
    )
    _run_message(
        public_url=azents_public_server_url,
        setup=setup,
        session_id=root_session_id,
        message="Subagent E2E spawn child",
    )

    def child_tree() -> dict[str, object] | None:
        tree = _subagent_tree(
            public_url=azents_public_server_url,
            setup=setup,
            session_id=root_session_id,
        )
        nodes = tree.get("nodes")
        if isinstance(nodes, list) and nodes:
            return tree
        return None

    tree = cast(
        dict[str, object],
        wait_until(
            child_tree,
            timeout=30,
            interval=0.5,
            message="Subagent child was not projected",
        ),
    )
    nodes = tree.get("nodes")
    assert isinstance(nodes, list) and nodes

    def child_session_ids(raw_nodes: list[object]) -> list[str]:
        result: list[str] = []
        for raw_node in raw_nodes:
            if not isinstance(raw_node, dict):
                continue
            node = cast(dict[str, object], raw_node)
            raw_children = node.get("children")
            if isinstance(raw_children, list):
                children = cast(list[object], raw_children)
                for child in children:
                    if isinstance(child, dict) and isinstance(
                        cast(dict[str, object], child).get("agent_session_id"), str
                    ):
                        result.append(
                            cast(
                                str, cast(dict[str, object], child)["agent_session_id"]
                            )
                        )
                result.extend(child_session_ids(children))
        return result

    child_ids = child_session_ids(cast(list[object], nodes))
    assert child_ids
    assert (
        _session_projects(
            public_url=azents_public_server_url,
            setup=setup,
            session_id=child_ids[0],
        )
        == paths[:2]
    )
    assert (
        len(
            _session_projects(
                public_url=azents_public_server_url,
                setup=setup,
                session_id=root_session_id,
            )
        )
        == 2
    )


@pytest.mark.web_surface
def test_agent_settings_projects_web_add_reorder_remove_save(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_main_web_url: str,
    browser_driver: WebDriver,
    runtime_provider_resource_id: str,
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """Use the real Agent Settings page to edit an ordered policy."""
    del azents_runtime_provider_docker_container
    setup = _create_runtime_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        runtime_provider_id=runtime_provider_resource_id,
    )
    paths = _prepare_runtime_workspace(
        public_api_client=public_api_client,
        public_url=azents_public_server_url,
        setup=setup,
    )
    _login_main_web(
        browser_driver,
        main_web_url=azents_main_web_url,
        email=f"automatic-projects-{setup.handle.removeprefix('automatic-projects-')}@example.com",
    )
    browser_driver.get(
        f"{azents_main_web_url}/w/{setup.handle}/agents/{setup.agent_id}/settings/projects"
    )
    wait = WebDriverWait(browser_driver, 30)
    wait.until(
        ec.visibility_of_element_located(
            (By.CSS_SELECTOR, '[data-testid="automatic-projects-page"]')
        )
    )

    def test_id(value: str) -> tuple[str, str]:
        return (By.XPATH, f"//*[@data-testid={json.dumps(value)}]")

    for path in paths[:2]:
        wait.until(
            ec.element_to_be_clickable(test_id("automatic-projects-add"))
        ).click()
        wait.until(
            ec.visibility_of_element_located(
                (By.CSS_SELECTOR, '[data-testid="agent-workspace-directory-picker"]')
            )
        )
        wait.until(
            ec.element_to_be_clickable(test_id(f"agent-workspace-picker-select-{path}"))
        ).click()
        wait.until(
            ec.invisibility_of_element_located(
                (By.CSS_SELECTOR, '[data-testid="agent-workspace-directory-picker"]')
            )
        )

    wait.until(ec.element_to_be_clickable(test_id("automatic-projects-save"))).click()
    wait_until(
        lambda: (
            _get_policy(public_api_client=public_api_client, setup=setup).project_paths
            == paths[:2]
        ),
        timeout=20,
        interval=0.5,
        message="Web settings did not persist the initial Project order",
    )
    for path in paths[:2]:
        wait.until(
            ec.visibility_of_element_located(test_id(f"automatic-project-row-{path}"))
        )

    wait.until(
        ec.element_to_be_clickable(test_id(f"automatic-projects-move-down-{paths[0]}"))
    ).click()
    wait.until(ec.element_to_be_clickable(test_id("automatic-projects-save"))).click()
    wait_until(
        lambda: (
            _get_policy(public_api_client=public_api_client, setup=setup).project_paths
            == [paths[1], paths[0]]
        ),
        timeout=20,
        interval=0.5,
        message="Web settings did not persist the reordered Projects",
    )
    rows = browser_driver.find_elements(
        By.CSS_SELECTOR, '[data-testid^="automatic-project-row-"]'
    )
    assert len(rows) == 2
    assert paths[1] in rows[0].text
    assert paths[0] in rows[1].text

    wait.until(
        ec.element_to_be_clickable(test_id(f"automatic-projects-remove-{paths[0]}"))
    ).click()
    wait.until(ec.element_to_be_clickable(test_id("automatic-projects-save"))).click()
    wait_until(
        lambda: (
            _get_policy(public_api_client=public_api_client, setup=setup).project_paths
            == [paths[1]]
        ),
        timeout=20,
        interval=0.5,
        message="Web settings did not persist the removed Project",
    )
    browser_driver.refresh()
    wait.until(
        ec.visibility_of_element_located(test_id(f"automatic-project-row-{paths[1]}"))
    )
    assert not browser_driver.find_elements(
        By.XPATH,
        f"//*[@data-testid={json.dumps(f'automatic-project-row-{paths[0]}')}]",
    )
