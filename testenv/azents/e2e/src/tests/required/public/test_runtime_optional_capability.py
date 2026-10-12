"""Optional managed Runtime public API E2E journeys."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, NamedTuple

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.agent_runtime_v1_api import AgentRuntimeV1Api
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.invitation_v1_api import InvitationV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_model_selection_input import (
    AgentModelSelectionInput,
)
from azentspublicclient.models.agent_runtime_capability import AgentRuntimeCapability
from azentspublicclient.models.agent_runtime_response import AgentRuntimeResponse
from azentspublicclient.models.agent_session_response import AgentSessionResponse
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.chat_event_page_response import ChatEventPageResponse
from azentspublicclient.models.chat_write_response import ChatWriteResponse
from azentspublicclient.models.create_invitation_request import (
    CreateInvitationRequest,
)
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.project_browser_manifest_response import (
    ProjectBrowserManifestResponse,
)
from azentspublicclient.models.secrets import Secrets
from testcontainers.core.container import DockerContainer

from support.observations import decode_history_page
from support.runtime_profiles import create_workspace_runtime_profile
from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    single_candidate_model_options,
    unique,
)


class _InvitedMember(NamedTuple):
    """Field-named result for ``_invite_member``."""

    access_token: str
    email: str


_RUNTIME_PROVIDER_ID = "system-docker"
_DETERMINISTIC_MODEL_MESSAGE = "Event durable hello"


@dataclass(frozen=True)
class _Workspace:
    """Product-created Workspace inputs for one Runtime journey."""

    token: str
    email: str
    handle: str
    model_selection: AgentModelSelectionInput
    runtime_profile_id: str | None


def _headers(token: str) -> dict[str, str]:
    """Return bearer authentication headers."""
    return {"Authorization": f"Bearer {token}"}


def _create_workspace(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
    with_runtime_profile: bool,
) -> _Workspace:
    """Create a Workspace and deterministic model integration through public APIs."""
    suffix = unique()
    token, _, email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"optional-runtime-{suffix}@example.com",
    )
    handle = f"optional-runtime-{suffix}"
    headers = _headers(token)
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Optional Runtime {suffix}",
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
            secrets=Secrets(ApiKeySecrets(api_key="sk-optional-runtime")),
        ),
        _headers=headers,
    )
    profile_id = (
        create_workspace_runtime_profile(
            public_api_client,
            token=token,
            workspace_handle=handle,
            provider_id=_RUNTIME_PROVIDER_ID,
        )
        if with_runtime_profile
        else None
    )
    return _Workspace(
        token=token,
        email=email,
        handle=handle,
        model_selection=model_selection_from_first_candidate(
            server_url,
            token,
            handle,
            integration.id,
        ),
        runtime_profile_id=profile_id,
    )


def _create_runtime_free_agent(
    *,
    public_api_client: azentspublicclient.ApiClient,
    workspace: _Workspace,
) -> str:
    """Create an Agent without granting managed Runtime capability."""
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace.handle,
        agent_create_request=AgentCreateRequest(
            name=f"Runtime-free Agent {unique()}",
            selectable_model_options=single_candidate_model_options(
                workspace.model_selection
            ),
            main_model_label="default",
            lightweight_model_label="default",
            type=AgentType.PUBLIC,
        ),
        _headers=_headers(workspace.token),
    )
    assert agent.runtime_capability == AgentRuntimeCapability.NONE
    assert agent.runtime_profile_id is None
    return agent.id


def _primary_session_id(
    *,
    server_url: str,
    token: str,
    agent_id: str,
) -> str:
    """Return the Agent's Team primary Session ID."""
    response = requests.get(
        f"{server_url}/chat/v1/agents/{agent_id}/team-primary-session",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()
    return AgentSessionResponse.model_validate(response.json()).id


def _write_session_message(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    message: str,
) -> str:
    """Write a model turn and return the canonical Session ID."""
    response = requests.post(
        f"{server_url}/chat/v1/sessions/{session_id}/inputs",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "agent_id": agent_id,
            "client_request_id": f"optional-runtime-message-{unique()}",
            "message": message,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    response.raise_for_status()
    return ChatWriteResponse.model_validate(response.json()).session_id


def _wait_for_assistant_message(
    *,
    server_url: str,
    token: str,
    session_id: str,
    timeout: float = 60,
) -> ChatEventPageResponse:
    """Wait for one durable assistant message in Session history."""
    deadline = time.monotonic() + timeout
    last_payload: ChatEventPageResponse | None = None
    while time.monotonic() < deadline:
        response = requests.get(
            f"{server_url}/chat/v1/sessions/{session_id}/history?limit=100",
            headers=_headers(token),
            timeout=10,
        )
        response.raise_for_status()
        payload = decode_history_page(response.json())
        last_payload = payload
        events = payload.items
        if any(event.kind == "assistant_message" for event in events):
            return payload
        time.sleep(0.5)
    raise AssertionError(f"Assistant response did not become durable: {last_payload!r}")


def _wait_runtime(
    *,
    runtime_api: AgentRuntimeV1Api,
    workspace: _Workspace,
    agent_id: str,
    predicate: Callable[[AgentRuntimeResponse], bool],
    message: str,
    timeout: float = 180,
) -> AgentRuntimeResponse:
    """Wait for a unified Runtime projection to satisfy a predicate."""
    deadline = time.monotonic() + timeout
    last_runtime: AgentRuntimeResponse | None = None
    while time.monotonic() < deadline:
        last_runtime = runtime_api.agent_runtime_v1_get_agent_runtime(
            agent_id=agent_id,
            handle=workspace.handle,
            _headers=_headers(workspace.token),
        )
        if predicate(last_runtime):
            return last_runtime
        time.sleep(1)
    raise AssertionError(f"{message}: {last_runtime!r}")


def _run_scheduler_task(
    container: DockerContainer,
    *,
    task_key: str,
) -> None:
    """Trigger and execute one scheduler pass inside the deployed server image."""
    script = f"""
import asyncio
from azents.app import run_with_container
from azents.core.config import Config
from azents.scheduler.service import SchedulerService

async def main():
    config = Config.from_env()
    async with run_with_container(config) as dependency_container:
        scheduler = await dependency_container.solve(SchedulerService)
        state = await scheduler.trigger({task_key!r})
        if state is None:
            raise RuntimeError('unknown scheduler task')
        await scheduler.run_once()

asyncio.run(main())
"""
    result = container.get_wrapped_container().exec_run(["python", "-c", script])
    exit_code = result.exit_code
    if exit_code != 0:
        raw_output = result.output
        if not isinstance(raw_output, bytes):
            raw_output = b"".join(raw_output)
        output = raw_output.decode(errors="replace")
        raise AssertionError(
            f"scheduler task {task_key} failed with exit {exit_code}:\n{output}"
        )


def _wait_runtime_with_scheduler(
    *,
    runtime_api: AgentRuntimeV1Api,
    workspace: _Workspace,
    agent_id: str,
    scheduler_container: DockerContainer,
    predicate: Callable[[AgentRuntimeResponse], bool],
    message: str,
    timeout: float = 180,
) -> AgentRuntimeResponse:
    """Run the removal coordinator while waiting for a Runtime projection."""
    deadline = time.monotonic() + timeout
    last_runtime: AgentRuntimeResponse | None = None
    while time.monotonic() < deadline:
        _run_scheduler_task(
            scheduler_container,
            task_key="agent_runtime_removal",
        )
        last_runtime = runtime_api.agent_runtime_v1_get_agent_runtime(
            agent_id=agent_id,
            handle=workspace.handle,
            _headers=_headers(workspace.token),
        )
        if predicate(last_runtime):
            return last_runtime
        time.sleep(1)
    raise AssertionError(f"{message}: {last_runtime!r}")


def _assert_manifest_unavailable(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> None:
    """Assert a retained Session cannot expose a Runtime-backed manifest."""
    response = requests.get(
        (
            f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}"
            "/workspace/project-browser-manifest"
        ),
        headers=_headers(token),
        timeout=10,
    )
    assert response.status_code == 400, response.text


def _create_team_session(
    *,
    server_url: str,
    token: str,
    agent_id: str,
) -> str:
    """Create a non-primary Team Session with empty Workspace intent."""
    response = requests.post(
        f"{server_url}/chat/v1/agents/{agent_id}/sessions",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={"existing_project_paths": [], "setup_actions": []},
        timeout=10,
    )
    response.raise_for_status()
    return AgentSessionResponse.model_validate(response.json()).id


def _prepare_session_folder(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> None:
    """Request explicit Session-folder preparation."""
    response = requests.post(
        (
            f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}"
            "/workspace/session-folder/prepare"
        ),
        headers={**_headers(token), "Content-Type": "application/json"},
        json={"client_request_id": f"optional-runtime-prepare-{unique()}"},
        timeout=10,
    )
    response.raise_for_status()


def _wait_for_manifest(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> ProjectBrowserManifestResponse:
    """Wait for a newly managed Session to bind to current Runner evidence."""
    path = (
        f"/chat/v1/agents/{agent_id}/sessions/{session_id}"
        "/workspace/project-browser-manifest"
    )
    deadline = time.monotonic() + 120
    last_response: requests.Response | None = None
    while time.monotonic() < deadline:
        response = requests.get(
            f"{server_url}{path}",
            headers=_headers(token),
            timeout=10,
        )
        last_response = response
        if response.ok:
            return ProjectBrowserManifestResponse.model_validate(response.json())
        if response.status_code != 400:
            response.raise_for_status()
        time.sleep(1)
    raise AssertionError(
        "Session manifest did not bind: "
        f"{last_response.status_code if last_response is not None else None} "
        f"{last_response.text if last_response is not None else None}"
    )


def _invite_member(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    workspace: _Workspace,
) -> _InvitedMember:
    """Invite a second user and return their token and email."""
    member_token, _, member_email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"optional-runtime-member-{unique()}@example.com",
    )
    invitation = InvitationV1Api(public_api_client).invitation_v1_create_invitation(
        workspace.handle,
        CreateInvitationRequest(email=member_email),
        _headers=_headers(workspace.token),
    )
    InvitationV1Api(public_api_client).invitation_v1_accept_invitation(
        invitation.id,
        _headers=_headers(member_token),
    )
    return _InvitedMember(
        access_token=member_token,
        email=member_email,
    )


def _create_user_session(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    message: str,
) -> str:
    """Create a private User Session through its first-message endpoint."""
    response = requests.post(
        f"{server_url}/chat/v1/agents/{agent_id}/user-sessions/messages",
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "client_request_id": f"optional-runtime-user-session-{unique()}",
            "message": message,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
            "existing_project_paths": [],
            "setup_actions": [],
        },
        timeout=10,
    )
    response.raise_for_status()
    return ChatWriteResponse.model_validate(response.json()).session_id


def _stop_runtime_provider(container: DockerContainer) -> None:
    """Stop the deterministic Provider without removing its container."""
    wrapped_container = container.get_wrapped_container()
    wrapped_container.stop(timeout=10)
    wrapped_container.reload()
    assert wrapped_container.status == "exited"


def _restart_runtime_provider(container: DockerContainer) -> None:
    """Restart the deterministic Provider and wait for a new registration."""
    marker = "Runtime Provider registered"
    stdout, stderr = container.get_logs()
    prior_registrations = (
        stdout.decode(errors="replace") + stderr.decode(errors="replace")
    ).count(marker)
    wrapped_container = container.get_wrapped_container()
    wrapped_container.start()

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        wrapped_container.reload()
        if wrapped_container.status == "exited":
            raise AssertionError("Runtime Provider exited while restarting")
        current_stdout, current_stderr = container.get_logs()
        registrations = (
            current_stdout.decode(errors="replace")
            + current_stderr.decode(errors="replace")
        ).count(marker)
        if registrations > prior_registrations:
            return
        time.sleep(1)
    raise AssertionError("Runtime Provider did not register after restart")


def test_runtime_free_model_turn_does_not_create_runtime(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: DockerContainer,
) -> None:
    """Model-only execution remains functional without logical or physical Runtime."""
    del azents_engine_worker_container
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=False,
    )
    agent_id = _create_runtime_free_agent(
        public_api_client=public_api_client,
        workspace=workspace,
    )
    runtime_api = AgentRuntimeV1Api(public_api_client)
    initial = runtime_api.agent_runtime_v1_get_agent_runtime(
        agent_id=agent_id,
        handle=workspace.handle,
        _headers=_headers(workspace.token),
    )
    assert initial.capability == AgentRuntimeCapability.NONE
    assert initial.runtime is None
    assert initial.lifecycle is None
    assert initial.configuration is None

    session_id = _primary_session_id(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent_id,
    )
    message = _DETERMINISTIC_MODEL_MESSAGE
    session_id = _write_session_message(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent_id,
        session_id=session_id,
        message=message,
    )
    history = _wait_for_assistant_message(
        server_url=azents_public_server_url,
        token=workspace.token,
        session_id=session_id,
    )
    assert message in str(history)

    after_turn = runtime_api.agent_runtime_v1_get_agent_runtime(
        agent_id=agent_id,
        handle=workspace.handle,
        _headers=_headers(workspace.token),
    )
    assert after_turn.capability == AgentRuntimeCapability.NONE
    assert after_turn.runtime is None
    assert after_turn.lifecycle is None
    assert after_turn.configuration is None
    _assert_manifest_unavailable(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent_id,
        session_id=session_id,
    )
