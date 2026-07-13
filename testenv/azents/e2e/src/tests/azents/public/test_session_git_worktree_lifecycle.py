"""Session Git worktree lifecycle E2E tests."""

import shlex
import time
from pathlib import PurePosixPath
from typing import Any, cast

import azentsadminclient
import azentspublicclient
import docker as docker_py
import pytest
import requests
from azentspublicclient.api.agent_runtime_v1_api import AgentRuntimeV1Api
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from docker.models.containers import Container
from pydantic import TypeAdapter, ValidationError

from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    unique,
)

pytestmark = [
    pytest.mark.runtime_provider,
    pytest.mark.usefixtures("azents_runtime_provider_docker_container"),
]

_RUNTIME_PROVIDER_ID = "system-docker"
_OBJECT_ADAPTER: TypeAdapter[dict[str, object]] = TypeAdapter(dict[str, object])
_OBJECT_LIST_ADAPTER: TypeAdapter[list[dict[str, object]]] = TypeAdapter(
    list[dict[str, object]]
)


def _headers(token: str) -> dict[str, str]:
    """Return bearer auth headers."""
    return {"Authorization": f"Bearer {token}"}


def _api_host(public_api_client: azentspublicclient.ApiClient) -> str:
    """Return generated public API host string."""
    configuration = cast(Any, public_api_client).configuration
    return str(configuration.host)


def _response_object(response: requests.Response, *, label: str) -> dict[str, object]:
    """Validate a JSON object response."""
    try:
        return _OBJECT_ADAPTER.validate_json(response.text)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object: {response.text!r}") from exc


def _object_list(value: object, *, label: str) -> list[dict[str, object]]:
    """Validate a JSON object list."""
    try:
        return _OBJECT_LIST_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise AssertionError(f"{label} is not an object list: {value!r}") from exc


def _get_json(
    *,
    server_url: str,
    token: str,
    path: str,
    params: dict[str, str] | None = None,
) -> dict[str, object]:
    """Call a public GET endpoint and return a JSON object."""
    response = requests.get(
        f"{server_url}{path}",
        headers=_headers(token),
        params=params,
        timeout=10,
    )
    response.raise_for_status()
    return _response_object(response, label=f"GET {path} response")


def _post_json(
    *,
    server_url: str,
    token: str,
    path: str,
    payload: dict[str, object],
) -> dict[str, object]:
    """Call a public POST endpoint and return a JSON object."""
    response = requests.post(
        f"{server_url}{path}",
        headers={**_headers(token), "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return _response_object(response, label=f"POST {path} response")


def _post_empty(*, server_url: str, token: str, path: str) -> None:
    """Call a public POST endpoint with no response body."""
    response = requests.post(
        f"{server_url}{path}",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()


def _create_runtime_agent(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> tuple[str, str, str]:
    """Create a workspace and Runtime-backed Agent for worktree tests."""
    uniq = unique()
    token, _, _ = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"session-worktree-{uniq}@example.com",
    )

    workspace_handle = f"session-worktree-{uniq}"
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Session Worktree {uniq}",
            workspace_handle=workspace_handle,
            owner_name=f"Owner {uniq}",
        ),
        _headers=_headers(token),
    )

    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=workspace_handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-session-worktree-qa")),
        ),
        _headers=_headers(token),
    )
    model_selection = model_selection_from_first_candidate(
        _api_host(public_api_client),
        token,
        workspace_handle,
        integration.id,
    )

    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace_handle,
        agent_create_request=AgentCreateRequest(
            name=f"Session Worktree Agent {uniq}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
            runtime_provider_id=_RUNTIME_PROVIDER_ID,
            shell_enabled=True,
        ),
        _headers=_headers(token),
    )
    return token, workspace_handle, agent.id


def _wait_for_runtime_runner_ready(
    public_api_client: azentspublicclient.ApiClient,
    *,
    token: str,
    workspace_handle: str,
    agent_id: str,
) -> None:
    """Start and wait for a usable Runtime Runner."""
    api = AgentRuntimeV1Api(public_api_client)
    headers = _headers(token)
    api.agent_runtime_v1_start_agent_runtime(
        agent_id=agent_id,
        handle=workspace_handle,
        _headers=headers,
    )
    deadline = time.monotonic() + 120
    last_state: object | None = None
    while time.monotonic() < deadline:
        state = api.agent_runtime_v1_observe_agent_runtime(
            agent_id=agent_id,
            handle=workspace_handle,
            _headers=headers,
        )
        last_state = state
        if state.state.actions.use_runner:
            return
        time.sleep(1)
    raise AssertionError(f"runtime runner did not become ready: {last_state!r}")


