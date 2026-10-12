"""Docker-free generated-contract regressions for Workspace E2E observations."""

import copy
import hashlib
import json

import pytest
import requests
from azentspublicclient.models.project_browser_manifest_response import (
    ProjectBrowserManifestResponse,
)
from azentspublicclient.models.workspace_upload_create_response import (
    WorkspaceUploadCreateResponse,
)
from azentspublicclient.models.workspace_upload_status_response import (
    WorkspaceUploadStatusResponse,
)
from pydantic import ValidationError

from support.utils import AgentSessionSetup
from tests.required.public import test_project_browser_manifest as manifest_flow
from tests.required.public import test_workspace_upload as upload_flow

_TIMESTAMP = "2026-10-13T00:00:00Z"


def _status(phase: str = "queued") -> dict[str, object]:
    return {
        "identity": {
            "upload_id": "upload-1",
            "requester_user_id": "user-1",
            "workspace_id": "workspace-1",
            "agent_id": "agent-1",
            "runtime_id": "runtime-1",
            "desired_generation": 1,
            "session_id": None,
        },
        "revision": 1,
        "destination_directory": "/workspace",
        "filename": "file.txt",
        "destination_path": "/workspace/file.txt",
        "expected_size": 3,
        "received_size": 3,
        "phase": phase,
        "retry_available": False,
        "cancel_available": True,
        "overwrite_available": False,
    }


def _create() -> dict[str, object]:
    return {
        "status": _status(),
        "ticket": {
            "method": "PUT",
            "url": "https://storage.example.test/upload?signature=opaque",
            "expires_at": _TIMESTAMP,
            "headers": {"Content-Type": "application/octet-stream"},
        },
    }


def _manifest(source: str = "session_folder") -> dict[str, object]:
    return {
        "agent_id": "agent-1",
        "session_id": None,
        "root": "/workspace",
        "active_mode": "projects",
        "modes": [
            {"id": "projects", "label": "Projects", "default": True},
            {
                "id": "all_files",
                "label": "All files",
                "default": False,
                "root_path": "/workspace",
            },
        ],
        "entries": [
            {
                "name": "Session",
                "path": "/workspace/session",
                "kind": "directory",
                "repository_type": None,
                "source": {"type": source, "project_id": None},
                "status": {"value": "unchecked", "stale": True},
                "capabilities": {
                    "open": True,
                    "remove_project": False,
                    "delete_worktree": False,
                    "filesystem_delete": False,
                    "filesystem_move": False,
                    "filesystem_rename": False,
                    "prepare_session_folder": True,
                },
            }
        ],
        "empty_state": None,
    }


def _response(payload: object, status_code: int = 200) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(payload).encode()
    response.url = "https://api.example.test/operation"
    return response


def _setup() -> AgentSessionSetup:
    return AgentSessionSetup(
        access_token="test-token",
        email="fixture@example.test",
        workspace_handle="workspace",
        agent_id="agent-1",
        session_id="session-1",
    )


@pytest.mark.parametrize("optional", [False, True])
def test_upload_contract_preserves_nullable_and_omitted_fields(optional: bool) -> None:
    payload = _status("conflicted")
    if optional:
        payload.update(
            actual_size=None,
            sha256=None,
            media_type=None,
            current_delivery_number=None,
            outcome=None,
            failure=None,
            destination_evidence=None,
        )
    observed = WorkspaceUploadStatusResponse.model_validate(payload)
    assert observed.phase == "conflicted"
    assert observed.actual_size is None
    assert observed.current_delivery_number is None
    assert observed.destination_evidence is None
    assert ("failure" in observed.model_fields_set) is optional
    assert observed.identity.session_id is None


@pytest.mark.parametrize(
    ("key", "invalid"),
    [
        ("revision", True),
        ("revision", "1"),
        ("phase", "unknown"),
        ("expected_size", -1),
        ("retry_available", 1),
        ("current_delivery_number", False),
    ],
)
def test_upload_status_rejects_malformed_interpreted_fields(
    key: str, invalid: object
) -> None:
    payload = _status()
    payload[key] = invalid
    with pytest.raises(ValidationError):
        WorkspaceUploadStatusResponse.model_validate(payload)


