"""Engine-created Browser task, native viewer, input and fresh reconnection E2E."""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlencode

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azents_runtime_control.browser_viewer_contract import ViewerTarget
from azentspublicclient.models.browser_page_response import BrowserPageResponse
from azentspublicclient.models.browser_projection_response import (
    BrowserProjectionResponse,
)
from azentspublicclient.models.password_login_response import PasswordLoginResponse
from azentspublicclient.models.subagent_tree_node_response import (
    SubagentTreeNodeResponse,
)
from azentspublicclient.models.subagent_tree_response import SubagentTreeResponse
from azentspublicclient.models.ws_ticket_response import WsTicketResponse
from pydantic import BaseModel, ConfigDict, Field
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect
from websockets.typing import Origin, Subprotocol

from support.session_browser import BrowserSocket
from support.utils import authenticate_user, unique, wait_until
from tests.required.public.test_runtime_terminal import _TerminalWorkspace
from tests.web.public.test_model_execution_options import _login_main_web
from tests.web.public.test_runtime_web_gateway import (
    _create_workspace,
    _RuntimeApplicationCommands,
)

_ORIGIN = "https://azents-web-gateway:8443"
_MESSAGE = "Open the synthetic Session Browser handoff"


class _DisplayedImage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: int = Field(ge=1)
    height: int = Field(ge=1)


_APP = '''
import http.server
import socketserver

HTML = b"""<!doctype html><title>Synthetic Browser ready</title>
<style>body{margin:0;background:white}button,input{position:absolute;left:20px;
width:200px;height:40px;box-sizing:border-box}button{top:20px}
#entry{top:100px}#secret{top:180px}</style>
<button onclick="alert('Synthetic handoff');document.title='Browser handoff completed'">
Continue</button><input id="entry" oninput="document.title=
this.value.includes('Synthetic GUI input')?String.fromCodePoint(0x2705):
String.fromCodePoint(0x270f,0xfe0f)">
<input id="secret" type="password" value="synthetic-password-canary">
<button style="top:260px" onclick="document.title='Browser GUI pointer verified'">
Verify GUI</button>
"""
class Handler(http.server.BaseHTTPRequestHandler):
    count = 0
    def do_GET(self):
        Handler.count += 1
        body = HTML
        if self.path == '/navigation':
            body = HTML.replace(b'Synthetic Browser ready',
                ('Navigation ' + str(Handler.count)).encode())
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass
with socketserver.TCPServer(('127.0.0.1', 8766), Handler) as server:
    server.serve_forever()
'''


def _enable_browser(public_url: str, handle: str, agent_id: str, token: str) -> None:
    response = requests.patch(
        f"{public_url}/agent/v1/workspaces/{handle}/agents/{agent_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"browser_enabled": True},
        timeout=10,
    )
    response.raise_for_status()
    assert response.json()["browser_enabled"] is True


