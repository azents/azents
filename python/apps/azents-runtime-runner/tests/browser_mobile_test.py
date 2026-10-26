"""Native mobile launch contracts across both selected browser engines."""

from base64 import b64encode
from io import BytesIO
from pathlib import Path
from random import Random

import pytest
from azents_runtime_control.browser_configuration import BrowserImplementation
from azents_runtime_control.browser_contract import BrowserAuthority, BrowserOpenCommand
from PIL import Image

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
                navigator.maxTouchPoints > 0 && devicePixelRatio === 2 &&
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
        pixels = await page.screenshot(type="jpeg", scale="device", quality=85)
        with Image.open(BytesIO(pixels)) as image:
            assert image.size == (800, 1120)
        # Decode a deterministic high-entropy fixture in both native engines.
        # Creating pixel arrays in page evaluation crosses Firefox Xray boundaries.
        noise = Image.frombytes(
            "RGB", (800, 1120), Random(12345).randbytes(800 * 1120 * 3)
        )
        buffer = BytesIO()
        noise.save(buffer, format="PNG")
        encoded = b64encode(buffer.getvalue()).decode("ascii")
        await page.set_content(
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            "<style>body{margin:0}img{width:400px;height:560px}</style>"
            f'<img src="data:image/png;base64,{encoded}">'
        )
        await page.locator("img").evaluate("image => image.decode()")
        detailed = await page.screenshot(
            type="jpeg", scale="device", quality=85, timeout=2000
        )
        # Include the maximal metadata allowance, not only encoded JPEG bytes.
        assert len(detailed) + 4096 + 4 <= 1024 * 1024
    finally:
        await manager.close()
