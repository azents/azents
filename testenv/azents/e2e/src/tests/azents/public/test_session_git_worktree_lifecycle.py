"""Session Git worktree lifecycle E2E tests."""

import shlex
import time
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
    """Create a non-primary session in Git worktree mode."""
    payload = _post_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/agents/{agent_id}/sessions",
        payload={
            "workspace_mode": {
                "type": "git_worktree",
                "source_project_path": source_project_path,
                "starting_ref": starting_ref,
            }
        },
    )
    session_id = payload.get("id")
    if not isinstance(session_id, str):
        raise AssertionError(f"Create session response did not include id: {payload!r}")
    return session_id


def _initialization_detail(
    *,
    server_url: str,
    token: str,
    session_id: str,
) -> dict[str, object]:
    """Fetch session initialization detail."""
    return _get_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/sessions/{session_id}/initialization",
    )


def _wait_for_initialization_ready(
    *,
    server_url: str,
    token: str,
    session_id: str,
) -> dict[str, object]:
    """Wait for Git worktree initialization to become ready."""
    deadline = time.monotonic() + 90
    last_detail: dict[str, object] | None = None
    while time.monotonic() < deadline:
        detail = _initialization_detail(
            server_url=server_url,
            token=token,
            session_id=session_id,
        )
        last_detail = detail
        initialization = _OBJECT_ADAPTER.validate_python(detail.get("initialization"))
        if initialization.get("status") == "ready":
            return detail
        if initialization.get("status") == "failed":
            raise AssertionError(f"initialization failed: {detail!r}")
        time.sleep(0.5)
    raise TimeoutError(f"initialization did not become ready: {last_detail!r}")


def _worktree_descriptor(detail: dict[str, object]) -> dict[str, object]:
    """Return the Git worktree resource descriptor from initialization detail."""
    initialization = _OBJECT_ADAPTER.validate_python(detail.get("initialization"))
    steps = _object_list(initialization.get("steps"), label="initialization steps")
    for step in steps:
        if step.get("step_type") != "create_git_worktree":
            continue
        descriptors = _object_list(
            step.get("resource_descriptors"),
            label="create_git_worktree resource descriptors",
        )
        for descriptor in descriptors:
            if descriptor.get("type") == "git_worktree":
                return descriptor
    raise AssertionError(f"Git worktree descriptor not found: {detail!r}")


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
        detail = _wait_for_initialization_ready(
            server_url=azents_public_server_url,
            token=token,
            session_id=session_id,
        )
        descriptor = _worktree_descriptor(detail)
        worktree_path = descriptor.get("worktree_path")
        branch_name = descriptor.get("branch_name")
        base_commit = descriptor.get("base_commit")
        assert isinstance(worktree_path, str)
        assert isinstance(branch_name, str)
        assert isinstance(base_commit, str)
        _exec(
            container,
            f"test -f {shlex.quote(worktree_path)}/README.md && "
            f"cd {shlex.quote(worktree_path)} && "
            f'test "$(git rev-parse HEAD)" = {shlex.quote(base_commit)}',
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
