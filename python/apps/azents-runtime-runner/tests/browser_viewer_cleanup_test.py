"""Navigation and disconnect cannot retain or steal transient input ownership."""

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest
from azents_runtime_control.browser_contract import (
    BrowserActCommand,
    BrowserAuthority,
    BrowserTarget,
)
from browser_test import _action
from browser_viewer_test import Budget, Transport, manager, scope, site, stop

from azents_runtime_runner.browser import RunnerBrowserManager
from azents_runtime_runner.browser_viewer import RunnerBrowserViewer

__all__ = ["manager", "site"]


@pytest.mark.parametrize("kind", ["pointer", "key", "composition"])
async def test_stale_navigation_cancel_cleans_only_its_attachment(
    manager: RunnerBrowserManager, tmp_path: Path, site: str, kind: str
) -> None:
    authority = await scope(manager, tmp_path, site)
    viewer = RunnerBrowserViewer(manager, Budget())
    a, b = Transport(), Transport()
    first = asyncio.create_task(viewer.run(authority, a.receive, a.send))
    second = asyncio.create_task(viewer.run(authority, b.receive, b.send))
    try:
        old = await a.frame()
        await b.frame()
        task = manager.tasks[authority.task_id]
        page = task.pages[authority.page_id].page
        if kind == "pointer":
            start: dict[str, object] = {
                "kind": "pointer",
                "phase": "down",
                "x": 5,
                "y": 5,
                "button": "left",
            }
            cancel: dict[str, object] = {
                "kind": "pointer",
                "phase": "cancel",
                "x": 5,
                "y": 5,
                "button": None,
            }
        elif kind == "key":
            start = {"kind": "key", "phase": "down", "key": "Shift"}
            cancel = {"kind": "key", "phase": "up", "key": "Shift"}
        else:
            start = {"kind": "composition", "phase": "start", "text": None}
            cancel = {"kind": "composition", "phase": "cancel", "text": None}
        assert (await a.input(1, start))["accepted"] is True
        assert task.guard.actor == a.attachment
        await page.goto(site + "/next")
        assert (await a.input(2, cancel, old))["reason_code"] == "browser_stale_frame"
        assert task.guard.actor is None
        assert await page.locator("#text").input_value() == ""
        async with asyncio.timeout(10):
            while True:
                frame = await b.frame()
                if frame.source.navigation_id != old.source.navigation_id:
                    break
        assert (await b.input(1, {"kind": "key", "phase": "down", "key": "Shift"}))[
            "accepted"
        ] is True
        assert task.guard.actor == b.attachment
        # Late cleanup of A cannot release B's now-current held key or guard.
        await stop(first, a)
        assert task.guard.actor == b.attachment
        assert (await b.input(2, {"kind": "key", "phase": "up", "key": "Shift"}))[
            "accepted"
        ] is True
        assert task.guard.actor is None
    finally:
        if not first.done():
            await stop(first, a)
        await stop(second, b)


async def test_cancelled_composition_never_commits_text_on_disconnect(
    manager: RunnerBrowserManager, tmp_path: Path, site: str
) -> None:
    authority = await scope(manager, tmp_path, site)
    viewer = RunnerBrowserViewer(manager, Budget())
    transport = Transport()
    running = asyncio.create_task(
        viewer.run(authority, transport.receive, transport.send)
    )
    await transport.frame()
    resource = manager.tasks[authority.task_id].pages[authority.page_id]
    await resource.page.locator("#text").focus()
    assert (
        await transport.input(
            1, {"kind": "composition", "phase": "start", "text": None}
        )
    )["accepted"] is True
    await stop(running, transport)
    assert await resource.page.locator("#text").input_value() == ""
    assert manager.tasks[authority.task_id].guard.actor is None
    assert resource.pending is None
    assert not viewer.sources


async def test_initial_prompt_without_image_and_readonly_dialog_fence(
    manager: RunnerBrowserManager, tmp_path: Path, site: str
) -> None:
    authority = await scope(manager, tmp_path, site + "/initial-dialog")
    viewer = RunnerBrowserViewer(manager, Budget())
    a, readonly = Transport(), Transport()
    running = asyncio.create_task(viewer.run(authority, a.receive, a.send))
    observing = asyncio.create_task(
        viewer.run(
            replace(authority, allow_input=False), readonly.receive, readonly.send
        )
    )
    try:
        status = await a.event("status")
        await readonly.event("status")
        assert status["dialog"] is not None
        assert a.frames.empty()
        resource = manager.tasks[authority.task_id].pages[authority.page_id]
        assert resource.dialog_id is not None
        response = {
            "kind": "dialog",
            "dialog_id": resource.dialog_id,
            "accept": True,
            "text": "fixture-answer",
        }
        assert (await readonly.input(1, response))["reason_code"] == "browser_read_only"
        assert (await a.input(1, {**response, "dialog_id": "stale"}))[
            "reason_code"
        ] == "browser_stale_dialog"
        assert (await a.input(2, response))["accepted"] is True
        assert resource.dialog_id is not None
        assert (
            await a.input(
                3,
                {
                    "kind": "dialog",
                    "dialog_id": resource.dialog_id,
                    "accept": True,
                    "text": None,
                },
            )
        )["accepted"] is True
        await a.frame()
        assert (
            await resource.page.locator("body").get_attribute("data-answer")
            == "fixture-answer"
        )
        assert resource.pending is None and resource.dialog is None
    finally:
        await stop(running, a)
        await stop(observing, readonly)


