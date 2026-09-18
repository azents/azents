"""Public API E2E journeys for direct Agent Workspace uploads."""

from __future__ import annotations

import hashlib
import time
from typing import TypedDict
from urllib.parse import urlparse, urlsplit, urlunsplit

import azentsadminclient
import azentspublicclient
import pytest
import requests

from support.utils import AgentSessionSetup, create_agent_session_setup

_TERMINAL_PHASES = {
    "conflicted",
    "succeeded",
    "cancelled",
    "failed",
    "expired",
    "retryable_failure",
}


class _WorkspaceUploadTicket(TypedDict):
    method: str
    url: str
    headers: dict[str, str]


class _WorkspaceUploadIdentity(TypedDict):
    upload_id: str


class _WorkspaceUploadStatus(TypedDict):
    identity: _WorkspaceUploadIdentity
    revision: int


class _WorkspaceUploadResponse(TypedDict):
    status: _WorkspaceUploadStatus
    ticket: _WorkspaceUploadTicket


def _headers(token: str) -> dict[str, str]:
    """Return a bearer authorization header."""
    return {"Authorization": f"Bearer {token}"}


def _create_upload(
    *,
    server_url: str,
    setup: AgentSessionSetup,
    destination_directory: str,
    filename: str,
    content: bytes,
) -> _WorkspaceUploadResponse:
    """Create one direct upload through the public API."""
    response = requests.post(
        f"{server_url}/chat/v1/agents/{setup.agent_id}/workspace/uploads",
        headers={**_headers(setup.access_token), "Content-Type": "application/json"},
        json={
            "destination_directory": destination_directory,
            "filename": filename,
            "expected_size": len(content),
            "expected_sha256": hashlib.sha256(content).hexdigest(),
            "media_type": "application/octet-stream",
            "session_id": setup.session_id,
        },
        timeout=10,
        verify=False,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("Workspace upload create response must be an object.")
    status = payload.get("status")
    ticket = payload.get("ticket")
    if not isinstance(status, dict) or not isinstance(ticket, dict):
        raise AssertionError("Workspace upload create response is incomplete.")
    identity = status.get("identity")
    revision = status.get("revision")
    upload_id = identity.get("upload_id") if isinstance(identity, dict) else None
    if not isinstance(upload_id, str) or not isinstance(revision, int):
        raise AssertionError("Workspace upload create response is missing identity.")
    method = ticket.get("method")
    url = ticket.get("url")
    headers = ticket.get("headers")
    if (
        method != "PUT"
        or not isinstance(url, str)
        or not isinstance(headers, dict)
        or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in headers.items()
        )
    ):
        raise AssertionError("Workspace upload ticket is malformed.")
    return {
        "status": {"identity": {"upload_id": upload_id}, "revision": revision},
        "ticket": {"method": method, "url": url, "headers": headers},
    }


def _put_direct(
    ticket: _WorkspaceUploadTicket,
    content: bytes,
    *,
    gateway_url: str,
) -> requests.Response:
    """Upload exact bytes through the host-mapped HTTPS gateway."""
    ticket_url = urlsplit(ticket["url"])
    gateway = urlsplit(gateway_url)
    if (
        ticket_url.scheme != "https"
        or not ticket_url.netloc
        or gateway.scheme != "https"
        or not gateway.netloc
    ):
        raise AssertionError("Workspace upload ticket must use an HTTPS URL.")
    request_url = urlunsplit(
        (
            gateway.scheme,
            gateway.netloc,
            ticket_url.path,
            ticket_url.query,
            ticket_url.fragment,
        )
    )
    headers = dict(ticket["headers"])
    headers["Host"] = ticket_url.netloc
    response = requests.request(
        ticket["method"],
        request_url,
        headers=headers,
        data=content,
        timeout=30,
        verify=False,
    )
    response.raise_for_status()
    return response


