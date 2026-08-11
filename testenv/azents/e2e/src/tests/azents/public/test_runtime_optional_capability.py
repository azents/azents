"""Optional managed Runtime public API E2E journeys."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, cast

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.api.agent_runtime_v1_api import AgentRuntimeV1Api
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.invitation_v1_api import InvitationV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.add_agent_runtime_request import AddAgentRuntimeRequest
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_model_selection_input import (
    AgentModelSelectionInput,
)
from azentspublicclient.models.agent_runtime_capability import AgentRuntimeCapability
from azentspublicclient.models.agent_runtime_removal_stage import (
    AgentRuntimeRemovalStage,
)
from azentspublicclient.models.agent_runtime_removal_status import (
    AgentRuntimeRemovalStatus,
)
from azentspublicclient.models.agent_runtime_response import AgentRuntimeResponse
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_invitation_request import (
    CreateInvitationRequest,
)
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.remove_agent_runtime_request import (
    RemoveAgentRuntimeRequest,
)
from azentspublicclient.models.runtime_desired_state import RuntimeDesiredState
from azentspublicclient.models.runtime_summary import RuntimeSummary
from azentspublicclient.models.secrets import Secrets
from pydantic import TypeAdapter, ValidationError
from testcontainers.core.container import DockerContainer

from support.runtime_profiles import create_workspace_runtime_profile
from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    unique,
)

_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])
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


def _response_object(response: requests.Response, *, label: str) -> dict[str, object]:
    """Validate a JSON object response."""
    try:
        return _JSON_OBJECT.validate_json(response.text)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object: {response.text!r}") from exc


def _object_items(raw_items: object, *, label: str) -> list[dict[str, object]]:
    """Validate a JSON object list."""
    try:
        return _JSON_OBJECT_LIST.validate_python(raw_items)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object list: {raw_items!r}") from exc


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
            model_selection=workspace.model_selection,
            lightweight_model_selection=workspace.model_selection,
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
    session_id = _response_object(
        response,
        label="Team primary session response",
    ).get("id")
    if not isinstance(session_id, str):
        raise AssertionError(
            f"Team primary session response did not include id: {response.text!r}"
        )
    return session_id


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
            },
        },
        timeout=10,
    )
    response.raise_for_status()
    observed_session_id = _response_object(
        response,
        label="Session input response",
    ).get("session_id")
    if not isinstance(observed_session_id, str):
        raise AssertionError(f"Session input response omitted id: {response.text!r}")
    return observed_session_id


def _wait_for_assistant_message(
    *,
    server_url: str,
    token: str,
    session_id: str,
    timeout: float = 60,
) -> dict[str, object]:
    """Wait for one durable assistant message in Session history."""
    deadline = time.monotonic() + timeout
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        response = requests.get(
            f"{server_url}/chat/v1/sessions/{session_id}/history?limit=100",
            headers=_headers(token),
            timeout=10,
        )
        response.raise_for_status()
        payload = _response_object(response, label="Session history response")
        last_payload = payload
        events = _object_items(payload.get("items"), label="Session history items")
        if any(event.get("kind") == "assistant_message" for event in events):
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
    exit_code = cast(Any, result).exit_code
    if exit_code != 0:
        output = cast(Any, result).output.decode(errors="replace")
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
    session_id = _response_object(response, label="Create Session response").get("id")
    if not isinstance(session_id, str):
        raise AssertionError(f"Create Session response omitted id: {response.text!r}")
    return session_id


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
) -> dict[str, object]:
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
            return _response_object(response, label="Project browser manifest")
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
) -> tuple[str, str]:
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
    return member_token, member_email


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
            },
            "existing_project_paths": [],
            "setup_actions": [],
        },
        timeout=10,
    )
    response.raise_for_status()
    session_id = _response_object(response, label="User Session response").get(
        "session_id"
    )
    if not isinstance(session_id, str):
        raise AssertionError(f"User Session response omitted id: {response.text!r}")
    return session_id


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
    assert initial.state is None
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
    assert after_turn.state is None
    assert after_turn.configuration is None
    _assert_manifest_unavailable(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent_id,
        session_id=session_id,
    )


@pytest.mark.runtime_provider
def test_add_remove_reconnect_and_readd_preserve_privacy_and_binding_fences(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_container: DockerContainer,
    azents_runtime_provider_docker_container: DockerContainer,
    azents_engine_worker_container: DockerContainer,
) -> None:
    """Exercise explicit add, irreversible removal, reconnect, and clean re-add."""
    del azents_engine_worker_container
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=True,
    )
    assert workspace.runtime_profile_id is not None
    agent_id = _create_runtime_free_agent(
        public_api_client=public_api_client,
        workspace=workspace,
    )
    old_runtime_free_session_id = _primary_session_id(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent_id,
    )
    runtime_api = AgentRuntimeV1Api(public_api_client)
    runtime_free = runtime_api.agent_runtime_v1_get_agent_runtime(
        agent_id=agent_id,
        handle=workspace.handle,
        _headers=_headers(workspace.token),
    )
    add_request = AddAgentRuntimeRequest(
        workspace_runtime_profile_id=workspace.runtime_profile_id,
        expected_capability_version=runtime_free.capability_version,
        expected_runtime_profile_selection_version=(
            runtime_free.runtime_profile_selection_version
        ),
        idempotency_key=f"optional-runtime-add-{unique()}",
    )
    added = runtime_api.agent_runtime_v1_add_agent_runtime(
        agent_id=agent_id,
        handle=workspace.handle,
        add_agent_runtime_request=add_request,
        _headers=_headers(workspace.token),
    )
    replayed_add = runtime_api.agent_runtime_v1_add_agent_runtime(
        agent_id=agent_id,
        handle=workspace.handle,
        add_agent_runtime_request=add_request,
        _headers=_headers(workspace.token),
    )
    assert added.replayed is False
    assert replayed_add.replayed is True
    assert added.runtime.capability == AgentRuntimeCapability.MANAGED
    assert added.runtime.runtime is not None
    assert added.runtime.runtime.desired_state == RuntimeDesiredState.STOPPED
    assert added.runtime.runtime.workspace_path is None
    logical_runtime_id = added.runtime.runtime.id
    initial_generation = added.runtime.runtime.desired_generation

    runtime_api.agent_runtime_v1_start_agent_runtime(
        agent_id=agent_id,
        handle=workspace.handle,
        _headers=_headers(workspace.token),
    )
    running = _wait_runtime(
        runtime_api=runtime_api,
        workspace=workspace,
        agent_id=agent_id,
        predicate=lambda value: (
            value.state is not None
            and value.state.summary == RuntimeSummary.RUNNING
            and value.state.actions.use_runner
            and value.runtime is not None
            and value.runtime.workspace_path is not None
        ),
        message="Added Runtime did not become Runner-ready",
    )
    assert running.runtime is not None
    workspace_path = running.runtime.workspace_path
    assert workspace_path is not None

    _assert_manifest_unavailable(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent_id,
        session_id=old_runtime_free_session_id,
    )
    managed_session_id = _create_team_session(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent_id,
    )
    _prepare_session_folder(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent_id,
        session_id=managed_session_id,
    )
    manifest = _wait_for_manifest(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent_id,
        session_id=managed_session_id,
    )
    assert workspace_path in str(manifest)

    member_token, member_email = _invite_member(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        workspace=workspace,
    )
    private_message = _DETERMINISTIC_MODEL_MESSAGE
    private_session_id = _create_user_session(
        server_url=azents_public_server_url,
        token=member_token,
        agent_id=agent_id,
        message=private_message,
    )
    _wait_for_assistant_message(
        server_url=azents_public_server_url,
        token=member_token,
        session_id=private_session_id,
    )

    before_remove = runtime_api.agent_runtime_v1_get_agent_runtime(
        agent_id=agent_id,
        handle=workspace.handle,
        _headers=_headers(workspace.token),
    )
    assert before_remove.removal_impact is not None
    public_projection = str(before_remove.to_dict())
    assert private_message not in public_projection
    assert private_session_id not in public_projection
    assert member_email not in public_projection

    runtime_api.agent_runtime_v1_stop_agent_runtime(
        agent_id=agent_id,
        handle=workspace.handle,
        _headers=_headers(workspace.token),
    )
    stopped = _wait_runtime(
        runtime_api=runtime_api,
        workspace=workspace,
        agent_id=agent_id,
        predicate=lambda value: (
            value.state is not None
            and value.state.summary == RuntimeSummary.STOPPED
            and value.runtime is not None
            and value.runtime.workspace_path is None
        ),
        message="Temporary stop did not disconnect the Runtime Runner",
    )
    assert stopped.runtime is not None
    assert stopped.runtime.id == logical_runtime_id

    runtime_api.agent_runtime_v1_start_agent_runtime(
        agent_id=agent_id,
        handle=workspace.handle,
        _headers=_headers(workspace.token),
    )
    restored = _wait_runtime(
        runtime_api=runtime_api,
        workspace=workspace,
        agent_id=agent_id,
        predicate=lambda value: (
            value.state is not None
            and value.state.summary == RuntimeSummary.RUNNING
            and value.state.actions.use_runner
            and value.runtime is not None
            and value.runtime.workspace_path == workspace_path
        ),
        message="Temporary stop did not preserve the Runtime Workspace",
    )
    assert restored.runtime is not None
    restored_generation = restored.runtime.desired_generation
    restored_manifest = _wait_for_manifest(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent_id,
        session_id=managed_session_id,
    )
    assert workspace_path in str(restored_manifest)

    runtime_api.agent_runtime_v1_stop_agent_runtime(
        agent_id=agent_id,
        handle=workspace.handle,
        _headers=_headers(workspace.token),
    )
    stopped = _wait_runtime(
        runtime_api=runtime_api,
        workspace=workspace,
        agent_id=agent_id,
        predicate=lambda value: (
            value.state is not None
            and value.state.summary == RuntimeSummary.STOPPED
            and value.runtime is not None
            and value.runtime.id == logical_runtime_id
            and value.runtime.desired_generation > restored_generation
        ),
        message="Runtime did not stop before permanent removal",
    )
    assert stopped.actions.remove is True

    provider_stopped = False
    try:
        _stop_runtime_provider(azents_runtime_provider_docker_container)
        provider_stopped = True
        remove_request = RemoveAgentRuntimeRequest(
            expected_capability_version=stopped.capability_version,
            expected_runtime_profile_selection_version=(
                stopped.runtime_profile_selection_version
            ),
            idempotency_key=f"optional-runtime-remove-{unique()}",
            confirmed=True,
        )
        removed = runtime_api.agent_runtime_v1_remove_agent_runtime(
            agent_id=agent_id,
            handle=workspace.handle,
            remove_agent_runtime_request=remove_request,
            _headers=_headers(workspace.token),
        )
        replayed_remove = runtime_api.agent_runtime_v1_remove_agent_runtime(
            agent_id=agent_id,
            handle=workspace.handle,
            remove_agent_runtime_request=remove_request,
            _headers=_headers(workspace.token),
        )
        assert removed.replayed is False
        assert replayed_remove.replayed is True
        assert removed.runtime.capability == AgentRuntimeCapability.REMOVING

        pending_delete = _wait_runtime_with_scheduler(
            runtime_api=runtime_api,
            workspace=workspace,
            agent_id=agent_id,
            scheduler_container=azents_admin_server_container,
            predicate=lambda value: (
                value.capability == AgentRuntimeCapability.REMOVING
                and value.removal is not None
                and value.removal.stage == AgentRuntimeRemovalStage.DELETING_RUNTIME
                and value.removal.physical_delete_requested_at is not None
                and value.removal.physical_delete_acknowledged_at is None
            ),
            message="Removal did not remain pending on disconnected Provider deletion",
        )
        assert pending_delete.removal is not None
        assert pending_delete.removal.status in {
            AgentRuntimeRemovalStatus.RUNNING,
            AgentRuntimeRemovalStatus.RETRY_WAIT,
        }
        pending_projection = str(pending_delete.to_dict())
        assert private_message not in pending_projection
        assert private_session_id not in pending_projection
        assert member_email not in pending_projection

        denied = requests.post(
            f"{azents_public_server_url}/chat/v1/sessions/{private_session_id}/inputs",
            headers={**_headers(member_token), "Content-Type": "application/json"},
            json={
                "agent_id": agent_id,
                "client_request_id": f"removing-denied-{unique()}",
                "message": "This write must remain fenced.",
                "inference_profile": {
                    "model_target_label": "default",
                    "reasoning_effort": None,
                },
            },
            timeout=10,
        )
        assert denied.status_code == 409, denied.text

        _restart_runtime_provider(azents_runtime_provider_docker_container)
        provider_stopped = False
    finally:
        if provider_stopped:
            _restart_runtime_provider(azents_runtime_provider_docker_container)

    completed = _wait_runtime_with_scheduler(
        runtime_api=runtime_api,
        workspace=workspace,
        agent_id=agent_id,
        scheduler_container=azents_admin_server_container,
        predicate=lambda value: (
            value.capability == AgentRuntimeCapability.NONE
            and value.removal is not None
            and value.removal.status == AgentRuntimeRemovalStatus.COMPLETED
            and value.removal.stage == AgentRuntimeRemovalStage.COMPLETED
            and value.removal.physical_delete_acknowledged_at is not None
        ),
        message="Removal did not converge after Provider reconnect",
    )
    assert completed.removal is not None
    assert completed.removal.cleanup_scanned_context_count >= 3
    assert completed.removal.cleanup_invalidated_context_count >= 2
    assert completed.runtime is not None
    assert completed.runtime.id == logical_runtime_id
    removed_generation = completed.runtime.desired_generation
    assert removed_generation >= initial_generation

    _assert_manifest_unavailable(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent_id,
        session_id=managed_session_id,
    )
    readded = runtime_api.agent_runtime_v1_add_agent_runtime(
        agent_id=agent_id,
        handle=workspace.handle,
        add_agent_runtime_request=AddAgentRuntimeRequest(
            workspace_runtime_profile_id=workspace.runtime_profile_id,
            expected_capability_version=completed.capability_version,
            expected_runtime_profile_selection_version=(
                completed.runtime_profile_selection_version
            ),
            idempotency_key=f"optional-runtime-readd-{unique()}",
        ),
        _headers=_headers(workspace.token),
    )
    assert readded.runtime.capability == AgentRuntimeCapability.MANAGED
    assert readded.runtime.runtime is not None
    assert readded.runtime.runtime.id == logical_runtime_id
    readded_generation = readded.runtime.runtime.desired_generation
    assert readded_generation > removed_generation
    assert readded.runtime.runtime.workspace_path is None

    runtime_api.agent_runtime_v1_start_agent_runtime(
        agent_id=agent_id,
        handle=workspace.handle,
        _headers=_headers(workspace.token),
    )
    _wait_runtime(
        runtime_api=runtime_api,
        workspace=workspace,
        agent_id=agent_id,
        predicate=lambda value: (
            value.state is not None
            and value.state.summary == RuntimeSummary.RUNNING
            and value.state.actions.use_runner
            and value.runtime is not None
            and value.runtime.desired_generation > readded_generation
        ),
        message="Re-added Runtime did not become Runner-ready",
    )
    _assert_manifest_unavailable(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent_id,
        session_id=old_runtime_free_session_id,
    )
    _assert_manifest_unavailable(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent_id,
        session_id=managed_session_id,
    )
    new_session_id = _create_team_session(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent_id,
    )
    _prepare_session_folder(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent_id,
        session_id=new_session_id,
    )
    new_manifest = _wait_for_manifest(
        server_url=azents_public_server_url,
        token=workspace.token,
        agent_id=agent_id,
        session_id=new_session_id,
    )
    assert "session_folder" in str(new_manifest)