def _runtime_container(agent_id: str) -> Container:
    """Return the Runtime container for an Agent."""
    client = docker_py.from_env()
    containers = client.containers.list(
        all=True,
        filters={"label": f"azents/agent-id={agent_id}"},
    )
    if len(containers) != 1:
        names = [container.name for container in containers]
        client.close()
        raise AssertionError(
            f"expected one runtime container for agent {agent_id}, found {names!r}"
        )
    return containers[0]


def _exec(container: Container, command: str) -> str:
    """Run a shell command in the Runtime container."""
    result = container.exec_run(["sh", "-lc", command])
    output = result.output.decode(errors="replace")
    if result.exit_code != 0:
        raise AssertionError(
            f"runtime command failed with exit {result.exit_code}: {command}\n{output}"
        )
    return output


def _create_source_repo(container: Container, *, name: str) -> str:
    """Create a deterministic Git repository inside the Runtime workspace."""
    source_path = f"/workspace/agent/{name}"
    quoted = shlex.quote(source_path)
    _exec(
        container,
        "\n".join(
            [
                "set -eu",
                f"mkdir -p {quoted}",
                f"cd {quoted}",
                "git init -b main",
                "git config user.email e2e@example.com",
                "git config user.name 'Azents E2E'",
                "printf 'session worktree e2e\\n' > README.md",
                "git add README.md",
                "git commit -m 'initial commit'",
                "git branch feature/e2e",
                "git tag e2e-v1",
            ]
        ),
    )
    return source_path


def _create_git_worktree_session(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    source_project_path: str,
    starting_ref: str,
) -> str:
    """Create a non-primary session with an ordered Git worktree action."""
    payload = _post_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/agents/{agent_id}/sessions",
        payload={
            "existing_project_paths": [],
            "setup_actions": [
                {
                    "type": "create_git_worktree",
                    "source_project_path": source_project_path,
                    "starting_ref": starting_ref,
                }
            ],
        },
    )
    session_id = payload.get("id")
    if not isinstance(session_id, str):
        raise AssertionError(f"Create session response did not include id: {payload!r}")
    return session_id


def _action_execution_status(projection: dict[str, object]) -> str:
    """Return an action execution status from a projection."""
    execution = _OBJECT_ADAPTER.validate_python(projection.get("execution"))
    status = execution.get("status")
    if not isinstance(status, str):
        raise AssertionError(f"action execution status is missing: {projection!r}")
    return status


def _action_execution_id(projection: dict[str, object]) -> str:
    """Return an action execution ID from a projection."""
    execution = _OBJECT_ADAPTER.validate_python(projection.get("execution"))
    execution_id = execution.get("id")
    if not isinstance(execution_id, str):
        raise AssertionError(f"action execution id is missing: {projection!r}")
    return execution_id


def _terminal_action_execution_projection(
    history: dict[str, object],
) -> dict[str, object] | None:
    """Return the latest durable action execution result projection."""
    events = _object_list(history.get("items"), label="history events")
    for event in reversed(events):
        if event.get("kind") != "action_execution_result":
            continue
        payload = _OBJECT_ADAPTER.validate_python(event.get("payload"))
        projection = payload.get("action_execution")
        if projection is None:
            raise AssertionError(f"action result projection is missing: {event!r}")
        return _OBJECT_ADAPTER.validate_python(projection)
    return None


def _wait_for_action_execution_status(
    *,
    server_url: str,
    token: str,
    session_id: str,
    status: str,
) -> dict[str, object]:
    """Wait for the session action execution to reach a status."""
    deadline = time.monotonic() + 90
    last_history: dict[str, object] | None = None
    while time.monotonic() < deadline:
        history = _get_json(
            server_url=server_url,
            token=token,
            path=f"/chat/v1/sessions/{session_id}/history",
            params={"limit": "100"},
        )
        last_history = history
        projection = _terminal_action_execution_projection(history)
        if projection is None:
            time.sleep(0.5)
            continue
        current_status = _action_execution_status(projection)
        if current_status == status:
            return projection
        if current_status == "failed" and status != "failed":
            raise AssertionError(f"action execution failed: {projection!r}")
        time.sleep(0.5)
    raise TimeoutError(f"action execution did not reach {status}: {last_history!r}")


def _assert_action_retry_controls_removed(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    action_execution_id: str,
) -> None:
    """Verify deprecated action retry and discard routes are unavailable."""
    base_path = (
        f"{server_url}/chat/v1/agents/{agent_id}/sessions/{session_id}"
        f"/action-executions/{action_execution_id}"
    )
    for operation in ("retry", "discard"):
        response = requests.post(
            f"{base_path}/{operation}",
            headers=_headers(token),
            timeout=10,
        )
        assert response.status_code in {404, 405}


def _list_session_projects(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> list[dict[str, object]]:
    """List registered Projects for a session."""
    response = _get_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/agents/{agent_id}/sessions/{session_id}/projects",
    )
    return _object_list(response.get("items"), label="session projects")