def _get_status(
    *,
    server_url: str,
    setup: AgentSessionSetup,
    upload_id: str,
) -> dict[str, object]:
    """Read one authoritative upload status through the public API."""
    response = requests.get(
        f"{server_url}/chat/v1/agents/{setup.agent_id}/workspace/uploads/{upload_id}",
        headers=_headers(setup.access_token),
        timeout=10,
        verify=False,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("Workspace upload status must be an object.")
    return payload


def _wait_for_phase(
    *,
    server_url: str,
    setup: AgentSessionSetup,
    upload_id: str,
    expected: set[str],
    timeout_seconds: float = 120,
) -> dict[str, object]:
    """Poll fresh API status until one of the expected phases is observed."""
    deadline = time.monotonic() + timeout_seconds
    last_status: dict[str, object] | None = None
    while time.monotonic() < deadline:
        status = _get_status(
            server_url=server_url,
            setup=setup,
            upload_id=upload_id,
        )
        last_status = status
        phase = status.get("phase")
        if phase in expected:
            return status
        time.sleep(0.5)
    raise AssertionError(
        f"Workspace upload did not reach {sorted(expected)}: {last_status!r}"
    )


def _finalize(
    *,
    server_url: str,
    setup: AgentSessionSetup,
    upload_id: str,
    revision: int,
) -> dict[str, object]:
    """Finalize one completed direct PUT through the public API."""
    response = requests.post(
        f"{server_url}/chat/v1/agents/{setup.agent_id}/workspace/uploads/{upload_id}/finalize",
        headers={**_headers(setup.access_token), "Content-Type": "application/json"},
        json={"expected_revision": revision},
        timeout=30,
        verify=False,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("Workspace upload finalize response must be an object.")
    return payload


def _cancel(
    *,
    server_url: str,
    setup: AgentSessionSetup,
    upload_id: str,
    revision: int,
    current_delivery_number: int | None = None,
) -> dict[str, object]:
    """Request one revision-fenced upload cancellation through the public API."""
    response = requests.post(
        f"{server_url}/chat/v1/agents/{setup.agent_id}/workspace/uploads/{upload_id}/cancel",
        headers={**_headers(setup.access_token), "Content-Type": "application/json"},
        json={
            "expected_revision": revision,
            "current_delivery_number": current_delivery_number,
        },
        timeout=30,
        verify=False,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("Workspace upload cancel response must be an object.")
    return payload


def _retry(
    *,
    server_url: str,
    setup: AgentSessionSetup,
    upload_id: str,
    revision: int,
    current_delivery_number: int,
    overwrite: bool,
    conflict_precondition: str | None,
) -> dict[str, object]:
    """Queue one Runtime delivery retry through the public API."""
    response = requests.post(
        f"{server_url}/chat/v1/agents/{setup.agent_id}/workspace/uploads/{upload_id}/retry",
        headers={**_headers(setup.access_token), "Content-Type": "application/json"},
        json={
            "expected_revision": revision,
            "current_delivery_number": current_delivery_number,
            "overwrite": overwrite,
            "conflict_precondition": conflict_precondition,
        },
        timeout=30,
        verify=False,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise AssertionError("Workspace upload retry response must be an object.")
    return payload


def _download_workspace_file(
    *,
    server_url: str,
    setup: AgentSessionSetup,
    path: str,
) -> bytes:
    """Download one committed Workspace file through the public API."""
    response = requests.get(
        f"{server_url}/chat/v1/agents/{setup.agent_id}/workspace/download",
        params={"path": path},
        headers=_headers(setup.access_token),
        timeout=30,
        verify=False,
    )
    response.raise_for_status()
    return response.content


def _wait_for_workspace_bytes(
    *,
    server_url: str,
    setup: AgentSessionSetup,
    path: str,
    expected: bytes,
    timeout_seconds: float = 120,
) -> None:
    """Wait until the committed Workspace path exposes exact bytes."""
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            actual = _download_workspace_file(
                server_url=server_url,
                setup=setup,
                path=path,
            )
        except requests.RequestException as error:
            last_error = error
        else:
            if actual == expected:
                return
            last_error = AssertionError(
                "Workspace bytes did not match: "
                f"expected {len(expected)}, received {len(actual)}"
            )
        time.sleep(0.5)
    raise AssertionError(
        "Workspace file did not reach the expected bytes."
    ) from last_error


def _upload_and_finalize(
    *,
    server_url: str,
    setup: AgentSessionSetup,
    gateway_url: str,
    destination_directory: str,
    filename: str,
    content: bytes,
) -> tuple[_WorkspaceUploadStatus, dict[str, object]]:
    """Perform one direct PUT and finalize it, returning create and terminal status."""
    created = _create_upload(
        server_url=server_url,
        setup=setup,
        destination_directory=destination_directory,
        filename=filename,
        content=content,
    )
    created_status = created["status"]
    upload_id = created_status["identity"]["upload_id"]
    revision = created_status["revision"]
    _put_direct(created["ticket"], content, gateway_url=gateway_url)
    _finalize(
        server_url=server_url,
        setup=setup,
        upload_id=upload_id,
        revision=revision,
    )
    terminal = _wait_for_phase(
        server_url=server_url,
        setup=setup,
        upload_id=upload_id,
        expected={"succeeded", "failed", "expired", "conflicted"},
    )
    return created_status, terminal


def test_workspace_upload_direct_put_finalize_and_exact_download(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_workspace_upload_gateway_url: str,
    runtime_workspace_path: str,
) -> None:
    """Upload exact bytes through the public API and download the committed file."""
    setup = create_agent_session_setup(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    filename = "workspace-direct-upload-api.txt"
    content = b"API direct Workspace upload\n\x00exact bytes\n"
    destination_directory = runtime_workspace_path
    created = _create_upload(
        server_url=azents_public_server_url,
        setup=setup,
        destination_directory=destination_directory,
        filename=filename,
        content=content,
    )
    upload_id = created["status"]["identity"]["upload_id"]
    revision = created["status"]["revision"]
    assert isinstance(upload_id, str)
    assert isinstance(revision, int)
    assert urlparse(created["ticket"]["url"]).netloc
    assert created["ticket"]["method"] == "PUT"
    _put_direct(
        created["ticket"],
        content,
        gateway_url=azents_workspace_upload_gateway_url,
    )
    _finalize(
        server_url=azents_public_server_url,
        setup=setup,
        upload_id=upload_id,
        revision=revision,
    )
    terminal = _wait_for_phase(
        server_url=azents_public_server_url,
        setup=setup,
        upload_id=upload_id,
        expected={"succeeded"},
    )
    assert terminal["actual_size"] == len(content)
    assert terminal["sha256"] == hashlib.sha256(content).hexdigest()
    _wait_for_workspace_bytes(
        server_url=azents_public_server_url,
        setup=setup,
        path=f"{destination_directory}/{filename}",
        expected=content,
    )


def test_workspace_upload_conflict_overwrite_and_retry_without_reupload(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_workspace_upload_gateway_url: str,
    runtime_workspace_path: str,
) -> None:
    """Require explicit overwrite while retrying the immutable source.

    The retry must not issue another browser PUT.
    """
    setup = create_agent_session_setup(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    filename = "workspace-conflict-upload-api.txt"
    first_content = b"first committed API content\n"
    second_content = b"second explicit API overwrite content\n"
    destination_directory = runtime_workspace_path
    _upload_and_finalize(
        server_url=azents_public_server_url,
        setup=setup,
        gateway_url=azents_workspace_upload_gateway_url,
        destination_directory=destination_directory,
        filename=filename,
        content=first_content,
    )

    created = _create_upload(
        server_url=azents_public_server_url,
        setup=setup,
        destination_directory=destination_directory,
        filename=filename,
        content=second_content,
    )
    upload_id = created["status"]["identity"]["upload_id"]
    revision = created["status"]["revision"]
    assert isinstance(upload_id, str)
    assert isinstance(revision, int)
    _put_direct(
        created["ticket"],
        second_content,
        gateway_url=azents_workspace_upload_gateway_url,
    )
    _finalize(
        server_url=azents_public_server_url,
        setup=setup,
        upload_id=upload_id,
        revision=revision,
    )
    conflict = _wait_for_phase(
        server_url=azents_public_server_url,
        setup=setup,
        upload_id=upload_id,
        expected={"conflicted"},
    )
    conflict_revision = conflict.get("revision")
    delivery_number = conflict.get("current_delivery_number")
    evidence = conflict.get("destination_evidence")
    if (
        not isinstance(conflict_revision, int)
        or not isinstance(delivery_number, int)
        or not isinstance(evidence, dict)
    ):
        raise AssertionError("Conflict status is missing retry fencing data.")
    precondition = evidence.get("conflict_precondition")
    assert isinstance(precondition, str) and precondition

    retry = _retry(
        server_url=azents_public_server_url,
        setup=setup,
        upload_id=upload_id,
        revision=conflict_revision,
        current_delivery_number=delivery_number,
        overwrite=True,
        conflict_precondition=precondition,
    )
    assert retry["phase"] == "moving_to_runtime"
    terminal = _wait_for_phase(
        server_url=azents_public_server_url,
        setup=setup,
        upload_id=upload_id,
        expected={"succeeded"},
    )
    assert terminal["current_delivery_number"] == delivery_number + 1
    _wait_for_workspace_bytes(
        server_url=azents_public_server_url,
        setup=setup,
        path=f"{destination_directory}/{filename}",
        expected=second_content,
    )


def test_workspace_upload_cancellation_does_not_publish_destination(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    runtime_workspace_path: str,
) -> None:
    """Cancel an admitted upload before PUT and verify no destination is visible."""
    setup = create_agent_session_setup(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
    )
    filename = "workspace-cancelled-upload-api.bin"
    content = b"cancelled API upload"
    created = _create_upload(
        server_url=azents_public_server_url,
        setup=setup,
        destination_directory=runtime_workspace_path,
        filename=filename,
        content=content,
    )
    upload_id = created["status"]["identity"]["upload_id"]
    revision = created["status"]["revision"]
    assert isinstance(upload_id, str)
    assert isinstance(revision, int)
    cancelled = _cancel(
        server_url=azents_public_server_url,
        setup=setup,
        upload_id=upload_id,
        revision=revision,
    )
    assert cancelled["phase"] == "cancelled"
    terminal = _wait_for_phase(
        server_url=azents_public_server_url,
        setup=setup,
        upload_id=upload_id,
        expected={"cancelled"},
    )
    assert terminal["failure"] == "cancelled"
    destination_path = f"{runtime_workspace_path}/{filename}"
    with pytest.raises(requests.HTTPError) as download_error:
        _download_workspace_file(
            server_url=azents_public_server_url,
            setup=setup,
            path=destination_path,
        )
    assert download_error.value.response is not None
    assert download_error.value.response.status_code == 404
