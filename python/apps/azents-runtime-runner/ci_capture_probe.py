"""Temporary synthetic timing probe; remove before final CI acceptance."""

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

from aiohttp import web
from azents_runtime_control.browser_contract import BrowserAuthority, BrowserOpenCommand
from patchright.async_api import Error

from azents_runtime_runner.browser import BrowserFailure, RunnerBrowserManager
from azents_runtime_runner.browser_editables import BrowserEditableRegions
from azents_runtime_runner.browser_input import BrowserInputKey
from azents_runtime_runner.browser_popups import BrowserPopupTracker
from azents_runtime_runner.browser_viewer import (
    _capture_error_code,
    _capture_timeout_stage,
)


def emit(record: dict[str, bool | int | float | str]) -> None:
    """Write machine-readable diagnostic records to the command's stdout."""
    sys.stdout.write(json.dumps(record) + "\n")
    sys.stdout.flush()


async def probe() -> None:
    with tempfile.TemporaryDirectory(prefix="capture-diagnostic-") as directory:
        root = Path(directory).resolve()
        app = web.Application()

        async def fixture(_request: web.Request) -> web.Response:
            return web.Response(text="<input>", content_type="text/html")

        app.router.add_get("/", fixture)
        server = web.AppRunner(app)
        manager = RunnerBrowserManager(
            workspace_root=root, proxy=None, input_key=BrowserInputKey()
        )
        manager.bind_runtime("diagnostic", lambda: 1)
        started = time.monotonic()
        try:
            await server.setup()
            await web.TCPSite(server, "127.0.0.1", 0).start()
            result = await manager.execute(
                BrowserOpenCommand(
                    BrowserAuthority("diagnostic", str(root / "session")),
                    None,
                    f"http://127.0.0.1:{server.addresses[0][1]}/",
                    None,
                )
            )
            assert result.page is not None
            page = manager.tasks[result.page.task_id].pages[result.page.id].page
            await page.set_content("<input>")
            await page.locator("input").fill("Synthetic fixture")
            popups = BrowserPopupTracker(page, lambda: None)
            try:
                await popups.start()
                editables = BrowserEditableRegions(page)
                for ordinal in (1, 2):
                    await editables.read()
                    before = time.monotonic()
                    # Ordinary image observation uses the SDK default deadline;
                    # this does not alter the live viewer's two-second deadline.
                    image = await page.screenshot(
                        type="jpeg", scale="css", quality=60, full_page=False
                    )
                    after = time.monotonic()
                    assert (
                        image.startswith(b"\xff\xd8") and len(image) < 6 * 1024 * 1024
                    )
                    emit(
                        {
                            "diagnostic_only": True,
                            "capture_ordinal": ordinal,
                            "capture_seconds": after - before,
                            "capture_started_since_manager_seconds": before - started,
                            "capture_finished_since_manager_seconds": after - started,
                            "image_bytes": len(image),
                        }
                    )
            finally:
                await popups.close()
        finally:
            try:
                await manager.close()
            finally:
                await server.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(probe())
    except Error as error:
        emit(
            {
                "diagnostic_only": True,
                "failed": True,
                "reason_code": _capture_error_code(error),
                "last_sdk_milestone": _capture_timeout_stage(error),
            }
        )
        raise SystemExit(1) from None
    except BrowserFailure as error:
        emit(
            {
                "diagnostic_only": True,
                "failed": True,
                "reason_code": error.code,
            }
        )
        raise SystemExit(1) from None
