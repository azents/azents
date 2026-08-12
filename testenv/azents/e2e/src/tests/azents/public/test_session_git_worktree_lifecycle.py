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
from azentsadminclient.api.system_v1_api import SystemV1Api
from azentsadminclient.models.file_lifecycle_settings_update_request import (
    FileLifecycleSettingsUpdateRequest,
)
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

from support.runtime_profiles import create_workspace_runtime_profile
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
    runtime_profile_id = create_workspace_runtime_profile(
        public_api_client,
        token=token,
        workspace_handle=workspace_handle,
        provider_id=_RUNTIME_PROVIDER_ID,
    )

    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace_handle,
        agent_create_request=AgentCreateRequest(
            name=f"Session Worktree Agent {uniq}",
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
            type=AgentType.PUBLIC,
            runtime_profile_id=runtime_profile_id,
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
        if state.state is not None and state.state.actions.use_runner:
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


def _create_agent_worktree_source_repo(container: Container, *, name: str) -> str:
    """Create a source whose target ref alone contains one filesystem Skill."""
    source_path = _create_source_repo(container, name=name)
    quoted = shlex.quote(source_path)
    _exec(
        container,
        "\n".join(
            [
                "set -eu",
                f"cd {quoted}",
                "git switch -c worktree-e2e-target",
                "mkdir -p .claude/skills/worktree-e2e",
                (
                    "cat > .claude/skills/worktree-e2e/SKILL.md <<'EOF'\n"
                    "---\n"
                    "name: worktree-e2e\n"
                    "description: Verify target-only dynamic worktree Skill adoption.\n"
                    "---\n\n"
                    "# Dynamic Worktree E2E Skill\n\n"
                    "This Skill is available only from the generated worktree ref.\n"
                    "EOF"
                ),
                "git add .claude/skills/worktree-e2e/SKILL.md",
                "git commit -m 'add target-only worktree skill'",
                "git switch main",
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


def _live_projection(
    *,
    server_url: str,
    token: str,
    session_id: str,
) -> dict[str, object]:
    """Fetch the current live projection for a session."""
    return _get_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/sessions/{session_id}/live",
    )


def _assert_no_live_action_executions(
    *,
    server_url: str,
    token: str,
    session_id: str,
) -> None:
    """Wait until terminal action handoff leaves the Session idle."""
    deadline = time.monotonic() + 30
    last_live: dict[str, object] | None = None
    while time.monotonic() < deadline:
        live = _live_projection(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        last_live = live
        if (
            live.get("action_executions") == []
            and live.get("session_run_state") == "idle"
        ):
            return
        time.sleep(0.5)
    raise AssertionError(
        f"terminal action handoff did not leave the Session idle: {last_live!r}"
    )


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
    *,
    action_type: str,
    client_tool_call_id: str | None = None,
) -> dict[str, object] | None:
    """Return the latest durable result projection for one action type."""
    events = _object_list(history.get("items"), label="history events")
    for event in reversed(events):
        if event.get("kind") != "action_execution_result":
            continue
        payload = _OBJECT_ADAPTER.validate_python(event.get("payload"))
        projection = payload.get("action_execution")
        if projection is None:
            raise AssertionError(f"action result projection is missing: {event!r}")
        action_projection = _OBJECT_ADAPTER.validate_python(projection)
        execution = _OBJECT_ADAPTER.validate_python(action_projection.get("execution"))
        if execution.get("action_type") != action_type:
            continue
        if client_tool_call_id is not None:
            action = _OBJECT_ADAPTER.validate_python(execution.get("action"))
            if action.get("client_tool_call_id") != client_tool_call_id:
                continue
        return action_projection
    return None


def _wait_for_action_execution_status(
    *,
    server_url: str,
    token: str,
    session_id: str,
    status: str,
    action_type: str,
    client_tool_call_id: str | None = None,
) -> dict[str, object]:
    """Wait for one session action execution to reach a status."""
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
        projection = _terminal_action_execution_projection(
            history,
            action_type=action_type,
            client_tool_call_id=client_tool_call_id,
        )
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


def _wait_for_generated_worktree_project_path(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    source_project_path: str,
) -> str:
    """Wait for one generated Project in addition to the source Project."""
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
        generated_paths = [
            path
            for project in projects
            if isinstance(path := project.get("path"), str)
            and path != source_project_path
        ]
        if len(generated_paths) == 1:
            return generated_paths[0]
        time.sleep(0.5)
    raise TimeoutError(
        f"generated worktree Project was not registered: {last_projects!r}"
    )


def _run_message(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
    message: str,
) -> None:
    """Submit one public chat input."""
    _post_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/sessions/{session_id}/inputs",
        payload={
            "agent_id": agent_id,
            "client_request_id": f"dynamic-worktree-e2e-{unique()}",
            "message": message,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
            },
        },
    )


def _wait_for_history_content(
    *,
    server_url: str,
    token: str,
    session_id: str,
    content: str,
    minimum_distinct_turn_runs: int = 0,
) -> dict[str, object]:
    """Wait for exact content and the required distinct model-turn Runs."""
    deadline = time.monotonic() + 120
    last_history: dict[str, object] | None = None
    while time.monotonic() < deadline:
        history = _get_json(
            server_url=server_url,
            token=token,
            path=f"/chat/v1/sessions/{session_id}/history",
            params={"limit": "100"},
        )
        last_history = history
        events = _object_list(history.get("items"), label="history events")
        content_present = any(
            _OBJECT_ADAPTER.validate_python(event.get("payload")).get("content")
            == content
            for event in events
            if event.get("kind") == "assistant_message"
        )
        turn_run_ids = {
            run_id
            for event in events
            if event.get("kind") == "turn_marker"
            and isinstance(
                run_id := _OBJECT_ADAPTER.validate_python(event.get("payload")).get(
                    "run_id"
                ),
                str,
            )
        }
        if content_present and len(turn_run_ids) >= minimum_distinct_turn_runs:
            return history
        time.sleep(0.5)
    raise TimeoutError(
        f"history content was not observed: {content!r}, {last_history!r}"
    )


def _turn_run_ids(history: dict[str, object]) -> list[str]:
    """Return model-turn Run IDs in durable history order."""
    run_ids: list[str] = []
    for event in _object_list(history.get("items"), label="history events"):
        if event.get("kind") != "turn_marker":
            continue
        payload = _OBJECT_ADAPTER.validate_python(event.get("payload"))
        run_id = payload.get("run_id")
        if isinstance(run_id, str):
            run_ids.append(run_id)
    return run_ids


def _tool_call_names(history: dict[str, object]) -> list[str]:
    """Return model-visible tool names from durable history."""
    names: list[str] = []
    for event in _object_list(history.get("items"), label="history events"):
        if event.get("kind") != "client_tool_call":
            continue
        payload = _OBJECT_ADAPTER.validate_python(event.get("payload"))
        name = payload.get("name")
        if isinstance(name, str):
            names.append(name)
    return names


def _assert_branch_present(
    container: Container,
    *,
    source_path: str,
    branch_name: str,
) -> None:
    """Assert a branch remains in the source repository."""
    _exec(
        container,
        f"cd {shlex.quote(source_path)} && "
        f'test -n "$(git branch --list {shlex.quote(branch_name)})"',
    )


def _branch_name_from_worktree_path(worktree_path: str) -> str:
    """Return the default Azents branch name for a worktree path."""
    path = PurePosixPath(worktree_path)
    if path.parent.name == "worktrees" and path.parent.parent.parent.name == "sessions":
        session_handle = path.parent.parent.name
    else:
        session_handle = path.parent.name
    return f"azents/{session_handle}"


def _assert_path_present(container: Container, path: str) -> None:
    """Assert a Runtime path remains present."""
    _exec(container, f"test -e {shlex.quote(path)}")


def _assert_path_absent(container: Container, path: str) -> None:
    """Assert a Runtime path is absent."""
    _exec(container, f"test ! -e {shlex.quote(path)}")


def _wait_for_path_absent(container: Container, path: str) -> None:
    """Wait for one Runtime path to become absent."""
    deadline = time.monotonic() + 60
    last_error: AssertionError | None = None
    while time.monotonic() < deadline:
        try:
            _assert_path_absent(container, path)
            return
        except AssertionError as exc:
            last_error = exc
            time.sleep(0.5)
    raise AssertionError(f"Runtime path did not become absent: {path}") from last_error


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


def _set_retention(system_api: SystemV1Api, retention_days: int | None) -> None:
    """Apply a future-archive retention revision."""
    current = system_api.system_v1_get_file_lifecycle_settings()
    if current.archived_session_retention_days == retention_days:
        return
    system_api.system_v1_update_file_lifecycle_settings(
        FileLifecycleSettingsUpdateRequest(
            expected_revision=current.revision,
            archived_session_retention_days=retention_days,
            application_scope="new_archives_only",
        )
    )


class TestSessionGitWorktreeLifecycle:
    """Session Git worktree product behavior."""

    def test_agent_managed_create_dirty_refusal_and_forced_removal(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
        openai_proxy_url: str,
    ) -> None:
        """Drive Agent-managed create/remove through public model execution."""
        del azents_engine_worker_container
        requests.delete(
            f"{openai_proxy_url}/v1/_dynamic_worktree_requests",
            timeout=10,
        ).raise_for_status()
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
        source_path = _create_agent_worktree_source_repo(
            container,
            name=f"agent-source-{unique()}",
        )
        session = _get_json(
            server_url=azents_public_server_url,
            token=token,
            path=f"/chat/v1/agents/{agent_id}/team-primary-session",
        )
        session_id = session.get("id")
        if not isinstance(session_id, str):
            raise AssertionError(f"team primary Session ID is missing: {session!r}")
        registered = _post_json(
            server_url=azents_public_server_url,
            token=token,
            path=(
                f"/chat/v1/agents/{agent_id}/sessions/{session_id}/projects/register"
            ),
            payload={"path": source_path},
        )
        assert registered.get("path") == source_path

        _run_message(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=f"Agent-managed worktree E2E create\nSource: {source_path}",
        )
        create_projection = _wait_for_action_execution_status(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            status="completed",
            action_type="agent_create_git_worktree",
            client_tool_call_id="call_dynamic_worktree_create",
        )
        worktree_path = _wait_for_generated_worktree_project_path(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            source_project_path=source_path,
        )
        create_history = _wait_for_history_content(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            content="Agent-managed worktree creation continuation completed.",
            minimum_distinct_turn_runs=2,
        )
        create_run_ids = _turn_run_ids(create_history)
        distinct_create_run_ids = set(create_run_ids)
        assert len(distinct_create_run_ids) == 2
        assert _tool_call_names(create_history).count("create_git_worktree") == 1
        assert _tool_call_names(create_history).count("load_skill") == 1
        create_execution = _OBJECT_ADAPTER.validate_python(
            create_projection.get("execution")
        )
        create_action = _OBJECT_ADAPTER.validate_python(create_execution.get("action"))
        assert create_action.get("originating_run_id") in distinct_create_run_ids
        create_result = _OBJECT_ADAPTER.validate_python(create_execution.get("result"))
        assert create_result.get("worktree_path") == worktree_path
        assert create_result.get("branch_name") == "e2e/agent-managed"
        _exec(
            container,
            f"test -f {shlex.quote(worktree_path)}/"
            ".claude/skills/worktree-e2e/SKILL.md",
        )

        _exec(
            container,
            f"printf 'dirty agent removal e2e\\n' > "
            f"{shlex.quote(worktree_path)}/dirty-agent-e2e.txt",
        )
        _run_message(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=(
                f"Agent-managed worktree E2E remove\nPath: {worktree_path}"
                "\nForce: false"
            ),
        )
        dirty_projection = _wait_for_action_execution_status(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            status="failed",
            action_type="agent_remove_git_worktree",
            client_tool_call_id="call_dynamic_worktree_remove_dirty",
        )
        dirty_execution = _OBJECT_ADAPTER.validate_python(
            dirty_projection.get("execution")
        )
        assert dirty_execution.get("failure_summary")
        dirty_history = _wait_for_history_content(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            content=(
                "Agent-managed worktree dirty removal refusal continuation completed."
            ),
        )
        assert _tool_call_names(dirty_history).count("remove_git_worktree") == 1
        assert {
            project.get("path")
            for project in _list_session_projects(
                server_url=azents_public_server_url,
                token=token,
                agent_id=agent_id,
                session_id=session_id,
            )
        } == {source_path, worktree_path}
        _assert_path_present(container, worktree_path)
        _assert_branch_present(
            container,
            source_path=source_path,
            branch_name="e2e/agent-managed",
        )

        _run_message(
            server_url=azents_public_server_url,
            token=token,
            agent_id=agent_id,
            session_id=session_id,
            message=(
                f"Agent-managed worktree E2E remove\nPath: {worktree_path}\nForce: true"
            ),
        )
        force_projection = _wait_for_action_execution_status(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            status="completed",
            action_type="agent_remove_git_worktree",
            client_tool_call_id="call_dynamic_worktree_remove_force",
        )
        force_execution = _OBJECT_ADAPTER.validate_python(
            force_projection.get("execution")
        )
        force_result = _OBJECT_ADAPTER.validate_python(force_execution.get("result"))
        assert force_result.get("dirty_content_discarded") is True
        force_history = _wait_for_history_content(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
            content=("Agent-managed worktree forced removal continuation completed."),
        )
        assert _tool_call_names(force_history).count("remove_git_worktree") == 2
        _wait_for_path_absent(container, worktree_path)
        assert [
            project.get("path")
            for project in _list_session_projects(
                server_url=azents_public_server_url,
                token=token,
                agent_id=agent_id,
                session_id=session_id,
            )
        ] == [source_path]
        _assert_branch_present(
            container,
            source_path=source_path,
            branch_name="e2e/agent-managed",
        )
        journal = requests.get(
            f"{openai_proxy_url}/v1/_dynamic_worktree_requests",
            timeout=10,
        )
        journal.raise_for_status()
        evidence = _object_list(journal.json(), label="dynamic worktree model evidence")
        assert any(
            item.get("operation") == "create"
            and item.get("stage") == "continuation"
            and item.get("load_skill_available") is True
            and item.get("target_skill_present") is True
            for item in evidence
        ), evidence
        assert any(
            item.get("operation") == "create" and item.get("stage") == "after_skill"
            for item in evidence
        ), evidence
        lifecycle_stages = [
            (
                item.get("operation"),
                item.get("stage"),
                item.get("force"),
            )
            for item in evidence
        ]
        for force in (False, True):
            assert any(
                item.get("operation") == "remove"
                and item.get("stage") == "continuation"
                and item.get("force") is force
                for item in evidence
            ), lifecycle_stages

    def test_git_ref_preview_worktree_archive_and_restore_cleanup(
        self,
        public_api_client: azentspublicclient.ApiClient,
        admin_api_client: azentsadminclient.ApiClient,
        azents_public_server_url: str,
        azents_engine_worker_container: object,
    ) -> None:
        """Archive deletes one owned Session folder without restoring old bytes."""
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
            action_type="create_git_worktree",
        )
        action_execution_id = _action_execution_id(projection)
        _assert_no_live_action_executions(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
        )
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
            action_type="create_git_worktree",
        )
        failed_execution_id = _action_execution_id(failed_projection)
        failed_execution = _OBJECT_ADAPTER.validate_python(
            failed_projection.get("execution")
        )
        assert failed_execution.get("failure_summary")
        _assert_no_live_action_executions(
            server_url=azents_public_server_url,
            token=token,
            session_id=failed_session_id,
        )
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
        session_folder_path = PurePosixPath(worktree_path).parent.parent.as_posix()
        assert PurePosixPath(session_folder_path).parent.name == "sessions"
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
        external_sentinel_path = f"{source_path}/session-folder-sentinel-{unique()}"
        external_link_path = f"{session_folder_path}/external-sentinel"
        create_external_sentinel = (
            f"printf 'external sentinel\\n' > {shlex.quote(external_sentinel_path)}"
        )
        _exec(
            container,
            "\n".join(
                [
                    create_external_sentinel,
                    (
                        f"ln -s {shlex.quote(external_sentinel_path)} "
                        f"{shlex.quote(external_link_path)}"
                    ),
                ]
            ),
        )
        system_api = SystemV1Api(admin_api_client)
        _set_retention(system_api, None)
        try:
            _post_empty(
                server_url=azents_public_server_url,
                token=token,
                path=f"/chat/v1/agents/{agent_id}/sessions/{session_id}/archive",
            )
            _wait_for_path_absent(container, session_folder_path)
            _assert_branch_absent(
                container,
                source_path=source_path,
                branch_name=branch_name,
            )
            _assert_path_present(container, external_sentinel_path)

            restored = _post_json(
                server_url=azents_public_server_url,
                token=token,
                path=f"/chat/v1/agents/{agent_id}/sessions/{session_id}/restore",
                payload={},
            )
            assert restored.get("status") == "active"
            _assert_path_absent(container, worktree_path)
        finally:
            _set_retention(system_api, 30)
