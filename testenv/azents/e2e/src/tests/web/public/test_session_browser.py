"""Engine-created Browser task, native viewer, input and fresh reconnection E2E."""

from __future__ import annotations

import base64
import json
import time
import zlib
from dataclasses import asdict
from urllib.parse import urlencode

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azents_runtime_control.browser_viewer_contract import ViewerSource, ViewerTarget
from azentspublicclient.models.agent_runtime_response import AgentRuntimeResponse
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
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait
from testcontainers.core.container import DockerContainer
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


class _BrowserEnabledObservation(BaseModel):
    """Consume current capability evidence without inspecting response extensions."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    browser_enabled: StrictBool


_APP = '''
import http.server

HTML = b"""<!doctype html>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Synthetic Browser ready</title>
<style>body{margin:0;background:white}button,input{position:absolute;left:20px;
width:200px;height:40px;box-sizing:border-box}button{top:20px}
#entry{top:100px}#secret{top:180px;border-radius:8px}
#email{top:340px}#manual{top:420px}</style>
<button onclick="alert('Synthetic handoff');document.title='Browser handoff completed'">
Continue</button><input id="entry" oninput="document.title=
this.value.includes('Synthetic GUI input')?String.fromCodePoint(0x2705):
String.fromCodePoint(0x270f,0xfe0f)">
<input id="secret" type="password" value="synthetic-password-canary"
oninput="document.title=this.value==='Synthetic GUI edit value'?
'Browser GUI edit verified':this.value==='Synthetic GUI paste value'?
'Browser GUI paste verified':'Browser GUI paste mismatch'">
<button style="top:260px" onclick="document.title='Browser GUI pointer verified'">
Verify GUI</button>
<input id=email type=email inputmode=email autocomplete=email name=contact
autocapitalize=off autocorrect=off spellcheck=false enterkeyhint=next maxlength=80
value='reader@example.test'>
<input id=manual inputmode=none
onfocus="document.title='Browser manual focus verified'"
oninput="document.title=this.value==='Synthetic manual input'?
'Browser manual keyboard verified':'Browser manual input pending'">
<button style="top:500px" onclick="document.title='Control memory '+
window.controlCanary+':'+(++window.controlClicks)">Reconnect canary</button>
<script>
window.controlCanary = crypto.randomUUID();
window.controlClicks = 0;
if (navigator.webdriver || /HeadlessChrome/.test(navigator.userAgent) ||
    /HeadlessChrome/.test(navigator.appVersion) ||
    (navigator.userAgentData?.brands || []).some(b => /HeadlessChrome/.test(b.brand))) {
  document.title = 'Browser automation markers exposed';
}
</script>
"""
class Handler(http.server.BaseHTTPRequestHandler):
    count = 0
    def do_GET(self):
        Handler.count += 1
        body = HTML
        if any('HeadlessChrome' in self.headers.get(name, '')
               for name in ('User-Agent', 'sec-ch-ua')):
            body = body.replace(b'Synthetic Browser ready',
                                b'Browser automation headers exposed')
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
# Chromium can hold an idle speculative connection while navigating on another.
with http.server.ThreadingHTTPServer(('127.0.0.1', 8766), Handler) as server:
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
    assert (
        _BrowserEnabledObservation.model_validate(response.json()).browser_enabled
        is True
    )


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
    _start_application_source(commands, _APP)


def _start_application_source(
    commands: _RuntimeApplicationCommands, application: str
) -> None:
    encoded = base64.b64encode(application.encode()).decode()
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
    # Fixture uploads must not burst PTY echo/output ACKs as the page grows.
    commands.command("stty -echo", f"SESSION_BROWSER_QUIET_{unique()}")
    payload = base64.b64encode(zlib.compress(script.encode())).decode()
    output = commands.command(
        "python -c \"import base64,zlib;exec(zlib.decompress(base64.b64decode('"
        + payload
        + "')))\"",
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
    source: ViewerSource,
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
    wait = WebDriverWait(driver, 60, poll_frequency=0.1)
    preview = wait.until(
        ec.element_to_be_clickable(
            (
                By.CSS_SELECTOR,
                '[aria-label="Remote browser page"] button[aria-label="Focus browser"]',
            )
        )
    )
    preview.click()
    wait.until(
        ec.visibility_of_element_located(
            (By.CSS_SELECTOR, '[role="dialog"][aria-label="Focus browser"]')
        )
    )
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
    assert dimensions.width == source.width * 2
    assert dimensions.height == source.height * 2

    def click_native(x: int, y: int) -> None:
        rect = viewport.rect
        scale = rect["width"] / source.width
        # WebDriver's element origin clips the center of a scrollable image.
        # Native coordinates use the logical input plane, not raster density.
        mouse = ActionBuilder(driver)
        mouse.pointer_action.move_to_location(
            int(rect["x"] + x * scale), int(rect["y"] + y * scale)
        )
        mouse.pointer_action.pointer_down()
        mouse.pointer_action.pointer_up()
        mouse.perform()

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
    try:
        wait_until(
            lambda: title_is("✅"),
            timeout=15,
            interval=0.1,
            message="The Web panel did not deliver the complete keyboard text",
        )
    except TimeoutError as error:
        # Content-free UI evidence distinguishes input loss from route/focus loss.
        diagnostics = driver.execute_script(
            """return {
                targetSelected: new URLSearchParams(location.search)
                    .has('browserPageId'),
                keyboardFocused: document.activeElement?.getAttribute('aria-label')
                    === 'Remote browser keyboard',
                keyboardPresent: !!document.querySelector(
                    'textarea[aria-label="Remote browser keyboard"]'),
                imagePresent: !!document.querySelector(
                    '[aria-label="Remote browser page"] img')
            };"""
        )
        error.add_note(json.dumps(diagnostics, sort_keys=True))
        raise
    click_native(100, 200)
    wait.until(
        lambda _: driver.execute_script(
            "return document.activeElement?.hasAttribute('data-browser-native-input');"
        )
    )
    ActionChains(driver).key_down(Keys.CONTROL).send_keys("a").key_up(
        Keys.CONTROL
    ).perform()
    # Synthetic event data exercises UI -> authenticated stream -> native password
    # insertion, not host clipboard permissions or OS consent UI.
    driver.execute_script("""