@pytest.mark.parametrize(
    "ticket",
    [
        {
            "method": "GET",
            "url": "https://storage.test/",
            "expires_at": _TIMESTAMP,
            "headers": {},
        },
        {"method": "PUT", "url": 3, "expires_at": _TIMESTAMP, "headers": {}},
        {
            "method": "PUT",
            "url": "https://storage.test/",
            "expires_at": _TIMESTAMP,
            "headers": {"x-test": 3},
        },
        {"method": "PUT", "url": "https://storage.test/", "headers": {}},
    ],
)
def test_upload_create_rejects_invalid_ticket(ticket: dict[str, object]) -> None:
    payload = _create()
    payload["ticket"] = ticket
    with pytest.raises(ValidationError):
        WorkspaceUploadCreateResponse.model_validate(payload)


def test_create_upload_decodes_actual_response_without_changing_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def post(url: str, **kwargs: object) -> requests.Response:
        calls.append((url, kwargs))
        return _response(_create())

    monkeypatch.setattr(upload_flow.requests, "post", post)
    observed = upload_flow._create_upload(
        server_url="https://api.example.test",
        setup=_setup(),
        destination_directory="/workspace",
        filename="file.txt",
        content=b"abc",
    )
    assert observed.status.identity.upload_id == "upload-1"
    assert observed.ticket.method == "PUT"
    assert calls == [
        (
            "https://api.example.test/chat/v1/agents/agent-1/workspace/uploads",
            {
                "headers": {
                    "Authorization": "Bearer test-token",
                    "Content-Type": "application/json",
                },
                "json": {
                    "destination_directory": "/workspace",
                    "filename": "file.txt",
                    "expected_size": 3,
                    "expected_sha256": hashlib.sha256(b"abc").hexdigest(),
                    "media_type": "application/octet-stream",
                    "session_id": "session-1",
                },
                "timeout": 10,
                "verify": False,
            },
        )
    ]


def test_upload_phase_wait_uses_validated_authoritative_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = iter([_response(_status("queued")), _response(_status("succeeded"))])
    sleeps: list[float] = []
    monkeypatch.setattr(
        upload_flow.requests, "get", lambda *args, **kwargs: next(states)
    )
    monkeypatch.setattr(upload_flow.time, "sleep", sleeps.append)
    observed = upload_flow._wait_for_phase(
        server_url="https://api.example.test",
        setup=_setup(),
        upload_id="upload-1",
        expected={"succeeded"},
    )
    assert observed.phase == "succeeded"
    assert sleeps == [0.5]


@pytest.mark.parametrize(
    "source", ["session_folder", "session_project", "preview_project"]
)
def test_manifest_retains_source_variants_and_nullable_projection(source: str) -> None:
    observed = ProjectBrowserManifestResponse.model_validate(_manifest(source))
    assert observed.session_id is None
    assert observed.empty_state is None
    assert [mode.id for mode in observed.modes] == ["projects", "all_files"]
    entries = manifest_flow._manifest_entries(observed)
    assert manifest_flow._entry_paths(entries) == ["/workspace/session"]
    assert entries[0].source.type == source
    assert entries[0].source.project_id is None
    assert entries[0].repository_type is None
    assert entries[0].status.checked_at is None
    manifest_flow._assert_project_root_capabilities(entries[0], remove_project=False)


@pytest.mark.parametrize("field", ["path", "source", "status", "capabilities"])
def test_manifest_rejects_invalid_nested_interpreted_projection(field: str) -> None:
    payload = _manifest()
    entries = copy.deepcopy(payload["entries"])
    assert isinstance(entries, list)
    assert isinstance(entries[0], dict)
    entries[0][field] = 1
    payload["entries"] = entries
    with pytest.raises(ValidationError):
        ProjectBrowserManifestResponse.model_validate(payload)