def _projection(
    public_url: str, resource_path: str, token: str
) -> BrowserProjectionResponse:
    response = requests.get(
        f"{public_url}{resource_path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    response.raise_for_status()
    return BrowserProjectionResponse.model_validate(response.json())


def _start_application(commands: _RuntimeApplicationCommands) -> None:
    encoded = base64.b64encode(_APP.encode()).decode()
    script = f"""
import base64
import socket
import subprocess
import sys
import time
subprocess.Popen(
    [sys.executable, '-c', base64.b64decode('{encoded}').decode()],
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL, start_new_session=True,
)
deadline = time.monotonic() + 15
while True:
    try:
        connection = socket.create_connection(('127.0.0.1', 8766), timeout=1)
    except OSError:
        if time.monotonic() >= deadline:
            raise
        time.sleep(0.1)
    else:
        connection.close()
        print('SESSION_BROWSER_APP_READY')
        break
"""
    payload = base64.b64encode(script.encode()).decode()
    output = commands.command(
        "python -c \"import base64;exec(base64.b64decode('" + payload + "'))\"",
        f"SESSION_BROWSER_SETUP_{unique()}",
    )
    assert b"SESSION_BROWSER_APP_READY" in output
    commands.terminate()


def _find_observer(nodes: list[SubagentTreeNodeResponse]) -> str | None:
    for node in nodes:
        if node.name == "browser_observer":
            return node.agent_session_id
        child = _find_observer(node.children or [])
        if child is not None:
            return child
    return None


def _expect_rejected_attach(
    *,
    public_url: str,
    resource_path: str,
    token: str,
    target: ViewerTarget,
    expected_code: int,
) -> None:
    """Require rejection before even one status or native image is returned."""
    response = requests.post(
        f"{public_url}/chat/v1/ticket",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    response.raise_for_status()
    ticket = WsTicketResponse.model_validate(response.json()).ticket
    websocket_url = public_url.replace("http://", "ws://").replace("https://", "wss://")
    with connect(
        f"{websocket_url}{resource_path}/ws",
        origin=Origin(_ORIGIN),
        subprotocols=[Subprotocol("azents.browser.v1")],
        open_timeout=10,
    ) as connection:
        connection.send(
            json.dumps({"type": "attach", "ticket": ticket, "target": asdict(target)})
        )
        with pytest.raises(ConnectionClosed) as closed:
            connection.recv(timeout=15)
        assert closed.value.rcvd is not None
        assert closed.value.rcvd.code == expected_code


def _verify_live_panel(
    *,
    driver: WebDriver,
    web_url: str,
    public_url: str,
    resource_path: str,
    token: str,
    email: str,
    handle: str,
    agent_id: str,
    session_id: str,
    target: ViewerTarget,
) -> None:
    """Cross the real login, BFF, public socket and native input boundaries."""
    _login_main_web(driver, base_url=web_url, email=email)
    query = urlencode(
        {
            "page": "browser",
            "browserTaskId": target.task_id,
            "browserPageId": target.page_id,
            "browserIncarnation": target.resource_incarnation,
        }
    )
    driver.get(f"{web_url}/w/{handle}/agents/{agent_id}/sessions/{session_id}?{query}")
    assert (
        driver.execute_script(
            "return new URLSearchParams(window.location.search).get('browserTaskId');"
        )
        == target.task_id
    )
    wait = WebDriverWait(driver, 60)
    viewport = wait.until(
        ec.visibility_of_element_located(
            (By.CSS_SELECTOR, '[aria-label="Remote browser page"][data-stale="false"]')
        )
    )
    image_query = "document.querySelector('[aria-label=\"Remote browser page\"] img')"
    dimensions = _DisplayedImage.model_validate(
        wait.until(
            lambda _: driver.execute_script(
                f"const image = {image_query}; "
                "return image !== null && image.complete && "
                "image.naturalWidth > 0 && image.naturalHeight > 0 "
                "? {width: image.naturalWidth, height: image.naturalHeight} : null;"
            )
        )
    )
    width, height = dimensions.width, dimensions.height
    scale = min(viewport.size["width"] / width, viewport.size["height"] / height)

    def click_native(x: int, y: int) -> None:
        ActionChains(driver).move_to_element_with_offset(
            viewport,
            int((x - width / 2) * scale),
            int((y - height / 2) * scale),
        ).click().perform()

    def title_is(expected: str) -> bool:
        projection = _projection(public_url, resource_path, token)
        return projection.tasks[0].pages[0].title == expected

    click_native(100, 280)
    wait_until(
        lambda: title_is("Browser GUI pointer verified"),
        timeout=15,
        interval=0.1,
        message="The authenticated Web panel pointer did not reach the native page",
    )
    click_native(100, 120)
    wait.until(
        lambda _: driver.execute_script(
            "return document.activeElement?.getAttribute('aria-label') "
            "=== 'Remote browser keyboard';"
        )
    )
    ActionChains(driver).send_keys("Synthetic GUI input").perform()
    wait_until(
        lambda: title_is("✅"),
        timeout=15,
        interval=0.1,
        message="The Web panel did not deliver the complete keyboard text",
    )
    address = wait.until(
        ec.element_to_be_clickable(
            (By.CSS_SELECTOR, 'input[aria-label="Browser address"]:not([readonly])')
        )
    )
    address.send_keys(Keys.CONTROL, "a")
    address.send_keys("http://127.0.0.1:8766/navigation", Keys.ENTER)

    def current_page() -> BrowserPageResponse:
        projection = _projection(public_url, resource_path, token)
        return projection.tasks[0].pages[0]

    def wait_destination(path: str) -> None:
        wait_until(
            lambda: current_page().url == f"http://127.0.0.1:8766{path}",
            timeout=15,
            interval=0.1,
            message="The browser navigation control did not change the native page",
        )
        wait.until(
            ec.element_to_be_clickable(
                (By.CSS_SELECTOR, 'button[aria-label="Reload page"]:not(:disabled)')
            )
        )

    wait_destination("/navigation")
    wait.until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, 'button[aria-label="Go back"]'))
    ).click()
    wait_destination("/")
    wait.until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, 'button[aria-label="Go forward"]'))
    ).click()
    wait_destination("/navigation")
    previous_title = current_page().title
    wait.until(
        ec.element_to_be_clickable(
            (By.CSS_SELECTOR, 'button[aria-label="Reload page"]')
        )
    ).click()
    try:
        wait_until(
            lambda: current_page().title != previous_title,
            timeout=15,
            interval=0.1,
            message="Reload did not request a fresh native page response",
        )
    except TimeoutError as error:
        diagnostic = driver.execute_script("""
const viewport = document.querySelector('[aria-label="Remote browser page"]');
let fiber = viewport &&
  viewport[Object.keys(viewport).find(key => key.startsWith('__reactFiber$'))];
for (let depth = 0; fiber && depth < 100; depth++, fiber = fiber.return) {
  const props = fiber.memoizedProps;
  if (props?.state?.type === 'READY') {
    return {connection: props.state.connection, input: props.state.canInput,
      navigationEnabled: props.navigationEnabled, conflict: props.state.conflict,
      outcomeUnknown: props.state.outcomeUnknown, image: !!props.state.image};
  }
}
return {ready: false};
""")
        raise AssertionError(
            f"Native reload outcome was not observed; bounded UI state: {diagnostic}"
        ) from error
    artifact_directory = os.environ.get("AZENTS_E2E_ARTIFACT_DIR")
    if artifact_directory is not None:
        artifacts = Path(artifact_directory)
        artifacts.mkdir(parents=True, exist_ok=True)
        assert driver.save_screenshot(str(artifacts / "session-browser-desktop.png"))
    driver.set_window_size(390, 844)
    wait.until(
        ec.visibility_of_element_located(
            (By.CSS_SELECTOR, '[aria-label="Remote browser page"][data-stale="false"]')
        )
    )
    assert driver.execute_script(
        "return document.documentElement.scrollWidth <= window.innerWidth;"
    )
    if artifact_directory is not None:
        assert driver.save_screenshot(
            str(Path(artifact_directory) / "session-browser-mobile-viewport.png")
        )
    driver.get(f"{web_url}/w/{handle}/agents/{agent_id}/sessions/{session_id}")


