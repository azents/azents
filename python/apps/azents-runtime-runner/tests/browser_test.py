"""Live synthetic tests for product browser resource and SDK command boundaries."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web
from azents_runtime_control.browser_configuration import BrowserImplementation
from azents_runtime_control.browser_contract import (
    BrowserActCommand,
    BrowserAction,
    BrowserActionKind,
    BrowserAuthority,
    BrowserObserveCommand,
    BrowserOpenCommand,
    BrowserResult,
    BrowserTarget,
)
from patchright.async_api import BrowserContext, CDPSession, Error, Playwright

import azents_runtime_runner.browser as browser_module
from azents_runtime_runner.browser import (
    BrowserFailure,
    BrowserInteractionGuard,
    RunnerBrowserManager,
    _sandbox_unavailable,
)
from azents_runtime_runner.browser_input import BrowserInputKey


def _action(
    kind: BrowserActionKind,
    *,
    ref: str | None = None,
    observation_id: str | None = None,
    text: str | None = None,
    url: str | None = None,
    values: tuple[str, ...] | None = None,
    checked: bool | None = None,
    key: str | None = None,
    x: float | None = None,
    y: float | None = None,
    end_ref: str | None = None,
    paths: tuple[str, ...] | None = None,
    dialog_id: str | None = None,
    accept: bool | None = None,
    condition: Literal["visible", "hidden", "url"] | None = None,
    expect: Literal["popup", "download"] | None = None,
    timeout_ms: int = 10000,
) -> BrowserAction:
    """Fixture options explicitly construct every production DTO field."""
    return BrowserAction(
        kind,
        ref,
        observation_id,
        text,
        None,
        url,
        values,
        checked,
        key,
        x,
        y,
        end_ref,
        paths,
        dialog_id,
        accept,
        condition,
        expect,
        timeout_ms,
    )


_HTML = """<!doctype html><title>Synthetic fixture</title><h1>Report</h1>
<p style="display:none">hidden-secret</p><input type=password value="input-secret">
<input id=otp autocomplete="one-time-code" value="246810">
<input id=text aria-label="Name">
<button id=click onclick="document.title='Clicked'">Submit</button>
<a href="/next?token=url-secret">Link</a>
<button id=popup onclick="window.open('/next')">Popup</button>
<a href="/download">Download</a><input aria-label="Upload" type=file>
<button onclick="alert('Synthetic alert')">Alert</button>
<button onclick="alert('First');alert('Second')">Consecutive alerts</button>
<button onclick="document.title=prompt('Synthetic prompt')||'Empty'">Prompt</button>
<button onclick="document.title=confirm('Synthetic confirm')?'Accepted':'Dismissed'">
Confirm</button>
<button onclick="if(confirm('Open popup?')) window.open('/next')">Confirm popup</button>
<button onclick="if(confirm('Download report?')) location.href='/download'">
Confirm download</button>
<input id=hiddenupload type=file style="display:none">
<button onclick="document.querySelector('#hiddenupload').click()">Choose file</button>
<iframe src=/frame></iframe>"""


@pytest.fixture
async def site() -> AsyncIterator[str]:
    async def handler(request: web.Request) -> web.Response:
        if request.path == "/download":
            return web.Response(
                body=b"column\nfixture\n",
                headers={"Content-Disposition": 'attachment; filename="report.csv"'},
                content_type="text/csv",
            )
        if request.path == "/initial-dialog":
            return web.Response(
                text="<script>alert('Initial question')</script><h1>Loaded</h1>",
                content_type="text/html",
            )
        if request.path == "/login":
            response = web.Response(text=_HTML, content_type="text/html")
            response.set_cookie("synthetic_login", "fixture", max_age=3600)
            return response
        if request.path == "/frame":
            return web.Response(
                text="<button onclick=\"this.textContent='Done'\">Frame</button>",
                content_type="text/html",
            )
        return web.Response(text=_HTML, content_type="text/html")

    app = web.Application()
    app.router.add_get("/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    server = web.TCPSite(runner, "127.0.0.1", 0)
    await server.start()
    address = runner.addresses[0]
    yield f"http://127.0.0.1:{address[1]}"
    await runner.cleanup()


@pytest.fixture
async def manager(
    tmp_path: Path, implementation: BrowserImplementation
) -> AsyncIterator[RunnerBrowserManager]:
    manager = RunnerBrowserManager(
        workspace_root=tmp_path,
        proxy=None,
        input_key=BrowserInputKey(),
        implementation=implementation,
    )
    yield manager
    await manager.close()


@pytest.fixture(params=tuple(BrowserImplementation))
def implementation(request: pytest.FixtureRequest) -> BrowserImplementation:
    value = request.param
    assert isinstance(value, BrowserImplementation)
    return value


def authority(tmp_path: Path, name: str = "session-a") -> BrowserAuthority:
    return BrowserAuthority(name, str(tmp_path / name))


def target(result: BrowserResult, frame: str | None = None) -> BrowserTarget:
    assert result.page is not None
    page = result.page
    return BrowserTarget(page.task_id, page.id, page.resource_incarnation, frame)


async def observe(
    manager: RunnerBrowserManager,
    actor: BrowserAuthority,
    current: BrowserTarget,
    view: str = "dom",
) -> BrowserResult:
    assert view in {"dom", "raw_dom", "glance", "image", "status"}
    return await manager.execute(
        BrowserObserveCommand(actor, current, view, False, 10000)
    )


async def act(
    manager: RunnerBrowserManager,
    actor: BrowserAuthority,
    current: BrowserTarget,
    observed: BrowserResult,
    label: str,
    *,
    kind: str = "click",
    expect: str | None = None,
    text: str | None = None,
) -> BrowserResult:
    assert kind in {"click", "fill", "upload"}
    assert expect in {None, "popup", "download"}
    ref = next(ref for ref in observed.refs if ref.label == label)
    command = BrowserActCommand(
        actor,
        current,
        _action(
            kind,
            ref=ref.id,
            observation_id=ref.observation_id,
            text=text,
            expect=expect,
        ),
    )
    return await manager.execute(command)


async def test_session_state_reuse_isolation_and_persistence(
    manager: RunnerBrowserManager, site: str, tmp_path: Path
) -> None:
    a, b = authority(tmp_path), authority(tmp_path, "session-b")
    first = await manager.execute(BrowserOpenCommand(a, None, site + "/login", None))
    await manager.execute(BrowserOpenCommand(a, None, site, None))
    await manager.execute(BrowserOpenCommand(b, None, site, None))
    assert any(
        c["name"] == "synthetic_login"
        for c in await manager.contexts[a.session_id].cookies()
    )
    assert not await manager.contexts[b.session_id].cookies()
    with pytest.raises(BrowserFailure, match="not authorized"):
        await observe(manager, b, target(first))
    await manager.close()
    fresh = RunnerBrowserManager(
        workspace_root=tmp_path,
        proxy=None,
        input_key=BrowserInputKey(),
        implementation=manager.implementation,
    )
    try:
        await fresh.execute(BrowserOpenCommand(a, None, site, None))
        assert any(
            c["name"] == "synthetic_login"
            for c in await fresh.contexts[a.session_id].cookies()
        )
        with pytest.raises(BrowserFailure, match="closed"):
            await observe(fresh, a, target(first))
    finally:
        await fresh.close()


@pytest.mark.parametrize("implementation", [BrowserImplementation.PATCHRIGHT])
async def test_replaced_runtime_reopens_profile_with_stale_process_markers(
    manager: RunnerBrowserManager, site: str, tmp_path: Path
) -> None:
    actor = authority(tmp_path)
    opened = await manager.execute(
        BrowserOpenCommand(actor, None, site + "/login", None)
    )
    await manager.close()
    [profile] = list((tmp_path / ".azents" / "browser-state").iterdir())
    socket_target = tmp_path / "old-native-socket"
    cookie_target = tmp_path / "old-native-cookie"
    socket_target.write_text("Retain external socket target")
    cookie_target.write_text("Retain external cookie target")
    (profile / "SingletonLock").symlink_to("previous-runtime-host-999999")
    (profile / "SingletonSocket").symlink_to(socket_target)
    (profile / "SingletonCookie").symlink_to(cookie_target)
    fresh = RunnerBrowserManager(
        workspace_root=tmp_path,
        proxy=None,
        input_key=BrowserInputKey(),
        implementation=BrowserImplementation.PATCHRIGHT,
    )
    try:
        await fresh.execute(BrowserOpenCommand(actor, None, site, None))
        assert any(
            cookie["name"] == "synthetic_login"
            for cookie in await fresh.contexts[actor.session_id].cookies()
        )
        assert socket_target.read_text() == "Retain external socket target"
        assert cookie_target.read_text() == "Retain external cookie target"
        with pytest.raises(BrowserFailure, match="closed"):
            await observe(fresh, actor, target(opened))
    finally:
        await fresh.close()


async def test_dom_glance_raw_and_capture_original(
    manager: RunnerBrowserManager, site: str, tmp_path: Path
) -> None:
    a = authority(tmp_path)
    opened = await manager.execute(
        BrowserOpenCommand(a, None, site + "/?signed=private", None)
    )
    current = target(opened)
    assert opened.page is not None and "signed" not in opened.page.url
    dom = await observe(manager, a, current)
    assert dom.refs and all(ref.observation_id for ref in dom.refs)
    for view in ("glance", "raw_dom"):
        result = await observe(manager, a, current, view)
        assert result.content is not None and "Report" in result.content
        assert all(
            secret not in result.content
            for secret in ("hidden-secret", "input-secret", "url-secret")
        )
    capture = await observe(manager, a, current, "image")
    assert capture.capture is not None
    png = Path(capture.capture.path).read_bytes()
    assert png.startswith(b"\x89PNG") and capture.capture.size == len(png)
    assert capture.capture.width == 1280 and capture.capture.height == 800


async def test_popup_download_upload_frame_and_scoped_close(
    manager: RunnerBrowserManager, site: str, tmp_path: Path
) -> None:
    a = authority(tmp_path)
    opened = await manager.execute(BrowserOpenCommand(a, None, site, None))
    current = target(opened)
    observed = await observe(manager, a, current)
    popup = await act(manager, a, current, observed, "Popup", expect="popup")
    assert popup.popup is not None and popup.popup.task_id == current.task_id
    observed = await observe(manager, a, current)
    downloaded = await act(manager, a, current, observed, "Download", expect="download")
    assert (
        downloaded.download is not None
        and Path(downloaded.download.path).read_bytes() == b"column\nfixture\n"
    )
    observed = await observe(manager, a, current)
    upload = next(ref for ref in observed.refs if ref.label == "Upload")
    await manager.execute(
        BrowserActCommand(
            a,
            current,
            _action(
                "upload",
                ref=upload.id,
                observation_id=upload.observation_id,
                paths=(downloaded.download.path,),
            ),
        )
    )
    assert opened.page is not None
    frame = (
        next(f for f in popup.page.frames if f.url.endswith("/frame"))
        if popup.page is not None
        else None
    )
    assert frame is not None
    scoped = target(opened, frame.id)
    framed = await observe(manager, a, scoped)
    await act(manager, a, scoped, framed, "Frame")
    with pytest.raises(BrowserFailure, match="frame"):
        await act(manager, a, current, framed, "Frame")
    await manager.execute(
        BrowserActCommand(
            a,
            BrowserTarget(
                current.task_id, popup.popup.id, current.resource_incarnation, None
            ),
            _action("close_page"),
        )
    )
    assert (await observe(manager, a, current, "status")).page is not None


@pytest.mark.parametrize(
    "label,response,accept,title",
    [
        ("Alert", None, True, "Synthetic fixture"),
        ("Prompt", "Answered", True, "Answered"),
        ("Confirm", None, False, "Dismissed"),
    ],
)
async def test_dialog_response_does_not_deadlock_other_work(
    manager: RunnerBrowserManager,
    site: str,
    tmp_path: Path,
    label: str,
    response: str | None,
    accept: bool,
    title: str,
) -> None:
    a = authority(tmp_path)
    opened = await manager.execute(BrowserOpenCommand(a, None, site, None))
    current = target(opened)
    observed = await observe(manager, a, current)
    blocked = await asyncio.wait_for(act(manager, a, current, observed, label), 5)
    assert blocked.dialog is not None
    assert blocked.action_state == "dialog_pending"
    assert (await observe(manager, a, current, "status")).dialog is not None
    other = await manager.execute(
        BrowserOpenCommand(authority(tmp_path, "session-b"), None, site, None)
    )
    assert other.page is not None
    with pytest.raises(BrowserFailure, match="dialog"):
        await manager.execute(BrowserActCommand(a, current, _action("reload")))
    answered = await manager.execute(
        BrowserActCommand(
            a,
            current,
            _action(
                "dialog", dialog_id=blocked.dialog.id, accept=accept, text=response
            ),
        )
    )
    assert (
        answered.dialog is None
        and answered.page is not None
        and answered.page.title == title
    )


async def test_current_ref_and_transient_input_guard(
    manager: RunnerBrowserManager, site: str, tmp_path: Path
) -> None:
    a = authority(tmp_path)
    opened = await manager.execute(BrowserOpenCommand(a, None, site, None))
    current = target(opened)
    observed = await observe(manager, a, current)
    task, _, _ = manager.target(a, current)
    task.guard.begin("human-composition")
    with pytest.raises(BrowserFailure, match="active"):
        await act(manager, a, current, observed, "Submit")
    task.guard.end("human-composition")
    clicked = await act(manager, a, current, observed, "Submit")
    assert clicked.page is not None and clicked.page.title == "Clicked"
    assert clicked.action_state == "dispatched"
    await manager.execute(BrowserActCommand(a, current, _action("reload")))
    with pytest.raises(BrowserFailure, match="reference"):
        await act(manager, a, current, observed, "Submit")


async def test_authority_paths_and_cross_task_refs(
    manager: RunnerBrowserManager, site: str, tmp_path: Path
) -> None:
    with pytest.raises(BrowserFailure, match="outside"):
        await manager.execute(
            BrowserOpenCommand(BrowserAuthority("a", "/tmp"), None, None, None)
        )
    a = authority(tmp_path)
    opened = await manager.execute(BrowserOpenCommand(a, None, site, None))
    with pytest.raises(BrowserFailure, match="changed"):
        await manager.execute(
            BrowserOpenCommand(
                BrowserAuthority(a.session_id, str(tmp_path / "new")), None, None, None
            )
        )
    second = await manager.execute(BrowserOpenCommand(a, None, site, None))
    refs = await observe(manager, a, target(opened))
    with pytest.raises(BrowserFailure, match="reference"):
        await act(manager, a, target(second), refs, "Submit")


def test_sandbox_classification_is_not_generic_downgrade() -> None:
    assert _sandbox_unavailable("Chromium failed: No usable sandbox!")
    assert not _sandbox_unavailable("TargetClosedError: executable missing")
    assert not _sandbox_unavailable("TimeoutError")


async def test_guard_releases_on_cancellation() -> None:
    guard = BrowserInteractionGuard()
    entered = asyncio.Event()

    async def active() -> None:
        async with guard.interaction("actor"):
            entered.set()
            await asyncio.Event().wait()

    running = asyncio.create_task(active())
    await entered.wait()
    assert guard.actor == "actor"
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert guard.actor is None


@pytest.mark.parametrize(
    "label,expect", [("Confirm popup", "popup"), ("Confirm download", "download")]
)
async def test_expected_event_survives_dialog_handoff(
    manager: RunnerBrowserManager,
    site: str,
    tmp_path: Path,
    label: str,
    expect: str,
) -> None:
    a = authority(tmp_path)
    opened = await manager.execute(BrowserOpenCommand(a, None, site, None))
    current = target(opened)
    observed = await observe(manager, a, current)
    pending = await asyncio.wait_for(
        act(manager, a, current, observed, label, expect=expect), 5
    )
    assert pending.dialog is not None
    assert "?" in pending.dialog.message
    result = await manager.execute(
        BrowserActCommand(
            a,
            current,
            _action("dialog", dialog_id=pending.dialog.id, accept=True),
        )
    )
    if expect == "popup":
        assert result.popup is not None
    else:
        assert result.download is not None
        assert Path(result.download.path).read_bytes() == b"column\nfixture\n"


async def test_closing_manager_drains_outstanding_dialog_task(
    manager: RunnerBrowserManager,
    site: str,
    tmp_path: Path,
) -> None:
    a = authority(tmp_path)
    opened = await manager.execute(BrowserOpenCommand(a, None, site, None))
    current = target(opened)
    pending = await act(
        manager, a, current, await observe(manager, a, current), "Alert"
    )
    assert pending.dialog is not None
    _, resource, _ = manager.target(a, current)
    outstanding = resource.pending
    assert outstanding is not None
    await manager.close()
    assert outstanding.done()


def test_transport_generation_is_bound_separately_from_session(tmp_path: Path) -> None:
    manager = RunnerBrowserManager(
        workspace_root=tmp_path,
        proxy=None,
        input_key=BrowserInputKey(),
        implementation=BrowserImplementation.PATCHRIGHT,
    )
    generation = 7
    manager.bind_runtime("runtime", lambda: generation)
    manager.validate_operation("runtime", 7)
    generation = 8
    with pytest.raises(BrowserFailure, match="generation"):
        manager.validate_operation("runtime", 7)
    with pytest.raises(BrowserFailure, match="generation"):
        manager.validate_operation("other", 8)


async def test_scoped_page_close_cancels_pending_dialog_without_profile_reset(
    manager: RunnerBrowserManager,
    site: str,
    tmp_path: Path,
) -> None:
    a = authority(tmp_path)
    opened = await manager.execute(BrowserOpenCommand(a, None, site, None))
    current = target(opened)
    pending = await act(
        manager, a, current, await observe(manager, a, current), "Alert"
    )
    assert pending.dialog is not None
    task, page, _ = manager.target(a, current)
    outstanding = page.pending
    assert outstanding is not None
    result = await manager.execute(BrowserActCommand(a, current, _action("close_page")))
    assert outstanding.done() and not task.pages
    assert result.page is None
    assert a.session_id in manager.contexts


async def test_web_filechooser_upload_is_registered_before_click(
    manager: RunnerBrowserManager,
    site: str,
    tmp_path: Path,
) -> None:
    a = authority(tmp_path)
    opened = await manager.execute(BrowserOpenCommand(a, None, site, None))
    current = target(opened)
    observed = await observe(manager, a, current)
    ref = next(ref for ref in observed.refs if ref.label == "Choose file")
    file = tmp_path / "upload.txt"
    file.write_text("fixture")
    result = await manager.execute(
        BrowserActCommand(
            a,
            current,
            _action(
                "upload",
                ref=ref.id,
                observation_id=ref.observation_id,
                paths=(str(file),),
            ),
        )
    )
    assert result.action_state == "dispatched"
    _, page, _ = manager.target(a, current)
    assert (
        await page.page.locator("#hiddenupload").evaluate("e => e.files[0].name")
        == "upload.txt"
    )


async def test_passive_wait_is_not_claimed_as_input_dispatch(
    manager: RunnerBrowserManager,
    site: str,
    tmp_path: Path,
) -> None:
    a = authority(tmp_path)
    opened = await manager.execute(BrowserOpenCommand(a, None, site, None))
    result = await manager.execute(
        BrowserActCommand(a, target(opened), _action("wait", condition="url", url=site))
    )
    assert result.action_state == "none"


@pytest.mark.parametrize(
    "failure, expected_sandbox",
    [
        (None, True),
        ("No usable sandbox!", False),
        ("Executable does not exist", None),
    ],
)
async def test_initialization_support_probe_does_not_hide_generic_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str | None,
    expected_sandbox: bool | None,
) -> None:
    driver = MagicMock(spec=Playwright)
    probe = MagicMock()
    probe.close = AsyncMock()
    probe_page = MagicMock()
    probe_page.evaluate = AsyncMock(return_value="Synthetic HeadlessChrome/156.0")
    probe.new_page = AsyncMock(return_value=probe_page)
    driver.stop = AsyncMock()
    driver.chromium.launch = AsyncMock(
        side_effect=[probe] if failure is None else [Error(failure), probe]
    )
    factory = MagicMock()
    factory.start = AsyncMock(return_value=driver)
    monkeypatch.setattr(browser_module, "async_playwright", lambda: factory)
    manager = RunnerBrowserManager(
        workspace_root=tmp_path,
        proxy=None,
        input_key=BrowserInputKey(),
        implementation=BrowserImplementation.PATCHRIGHT,
    )
    if expected_sandbox is None:
        with pytest.raises(BrowserFailure, match="startup"):
            await manager.initialize()
        assert driver.chromium.launch.call_count == 1
        driver.stop.assert_awaited_once()
    else:
        await manager.initialize()
        assert manager.sandbox is expected_sandbox
        calls = driver.chromium.launch.call_args_list
        assert calls[0].kwargs["chromium_sandbox"] is True
        if not expected_sandbox:
            assert len(calls) == 2 and calls[1].kwargs["chromium_sandbox"] is False
        await manager.close()
    assert not list(tmp_path.iterdir())
    for call in driver.chromium.launch.call_args_list:
        assert call.kwargs["headless"] is False
        assert call.kwargs["channel"] == "chromium"


@pytest.mark.parametrize("implementation", [BrowserImplementation.PATCHRIGHT])
async def test_context_admission_waits_for_initial_graphics_information(
    manager: RunnerBrowserManager,
    site: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    sessions: list[CDPSession] = []
    send = CDPSession.send

    async def delayed(session: CDPSession, method: str) -> object:
        assert method == "SystemInfo.getInfo"
        sessions.append(session)
        entered.set()
        await release.wait()
        return await send(session, method)

    monkeypatch.setattr(CDPSession, "send", delayed)
    actor = authority(tmp_path)
    opening = asyncio.create_task(
        manager.execute(BrowserOpenCommand(actor, None, site, None))
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert not opening.done() and not manager.contexts
        assert all(not task.pages for task in manager.tasks.values())
    finally:
        release.set()
        opened = await asyncio.wait_for(opening, 5)
    assert opened.page is not None
    assert len(sessions) == 1
    with pytest.raises(Error):
        await send(sessions[0], "SystemInfo.getInfo")
    await manager.execute(BrowserOpenCommand(actor, None, site, None))
    assert len(sessions) == 1  # Reused contexts do not repeat startup work.


@pytest.mark.parametrize("failure_kind", ["protocol", "deadline"])
@pytest.mark.parametrize("implementation", [BrowserImplementation.PATCHRIGHT])
async def test_failed_graphics_startup_closes_unpublished_context(
    manager: RunnerBrowserManager,
    site: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    deadlines: list[asyncio.Timeout] = []
    closed: list[BrowserContext] = []
    timeout, close = asyncio.timeout, BrowserContext.close

    def observed_timeout(delay: float | None) -> asyncio.Timeout:
        assert delay == 180
        value = timeout(delay)
        deadlines.append(value)
        return value

    async def failed(session: CDPSession, method: str) -> object:
        del session
        assert method == "SystemInfo.getInfo"
        if failure_kind == "protocol":
            raise Error("Synthetic native startup failure")
        deadlines[0].reschedule(asyncio.get_running_loop().time())
        await asyncio.Event().wait()
        raise AssertionError("The context startup deadline must expire")

    async def observed_close(context: BrowserContext) -> None:
        await close(context)
        closed.append(context)

    monkeypatch.setattr(asyncio, "timeout", observed_timeout)
    monkeypatch.setattr(CDPSession, "send", failed)
    monkeypatch.setattr(BrowserContext, "close", observed_close)
    with pytest.raises(BrowserFailure) as error:
        await manager.execute(BrowserOpenCommand(authority(tmp_path), None, site, None))
    assert error.value.code == "browser_unavailable"
    assert not manager.contexts and not manager.tasks
    assert len(closed) == 1 and closed[0].browser is not None
    assert not closed[0].browser.is_connected()
    assert len(deadlines) == 1


@pytest.mark.parametrize("cleanup_failure", [False, True])
@pytest.mark.parametrize("implementation", [BrowserImplementation.PATCHRIGHT])
async def test_cancelled_graphics_startup_preserves_cancellation_and_closes_context(
    manager: RunnerBrowserManager,
    site: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_failure: bool,
) -> None:
    entered = asyncio.Event()
    closed: list[BrowserContext] = []
    close = BrowserContext.close

    async def stalled(session: CDPSession, method: str) -> object:
        del session
        assert method == "SystemInfo.getInfo"
        entered.set()
        await asyncio.Event().wait()
        raise AssertionError("Cancelled startup must not finish")

    async def observed_close(context: BrowserContext) -> None:
        await close(context)
        closed.append(context)
        if cleanup_failure:
            raise Error("Synthetic private cleanup details")

    monkeypatch.setattr(CDPSession, "send", stalled)
    monkeypatch.setattr(BrowserContext, "close", observed_close)
    opening = asyncio.create_task(
        manager.execute(BrowserOpenCommand(authority(tmp_path), None, site, None))
    )
    await asyncio.wait_for(entered.wait(), 5)
    opening.cancel()
    with pytest.raises(asyncio.CancelledError) as error:
        await opening
    assert not manager.contexts and not manager.tasks
    assert len(closed) == 1 and closed[0].browser is not None
    assert not closed[0].browser.is_connected()
    if cleanup_failure:
        assert error.value.__notes__ == ["Native browser context cleanup also failed."]


async def test_open_navigation_dialog_returns_current_resources_without_deadlock(
    manager: RunnerBrowserManager,
    site: str,
    tmp_path: Path,
) -> None:
    a = authority(tmp_path)
    opened = await asyncio.wait_for(
        manager.execute(BrowserOpenCommand(a, None, site + "/initial-dialog", None)), 5
    )
    assert opened.page is not None and opened.dialog is not None
    assert opened.action_state == "dialog_pending"
    assert opened.dialog.message == "Initial question"
    answered = await manager.execute(
        BrowserActCommand(
            a,
            target(opened),
            _action("dialog", dialog_id=opened.dialog.id, accept=True),
        )
    )
    assert answered.dialog is None and answered.action_state == "dispatched"
    read = await observe(manager, a, target(opened), "glance")
    assert read.content is not None and "Loaded" in read.content


async def test_consecutive_dialogs_retain_pending_action_and_release_guard(
    manager: RunnerBrowserManager, site: str, tmp_path: Path
) -> None:
    a = authority(tmp_path)
    opened = await manager.execute(BrowserOpenCommand(a, None, site, None))
    current = target(opened)
    first = await act(
        manager, a, current, await observe(manager, a, current), "Consecutive alerts"
    )
    assert first.dialog is not None and first.dialog.message == "First"
    task, resource, _ = manager.target(a, current)
    pending = resource.pending
    assert pending is not None
    second = await asyncio.wait_for(
        manager.execute(
            BrowserActCommand(
                a, current, _action("dialog", dialog_id=first.dialog.id, accept=True)
            )
        ),
        5,
    )
    assert second.dialog is not None and second.dialog.message == "Second"
    assert second.action_state == "dialog_pending"
    assert resource.pending is pending and task.guard.actor is None
    finished = await asyncio.wait_for(
        manager.execute(
            BrowserActCommand(
                a, current, _action("dialog", dialog_id=second.dialog.id, accept=True)
            )
        ),
        5,
    )
    assert finished.dialog is None and finished.action_state == "dispatched"
    assert pending.done() and resource.pending is None and task.guard.actor is None


async def test_dialog_response_cancellation_drains_original_action(
    manager: RunnerBrowserManager,
    site: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = authority(tmp_path)
    opened = await manager.execute(BrowserOpenCommand(a, None, site, None))
    current = target(opened)
    first = await act(
        manager, a, current, await observe(manager, a, current), "Consecutive alerts"
    )
    assert first.dialog is not None
    task, resource, _ = manager.target(a, current)
    pending = resource.pending
    assert pending is not None and resource.dialog is not None
    responding = asyncio.Event()

    async def stalled_accept(prompt_text: str | None) -> None:
        del prompt_text
        responding.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(resource.dialog, "accept", stalled_accept)
    response = asyncio.create_task(
        manager.execute(
            BrowserActCommand(
                a, current, _action("dialog", dialog_id=first.dialog.id, accept=True)
            )
        )
    )
    await responding.wait()
    response.cancel()
    with pytest.raises(asyncio.CancelledError):
        await response
    assert pending.done() and resource.pending is None and task.guard.actor is None


async def test_frame_navigation_wait_and_page_only_rejection(
    manager: RunnerBrowserManager, site: str, tmp_path: Path
) -> None:
    a = authority(tmp_path)
    opened = await manager.execute(BrowserOpenCommand(a, None, site, None))
    current = target(opened)
    _, resource, _ = manager.target(a, current)
    await (
        resource.page.frame_locator("iframe")
        .get_by_role("button", name="Frame", exact=True)
        .wait_for()
    )
    observed = await observe(manager, a, current)
    assert observed.page is not None
    frame = next(f for f in observed.page.frames if f.url.endswith("/frame"))
    scoped = target(observed, frame.id)
    for kind in ("back", "forward", "reload", "close_page", "dialog"):
        assert kind in {"back", "forward", "reload", "close_page", "dialog"}
        with pytest.raises(BrowserFailure, match="main page"):
            await manager.execute(
                BrowserActCommand(
                    a,
                    scoped,
                    _action(
                        kind,
                        dialog_id="irrelevant" if kind == "dialog" else None,
                        accept=True if kind == "dialog" else None,
                    ),
                )
            )
    await manager.execute(
        BrowserActCommand(a, scoped, _action("navigate", url=site + "/next"))
    )
    await manager.execute(
        BrowserActCommand(
            a, scoped, _action("wait", condition="url", url=site + "/next")
        )
    )
    _, page, selected = manager.target(a, scoped)
    assert page.page.url == site + "/"
    assert selected.url == site + "/next"


async def test_rejected_open_does_not_allocate_native_resources(
    manager: RunnerBrowserManager,
    site: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_module, "_MAX_PAGES", 2)
    monkeypatch.setattr(browser_module, "_MAX_TASKS", 1)
    a = authority(tmp_path)
    opened = await manager.execute(BrowserOpenCommand(a, None, site, None))
    current = target(opened)
    await manager.execute(BrowserOpenCommand(a, current.task_id, site, None))
    context = manager.contexts[a.session_id]
    assert len(context.pages) == 3
    for _ in range(3):
        with pytest.raises(BrowserFailure, match="page limit"):
            await manager.execute(BrowserOpenCommand(a, current.task_id, site, None))
        with pytest.raises(BrowserFailure, match="task limit"):
            await manager.execute(
                BrowserOpenCommand(authority(tmp_path, "session-b"), None, site, None)
            )
        assert len(context.pages) == 3
        assert len(manager.tasks) == 1 and len(manager.contexts) == 1


async def test_failed_registration_closes_allocated_page(
    manager: RunnerBrowserManager,
    site: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = authority(tmp_path)
    opened = await manager.execute(BrowserOpenCommand(a, None, site, None))
    context = manager.contexts[a.session_id]
    before = len(context.pages)
    monkeypatch.setattr(
        manager,
        "_register",
        MagicMock(side_effect=BrowserFailure("browser_stale_target", "retired")),
    )
    with pytest.raises(BrowserFailure, match="retired"):
        await manager.execute(BrowserOpenCommand(a, target(opened).task_id, site, None))
    assert len(context.pages) == before


async def test_final_close_reclaims_task_quota_and_preserves_profile(
    manager: RunnerBrowserManager,
    site: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser_module, "_MAX_TASKS", 2)
    monkeypatch.setattr(browser_module, "_MAX_SESSION_TASKS", 2)
    a = authority(tmp_path)
    for _ in range(5):
        opened = await manager.execute(
            BrowserOpenCommand(a, None, site + "/login", None)
        )
        old = target(opened)
        await manager.execute(BrowserActCommand(a, old, _action("close_page")))
        assert not manager.tasks
        assert [p.url for p in manager.contexts[a.session_id].pages] == ["about:blank"]
        with pytest.raises(BrowserFailure, match="closed"):
            await observe(manager, a, old, "status")
    assert any(
        c["name"] == "synthetic_login"
        for c in await manager.contexts[a.session_id].cookies()
    )
