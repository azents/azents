"""Field editor operations through an actual private Runner viewer attachment."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest
from azents_runtime_control.runtime_stream_session import WebSocketOpcode
from browser_viewer_test import (
    Budget,
    Transport,
    scope,
    stop,
)
from browser_viewer_test import (
    manager as manager,  # noqa: PLC0414 - pytest fixture export
)
from browser_viewer_test import site as site  # noqa: PLC0414 - pytest fixture export

from azents_runtime_runner.browser import RunnerBrowserManager
from azents_runtime_runner.browser_viewer import RunnerBrowserViewer


class FieldTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.values: asyncio.Queue[dict[str, object]] = asyncio.Queue()

    async def send(self, opcode: WebSocketOpcode, data: bytes) -> None:
        await super().send(opcode, data)
        if opcode is WebSocketOpcode.TEXT:
            value = json.loads(data)
            if value["type"] == "field_value":
                await self.values.put(value)

    async def value(self) -> dict[str, object]:
        async with asyncio.timeout(10):
            return await self.values.get()


@pytest.mark.parametrize(
    "markup,kind,replacement",
    [
        ("<input>", "text", "Changed value"),
        ("<input type=password>", "password", "Synthetic replacement"),
        ("<textarea></textarea>", "multiline", "First\nSecond"),
        ("<input>", "text", ""),
    ],
)
async def test_private_field_read_and_single_replace(
    manager: RunnerBrowserManager,
    tmp_path: Path,
    site: str,
    markup: str,
    kind: str,
    replacement: str,
) -> None:
    authority = await scope(manager, tmp_path, site)
    native = manager.tasks[authority.task_id].pages[authority.page_id].page
    await native.set_content(markup)
    field = native.locator("input,textarea")
    await field.fill("Original synthetic value")
    viewer = RunnerBrowserViewer(manager, Budget())
    transport = FieldTransport()
    running = asyncio.create_task(
        viewer.run(authority, transport.receive, transport.send)
    )
    try:
        frame = await transport.frame()
        identifier = frame.editables[0].id
        assert (
            await transport.input(1, {"kind": "field_open", "editable_id": identifier})
        )["accepted"] is True
        value = await transport.value()
        assert value["value"] == "Original synthetic value" and value["kind"] == kind
        assert value["sequence"] == 1 and value["attachment_id"] == frame.attachment_id
        action = {
            "kind": "field_replace",
            "editable_id": identifier,
            "edit_id": value["edit_id"],
            "text": replacement,
        }
        assert (await transport.input(2, action))["accepted"] is True
        assert await field.input_value() == replacement
        assert (await transport.input(3, action))["accepted"] is False
        assert await field.input_value() == replacement
    finally:
        await stop(running, transport)


@pytest.mark.parametrize(
    "change",
    [
        "cancel",
        "value",
        "focus",
        "disabled",
        "readonly",
        "element",
        "beforeinput",
        "navigation",
    ],
)
async def test_private_field_rejects_stale_or_cancelled_replacement(
    manager: RunnerBrowserManager, tmp_path: Path, site: str, change: str
) -> None:
    authority = await scope(manager, tmp_path, site)
    native = manager.tasks[authority.task_id].pages[authority.page_id].page
    await native.set_content("<input value='Original'><button>Other</button>")
    await native.locator("input").focus()
    viewer = RunnerBrowserViewer(manager, Budget())
    transport = FieldTransport()
    running = asyncio.create_task(
        viewer.run(authority, transport.receive, transport.send)
    )
    try:
        frame = await transport.frame()
        identifier = frame.editables[0].id
        assert (
            await transport.input(1, {"kind": "field_open", "editable_id": identifier})
        )["accepted"] is True
        value = await transport.value()
        sequence = 2
        if change == "cancel":
            assert (
                await transport.input(
                    2, {"kind": "field_cancel", "edit_id": value["edit_id"]}
                )
            )["accepted"] is True
            sequence = 3
        elif change == "navigation":
            await native.goto(site + "/new-document")
        else:
            changes = {
                "value": "document.querySelector('input').value='Independent'",
                "focus": "document.querySelector('button').focus()",
                "disabled": "document.querySelector('input').disabled=true",
                "readonly": "document.querySelector('input').readOnly=true",
                "element": (
                    "document.querySelector('input')"
                    ".replaceWith(document.createElement('input'))"
                ),
                "beforeinput": (
                    "document.querySelector('input')"
                    ".addEventListener('beforeinput',e=>e.preventDefault())"
                ),
            }
            await native.evaluate(changes[change])
        result = await transport.input(
            sequence,
            {
                "kind": "field_replace",
                "editable_id": identifier,
                "edit_id": value["edit_id"],
                "text": "Must not overwrite",
            },
            frame,
        )
        assert result["accepted"] is False
        assert await native.locator("input").first.input_value() != "Must not overwrite"
    finally:
        await stop(running, transport)


async def test_readonly_attachment_cannot_read_private_value(
    manager: RunnerBrowserManager, tmp_path: Path, site: str
) -> None:
    authority = await scope(manager, tmp_path, site)
    native = manager.tasks[authority.task_id].pages[authority.page_id].page
    await native.locator("#text").fill("Synthetic private value")
    viewer = RunnerBrowserViewer(manager, Budget())
    transport = FieldTransport()
    running = asyncio.create_task(
        viewer.run(
            replace(authority, allow_input=False), transport.receive, transport.send
        )
    )
    try:
        frame = await transport.frame()
        result = await transport.input(
            1, {"kind": "field_open", "editable_id": frame.editables[0].id}
        )
        assert result["reason_code"] == "browser_read_only"
        assert transport.values.empty()
        assert await native.locator("#text").input_value() == "Synthetic private value"
    finally:
        await stop(running, transport)


async def test_child_document_replacement_retires_original_field_snapshot(
    manager: RunnerBrowserManager, tmp_path: Path, site: str
) -> None:
    authority = await scope(manager, tmp_path, site)
    native = manager.tasks[authority.task_id].pages[authority.page_id].page
    await native.set_content("<iframe srcdoc=\"<input value='Original'>\"></iframe>")
    field = native.frame_locator("iframe").locator("input")
    await field.focus()
    viewer = RunnerBrowserViewer(manager, Budget())
    transport = FieldTransport()
    running = asyncio.create_task(
        viewer.run(authority, transport.receive, transport.send)
    )
    try:
        frame = await transport.frame()
        identifier = frame.editables[0].id
        assert (
            await transport.input(1, {"kind": "field_open", "editable_id": identifier})
        )["accepted"] is True
        value = await transport.value()
        await native.locator("iframe").evaluate(
            "element => element.srcdoc=\"<input value='Replacement document'>\""
        )
        await field.wait_for()
        async with asyncio.timeout(10):
            latest = await transport.frame()
            while any(region.id == identifier for region in latest.editables):
                latest = await transport.frame()
        assert latest.source.navigation_id == frame.source.navigation_id
        result = await transport.input(
            2,
            {
                "kind": "field_replace",
                "editable_id": identifier,
                "edit_id": value["edit_id"],
                "text": "Must not overwrite",
            },
            latest,
        )
        assert result["reason_code"] == "browser_field_changed"
        assert await field.input_value() == "Replacement document"
    finally:
        await stop(running, transport)
