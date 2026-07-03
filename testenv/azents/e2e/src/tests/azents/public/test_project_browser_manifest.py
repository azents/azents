"""Project browser manifest public API E2E tests."""

from dataclasses import dataclass

import azentsadminclient
import azentspublicclient
import requests
from pydantic import TypeAdapter, ValidationError

from support.utils import create_chat_session_with_agent, unique

_JSON_OBJECT = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])


@dataclass(frozen=True)
class _ProjectBrowserSetup:
    """Created AgentSession state for Project browser manifest tests."""

    token: str
    primary_session_id: str
    agent_id: str


def _headers(token: str) -> dict[str, str]:
    """Return bearer auth headers."""
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


def _get_json(*, server_url: str, token: str, path: str) -> dict[str, object]:
    """Call a public GET endpoint and return a JSON object."""
    response = requests.get(
        f"{server_url}{path}",
        headers=_headers(token),
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
        timeout=10,
    )
    response.raise_for_status()
    return _response_object(response, label=f"POST {path} response")


def _delete(*, server_url: str, token: str, path: str) -> None:
    """Call a public DELETE endpoint and assert it succeeds."""
    response = requests.delete(
        f"{server_url}{path}",
        headers=_headers(token),
        timeout=10,
    )
    response.raise_for_status()


def _setup_project_browser(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    public_url: str,
) -> _ProjectBrowserSetup:
    """Create an Agent with a primary session for Project browser tests."""
    token, primary_session_id, agent_id = create_chat_session_with_agent(
        public_api_client,
        admin_api_client,
        public_url,
    )
    return _ProjectBrowserSetup(
        token=token,
        primary_session_id=primary_session_id,
        agent_id=agent_id,
    )


def _create_session(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    project_paths: list[str],
) -> str:
    """Create a non-primary AgentSession with explicit Project paths."""
    payload = _post_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/agents/{agent_id}/sessions",
        payload={"project_paths": project_paths},
    )
    session_id = payload.get("id")
    if not isinstance(session_id, str):
        raise AssertionError(f"Create session response did not include id: {payload!r}")
    return session_id


def _session_manifest(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> dict[str, object]:
    """Fetch a session Project browser manifest."""
    return _get_json(
        server_url=server_url,
        token=token,
        path=(
            f"/chat/v1/agents/{agent_id}/sessions/{session_id}"
            "/workspace/project-browser-manifest"
        ),
    )


def _preview_manifest(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    project_paths: list[str],
) -> dict[str, object]:
    """Fetch a pre-session Project browser manifest preview."""
    return _post_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/agents/{agent_id}/workspace/project-browser-manifest/preview",
        payload={"project_paths": project_paths},
    )