def test_session_browser_engine_native_input_dialog_and_reconnect(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_runtime_provider_docker_container: object,
    mock_openai_url: str,
    browser_driver: WebDriver,
    azents_main_web_url: str,
) -> None:
    """Exercise authenticated API/Control/Owner/Runner without pre-admitted state."""
    del azents_runtime_provider_docker_container, mock_openai_url
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
    )
    resource_path = (
        f"/browser/v1/workspaces/{workspace.handle}/agents/{workspace.agent_id}"
        f"/sessions/{workspace.session_id}"
    )
    headers = {"Authorization": f"Bearer {workspace.token}"}
    disabled = _projection(azents_public_server_url, resource_path, workspace.token)
    assert not disabled.available
    assert disabled.tasks == []
    _enable_browser(
        azents_public_server_url, workspace.handle, workspace.agent_id, workspace.token
    )
    commands = _RuntimeApplicationCommands(
        public_api_client=public_api_client,
        workspace=_TerminalWorkspace(
            token=workspace.token,
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            session_id=workspace.session_id,
        ),
        server_url=azents_public_server_url,
    )
    _start_application(commands)
    empty = _projection(azents_public_server_url, resource_path, workspace.token)
    assert empty.tasks == []
    write = requests.post(
        f"{azents_public_server_url}/chat/v1/sessions/{workspace.session_id}/inputs",
        headers=headers,
        json={
            "agent_id": workspace.agent_id,
            "client_request_id": f"session-browser-open-{unique()}",
            "message": _MESSAGE,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    write.raise_for_status()

    def opened() -> ViewerTarget | None:
        projection = _projection(
            azents_public_server_url, resource_path, workspace.token
        )
        if not projection.tasks:
            return None
        assert projection.available
        assert projection.allow_input
        assert len(projection.tasks) == 1
        task = projection.tasks[0]
        if not task.pages or task.pages[0].title != "Synthetic Browser ready":
            return None
        assert len(task.pages) == 1
        page = task.pages[0]
        return ViewerTarget(task.id, page.id, page.resource_incarnation)

    target = wait_until(
        opened,
        timeout=120,
        interval=0.2,
        message="Engine browser_open did not create the synthetic task",
    )
    assert target is not None
    outsider = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"browser-outsider-{unique()}@example.com",
    )
    _expect_rejected_attach(
        public_url=azents_public_server_url,
        resource_path=resource_path,
        token=outsider.access_token,
        target=target,
        expected_code=4403,
    )

    def observer_session() -> str | None:
        response = requests.get(
            f"{azents_public_server_url}/chat/v1/agents/{workspace.agent_id}"
            f"/sessions/{workspace.session_id}/subagents/tree",
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        tree = SubagentTreeResponse.model_validate(response.json())
        return _find_observer(tree.nodes)

    child_session_id = wait_until(
        observer_session,
        timeout=60,
        interval=0.2,
        message="Engine did not expose the observer child Session",
    )
    assert child_session_id is not None
    child_resource = (
        f"/browser/v1/workspaces/{workspace.handle}/agents/{workspace.agent_id}"
        f"/sessions/{child_session_id}"
    )

    def child_opened() -> ViewerTarget | None:
        current = _projection(azents_public_server_url, child_resource, workspace.token)
        if not current.tasks or not current.tasks[0].pages:
            return None
        assert current.available
        assert not current.allow_input
        page = current.tasks[0].pages[0]
        if page.title != "Synthetic Browser ready":
            return None
        assert page.id != target.page_id
        return ViewerTarget(current.tasks[0].id, page.id, page.resource_incarnation)

    child_target = wait_until(
        child_opened,
        timeout=120,
        interval=0.2,
        message="Child Session browser_open did not create an observation task",
    )
    assert child_target is not None
    _expect_rejected_attach(
        public_url=azents_public_server_url,
        resource_path=resource_path,
        token=workspace.token,
        target=child_target,
        expected_code=4409,
    )
    observer = BrowserSocket.open(
        public_url=azents_public_server_url,
        token=workspace.token,
        resource_path=child_resource,
        target=child_target,
        origin=_ORIGIN,
    )
    try:
        assert observer.status is not None and not observer.status.allow_input
        assert observer.frame is not None
        with pytest.raises(ConnectionClosed) as denied:
            observer.input(
                {
                    "kind": "pointer",
                    "phase": "down",
                    "x": 100,
                    "y": 40,
                    "button": "left",
                },
                source=observer.frame.source,
            )
        assert denied.value.rcvd is not None
        assert denied.value.rcvd.code == 4403
        child_close = requests.post(
            f"{azents_public_server_url}{child_resource}/pages/{child_target.page_id}/close",
            headers=headers,
            json={
                "task_id": child_target.task_id,
                "resource_incarnation": child_target.resource_incarnation,
            },
            timeout=10,
        )
        assert child_close.status_code == 409
        unchanged = _projection(
            azents_public_server_url, child_resource, workspace.token
        )
        assert unchanged.tasks[0].pages[0].title == "Synthetic Browser ready"
    finally:
        observer.close()

    socket = BrowserSocket.open(
        public_url=azents_public_server_url,
        token=workspace.token,
        resource_path=resource_path,
        target=target,
        origin=_ORIGIN,
    )
    assert socket.status is not None
    first_attachment = socket.status.attachment_id
    try:
        assert socket.status.allow_input
        assert socket.frame is not None
        assert socket.frame.source.width >= 220
        assert socket.frame.source.height >= 220
        assert "synthetic-password-canary" not in socket.status.model_dump_json()
        socket.click(x=100, y=40)
        deadline = time.monotonic() + 15
        while socket.status is None or socket.status.dialog is None:
            if time.monotonic() >= deadline:
                raise TimeoutError("Human pointer did not open the synthetic dialog")
            socket.receive(timeout=max(0.01, deadline - time.monotonic()))
        assert socket.status.dialog.message == "Synthetic handoff"
        ack = socket.input(
            {
                "kind": "dialog",
                "dialog_id": socket.status.dialog.id,
                "accept": True,
                "text": None,
            },
            source=None,
        )
        assert ack.accepted, ack.reason_code

        def title_is(expected: str) -> bool:
            current = _projection(
                azents_public_server_url, resource_path, workspace.token
            )
            return current.tasks[0].pages[0].title == expected

        wait_until(
            lambda: title_is("Browser handoff completed"),
            timeout=15,
            interval=0.1,
            message="The site did not complete the accepted human dialog",
        )
        socket.next_frame()
        socket.click(x=100, y=120)
        assert socket.frame is not None
        for action in (
            {"kind": "composition", "phase": "start", "text": None},
            {"kind": "composition", "phase": "commit", "text": "Synthetic IME"},
        ):
            ack = socket.input(action, source=socket.frame.source)
            assert ack.accepted, ack.reason_code
        wait_until(
            lambda: title_is("✏️"),
            timeout=15,
            interval=0.1,
            message="The site did not observe committed human input",
        )
    finally:
        socket.close()

    reconnected = BrowserSocket.open(
        public_url=azents_public_server_url,
        token=workspace.token,
        resource_path=resource_path,
        target=target,
        origin=_ORIGIN,
    )
    try:
        assert reconnected.status is not None
        assert reconnected.status.attachment_id != first_attachment
        assert reconnected.frame is not None
        assert reconnected.frame.target == target
        _verify_live_panel(
            driver=browser_driver,
            web_url=azents_main_web_url,
            public_url=azents_public_server_url,
            resource_path=resource_path,
            token=workspace.token,
            email=workspace.email,
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            session_id=workspace.session_id,
            target=target,
        )
        logout = requests.post(
            f"{azents_public_server_url}/auth/v1/logout",
            headers=headers,
            timeout=10,
        )
        assert logout.status_code == 204
        deadline = time.monotonic() + 8
        with pytest.raises(ConnectionClosed) as revoked:
            while time.monotonic() < deadline:
                reconnected.receive(timeout=max(0.01, deadline - time.monotonic()))
        assert revoked.value.rcvd is not None
        assert revoked.value.rcvd.code in {4401, 4403}
        login = requests.post(
            f"{azents_public_server_url}/auth/v1/login/password",
            json={"email": workspace.email, "password": "TestPass123!"},
            timeout=10,
        )
        login.raise_for_status()
        fresh = PasswordLoginResponse.model_validate(login.json())
        preserved = _projection(
            azents_public_server_url, resource_path, fresh.access_token
        )
        assert any(
            page.id == target.page_id for task in preserved.tasks for page in task.pages
        )
        close = requests.post(
            f"{azents_public_server_url}{resource_path}/pages/{target.page_id}/close",
            headers={"Authorization": f"Bearer {fresh.access_token}"},
            json={
                "task_id": target.task_id,
                "resource_incarnation": target.resource_incarnation,
            },
            timeout=10,
        )
        close.raise_for_status()
        closed = BrowserProjectionResponse.model_validate(close.json())
        assert all(
            page.id != target.page_id for task in closed.tasks for page in task.pages
        )
        _expect_rejected_attach(
            public_url=azents_public_server_url,
            resource_path=resource_path,
            token=fresh.access_token,
            target=target,
            expected_code=4409,
        )
    finally:
        reconnected.close()