const data = new DataTransfer();
data.setData('text/plain', 'Synthetic GUI paste value');
document.activeElement.dispatchEvent(new ClipboardEvent('paste', {
  bubbles: true, cancelable: true, clipboardData: data
}));
""")
    wait_until(
        lambda: title_is("Browser GUI paste verified"),
        timeout=15,
        interval=0.1,
        message="The Web panel paste did not reach the native password input",
    )
    edit_button = (
        By.XPATH,
        '//*[@data-browser-input-toolbar]//button[normalize-space(.)="Edit"]',
    )
    wait.until(ec.element_to_be_clickable(edit_button)).click()
    editor_input = (
        By.CSS_SELECTOR,
        '[data-browser-field-editor] input[type="password"]',
    )
    local = wait.until(ec.visibility_of_element_located(editor_input))
    assert local.get_attribute("value") == "Synthetic GUI paste value"
    # Native deletion updates the controlled draft, unlike WebDriver clear().
    local.send_keys(Keys.CONTROL, "a", Keys.NULL, Keys.BACKSPACE)
    local.send_keys("Discard this synthetic edit")
    assert local.get_attribute("value") == "Discard this synthetic edit"
    wait.until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                '//*[@data-browser-field-editor]//button[normalize-space(.)="Cancel"]',
            )
        )
    ).click()
    wait.until(
        lambda _: (
            not driver.find_elements(By.CSS_SELECTOR, "[data-browser-field-editor]")
        )
    )
    assert title_is("Browser GUI paste verified")
    click_native(100, 200)
    wait.until(ec.element_to_be_clickable(edit_button)).click()
    local = wait.until(ec.visibility_of_element_located(editor_input))
    assert local.get_attribute("value") == "Synthetic GUI paste value"
    local.send_keys(Keys.CONTROL, "a", Keys.NULL, Keys.BACKSPACE)
    local.send_keys("Synthetic GUI edit value")
    assert local.get_attribute("value") == "Synthetic GUI edit value"
    wait.until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                '//*[@data-browser-field-editor]//button[normalize-space(.)="Apply"]',
            )
        )
    ).click()
    wait.until(
        lambda _: (
            not driver.find_elements(By.CSS_SELECTOR, "[data-browser-field-editor]")
        )
    )
    wait_until(
        lambda: title_is("Browser GUI edit verified"),
        timeout=15,
        interval=0.1,
        message="The Web panel editor did not replace the original password field",
    )
    click_native(100, 360)
    wait.until(ec.element_to_be_clickable(edit_button)).click()
    email_input = wait.until(
        ec.visibility_of_element_located(
            (
                By.CSS_SELECTOR,
                '[data-browser-field-editor] input[type="email"]',
            )
        )
    )
    assert email_input.get_attribute("value") == "reader@example.test"
    for name, value in {
        "inputmode": "email",
        "autocomplete": "email",
        "name": "contact",
        "autocapitalize": "none",
        "autocorrect": "off",
        "spellcheck": "false",
        "enterkeyhint": "next",
        "maxlength": "80",
    }.items():
        assert email_input.get_dom_attribute(name) == value
    wait.until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                '//*[@data-browser-field-editor]//button[normalize-space(.)="Cancel"]',
            )
        )
    ).click()
    wait.until(
        lambda _: (
            not driver.find_elements(By.CSS_SELECTOR, "[data-browser-field-editor]")
        )
    )
    # This native field intentionally publishes no editable receiver. The manual
    # keyboard action must retain its existing remote focus and ordinary text path.
    click_native(100, 440)
    wait_until(
        lambda: title_is("Browser manual focus verified"),
        timeout=15,
        interval=0.1,
        message="The unrecognized native field did not receive the participant tap",
    )
    wait.until(
        ec.element_to_be_clickable(
            (By.CSS_SELECTOR, 'button[aria-label="Show keyboard"]')
        )
    ).click()
    wait.until(
        lambda _: driver.execute_script(
            "return document.activeElement?.tagName === 'TEXTAREA' && "
            "!document.activeElement.hasAttribute('data-browser-native-input') && "
            "document.activeElement.inputMode === 'text';"
        )
    )
    ActionChains(driver).send_keys("Synthetic manual input").perform()
    wait_until(
        lambda: title_is("Browser manual keyboard verified"),
        timeout=15,
        interval=0.1,
        message="The manual keyboard did not type into the existing remote focus",
    )
    ActionChains(driver).send_keys(Keys.ESCAPE).perform()
    wait.until(
        ec.invisibility_of_element_located(
            (By.CSS_SELECTOR, '[role="dialog"][aria-label="Focus browser"]')
        )
    )
    address = wait.until(
        ec.element_to_be_clickable(
            (By.CSS_SELECTOR, 'input[aria-label="Browser address"]:not([readonly])')
        )
    )
    address.send_keys(Keys.CONTROL, "a", Keys.NULL)
    address.send_keys("http://127.0.0.1:8766/navigation")
    wait.until(
        lambda _: address.get_attribute("value") == "http://127.0.0.1:8766/navigation"
    )
    # Capture acceptance state at the native key event, not just after a timeout.
    # Store booleans only: never copy addresses, field values, or target identities.
    driver.execute_script("""