def _list_projects(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> list[dict[str, object]]:
    """Fetch session Project registry rows."""
    payload = _get_json(
        server_url=server_url,
        token=token,
        path=f"/chat/v1/agents/{agent_id}/sessions/{session_id}/projects",
    )
    return _object_items(payload.get("items"), label="session project items")


def _manifest_entries(manifest: dict[str, object]) -> list[dict[str, object]]:
    """Return validated manifest entries."""
    return _object_items(manifest.get("entries"), label="manifest entries")


def _entry_paths(entries: list[dict[str, object]]) -> list[str]:
    """Return Project browser entry paths."""
    paths: list[str] = []
    for entry in entries:
        path = entry.get("path")
        if not isinstance(path, str):
            raise AssertionError(f"Manifest entry path is not a string: {entry!r}")
        paths.append(path)
    return paths


def _assert_project_root_capabilities(
    entry: dict[str, object],
    *,
    remove_project: bool,
) -> None:
    """Assert backend-provided Project root capability policy."""
    capabilities = _JSON_OBJECT.validate_python(entry.get("capabilities"))
    assert capabilities.get("open") is True
    assert capabilities.get("remove_project") is remove_project
    assert capabilities.get("filesystem_delete") is False
    assert capabilities.get("filesystem_move") is False
    assert capabilities.get("filesystem_rename") is False


def test_empty_project_manifest_has_explicit_empty_state(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
) -> None:
    """A session with no Projects returns empty Projects mode without root fallback."""
    setup = _setup_project_browser(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        public_url=azents_public_server_url,
    )

    manifest = _session_manifest(
        server_url=azents_public_server_url,
        token=setup.token,
        agent_id=setup.agent_id,
        session_id=setup.primary_session_id,
    )

    assert manifest.get("active_mode") == "projects"
    assert _manifest_entries(manifest) == []
    empty_state = _JSON_OBJECT.validate_python(manifest.get("empty_state"))
    assert isinstance(empty_state.get("title"), str)
    assert isinstance(empty_state.get("description"), str)

    modes = _object_items(manifest.get("modes"), label="manifest modes")
    assert [mode.get("id") for mode in modes] == ["projects", "all_files"]
    assert modes[0].get("default") is True


def test_session_project_manifest_uses_registry_capabilities_and_removal(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
) -> None:
    """Session manifest entries are Project roots with registry-scoped removal."""
    setup = _setup_project_browser(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        public_url=azents_public_server_url,
    )
    prefix = f"/workspace/agent/project-browser-{unique()}"
    paths = [f"{prefix}-alpha", f"{prefix}-beta"]
    session_id = _create_session(
        server_url=azents_public_server_url,
        token=setup.token,
        agent_id=setup.agent_id,
        project_paths=paths,
    )

    manifest = _session_manifest(
        server_url=azents_public_server_url,
        token=setup.token,
        agent_id=setup.agent_id,
        session_id=session_id,
    )
    entries = _manifest_entries(manifest)

    assert manifest.get("active_mode") == "projects"
    assert _entry_paths(entries) == paths
    for entry in entries:
        assert entry.get("kind") == "directory"
        source = _JSON_OBJECT.validate_python(entry.get("source"))
        assert source.get("type") == "session_project"
        assert isinstance(source.get("project_id"), str)
        _assert_project_root_capabilities(entry, remove_project=True)

    projects = _list_projects(
        server_url=azents_public_server_url,
        token=setup.token,
        agent_id=setup.agent_id,
        session_id=session_id,
    )
    removed_project = next(
        project for project in projects if project.get("path") == paths[0]
    )
    project_id = removed_project.get("id")
    if not isinstance(project_id, str):
        raise AssertionError(
            f"Project registry row did not include id: {removed_project!r}"
        )

    _delete(
        server_url=azents_public_server_url,
        token=setup.token,
        path=f"/chat/v1/agents/{setup.agent_id}/sessions/{session_id}/projects/{project_id}",
    )

    after_manifest = _session_manifest(
        server_url=azents_public_server_url,
        token=setup.token,
        agent_id=setup.agent_id,
        session_id=session_id,
    )
    assert _entry_paths(_manifest_entries(after_manifest)) == [paths[1]]


def test_pre_session_preview_uses_project_manifest_entry_model(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
) -> None:
    """Pre-session preview returns the same Project browser entry model."""
    setup = _setup_project_browser(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        public_url=azents_public_server_url,
    )
    preview_path = f"/workspace/agent/project-preview-{unique()}"

    manifest = _preview_manifest(
        server_url=azents_public_server_url,
        token=setup.token,
        agent_id=setup.agent_id,
        project_paths=[
            f"{preview_path}/../{preview_path.rsplit('/', maxsplit=1)[-1]}",
            preview_path,
        ],
    )
    entries = _manifest_entries(manifest)

    assert manifest.get("session_id") is None
    assert manifest.get("active_mode") == "projects"
    assert _entry_paths(entries) == [preview_path]
    source = _JSON_OBJECT.validate_python(entries[0].get("source"))
    assert source.get("type") == "preview_project"
    assert source.get("project_id") is None
    _assert_project_root_capabilities(entries[0], remove_project=False)

    status = _JSON_OBJECT.validate_python(entries[0].get("status"))
    assert status.get("value") == "unchecked"
    assert status.get("stale") is True
