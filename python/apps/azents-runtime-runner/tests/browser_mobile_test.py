"""Native mobile launch contracts across both selected browser engines."""

from pathlib import Path

import pytest
from azents_runtime_control.browser_configuration import BrowserImplementation
from azents_runtime_control.browser_contract import BrowserAuthority, BrowserOpenCommand

from azents_runtime_runner.browser import RunnerBrowserManager
from azents_runtime_runner.browser_input import BrowserInputKey


@pytest.mark.parametrize("implementation", tuple(BrowserImplementation))
async def test_mobile_identity_geometry_touch_and_edge_input(
    tmp_path: Path, implementation: BrowserImplementation
) -> None:
    manager = RunnerBrowserManager(
        workspace_root=tmp_path,
        proxy=None,
        input_key=BrowserInputKey(),
        implementation=implementation,
    )
    try:
        opened = await manager.execute(
            BrowserOpenCommand(
                BrowserAuthority("mobile-fixture", str(tmp_path / "session")),
                None,
                None,
                None,
            )
        )
        assert opened.page is not None
        page = manager.tasks[opened.page.task_id].pages[opened.page.id].page
        await page.set_content(
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<label style="position:fixed;left:350px;top:510px">'
            '<input type="checkbox">Edge</label>'
        )
        assert page.viewport_size == {"width": 400, "height": 560}
        assert await page.evaluate(
            """() => innerWidth === 400 && innerHeight === 560 &&
                screen.width === 400 && screen.height === 560 &&
                navigator.userAgent.includes('Mobile') &&
                navigator.maxTouchPoints > 0 &&
                matchMedia('(pointer: coarse)').matches"""
        )
        checkbox = page.get_by_role("checkbox")
        bounds = await checkbox.bounding_box()
        assert bounds is not None
        await page.mouse.move(
            bounds["x"] + bounds["width"] / 2,
            bounds["y"] + bounds["height"] / 2,
        )
        await page.mouse.down()
        await page.mouse.up()
        assert await checkbox.is_checked()
    finally:
        await manager.close()
