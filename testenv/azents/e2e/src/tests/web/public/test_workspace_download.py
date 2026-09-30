"""Native Workspace downloads across Web, API, Runner, and private storage."""

import hashlib
import os
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.models.workspace_upload_create_response import (
    WorkspaceUploadCreateResponse,
)
from azentspublicclient.models.workspace_upload_phase import WorkspaceUploadPhase
from azentspublicclient.models.workspace_upload_status_response import (
    WorkspaceUploadStatusResponse,
)
from pydantic import BaseModel
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait
from testcontainers.core.container import DockerContainer

from support.utils import create_agent_session_setup, wait_until
from tests.web.public.test_workspace_settings_web import _login_main_web


class _WorkspaceDownloadEvidence(BaseModel):
    """Completed byte and status evidence without credentials or storage keys."""

    web_status: int
    filename: str
    size: int
    expected_sha256: str
    browser_sha256: str


def test_workspace_native_browser_get_uses_empty_web_redirect_and_exact_bytes(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_admin_gateway_container: DockerContainer,
    azents_public_server_url: str,
    azents_workspace_upload_gateway_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    runtime_workspace_path: str,
    tmp_path: Path,
) -> None:
    """Publish a Runtime file, then navigate to its authenticated direct GET."""
    setup = create_agent_session_setup(
        public_api_client, admin_api_client, azents_public_server_url
    )
    headers = {"Authorization": f"Bearer {setup.access_token}"}
    content = b"Native Workspace browser direct GET.\n\x00exact bytes\n"
    digest = hashlib.sha256(content).hexdigest()
    filename = "browser-workspace ü.txt"
    base = (
        f"{azents_public_server_url}/chat/v1/agents/{setup.agent_id}/workspace/uploads"
    )
    admitted = requests.post(
        base,
        headers=headers,
        json={
            "destination_directory": runtime_workspace_path,
            "filename": filename,
            "expected_size": len(content),
            "expected_sha256": digest,
            "media_type": "text/plain",
            "session_id": setup.session_id,
        },
        timeout=30,
    )
    admitted.raise_for_status()
    created = WorkspaceUploadCreateResponse.model_validate(admitted.json())
    ticket_url = urlsplit(created.ticket.url)
    gateway = urlsplit(azents_workspace_upload_gateway_url)
    request_url = urlunsplit(
        (gateway.scheme, gateway.netloc, ticket_url.path, ticket_url.query, "")
    )
    try:
        uploaded = requests.put(
            request_url,
            headers={**created.ticket.headers, "Host": ticket_url.netloc},
            data=content,
            timeout=30,
            verify=False,
            allow_redirects=False,
        )
    except requests.RequestException as error:
        raise AssertionError(
            f"Workspace direct PUT transport failed: {type(error).__name__}."
        ) from None
    assert uploaded.status_code == 200
    upload_id = created.status.identity.upload_id
    finalized = requests.post(
        f"{base}/{upload_id}/finalize",
        headers=headers,
        json={"expected_revision": created.status.revision},
        timeout=30,
    )
    finalized.raise_for_status()

    def terminal_status() -> WorkspaceUploadStatusResponse | None:
        response = requests.get(f"{base}/{upload_id}", headers=headers, timeout=10)
        response.raise_for_status()
        status = WorkspaceUploadStatusResponse.model_validate(response.json())
        if status.phase in {
            WorkspaceUploadPhase.SUCCEEDED,
            WorkspaceUploadPhase.FAILED,
            WorkspaceUploadPhase.EXPIRED,
            WorkspaceUploadPhase.CONFLICTED,
        }:
            return status
        return None

    terminal = wait_until(
        terminal_status,
        timeout=120,
        interval=0.5,
        message="Workspace browser download source did not publish",
    )
    assert terminal is not None
    assert terminal.phase == WorkspaceUploadPhase.SUCCEEDED
    assert terminal.actual_size == len(content)
    assert terminal.sha256 == digest

    _login_main_web(browser_driver, base_url=azents_main_web_url, email=setup.email)
    browser_driver.get(
        f"{azents_main_web_url}/w/{setup.workspace_handle}/agents/{setup.agent_id}"
        f"/sessions/{setup.session_id}"
    )
    entry_path = (
        f"/api/chat/agents/{setup.agent_id}/workspace/download"
        f"?path={quote(terminal.destination_path, safe='')}"
    )
    gateway_host = azents_admin_gateway_container.get_container_host_ip()
    gateway_port = azents_admin_gateway_container.get_exposed_port(8443)
    redirect = requests.get(
        f"https://{gateway_host}:{gateway_port}{entry_path}",
        headers={"Host": urlsplit(azents_main_web_url).netloc},
        cookies={
            cookie["name"]: cookie["value"] for cookie in browser_driver.get_cookies()
        },
        timeout=30,
        verify=False,
        allow_redirects=False,
    )
    assert redirect.status_code == 302
    assert redirect.content == b""
    assert redirect.headers["Cache-Control"] == "no-store"
    assert redirect.headers["Referrer-Policy"] == "no-referrer"
    assert (
        urlsplit(redirect.headers["Location"]).netloc
        != urlsplit(azents_main_web_url).netloc
    )

    # Native browser navigation follows the capability without cross-origin fetch.
    browser_driver.execute_script(
        "window.location.assign(arguments[0]);", f"{azents_main_web_url}{entry_path}"
    )
    WebDriverWait(browser_driver, 90, poll_frequency=0.2).until(
        lambda driver: filename in driver.get_downloadable_files()
    )
    destination = tmp_path / "workspace-download"
    browser_driver.download_file(filename, str(destination))
    browser_bytes = (destination / filename).read_bytes()
    assert browser_bytes == content
    artifact_root = os.environ.get("AZENTS_E2E_ARTIFACT_DIR")
    if artifact_root is not None:
        evidence_root = Path(artifact_root) / "browser"
        evidence_root.mkdir(parents=True, exist_ok=True)
        (evidence_root / "workspace-direct-download-evidence.json").write_text(
            _WorkspaceDownloadEvidence(
                web_status=redirect.status_code,
                filename=filename,
                size=len(browser_bytes),
                expected_sha256=digest,
                browser_sha256=hashlib.sha256(browser_bytes).hexdigest(),
            ).model_dump_json(indent=2),
            encoding="utf-8",
        )
