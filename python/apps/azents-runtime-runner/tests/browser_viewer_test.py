"""Actual SDK Browser viewer, input fences and volatile page-frame ownership."""

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aiohttp import web
from azents_runtime_control.browser_contract import (
    BrowserActCommand,
    BrowserAuthority,
    BrowserOpenCommand,
    BrowserTarget,
)
from azents_runtime_control.browser_viewer_contract import (
    ViewerFrame,
    decode_viewer_frame,
)
from azents_runtime_control.runtime_stream_session import (
    BrowserStreamAuthority,
    WebSocketOpcode,
)
from browser_test import _action
from playwright.async_api import Error

from azents_runtime_runner.browser import BrowserFailure, RunnerBrowserManager
from azents_runtime_runner.browser_viewer import (
    RunnerBrowserViewer,
    _capture_error_code,
)


@pytest.mark.parametrize(
    "message,code",
    [
        ("Execution context was destroyed", "browser_capture_context_destroyed"),
        ("Cannot find context with specified id", "browser_capture_context_missing"),
        ("Frame was detached", "browser_capture_frame_detached"),
        ("Unable to capture screenshot", "browser_capture_unavailable"),
        ("Protocol error in screenshot", "browser_capture_protocol_error"),
        ("unexpected synthetic page content", "browser_capture_sdk_error"),
    ],
)
def test_live_capture_error_diagnostics_are_fixed_codes(
    message: str, code: str
) -> None:
    assert _capture_error_code(Error(message)) == code


class Budget:
    def __init__(self, maximum: int = 32 * 1024 * 1024) -> None:
        self.bytes = 0
        self.maximum = maximum
        self.peak = 0

    def try_reserve_browser_frame(self, size: int) -> bool:
        if self.bytes + size > self.maximum:
            return False
        self.bytes += size
        self.peak = max(self.peak, self.bytes)
        return True

    def release_browser_frame(self, size: int) -> None:
        self.bytes -= size
        assert self.bytes >= 0


class Transport:
    def __init__(self) -> None:
        self.requests: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.frames: asyncio.Queue[ViewerFrame] = asyncio.Queue()
        self.events: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self.attachment: str | None = None
        self.source: ViewerFrame | None = None

    async def receive(self) -> bytes | None:
        return await self.requests.get()

    async def send(self, opcode: WebSocketOpcode, data: bytes) -> None:
        if opcode is WebSocketOpcode.BINARY:
            await self.frames.put(decode_viewer_frame(data))
        else:
            value = json.loads(data)
            self.attachment = value["attachment_id"]
            await self.events.put(value)

    async def frame(self) -> ViewerFrame:
        async with asyncio.timeout(10):
            frame = await self.frames.get()
            self.source = frame
            await self.requests.put(
                json.dumps(
                    {
                        "type": "frame_ack",
                        "attachment_id": frame.attachment_id,
                        "frame_sequence": frame.source.frame_sequence,
                    }
                ).encode()
            )
            return frame

    async def event(self, kind: str) -> dict[str, object]:
        async with asyncio.timeout(10):
            while True:
                event = await self.events.get()
                if event["type"] == kind:
                    return event

    async def input(
        self,
        sequence: int,
        action: Mapping[str, object],
        source: ViewerFrame | None = None,
    ) -> dict[str, object]:
        frame = source or self.source
        if action["kind"] == "dialog":
            assert self.attachment is not None
            attachment, metadata = self.attachment, None
        else:
            assert frame is not None
            attachment, metadata = frame.attachment_id, asdict(frame.source)
        await self.requests.put(
            json.dumps(
                {
                    "type": "input",
                    "attachment_id": attachment,
                    "sequence": sequence,
                    "source": metadata,
                    "action": action,
                }
            ).encode()
        )
        return await self.event("input_ack")