def _wait_for_worktree_project_path(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> str:
    """Wait for action-created worktree Project registration."""
    deadline = time.monotonic() + 60
    last_projects: list[dict[str, object]] | None = None
    while time.monotonic() < deadline:
        projects = _list_session_projects(
            server_url=server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
        )
        last_projects = projects
        if len(projects) == 1:
            path = projects[0].get("path")
            if isinstance(path, str):
                return path
        time.sleep(0.5)
    raise TimeoutError(f"worktree Project was not registered: {last_projects!r}")


def _branch_name_from_worktree_path(worktree_path: str) -> str:
    """Return the default Azents branch name for a worktree path."""
    path = PurePosixPath(worktree_path)
    session_handle = path.parent.name
    return f"azents/{session_handle}"


def _assert_path_absent(container: Container, path: str) -> None:
    """Assert a Runtime path is absent."""
    _exec(container, f"test ! -e {shlex.quote(path)}")


def _assert_branch_absent(
    container: Container,
    *,
    source_path: str,
    branch_name: str,
) -> None:
    """Assert a branch is absent from the source repository."""
    _exec(
        container,
        f"cd {shlex.quote(source_path)} && "
        f'test -z "$(git branch --list {shlex.quote(branch_name)})"',
    )


class TestSessionGitWorktreeLifecycle:
    """Session Git worktree product behavior."""

    def test_git_ref_preview_worktree_creation_and_dirty_archive_cleanup(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """A Runtime-backed session creates and cleans an owned dirty worktree."""
        del azents_engine_worker_container
        token, workspace_handle, agent_id = _create_runtime_agent(
            public_api_client=public_api_client,
            admin_api_client=admin_api_client,
        )
        _wait_for_runtime_runner_ready(
            public_api_client,
            token=token,
            workspace_handle=workspace_handle,
            agent_id=agent_id,
        )
        container = _runtime_container(agent_id)
        source_path = _create_source_repo(container, name=f"source-{unique()}")

        preview = _get_json(
            server_url=azents_public_server_url,
            token=token,
            path=f"/chat/v1/agents/{agent_id}/git-refs",
            params={"source_project_path": source_path},
        )
        refs = _object_list(preview.get("refs"), label="Git refs")
        assert preview.get("default_branch") == "main"
        assert {ref.get("name") for ref in refs} >= {"main", "feature/e2e", "e2e-v1"}

        session_id = _create_git_worktree_session(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            source_project_path=source_path,
            starting_ref="main",
        )
        projection = _wait_for_action_execution_status(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            status="completed",
        )
        action_execution_id = _action_execution_id(projection)
        _assert_action_retry_controls_removed(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            action_execution_id=action_execution_id,
        )
        events = _object_list(projection.get("events"), label="action events")
        assert {event.get("step_key") for event in events} >= {
            "create_git_worktree",
            "register_project",
            "upsert_catalog",
            "refresh_project_status",
        }

        failed_session_id = _create_git_worktree_session(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            source_project_path=source_path,
            starting_ref="missing-e2e-ref",
        )
        failed_projection = _wait_for_action_execution_status(
            server_url=azents_public_server_url,
            token=token,
            session_id=failed_session_id,
            status="failed",
        )
        failed_execution_id = _action_execution_id(failed_projection)
        failed_execution = _OBJECT_ADAPTER.validate_python(
            failed_projection.get("execution")
        )
        assert failed_execution.get("failure_summary")
        assert (
            _list_session_projects(
                server_url=azents_public_server_url,
                token=token,
                agent_id=agent_id,
                session_id=failed_session_id,
            )
            == []
        )
        _assert_action_retry_controls_removed(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=failed_session_id,
            action_execution_id=failed_execution_id,
        )

        worktree_path = _wait_for_worktree_project_path(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
        )
        branch_name = _branch_name_from_worktree_path(worktree_path)
        _exec(
            container,
            f"test -f {shlex.quote(worktree_path)}/README.md && "
            f"cd {shlex.quote(worktree_path)} && "
            f'test "$(git rev-parse HEAD)" = '
            f'"$(git -C {shlex.quote(source_path)} rev-parse main)"',
        )

        _exec(
            container,
            f"printf 'dirty cleanup e2e\\n' > {shlex.quote(worktree_path)}/dirty.txt",
        )
        _post_empty(
            server_url=azents_public_server_url,
            token=token,
            path=f"/chat/v1/agents/{agent_id}/sessions/{session_id}/archive",
        )

        deadline = time.monotonic() + 60
        last_error: AssertionError | None = None
        while time.monotonic() < deadline:
            try:
                _assert_path_absent(container, worktree_path)
                _assert_branch_absent(
                    container,
                    source_path=source_path,
                    branch_name=branch_name,
                )
                return
            except AssertionError as exc:
                last_error = exc
                time.sleep(0.5)
        raise AssertionError("worktree cleanup did not finish") from last_error
