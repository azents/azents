"""One browser-only switch keeps the existing Runtime shell alive."""

from __future__ import annotations

import base64
import time

import azentsadminclient
import azentspublicclient
import requests
from azents_runtime_control.browser_viewer_contract import ViewerTarget
from azentspublicclient.api.browser_v1_api import BrowserV1Api
from azentspublicclient.models.agent_browser_configuration import (
    AgentBrowserConfiguration,
)
from azentspublicclient.models.browser_implementation import BrowserImplementation
from azentspublicclient.models.browser_projection_response import (
    BrowserProjectionResponse,
)

from support.session_browser import BrowserSocket
from tests.required.public.test_runtime_terminal import (
    _MAIN_WEB_ORIGIN,
    _create_workspace,
    _headers,
    _marked_value,
    _start_runtime,
    _TerminalSocket,
    _TerminalWorkspace,
)

_SERVER = '''
import http.server
HTML = b"""<!doctype html><title>Browser fixture</title><script>
document.title=navigator.userAgent.includes('Firefox')?'Camoufox':'Patchright';
</script>"""
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type','text/html')
        self.send_header('Content-Length',str(len(HTML)))
        self.end_headers()
        self.wfile.write(HTML)
    def log_message(self,*args):
        pass
with http.server.ThreadingHTTPServer(('127.0.0.1',8765),Handler) as server:
    print('BROWSER_HTTP_'+'READY',flush=True)
    server.serve_forever()
'''


def _settings_path(workspace: _TerminalWorkspace) -> str:
    return (
        f"/agent/v1/workspaces/{workspace.handle}/agents/{workspace.agent_id}"
        "/browser-configuration"
    )


def _ready(
    server: str, workspace: _TerminalWorkspace, implementation: BrowserImplementation
) -> AgentBrowserConfiguration:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        response = requests.get(
            server + _settings_path(workspace),
            headers=_headers(workspace.token),
            timeout=10,
        )
        response.raise_for_status()
        current = AgentBrowserConfiguration.model_validate_json(response.text)
        if current.state == "ready" and current.applied is implementation:
            return current
        assert current.state != "failed", current.reason_code
        time.sleep(0.25)
    raise AssertionError("Current requested browser did not become ready")


def _resource(workspace: _TerminalWorkspace) -> str:
    return (
        f"/browser/v1/workspaces/{workspace.handle}/agents/{workspace.agent_id}"
        f"/sessions/{workspace.session_id}"
    )


def _projection(
    server: str, workspace: _TerminalWorkspace
) -> BrowserProjectionResponse:
    response = requests.get(
        server + _resource(workspace), headers=_headers(workspace.token), timeout=10
    )
    response.raise_for_status()
    return BrowserProjectionResponse.model_validate_json(response.text)


def _open_fixture(
    client: azentspublicclient.ApiClient,
    server: str,
    workspace: _TerminalWorkspace,
    expected_title: str,
) -> BrowserSocket:
    page = (
        BrowserV1Api(client)
        .browser_v1_create_browser_page(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            session_id=workspace.session_id,
            body={},
            _headers=_headers(workspace.token),
        )
        .page
    )
    socket = BrowserSocket.open(
        public_url=server,
        token=workspace.token,
        resource_path=_resource(workspace),
        target=ViewerTarget(page.task_id, page.id, page.resource_incarnation),
        origin=_MAIN_WEB_ORIGIN,
    )
    try:
        frame = socket.next_frame()
        acknowledgement = socket.input(
            {
                "kind": "navigation",
                "action": "navigate",
                "url": "http://127.0.0.1:8765/",
            },
            source=frame.source,
        )
        assert acknowledgement.accepted, acknowledgement.reason_code
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            titles = [
                item.title
                for task in _projection(server, workspace).tasks
                for item in task.pages
            ]
            if expected_title in titles:
                socket.next_frame()
                return socket
            time.sleep(0.25)
        raise AssertionError(f"Native engine did not render {expected_title!r}")
    except BaseException:
        socket.close()
        raise


def test_browser_switch_preserves_runtime_shell(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
) -> None:
    server = azents_public_server_url
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=server,
    )
    response = requests.patch(
        f"{server}/agent/v1/workspaces/{workspace.handle}/agents/{workspace.agent_id}",
        headers=_headers(workspace.token),
        json={"browser_enabled": True},
        timeout=10,
    )
    response.raise_for_status()
    _start_runtime(
        public_api_client=public_api_client, workspace=workspace, server_url=server
    )
    before = _ready(server, workspace, BrowserImplementation.PATCHRIGHT)
    terminal = _TerminalSocket.connect(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=server,
        origin=_MAIN_WEB_ORIGIN,
    )
    browser: BrowserSocket | None = None
    try:
        encoded = base64.b64encode(_SERVER.encode()).decode()
        terminal.command(
            f"printf '%s' '{encoded}' | base64 -d > browser-choice-fixture.py",
            "BROWSER_FILE_WRITTEN",
        )
        terminal.send(
            b"python browser-choice-fixture.py & export BROWSER_CHOICE_JOB=$!\n"
        )
        terminal.wait_for_output(b"BROWSER_HTTP_READY")
        output = terminal.command(
            "printf '__P''ID__%s__' \"$$\"", "BROWSER_SHELL_READY"
        )
        shell_pid = _marked_value(output, "PID")
        browser = _open_fixture(public_api_client, server, workspace, "Patchright")
        response = requests.put(
            server + _settings_path(workspace),
            headers=_headers(workspace.token),
            json={
                "expected_intent_id": before.intent_id,
                "implementation": "camoufox",
                "retry": False,
            },
            timeout=90,
        )
        response.raise_for_status()
        after = _ready(server, workspace, BrowserImplementation.CAMOUFOX)
        assert (after.runtime_id, after.runner_generation) == (
            before.runtime_id,
            before.runner_generation,
        )
        assert not _projection(server, workspace).tasks
        browser.close()
        output = terminal.command(
            "kill -0 \"$BROWSER_CHOICE_JOB\" && printf '__P''ID__%s__' \"$$\"",
            "BROWSER_SHELL_CONTINUED",
        )
        assert _marked_value(output, "PID") == shell_pid
        browser = _open_fixture(public_api_client, server, workspace, "Camoufox")
        terminal.command('kill "$BROWSER_CHOICE_JOB"', "BROWSER_JOB_CLEANED")
    finally:
        if browser is not None:
            browser.close()
        terminal.close()
