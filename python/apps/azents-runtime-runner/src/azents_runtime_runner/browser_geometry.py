"""Map mobile visual-viewport pixels to the SDK's layout-viewport coordinates."""

import math
from dataclasses import dataclass

from azents_runtime_runner.browser_sdk import Page


@dataclass(frozen=True)
class BrowserVisualGeometry:
    scale: float
    left: float
    top: float

    def native_x(self, x: float) -> float:
        return x / self.scale + self.left

    def native_y(self, y: float) -> float:
        return y / self.scale + self.top


async def browser_visual_geometry(page: Page) -> BrowserVisualGeometry:
    raw: object = await page.evaluate(
        """() => ({scale:visualViewport?.scale ?? 1,
            left:visualViewport?.offsetLeft ?? 0,
            top:visualViewport?.offsetTop ?? 0})"""
    )
    if not isinstance(raw, dict):
        raise ValueError("Invalid Browser visual viewport")
    scale, left, top = raw.get("scale"), raw.get("left"), raw.get("top")
    if (
        not isinstance(scale, (int, float))
        or not isinstance(left, (int, float))
        or not isinstance(top, (int, float))
        or not all(math.isfinite(v) for v in (scale, left, top))
        or scale <= 0
    ):
        raise ValueError("Invalid Browser visual viewport geometry")
    return BrowserVisualGeometry(float(scale), float(left), float(top))
