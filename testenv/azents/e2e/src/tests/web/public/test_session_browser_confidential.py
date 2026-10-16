"""Actual Skill import and Runtime encryption reach native Browser fill value-free."""

import hashlib
import json

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.models.agent_runtime_response import AgentRuntimeResponse
from testcontainers.core.container import DockerContainer

from support.browser_confidential_fixture import (
    FINAL,
    PREFIX,
    PROMPT,
    REPLACEMENT_PREFIX,
    REPLACEMENT_PROMPT,
    decode_output,
)
from support.observations import HistoryEventObservation, ToolResultObservation
from support.runtime_profiles import start_and_wait_for_agent_runtime
from support.utils import unique, wait_until
from tests.required.public.test_agent_execution_persistence import (
    history_events,
    list_history,
)
from tests.required.public.test_per_prompt_inference_profile import _setup_profile_agent
from tests.required.public.test_runtime_terminal import (
    _prepare_terminal_session,
    _TerminalWorkspace,
)
from tests.web.public.test_runtime_web_gateway import _RuntimeApplicationCommands
from tests.web.public.test_session_browser import (
    _enable_browser,
    _start_application_source,
)
from tests.web.public.test_session_browser_files import _parts

_APP = '''
import http.server
import socketserver

HTML = b"""<!doctype html><title>Confidential input ready</title>
<input id=account aria-label="Confidential account" oninput="verify()">
<input id=password aria-label="Confidential password" type=password oninput="verify()">
<script>function verify(){
const value=document.querySelector('#account').value+String.fromCharCode(0)+
document.querySelector('#password').value;
crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)).then(b=>{
const hash=Array.from(new Uint8Array(b),v=>v.toString(16).padStart(2,'0')).join('');
document.title=hash==='EXPECTED_HASH'?'Confidential input verified':'Input pending';
if(hash==='EXPECTED_HASH')location.hash='verified';
})}</script>"""
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type','text/html')
        self.send_header('Content-Length',str(len(HTML)))
        self.end_headers()
        self.wfile.write(HTML)
    def log_message(self,*args):
        pass
socketserver.TCPServer.allow_reuse_address=True
with socketserver.TCPServer(('127.0.0.1',8766),Handler) as server:
    server.serve_forever()
'''


