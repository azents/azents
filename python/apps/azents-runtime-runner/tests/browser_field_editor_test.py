"""Native field snapshots preserve identity and reject independent mutations."""

from collections.abc import AsyncIterator
from dataclasses import asdict

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


async def test_original_native_editing_attributes_are_read_with_value(
    field_page: Page,
) -> None:
    await field_page.set_content("""
        <form autocapitalize=off autocorrect=off>
          <input type=email inputmode=email autocomplete=email name=contact
            placeholder='name@example.test' spellcheck=false enterkeyhint=next
            maxlength=80 minlength=3 pattern='.+@.+' required multiple>
        </form>
    """)
    await field_page.locator("input").fill("reader@example.test")
    regions = BrowserEditableRegions(field_page)
    edit = await regions.open_edit((await regions.read())[0].id)
    assert edit is not None
    value = await edit.value()
    assert asdict(value.attributes) == {
        "input_type": "email",
        "input_mode": "email",
        "autocomplete": "email",
        "autocapitalize": "none",
        "autocorrect": "off",
        "spellcheck": False,
        "enter_key_hint": "next",
        "max_length": 80,
        "min_length": 3,
        "pattern": ".+@.+",
        "required": True,
        "multiple": True,
        "placeholder": "name@example.test",
        "name": "contact",
    }
    assert value.kind == "text"
    assert "reader@example.test" not in repr(value)
    assert "name@example.test" not in repr(value)
    await edit.close()
    await regions.close()


@pytest.mark.parametrize(
    "markup,capitalize,correct",
    [
        (
            "<form id=f autocapitalize=characters autocorrect=off></form>"
            "<input form=f value=Original>",
            "characters",
            "off",
        ),
        ("<div autocapitalize=characters autocorrect=off><input></div>", None, "on"),
        (
            "<form autocapitalize=words autocorrect=off>"
            "<div autocapitalize=characters autocorrect=on><input></div></form>",
            "words",
            "off",
        ),
    ],
)
async def test_effective_native_hints_follow_form_owner_not_generic_ancestors(
    field_page: Page, markup: str, capitalize: str | None, correct: str
) -> None:
    await field_page.set_content(markup)
    await field_page.locator("input").focus()
    regions = BrowserEditableRegions(field_page)
    edit = await regions.open_edit((await regions.read())[0].id)
    assert edit is not None
    attributes = (await edit.value()).attributes
    assert attributes.autocapitalize == capitalize and attributes.autocorrect == correct
    await edit.close()
    await regions.close()


async def test_external_form_hint_change_retires_edit_configuration(
    field_page: Page,
) -> None:
    await field_page.set_content(
        "<form id=f autocapitalize=characters autocorrect=off></form>"
        "<input form=f value=Original>"
    )
    await field_page.locator("input").focus()
    regions = BrowserEditableRegions(field_page)
    edit = await regions.open_edit((await regions.read())[0].id)
    assert edit is not None
    await field_page.locator("form").evaluate("form=>form.autocapitalize='off'")
    assert not await edit.replace("Must not overwrite")
    assert await field_page.locator("input").input_value() == "Original"
    await edit.close()
    await regions.close()


async def test_irrelevant_ancestor_hint_change_does_not_invent_config_change(
    field_page: Page,
) -> None:
    await field_page.set_content(
        "<div autocapitalize=characters autocorrect=off><input value=Original></div>"
    )
    await field_page.locator("input").focus()
    regions = BrowserEditableRegions(field_page)
    edit = await regions.open_edit((await regions.read())[0].id)
    assert edit is not None
    await field_page.locator("div").evaluate("div=>div.autocapitalize='off'")
    assert await edit.replace("Replacement")
    await edit.close()
    await regions.close()


async def test_form_autocomplete_default_is_respected(field_page: Page) -> None:
    await field_page.set_content("<form autocomplete=off><input></form>")
    await field_page.locator("input").focus()
    regions = BrowserEditableRegions(field_page)
    edit = await regions.open_edit((await regions.read())[0].id)
    assert edit is not None
    assert (await edit.value()).attributes.autocomplete == "off"
    await edit.close()
    await regions.close()


@pytest.mark.parametrize(
    "change",
    [
        "field.autocomplete='email'",
        "field.name='different'",
        "field.maxLength=10",
        "field.pattern='different'",
        "field.spellcheck=false",
    ],
)
async def test_changed_native_attributes_reject_before_replacement(
    field_page: Page, change: str
) -> None:
    await field_page.set_content("<input value=Original>")
    await field_page.locator("input").focus()
    regions = BrowserEditableRegions(field_page)
    edit = await regions.open_edit((await regions.read())[0].id)
    assert edit is not None
    await field_page.evaluate("const field=document.querySelector('input');" + change)
    assert not await edit.replace("Must not overwrite")
    assert await field_page.locator("input").input_value() == "Original"
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


@pytest.mark.parametrize(
    "markup,text",
    [
        ("<input>", "First\nSecond"),
        ("<input type=password>", "Synthetic\r\nSecret"),
        ("<input type=tel>", "123\n456"),
        ("<input type=email>", "  user@example.test  "),
        ("<input type=url>", "  https://example.test  "),
        ("<textarea></textarea>", "First\r\nSecond"),
    ],
)
async def test_unrepresentable_draft_preserves_original_before_events(
    field_page: Page, markup: str, text: str
) -> None:
    await field_page.set_content(markup)
    native = field_page.locator("input,textarea")
    await native.fill("Original")
    await field_page.evaluate("""
        document.body.dataset.events='0';
        for (const type of ['beforeinput','input'])
            document.addEventListener(type,()=>
                document.body.dataset.events=String(
                    Number(document.body.dataset.events)+1));
    """)
    regions = BrowserEditableRegions(field_page)
    edit = await regions.open_edit((await regions.read())[0].id)
    assert edit is not None
    assert not await edit.replace(text)
    assert await native.input_value() == "Original"
    assert await field_page.evaluate("document.body.dataset.events") == "0"
    await edit.close()
    await regions.close()


async def test_beforeinput_cannot_change_value_sanitization_configuration(
    field_page: Page,
) -> None:
    await field_page.set_content("<input type=email value='original@example.test'>")
    await field_page.locator("input").focus()
    regions = BrowserEditableRegions(field_page)
    edit = await regions.open_edit((await regions.read())[0].id)
    assert edit is not None
    await field_page.evaluate("""
        const field=document.querySelector('input');
        field.addEventListener('beforeinput',()=>field.multiple=true);
        document.body.dataset.inputs='0';
        field.addEventListener('input',()=>document.body.dataset.inputs='1');
    """)
    assert not await edit.replace("replacement@example.test")
    assert await field_page.locator("input").input_value() == "original@example.test"
    assert await field_page.evaluate("document.body.dataset.inputs") == "0"
    await edit.close()
    await regions.close()
