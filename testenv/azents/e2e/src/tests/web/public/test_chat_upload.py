"""Real Chat composer file upload across Web, API, worker, and RustFS."""

import base64
import hashlib
import os
from pathlib import Path

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.models.upload_response import UploadResponse
from pydantic import BaseModel, ConfigDict
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.file_detector import LocalFileDetector
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from support.utils import create_agent_session_setup
from tests.web.public.test_workspace_settings_web import _login_main_web

# Observe real requests without replacing their responses, buffering file bodies,
# or retaining signed URLs. Install before app modules capture global fetch.
_OBSERVE_UPLOAD = """
(() => {
  const evidence = {
    workers: 0, worker_hashes: [], stages: [], prepare: null,
    prepare_body_type: null, put: null, finalized: null, failure: null
  };
  window.__chatUploadEvidence = evidence;
  const NativeWorker = window.Worker;
  window.Worker = class extends NativeWorker {
    constructor(...args) {
      super(...args);
      evidence.workers++;
      this.addEventListener("message", ({data}) => {
        if (data.type === "done" && typeof data.sha256 === "string") {
          evidence.worker_hashes.push(data.sha256);
        }
      });
    }
  };
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = new URL(typeof input === "string" ? input : input.url,
                        location.href);
    const method = (init?.method || "GET").toUpperCase();
    const prepare = url.origin === location.origin &&
                    url.pathname === "/api/chat/upload" && method === "POST";
    const finalize = url.origin === location.origin &&
                     /^\\/api\\/chat\\/upload\\/[^/]+\\/finalize$/.test(url.pathname);
    const directPut = url.origin !== location.origin && method === "PUT";
    if (prepare) {
      evidence.stages.push("prepare");
      evidence.prepare_body_type = typeof init.body;
      evidence.prepare = JSON.parse(init.body);
    }
    if (directPut) {
      evidence.stages.push("put");
      evidence.put = {
        file_body: init.body instanceof File,
        size: init.body.size,
        name: init.body.name,
        checksum: new Headers(init.headers).get("x-amz-checksum-sha256"),
        status: null
      };
    }
    if (finalize) evidence.stages.push("finalize");
    try {
      const response = await nativeFetch(input, init);
      if (directPut) evidence.put.status = response.status;
      if (finalize && response.ok) {
        evidence.finalized = await response.clone().json();
      }
      return response;
    } catch (error) {
      evidence.failure = error.name;
      throw error;
    }
  };
})();
"""


class _PreparedUpload(BaseModel):
    """Only metadata is permitted in the Next upload request."""

    model_config = ConfigDict(extra="forbid")
    agentId: str
    filename: str
    media_type: str
    size: int
    sha256: str


class _DirectPut(BaseModel):
    """Safe evidence of the native browser File request, with no capability."""

    file_body: bool
    size: int
    name: str
    checksum: str
    status: int


class _UploadObservation(BaseModel):
    """Validate the completed browser journey without private storage metadata."""

    workers: int
    worker_hashes: list[str]
    stages: list[str]
    prepare_body_type: str
    prepare: _PreparedUpload
    put: _DirectPut
    finalized: UploadResponse
    failure: str | None


def test_chat_composer_uploads_real_file_directly_then_publishes_attachment(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_public_server_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    tmp_path: Path,
) -> None:
    """Worker digest, CORS File PUT and finalize precede a usable attachment."""
    setup = create_agent_session_setup(
        public_api_client, admin_api_client, azents_public_server_url
    )
    content = b"Real Chat browser direct upload.\n" * 4096
    filename = "browser-direct-upload.txt"
    upload_path = tmp_path / filename
    upload_path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    _login_main_web(browser_driver, base_url=azents_main_web_url, email=setup.email)
    browser_driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument", {"source": _OBSERVE_UPLOAD}
    )
    browser_driver.get(
        f"{azents_main_web_url}/w/{setup.workspace_handle}/agents/{setup.agent_id}"
        f"/sessions/{setup.session_id}"
    )
    wait = WebDriverWait(browser_driver, 90, poll_frequency=0.2)
    composer = wait.until(ec.element_to_be_clickable((By.NAME, "chat-message")))
    browser_driver.file_detector = LocalFileDetector()
    file_input = wait.until(
        ec.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
    )
    file_input.send_keys(str(upload_path))
    composer.send_keys("Read this direct-upload attachment.")
    wait.until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='Send']"))
    ).click()
    wait.until(
        lambda driver: driver.execute_script(
            "return Boolean(window.__chatUploadEvidence?.finalized);"
        )
    )
    observation = _UploadObservation.model_validate(
        browser_driver.execute_script("return window.__chatUploadEvidence;")
    )
    assert observation.failure is None
    assert observation.workers >= 1
    assert digest in observation.worker_hashes
    assert observation.stages == ["prepare", "put", "finalize"]
    assert observation.prepare_body_type == "string"
    assert observation.prepare.agentId == setup.agent_id
    assert observation.prepare.filename == filename
    assert observation.prepare.media_type == "text/plain"
    assert observation.prepare.size == len(content)
    assert observation.prepare.sha256 == digest
    assert observation.put.file_body
    assert observation.put.size == len(content)
    assert observation.put.name == filename
    assert observation.put.checksum == base64.b64encode(bytes.fromhex(digest)).decode()
    assert observation.put.status == 200
    assert observation.finalized.size == len(content)
    assert observation.finalized.name == filename
    assert observation.finalized.uri.startswith("exchange://")
    downloaded = requests.get(
        f"{azents_public_server_url}/chat/v1/exchange-files/"
        f"{observation.finalized.attachment_id}/download",
        headers={"Authorization": f"Bearer {setup.access_token}"},
        timeout=30,
    )
    assert downloaded.status_code == 200
    assert downloaded.content == content
    artifact_root = os.environ.get("AZENTS_E2E_ARTIFACT_DIR")
    if artifact_root is not None:
        browser_artifacts = Path(artifact_root) / "browser"
        browser_artifacts.mkdir(parents=True, exist_ok=True)
        (browser_artifacts / "chat-direct-upload-evidence.json").write_text(
            observation.model_dump_json(indent=2), encoding="utf-8"
        )