def test_manifest_wait_decodes_only_success_and_preserves_preparation_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [_response({"detail": "preparation pending"}, 400), _response(_manifest())]
    )
    sleeps: list[float] = []
    monkeypatch.setattr(
        manifest_flow.requests, "get", lambda *args, **kwargs: next(responses)
    )
    monkeypatch.setattr(manifest_flow.time, "sleep", sleeps.append)
    observed = manifest_flow._wait_for_session_manifest(
        server_url="https://api.example.test",
        token="token",
        agent_id="agent-1",
        session_id="session-1",
    )
    assert observed.active_mode == "projects"
    assert sleeps == [1]


def test_manifest_wait_does_not_default_after_malformed_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        manifest_flow.requests,
        "get",
        lambda *args, **kwargs: _response({"entries": []}),
    )
    with pytest.raises(ValidationError):
        manifest_flow._wait_for_session_manifest(
            server_url="https://api.example.test",
            token="token",
            agent_id="agent-1",
            session_id="session-1",
        )


@pytest.mark.parametrize("operation", ["get", "finalize", "cancel", "retry"])
def test_upload_status_operations_validate_response_and_preserve_fences(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def request(url: str, **kwargs: object) -> requests.Response:
        calls.append((url, kwargs))
        return _response(_status("moving_to_runtime"))

    monkeypatch.setattr(upload_flow.requests, "get", request)
    monkeypatch.setattr(upload_flow.requests, "post", request)
    setup = _setup()
    if operation == "get":
        observed = upload_flow._get_status(
            server_url="https://api.example.test", setup=setup, upload_id="upload-1"
        )
        expected_payload = None
    elif operation == "finalize":
        observed = upload_flow._finalize(
            server_url="https://api.example.test",
            setup=setup,
            upload_id="upload-1",
            revision=2,
        )
        expected_payload = {"expected_revision": 2}
    elif operation == "cancel":
        observed = upload_flow._cancel(
            server_url="https://api.example.test",
            setup=setup,
            upload_id="upload-1",
            revision=2,
        )
        expected_payload = {"expected_revision": 2, "current_delivery_number": None}
    else:
        observed = upload_flow._retry(
            server_url="https://api.example.test",
            setup=setup,
            upload_id="upload-1",
            revision=2,
            current_delivery_number=3,
            overwrite=True,
            conflict_precondition="opaque-fence",
        )
        expected_payload = {
            "expected_revision": 2,
            "current_delivery_number": 3,
            "overwrite": True,
            "conflict_precondition": "opaque-fence",
        }
    assert observed.phase == "moving_to_runtime"
    assert observed.identity.upload_id == "upload-1"
    assert len(calls) == 1
    url, kwargs = calls[0]
    suffix = "" if operation == "get" else f"/{operation}"
    assert url.endswith(f"/workspace/uploads/upload-1{suffix}")
    assert kwargs.get("json") == expected_payload
    assert kwargs["verify"] is False


def test_direct_put_preserves_signed_authority_and_gateway_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    def request(method: str, url: str, **kwargs: object) -> requests.Response:
        calls.append((method, url, kwargs))
        return _response({})

    monkeypatch.setattr(upload_flow.requests, "request", request)
    observed = WorkspaceUploadCreateResponse.model_validate(_create())
    upload_flow._put_direct(
        observed.ticket,
        b"abc",
        gateway_url="https://localhost:8080/ignored",
    )
    assert calls == [
        (
            "PUT",
            "https://localhost:8080/upload?signature=opaque",
            {
                "headers": {
                    "Content-Type": "application/octet-stream",
                    "Host": "storage.example.test",
                },
                "data": b"abc",
                "timeout": 30,
                "verify": False,
            },
        )
    ]


def test_manifest_public_extensions_do_not_change_interpreted_fields() -> None:
    payload = _manifest()
    payload["future_evidence"] = {"opaque": [1, "text", None]}
    observed = ProjectBrowserManifestResponse.model_validate(payload)
    assert observed.active_mode == "projects"
    assert observed.entries[0].path == "/workspace/session"