def test_confidential_environment_input_through_skill_and_native_browser(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_runtime_provider_docker_container: object,
    azents_engine_worker_container: DockerContainer,
    azents_public_server_container: DockerContainer,
    azents_runtime_control_container: DockerContainer,
) -> None:
    del azents_runtime_provider_docker_container
    handle = f"browser-confidential-{unique()}"
    token, agent_id, session_id = _setup_profile_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        workspace_handle=handle,
    )
    workspace = _TerminalWorkspace(
        token=token, handle=handle, agent_id=agent_id, session_id=session_id
    )
    headers = {"Authorization": f"Bearer {token}"}
    canary = f"synthetic-confidential-{unique()}"
    account = f"synthetic-account-{unique()}@example.test"
    expected = hashlib.sha256((account + "\0" + canary).encode()).hexdigest()
    response = requests.put(
        f"{azents_public_server_url}/agent-runtime/v1/workspaces/{handle}"
        f"/agents/{agent_id}/runtime/environment",
        headers=headers,
        json={
            "entries": [
                {
                    "name": "E2E_BROWSER_PASSWORD",
                    "value": {"type": "replace", "value": canary},
                },
                {
                    "name": "E2E_BROWSER_ACCOUNT",
                    "value": {"type": "replace", "value": account},
                },
            ]
        },
        timeout=10,
    )
    response.raise_for_status()
    if any(value in response.text for value in (canary, account)):
        pytest.fail("Environment response disclosed plaintext", pytrace=False)
    _enable_browser(azents_public_server_url, handle, agent_id, token)
    _prepare_terminal_session(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
    )
    commands = _RuntimeApplicationCommands(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
    )
    _start_application_source(commands, _APP.replace("EXPECTED_HASH", expected))
    response = requests.post(
        f"{azents_public_server_url}/chat/v1/sessions/{session_id}/inputs",
        headers=headers,
        json={
            "agent_id": agent_id,
            "client_request_id": f"browser-confidential-{unique()}",
            "message": PROMPT,
            "inference_profile": {
                "model_target_label": "Quality",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    response.raise_for_status()

    def results(prefix: str) -> dict[str, ToolResultObservation]:
        output: dict[str, ToolResultObservation] = {}
        for raw in history_events(
            list_history(
                server_url=azents_public_server_url, token=token, session_id=session_id
            )
        ):
            event = HistoryEventObservation.model_validate(raw)
            if event.kind != "client_tool_result":
                continue
            result = ToolResultObservation.model_validate(event.payload)
            if result.call_id.startswith(prefix):
                output[result.call_id.removeprefix(prefix)] = result
        return output

    wait_until(
        lambda: "verify" in results(PREFIX),
        timeout=180,
        interval=0.3,
        message="Confidential Browser journey did not complete",
    )
    observed = results(PREFIX)
    assert {
        "skill",
        "import",
        "encrypt",
        "open",
        "observe",
        "fill",
        "account_encrypt",
        "account_fill",
        "verify",
    } <= (observed.keys())
    assert all(result.status == "completed" for result in observed.values())
    texts = [part.text for part in _parts(observed["verify"]) if part.text]
    verified = json.loads(texts[0])
    assert verified["page"]["title"] == "Confidential input verified"
    wait_until(
        lambda: (
            FINAL
            in json.dumps(
                list_history(
                    server_url=azents_public_server_url,
                    token=token,
                    session_id=session_id,
                )
            )
        ),
        timeout=30,
        interval=0.2,
        message="Initial confidential Browser Run did not finish its final response",
    )
    process_outputs = [
        decode_output(PREFIX + stage, result.output)
        for stage, result in observed.items()
        if stage == "encrypt" or stage.startswith("poll")
    ]
    old_ciphertext = "".join(
        item.stdout for item in process_outputs if item is not None
    ).strip()
    assert old_ciphertext
    runtime_url = (
        f"{azents_public_server_url}/agent-runtime/v1/workspaces/{handle}"
        f"/agents/{agent_id}/runtime"
    )
    before = requests.get(runtime_url, headers=headers, timeout=10)
    before.raise_for_status()
    before_state = AgentRuntimeResponse.model_validate(before.json())
    assert before_state.runtime is not None
    restarted = requests.post(runtime_url + "/restart", headers=headers, timeout=10)
    restarted.raise_for_status()
    start_and_wait_for_agent_runtime(
        public_api_client, token=token, workspace_handle=handle, agent_id=agent_id
    )
    after = requests.get(runtime_url, headers=headers, timeout=10)
    after.raise_for_status()
    after_state = AgentRuntimeResponse.model_validate(after.json())
    assert after_state.runtime is not None
    assert (
        after_state.runtime.desired_generation > before_state.runtime.desired_generation
    )
    _prepare_terminal_session(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
    )
    commands = _RuntimeApplicationCommands(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
    )
    _start_application_source(commands, _APP.replace("EXPECTED_HASH", expected))
    resumed = requests.post(
        f"{azents_public_server_url}/chat/v1/sessions/{session_id}/inputs",
        headers=headers,
        json={
            "agent_id": agent_id,
            "client_request_id": f"browser-confidential-replacement-{unique()}",
            "message": REPLACEMENT_PROMPT + old_ciphertext,
            "inference_profile": {
                "model_target_label": "Quality",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    resumed.raise_for_status()
    wait_until(
        lambda: "verify" in results(REPLACEMENT_PREFIX),
        timeout=180,
        interval=0.3,
        message="Confidential Browser key-loss recovery did not complete",
    )
    replacement_results = results(REPLACEMENT_PREFIX)
    assert replacement_results["oldfill"].status == "failed"
    assert all(
        result.status == "completed"
        for stage, result in replacement_results.items()
        if stage != "oldfill"
    )
    texts = [part.text for part in _parts(replacement_results["verify"]) if part.text]
    assert json.loads(texts[0])["page"]["title"] == "Confidential input verified"
    history = list_history(
        server_url=azents_public_server_url, token=token, session_id=session_id
    )
    # Keep assertion output value-free even on failure.
    if any(value in json.dumps(history) for value in (canary, account)):
        pytest.fail("Plaintext appeared in Session history", pytrace=False)
    for container in (
        azents_engine_worker_container,
        azents_public_server_container,
        azents_runtime_control_container,
    ):
        if any(
            value.encode() in chunk
            for chunk in container.get_logs()
            for value in (canary, account)
        ):
            pytest.fail("Plaintext appeared in service diagnostics", pytrace=False)
    assert "encrypted_text" in json.dumps(history)
