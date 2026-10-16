"""Native field snapshots preserve identity and reject independent mutations."""

from collections.abc import AsyncIterator

import pytest
from playwright.async_api import Page, async_playwright

from azents_runtime_runner.browser_editables import BrowserEditableRegions


@pytest.fixture
async def field_page() -> AsyncIterator[Page]:
    async with async_playwright() as driver:
        browser = await driver.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 800, "height": 600})
        yield page
        await browser.close()


@pytest.mark.parametrize(
    "markup,kind",
    [
        ("<input type=text>", "text"),
        ("<input type=password>", "password"),
        ("<textarea></textarea>", "multiline"),
    ],
)
async def test_explicit_snapshot_replaces_native_value_once(
    field_page: Page, markup: str, kind: str
) -> None:
    await field_page.set_content(markup)
    field = field_page.locator("input,textarea")
    await field.fill("Existing synthetic value 한글")
    await field.focus()
    regions = BrowserEditableRegions(field_page)
    entries = await regions.read()
    assert len(entries) == 1
    edit = await regions.open_edit(entries[0].id)
    assert edit is not None
    value = await edit.value()
    assert value.kind == kind and value.value == "Existing synthetic value 한글"
    assert value.value not in repr(value)
    await field_page.evaluate(
        "document.body.dataset.inputs='0';document.addEventListener('input',()=>document.body.dataset.inputs=String(Number(document.body.dataset.inputs)+1))"
    )
    assert await edit.replace("Changed synthetic value 🔑")
    assert await field.input_value() == "Changed synthetic value 🔑"
    assert await field_page.evaluate("document.body.dataset.inputs") == "1"
    assert not await edit.replace("Cannot replay")
    assert await field.input_value() == "Changed synthetic value 🔑"
    await edit.close()
    await regions.close()


@pytest.mark.parametrize(
    "change",
    [
        "document.querySelector('input').value='Independent change'",
        "document.querySelector('input').readOnly=true",
        "document.querySelector('input').disabled=true",
        "document.querySelector('input').type='password'",
        "document.querySelector('input').replaceWith(document.createElement('input'))",
        "document.querySelector('button').focus()",
        "document.querySelector('input').addEventListener('beforeinput',event=>event.preventDefault())",
        "document.querySelector('input').addEventListener('beforeinput',"
        "()=>document.querySelector('input').value='Site change')",
    ],
)
async def test_snapshot_refuses_changed_target_before_any_overwrite(
    field_page: Page, change: str
) -> None:
    await field_page.set_content("<input value='Original'><button>Other</button>")
    await field_page.locator("input").focus()
    regions = BrowserEditableRegions(field_page)
    identifier = (await regions.read())[0].id
    edit = await regions.open_edit(identifier)
    assert edit is not None
    await field_page.evaluate(change)
    assert not await edit.replace("Must never overwrite")
    assert await field_page.locator("input").input_value() != "Must never overwrite"
    await edit.close()
    await regions.close()


async def test_empty_replacement_and_unsupported_editor(field_page: Page) -> None:
    await field_page.set_content(
        "<input value='Clear me'><div contenteditable=true>Custom editor</div>"
    )
    regions = BrowserEditableRegions(field_page)
    await field_page.locator("input").focus()
    identifier = (await regions.read())[0].id
    edit = await regions.open_edit(identifier)
    assert edit is not None and await edit.replace("")
    assert await field_page.locator("input").input_value() == ""
    await edit.close()
    await field_page.locator("[contenteditable]").focus()
    custom = (await regions.read())[1]
    assert await regions.open_edit(custom.id) is None
    await regions.close()