async def test_navigation_dialog_does_not_require_stale_screen_coordinates(
    manager: RunnerBrowserManager, tmp_path: Path, site: str
) -> None:
    authority = await scope(manager, tmp_path, site)
    viewer = RunnerBrowserViewer(manager, Budget())
    transport = Transport()
    running = asyncio.create_task(
        viewer.run(authority, transport.receive, transport.send)
    )
    try:
        old = await transport.frame()
        await manager.execute(
            BrowserActCommand(
                BrowserAuthority(authority.session_id, str(tmp_path / "session-a")),
                BrowserTarget(
                    authority.task_id,
                    authority.page_id,
                    authority.resource_incarnation,
                    None,
                ),
                _action("navigate", url=site + "/initial-dialog"),
            )
        )
        resource = manager.tasks[authority.task_id].pages[authority.page_id]
        assert resource.navigation_id != old.source.navigation_id
        assert (
            await transport.input(
                1,
                {"kind": "pointer", "phase": "move", "x": 10, "y": 10, "button": None},
                old,
            )
        )["reason_code"] == "browser_stale_frame"
        assert resource.dialog_id is not None
        assert (
            await transport.input(
                2,
                {
                    "kind": "dialog",
                    "dialog_id": resource.dialog_id,
                    "accept": True,
                    "text": "navigation-answer",
                },
            )
        )["accepted"] is True
        assert resource.dialog_id is not None
        assert (
            await transport.input(
                3,
                {
                    "kind": "dialog",
                    "dialog_id": resource.dialog_id,
                    "accept": True,
                    "text": None,
                },
            )
        )["accepted"] is True
        assert (
            await resource.page.locator("body").get_attribute("data-answer")
            == "navigation-answer"
        )
    finally:
        await stop(running, transport)


async def test_human_keyboard_prompt_handoff_does_not_block_dialog_response(
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
        resource = manager.tasks[authority.task_id].pages[authority.page_id]
        await resource.page.locator("#keydialog").focus()
        assert (
            await transport.input(1, {"kind": "key", "phase": "down", "key": "Enter"})
        )["accepted"] is True
        assert resource.dialog_id is not None and resource.pending is not None
        assert manager.tasks[authority.task_id].guard.actor is None
        assert (
            await transport.input(
                2,
                {
                    "kind": "dialog",
                    "dialog_id": resource.dialog_id,
                    "accept": True,
                    "text": "human-prompt",
                },
            )
        )["accepted"] is True
        assert (
            await resource.page.locator("body").get_attribute("data-answer")
            == "human-prompt"
        )
        assert resource.pending is None and resource.dialog is None
    finally:
        await stop(running, transport)


async def test_disconnect_after_dispatch_cleans_pressed_state_without_replay(
    manager: RunnerBrowserManager,
    tmp_path: Path,
    site: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = await scope(manager, tmp_path, site)
    budget = Budget()
    viewer = RunnerBrowserViewer(manager, budget)
    transport = Transport()
    running = asyncio.create_task(
        viewer.run(authority, transport.receive, transport.send)
    )
    await transport.frame()
    resource = manager.tasks[authority.task_id].pages[authority.page_id]
    native_down = resource.page.mouse.down
    dispatched = asyncio.Event()
    calls: list[str] = []

    async def uncertain_down(
        *, button: Literal["left", "middle", "right"] | None
    ) -> None:
        await native_down(button=button)
        calls.append("dispatched")
        dispatched.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(resource.page.mouse, "down", uncertain_down)
    waiting = asyncio.create_task(
        transport.input(
            1, {"kind": "pointer", "phase": "down", "x": 10, "y": 10, "button": "left"}
        )
    )
    try:
        async with asyncio.timeout(5):
            await dispatched.wait()
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert calls == ["dispatched"]
        assert manager.tasks[authority.task_id].guard.actor is None
        assert resource.pending is None
        assert await resource.page.locator("body").get_attribute("data-up") == "yes"
        assert budget.bytes == 0 and not viewer.sources
    finally:
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)
        if not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)


async def test_child_frame_navigation_invalidates_main_page_coordinate_source(
    manager: RunnerBrowserManager, tmp_path: Path, site: str
) -> None:
    authority = await scope(manager, tmp_path, site)
    viewer = RunnerBrowserViewer(manager, Budget())
    transport = Transport()
    running = asyncio.create_task(
        viewer.run(authority, transport.receive, transport.send)
    )
    try:
        old = await transport.frame()
        resource = manager.tasks[authority.task_id].pages[authority.page_id]
        # Fixture setup only; production viewer has no script action.
        async with resource.page.expect_event(
            "framenavigated", predicate=lambda frame: frame.parent_frame is not None
        ):
            await resource.page.evaluate(
                "url => { const iframe = document.createElement('iframe'); "
                "iframe.src = url; document.body.appendChild(iframe); }",
                site + "/child",
            )
        assert resource.navigation_id != old.source.navigation_id
        ack = await transport.input(
            1,
            {"kind": "pointer", "phase": "move", "x": 10, "y": 10, "button": None},
            old,
        )
        assert ack["reason_code"] == "browser_stale_frame"
        assert manager.tasks[authority.task_id].guard.actor is None
    finally:
        await stop(running, transport)
