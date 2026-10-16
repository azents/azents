"""Native receiver rectangles stay inside rounded controls and reject occlusion."""

from collections.abc import AsyncIterator

import pytest
from playwright.async_api import Page, async_playwright

from azents_runtime_runner.browser_editables import BrowserEditableRegions


@pytest.fixture
async def geometry_page() -> AsyncIterator[Page]:
    async with async_playwright() as driver:
        browser = await driver.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 800, "height": 600})
        yield page
        await browser.close()


@pytest.mark.parametrize(
    "tag,radius",
    [
        ("input", "8px"),
        ("input", "9999px"),
        ("input", "50%"),
        ("input", "30% / 45%"),
        ("input", "40px 8px 24px 0px / 12px 20px 16px 0px"),
        ("input", "200px 180px / 100px 80px"),
        ("textarea", "8px"),
    ],
)
async def test_rounded_native_receiver_is_inscribed_and_keeps_identity(
    geometry_page: Page, tag: str, radius: str
) -> None:
    await geometry_page.set_content(
        f"<style>{tag} {{position:absolute;left:100px;top:100px;"
        f"box-sizing:border-box;width:300px;height:48px;border-radius:{radius};}}"
        f"</style><{tag} id=field></{tag}>"
    )
    regions = BrowserEditableRegions(geometry_page)
    try:
        first = await regions.read()
        assert len(first) == 1
        region = first[0]
        assert 100 < region.x < 250
        assert 100 < region.y < 124
        assert 4 <= region.width < 300
        assert 4 <= region.height < 48
        assert await geometry_page.evaluate(
            """r => [0.01, 0.25, 0.5, 0.75, 0.99].every(dx =>
                [0.01, 0.25, 0.5, 0.75, 0.99].every(dy =>
                    document.elementFromPoint(r.x+r.width*dx,r.y+r.height*dy)
                    === document.querySelector('#field')))""",
            {
                "x": region.x,
                "y": region.y,
                "width": region.width,
                "height": region.height,
            },
        )
        field = geometry_page.locator("#field")
        await field.focus()
        assert await regions.focused(region.id)
        edit = await regions.open_edit(region.id)
        assert edit is not None
        assert await edit.replace("Synthetic rounded edit")
        assert await field.input_value() == "Synthetic rounded edit"
        await edit.close()
        await field.evaluate("e => e.style.borderRadius='0px'")
        square = await regions.read()
        assert len(square) == 1
        assert square[0].id == region.id
        assert square[0].x == 100 and square[0].width == 300
    finally:
        await regions.close()


@pytest.mark.parametrize("position", ["center", "left", "top", "all"])
async def test_rounded_input_still_rejects_actual_occlusion(
    geometry_page: Page, position: str
) -> None:
    await geometry_page.set_content("""<style>
        input {position:absolute;left:100px;top:100px;width:300px;height:48px;
        border-radius:8px;box-sizing:border-box}
        </style><input><div id=overlay style='position:absolute;z-index:2'></div>""")
    regions = BrowserEditableRegions(geometry_page)
    try:
        original = await regions.read()
        assert len(original) == 1
        r = original[0]
        x = r.x if position in ("left", "all") else r.x + r.width / 2 - 3
        y = r.y if position in ("top", "all") else r.y + r.height / 2 - 3
        await geometry_page.locator("#overlay").evaluate(
            """(e,b) => Object.assign(e.style, {
                left:b.x+'px',top:b.y+'px',width:b.width+'px',height:b.height+'px'
            })""",
            {
                "x": x,
                "y": y,
                "width": r.width if position == "all" else 6,
                "height": r.height if position == "all" else 6,
            },
        )
        assert await regions.read() == ()
    finally:
        await regions.close()


async def test_rounded_geometry_preserves_clipping_and_writable_eligibility(
    geometry_page: Page,
) -> None:
    await geometry_page.set_content("""<style>
        div {position:absolute;left:100px;top:100px;width:140px;
        height:48px;overflow:hidden}
        input {width:300px;height:48px;border-radius:8px;box-sizing:border-box}
        </style><div><input id=field></div>""")
    regions = BrowserEditableRegions(geometry_page)
    try:
        region = (await regions.read())[0]
        assert region.x + region.width <= 240
        field = geometry_page.locator("#field")
        for attribute in ("readonly", "disabled"):
            await field.evaluate("(e,a)=>e.setAttribute(a,'')", attribute)
            assert await regions.read() == ()
            await field.evaluate("(e,a)=>e.removeAttribute(a)", attribute)
            assert (await regions.read())[0].id == region.id
    finally:
        await regions.close()