const address = document.querySelector('input[aria-label="Browser address"]');
const snapshot = () => {
  const viewport = document.querySelector('[aria-label="Remote browser page"]');
  let fiber = viewport &&
    viewport[Object.keys(viewport).find(key => key.startsWith('__reactFiber$'))];
  for (let depth = 0; fiber && depth < 100; depth++, fiber = fiber.return) {
    const props = fiber.memoizedProps;
    if (props?.state?.type === 'READY') {
      const state = props.state;
      return {ready: true, connected: state.connection === 'connected',
        canInput: state.canInput, navigationEnabled: props.navigationEnabled,
        selected: !!state.selected, image: !!state.image,
        status: !!state.status, allowInput: state.status?.allow_input === true,
        dialog: state.dialog !== null, conflict: !!state.conflict,
        outcomeUnknown: !!state.outcomeUnknown, readOnly: address.readOnly,
        reloadEnabled: !document.querySelector(
          'button[aria-label="Reload page"]')?.disabled};
    }
  }
  return {ready: false, readOnly: address.readOnly};
};
window.__browserNavigationDiagnostic = {before: snapshot()};
address.addEventListener('keydown', event => {
  if (event.key !== 'Enter') return;
  window.__browserNavigationDiagnostic.enter = snapshot();
  // Document bubbling runs after React's root listener has handled the event.
  document.addEventListener('keydown', handled => {
    if (handled !== event) return;
    window.__browserNavigationDiagnostic.prevented = event.defaultPrevented;
    window.__browserNavigationDiagnostic.after = snapshot();
  }, {once: true});
}, {once: true});
""")
    address.send_keys(Keys.ENTER)

    def current_page() -> BrowserPageResponse:
        projection = _projection(public_url, resource_path, token)
        return projection.tasks[0].pages[0]

    def wait_destination(path: str) -> None:
        try:
            wait_until(
                lambda: current_page().url == f"http://127.0.0.1:8766{path}",
                timeout=15,
                interval=0.1,
                message="The browser navigation control did not change the native page",
            )
        except TimeoutError as error:
            diagnostic = driver.execute_script(
                "return window.__browserNavigationDiagnostic;"
            )
            raise AssertionError(
                f"Native navigation was not observed; value-free state: {diagnostic}"
            ) from error
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
    driver.get(f"{web_url}/w/{handle}/agents/{agent_id}/sessions/{session_id}")


def test_session_browser_engine_native_input_dialog_and_reconnect(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_runtime_provider_docker_container: object,
    azents_runtime_control_container: DockerContainer,
    mock_openai_url: str,
    request: pytest.FixtureRequest,
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

    # The GUI is the active frame consumer during its own input journey.
    # Open the raw revocation observer afterwards so it keeps reading and ACKing
    # instead of filling its receive queue during unrelated Selenium operations.
    driver = request.getfixturevalue("browser_driver")
    assert isinstance(driver, WebDriver)
    _verify_live_panel(
        driver=driver,
        web_url=azents_main_web_url,
        public_url=azents_public_server_url,
        resource_path=resource_path,
        token=workspace.token,
        email=workspace.email,
        handle=workspace.handle,
        agent_id=workspace.agent_id,
        session_id=workspace.session_id,
        target=target,
        source=socket.frame.source,
    )
    # Each xdist worker owns its container network and runs its tests serially.
    # Replace the former socket-only reconnect with a real Control-only loss;
    # never restart the Runner or the native browser to manufacture recovery.
    canary = BrowserSocket.open(
        public_url=azents_public_server_url,
        token=workspace.token,
        resource_path=resource_path,
        target=target,
        origin=_ORIGIN,
    )
    try:
        canary.click(x=100, y=520)
    finally:
        canary.close()

    def canary_title() -> str | None:
        response = requests.get(
            f"{azents_public_server_url}{resource_path}",
            headers=headers,
            timeout=10,
        )
        if response.status_code != 200:
            return None
        current = BrowserProjectionResponse.model_validate(response.json())
        for task in current.tasks:
            for page in task.pages:
                if page.id == target.page_id and page.title.startswith(
                    "Control memory "
                ):
                    return page.title
        return None

    first_canary = wait_until(
        canary_title, timeout=10, interval=0.2, message="Native canary was not set"
    )
    assert first_canary is not None
    assert first_canary.endswith(":1")
    runtime_url = (
        f"{azents_public_server_url}/agent-runtime/v1/workspaces/{workspace.handle}"
        f"/agents/{workspace.agent_id}/runtime"
    )

    def runtime_epoch() -> tuple[str, int, int] | None:
        response = requests.get(runtime_url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        current = AgentRuntimeResponse.model_validate(response.json()).runtime
        if current is None or current.runner_generation is None:
            return None
        return current.id, current.desired_generation, int(current.runner_generation)

    before_epoch = runtime_epoch()
    assert before_epoch is not None
    azents_runtime_control_container.get_wrapped_container().restart(timeout=10)

    def rejoined() -> bool:
        current = runtime_epoch()
        return (
            current is not None
            and current[:2] == before_epoch[:2]
            and current[2] > before_epoch[2]
            and canary_title() == first_canary
        )

    wait_until(
        rejoined,
        timeout=90,
        interval=0.2,
        message="Control reconnect did not preserve the original native tab",
    )
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
        reconnected.click(x=100, y=520)
        wait_until(
            lambda: canary_title() == first_canary[:-1] + "2",
            timeout=10,
            interval=0.2,
            message="Fresh Control authority did not preserve native page memory",
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
    # A disabled Agent must not expose Browser UI through a stale deep link.
    disabled_response = requests.patch(
        f"{azents_public_server_url}/agent/v1/workspaces/{workspace.handle}"
        f"/agents/{workspace.agent_id}",
        headers={"Authorization": f"Bearer {fresh.access_token}"},
        json={"browser_enabled": False},
        timeout=10,
    )
    disabled_response.raise_for_status()
    assert (
        _BrowserEnabledObservation.model_validate(
            disabled_response.json()
        ).browser_enabled
        is False
    )
    # The earlier revocation phase invalidated the Web session's cookies.
    _login_main_web(driver, base_url=azents_main_web_url, email=workspace.email)
    driver.get(
        f"{azents_main_web_url}/w/{workspace.handle}/agents/{workspace.agent_id}"
        f"/sessions/{workspace.session_id}?"
        + urlencode(
            {
                "page": "browser",
                "browserTaskId": target.task_id,
                "browserPageId": target.page_id,
                "browserIncarnation": target.resource_incarnation,
                "retained": "fixture",
            }
        )
    )
    WebDriverWait(driver, 60, poll_frequency=0.1).until(
        lambda _: driver.execute_script(
            "return new URLSearchParams(location.search).get('page') === 'files';"
        )
    )
    assert driver.execute_script(
        "const p = new URLSearchParams(location.search);"
        "return p.get('retained') === 'fixture' && "
        "!p.has('browserTaskId') && !p.has('browserPageId') && "
        "!p.has('browserIncarnation');"
    )
    assert not driver.find_elements(
        By.XPATH, '//*[@role="tab" and normalize-space(.)="Browser"]'
    )
    assert not driver.find_elements(
        By.CSS_SELECTOR, '[aria-label="Remote browser page"]'
    )
    assert not driver.find_elements(
        By.XPATH, '//a[normalize-space(.)="Open in Browser"]'
    )