@pytest.fixture
async def site() -> AsyncIterator[str]:
    async def handler(request: web.Request) -> web.Response:
        if request.path == "/initial-dialog":
            return web.Response(
                text="<body><input id=text><script>"
                "document.body.dataset.answer=prompt('Initial question');"
                "alert('Second');</script>",
                content_type="text/html",
            )
        return web.Response(
            text="""<title>Viewer fixture</title><input id=text style='margin:30px'>
<button id=dialog style='margin:20px'
onclick="alert('First');alert('Second')">Question</button>
<input id=keydialog
onkeydown="if(event.key==='Enter') document.body.dataset.answer=prompt('Key question')">
<script>document.addEventListener('mouseup',()=>document.body.dataset.up='yes')</script>""",
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    server = web.TCPSite(runner, "127.0.0.1", 0)
    await server.start()
    yield f"http://127.0.0.1:{runner.addresses[0][1]}"
    await runner.cleanup()


@pytest.fixture
async def manager(tmp_path: Path) -> AsyncIterator[RunnerBrowserManager]:
    value = RunnerBrowserManager(workspace_root=tmp_path, proxy=None)
    value.bind_runtime("runtime", lambda: 7)
    yield value
    await value.close()


async def scope(
    manager: RunnerBrowserManager, tmp_path: Path, site: str
) -> BrowserStreamAuthority:
    result = await manager.execute(
        BrowserOpenCommand(
            BrowserAuthority("session-a", str(tmp_path / "session-a")), None, site, None
        )
    )
    assert result.page is not None
    page = result.page
    now = datetime.now(UTC)
    return BrowserStreamAuthority(
        "correlation",
        "auth-session",
        "user",
        "agent",
        "runtime",
        3,
        7,
        now + timedelta(seconds=10),
        now + timedelta(minutes=1),
        "session-a",
        page.task_id,
        page.id,
        page.resource_incarnation,
        True,
    )


async def stop(task: asyncio.Task[None], transport: Transport) -> None:
    await transport.requests.put(None)
    async with asyncio.timeout(10):
        await task


async def test_latest_frame_shared_and_ack_metadata_not_latest_capture(
    manager: RunnerBrowserManager, tmp_path: Path, site: str
) -> None:
    authority = await scope(manager, tmp_path, site)
    budget = Budget()
    viewer = RunnerBrowserViewer(manager, budget)
    a, b = Transport(), Transport()
    first = asyncio.create_task(viewer.run(authority, a.receive, a.send))
    second = asyncio.create_task(viewer.run(authority, b.receive, b.send))
    try:
        frame = await a.frame()
        await b.frame()
        assert frame.image.startswith(b"\xff\xd8")
        assert frame.source.width == 1280 and frame.source.height == 800
        assert len(viewer.sources) == 1
        source = viewer.sources[authority.page_id]
        assert source.subscribers == 2
        async with asyncio.timeout(5), source.changed:
            await source.changed.wait_for(
                lambda: source.sequence > frame.source.frame_sequence + 1
            )
        # A newer capture must not invalidate decoded coordinates.
        ack = await a.input(
            1,
            {"kind": "pointer", "phase": "move", "x": 10, "y": 10, "button": None},
            frame,
        )
        assert ack["accepted"] is True
        assert not list(tmp_path.rglob("*.png"))
        assert not list(tmp_path.rglob("*.jpg"))
        assert a.frames.qsize() <= 1 and b.frames.qsize() <= 1
    finally:
        await stop(first, a)
        await stop(second, b)
    assert not viewer.sources and budget.bytes == 0
    assert authority.task_id in manager.tasks


async def test_unfocused_iframe_navigation_preserves_main_view_and_text_input(
    manager: RunnerBrowserManager, tmp_path: Path, site: str
) -> None:
    authority = await scope(manager, tmp_path, site)
    resource = manager.tasks[authority.task_id].pages[authority.page_id]
    native = resource.page
    await native.evaluate(
        """url => {
            const frame = document.createElement('iframe');
            frame.src = url;
            document.body.append(frame);
        }""",
        site + "/child",
    )
    child = native.frames[-1]
    await child.wait_for_url(site + "/child")
    await native.locator("#text").focus()
    viewer = RunnerBrowserViewer(manager, Budget())
    transport = Transport()
    running = asyncio.create_task(
        viewer.run(authority, transport.receive, transport.send)
    )
    try:
        displayed = await transport.frame()
        await child.goto(site + "/child-updated")
        assert resource.navigation_id == displayed.source.navigation_id
        assert (
            await transport.input(
                1, {"kind": "composition", "phase": "start", "text": None}
            )
        )["accepted"] is True
        assert (
            await transport.input(
                2, {"kind": "composition", "phase": "commit", "text": "Synthetic 한글"}
            )
        )["accepted"] is True
        assert await native.locator("#text").input_value() == "Synthetic 한글"
    finally:
        await stop(running, transport)


async def test_keys_composition_conflict_sequence_and_disconnect_cleanup(
    manager: RunnerBrowserManager, tmp_path: Path, site: str
) -> None:
    authority = await scope(manager, tmp_path, site)
    viewer = RunnerBrowserViewer(manager, Budget())
    a, b = Transport(), Transport()
    first = asyncio.create_task(viewer.run(authority, a.receive, a.send))
    second = asyncio.create_task(viewer.run(authority, b.receive, b.send))
    try:
        await a.frame()
        await b.frame()
        page = manager.tasks[authority.task_id].pages[authority.page_id].page
        await page.locator("#text").focus()
        assert (await a.input(1, {"kind": "key", "phase": "down", "key": "Control"}))[
            "accepted"
        ] is True
        assert (await b.input(1, {"kind": "key", "phase": "down", "key": "a"}))[
            "reason_code"
        ] == "browser_input_conflict"
        assert (await a.input(2, {"kind": "key", "phase": "up", "key": "Control"}))[
            "accepted"
        ] is True
        assert (
            await a.input(3, {"kind": "composition", "phase": "start", "text": None})
        )["accepted"] is True
        assert manager.tasks[authority.task_id].guard.actor == a.attachment
        assert (
            await a.input(4, {"kind": "composition", "phase": "commit", "text": "한글"})
        )["accepted"] is True
        assert (
            await a.input(4, {"kind": "composition", "phase": "commit", "text": "한글"})
        )["reason_code"] == "browser_stale_input"
        assert await page.locator("#text").input_value() == "한글"
        assert manager.tasks[authority.task_id].guard.actor is None
        assert (
            await a.input(
                5,
                {
                    "kind": "pointer",
                    "phase": "down",
                    "x": 10,
                    "y": 10,
                    "button": "left",
                },
            )
        )["accepted"] is True
        assert manager.tasks[authority.task_id].guard.actor == a.attachment
        with pytest.raises(BrowserFailure, match="interaction is active"):
            await manager.execute(
                BrowserActCommand(
                    BrowserAuthority(authority.session_id, str(tmp_path / "session-a")),
                    BrowserTarget(
                        authority.task_id,
                        authority.page_id,
                        authority.resource_incarnation,
                        None,
                    ),
                    _action("reload"),
                )
            )
    finally:
        await stop(first, a)
        await stop(second, b)
    assert manager.tasks[authority.task_id].guard.actor is None
    assert await page.locator("body").get_attribute("data-up") == "yes"


@pytest.mark.parametrize("change", ["navigation", "viewport"])
async def test_inflight_image_retires_when_display_scope_changes(
    manager: RunnerBrowserManager, tmp_path: Path, site: str, change: str
) -> None:
    authority = await scope(manager, tmp_path, site)
    viewer = RunnerBrowserViewer(manager, Budget())
    transport = Transport()
    running = asyncio.create_task(
        viewer.run(authority, transport.receive, transport.send)
    )
    try:
        async with asyncio.timeout(10):
            previous = await transport.frames.get()
        native = manager.tasks[authority.task_id].pages[authority.page_id].page
        if change == "navigation":
            await native.goto(site + "/destination")
        else:
            await native.set_viewport_size({"width": 900, "height": 700})
        current = await transport.frame()
        assert current.source.frame_sequence > previous.source.frame_sequence
        if change == "navigation":
            assert current.source.navigation_id != previous.source.navigation_id
        else:
            assert (current.source.width, current.source.height) == (900, 700)
        # A late image decode may ACK the retired frame after the fresh one.
        await transport.requests.put(
            json.dumps(
                {
                    "type": "frame_ack",
                    "attachment_id": previous.attachment_id,
                    "frame_sequence": previous.source.frame_sequence,
                }
            ).encode()
        )
        following = await transport.frame()
        assert following.source.frame_sequence > current.source.frame_sequence
        assert not running.done()
    finally:
        await stop(running, transport)


async def test_viewer_address_history_and_reload_use_native_page(
    manager: RunnerBrowserManager, tmp_path: Path, site: str
) -> None:
    authority = await scope(manager, tmp_path, site)
    viewer = RunnerBrowserViewer(manager, Budget())
    transport = Transport()
    running = asyncio.create_task(
        viewer.run(authority, transport.receive, transport.send)
    )
    try:
        await transport.frame()
        native = manager.tasks[authority.task_id].pages[authority.page_id].page
        for sequence, action, url, expected in (
            (1, "navigate", site + "/destination", site + "/destination"),
            (2, "back", None, site + "/"),
            (3, "forward", None, site + "/destination"),
            (4, "reload", None, site + "/destination"),
        ):
            if action == "reload":
                await native.evaluate("document.body.dataset.reloadProbe='temporary'")
            ack = await transport.input(
                sequence, {"kind": "navigation", "action": action, "url": url}
            )
            assert ack["accepted"] is True, ack["reason_code"]
            assert native.url == expected
            assert (
                await native.locator("body").get_attribute("data-reload-probe") is None
            )
            while True:
                latest = await transport.frame()
                current = manager.tasks[authority.task_id].pages[authority.page_id]
                if latest.source.navigation_id == current.navigation_id:
                    break
        assert manager.tasks[authority.task_id].guard.actor is None
    finally:
        await stop(running, transport)


async def test_viewer_navigation_denies_readonly_and_other_active_actor(
    manager: RunnerBrowserManager, tmp_path: Path, site: str
) -> None:
    authority = await scope(manager, tmp_path, site)
    viewer = RunnerBrowserViewer(manager, Budget())
    read, active = Transport(), Transport()
    tasks = [
        asyncio.create_task(
            viewer.run(replace(authority, allow_input=False), read.receive, read.send)
        ),
        asyncio.create_task(viewer.run(authority, active.receive, active.send)),
    ]
    try:
        await read.frame()
        await active.frame()
        native = manager.tasks[authority.task_id].pages[authority.page_id].page
        navigation = {
            "kind": "navigation",
            "action": "navigate",
            "url": site + "/forbidden",
        }
        assert (await read.input(1, navigation))["reason_code"] == "browser_read_only"
        guard = manager.tasks[authority.task_id].guard
        guard.begin("another-actor")
        try:
            assert (await active.input(1, navigation))[
                "reason_code"
            ] == "browser_input_conflict"
        finally:
            guard.end("another-actor")
        assert native.url == site + "/"
    finally:
        await stop(tasks[0], read)
        await stop(tasks[1], active)


async def test_navigation_readonly_and_generation_fences(
    manager: RunnerBrowserManager, tmp_path: Path, site: str
) -> None:
    authority = await scope(manager, tmp_path, site)
    viewer = RunnerBrowserViewer(manager, Budget())
    a, read = Transport(), Transport()
    first = asyncio.create_task(viewer.run(authority, a.receive, a.send))
    second = asyncio.create_task(
        viewer.run(replace(authority, allow_input=False), read.receive, read.send)
    )
    try:
        old = await a.frame()
        await read.frame()
        assert (await read.input(1, {"kind": "key", "phase": "down", "key": "x"}))[
            "reason_code"
        ] == "browser_read_only"
        assert manager.tasks[authority.task_id].guard.actor is None
        page = manager.tasks[authority.task_id].pages[authority.page_id].page
        await page.goto(site + "/next")
        assert (
            await a.input(
                1,
                {"kind": "pointer", "phase": "move", "x": 10, "y": 10, "button": None},
                old,
            )
        )["reason_code"] == "browser_stale_frame"
        with pytest.raises(BrowserFailure, match="generation"):
            viewer.validate(replace(authority, runner_generation=8))
        with pytest.raises(BrowserFailure):
            viewer.validate(replace(authority, session_id="session-b"))
        with pytest.raises(BrowserFailure):
            viewer.validate(replace(authority, resource_incarnation="stale"))
    finally:
        await stop(first, a)
        await stop(second, read)
    assert "session-b" not in manager.contexts


async def test_dialog_continuation_and_budget_failure(
    manager: RunnerBrowserManager, tmp_path: Path, site: str
) -> None:
    authority = await scope(manager, tmp_path, site)
    viewer = RunnerBrowserViewer(manager, Budget())
    a = Transport()
    running = asyncio.create_task(viewer.run(authority, a.receive, a.send))
    try:
        await a.frame()
        resource = manager.tasks[authority.task_id].pages[authority.page_id]
        box = await resource.page.locator("#dialog").bounding_box()
        assert box is not None
        x, y = box["x"] + 10, box["y"] + 10
        await a.input(
            1, {"kind": "pointer", "phase": "down", "x": x, "y": y, "button": "left"}
        )
        assert (
            await a.input(
                2, {"kind": "pointer", "phase": "up", "x": x, "y": y, "button": "left"}
            )
        )["accepted"] is True
        assert resource.dialog is not None and resource.dialog_id is not None
        first_id = resource.dialog_id
        assert (
            await a.input(
                3,
                {"kind": "dialog", "dialog_id": first_id, "accept": True, "text": None},
            )
        )["accepted"] is True
        assert resource.dialog_id is not None and resource.dialog_id != first_id
        assert (
            await a.input(
                4,
                {"kind": "dialog", "dialog_id": first_id, "accept": True, "text": None},
            )
        )["reason_code"] == "browser_stale_dialog"
        assert (
            await a.input(
                5,
                {
                    "kind": "dialog",
                    "dialog_id": resource.dialog_id,
                    "accept": True,
                    "text": None,
                },
            )
        )["accepted"] is True
        assert resource.dialog is None and resource.pending is None
    finally:
        await stop(running, a)
    limited = RunnerBrowserViewer(manager, Budget(maximum=1))
    transport = Transport()
    bounded = asyncio.create_task(
        limited.run(authority, transport.receive, transport.send)
    )
    async with asyncio.timeout(10):
        while (await transport.event("status"))["state"] != "unavailable":
            pass
        await bounded
    assert not limited.sources
    assert authority.task_id in manager.tasks
