"""Strict browser command/result wire validation and closed capability tests."""

from dataclasses import replace
from typing import Literal

import pytest

from azents_runtime_control.browser_contract import (
    BrowserActCommand,
    BrowserAction,
    BrowserActionKind,
    BrowserAuthority,
    BrowserCapture,
    BrowserContractError,
    BrowserDialog,
    BrowserElementRef,
    BrowserFrame,
    BrowserObserveCommand,
    BrowserOpenCommand,
    BrowserPage,
    BrowserResult,
    BrowserTarget,
    BrowserTask,
    browser_operation_type,
    decode_browser_command,
    decode_browser_result,
    encode_browser_command,
    encode_browser_result,
)


def _action(
    kind: BrowserActionKind,
    *,
    ref: str | None = None,
    observation_id: str | None = None,
    text: str | None = None,
    url: str | None = None,
    values: tuple[str, ...] | None = None,
    checked: bool | None = None,
    key: str | None = None,
    x: float | None = None,
    y: float | None = None,
    end_ref: str | None = None,
    paths: tuple[str, ...] | None = None,
    dialog_id: str | None = None,
    accept: bool | None = None,
    condition: Literal["visible", "hidden", "url"] | None = None,
    expect: Literal["popup", "download"] | None = None,
    timeout_ms: int = 10000,
) -> BrowserAction:
    """Fixture options explicitly construct every production DTO field."""
    return BrowserAction(
        kind,
        ref,
        observation_id,
        text,
        None,
        url,
        values,
        checked,
        key,
        x,
        y,
        end_ref,
        paths,
        dialog_id,
        accept,
        condition,
        expect,
        timeout_ms,
    )


AUTHORITY = BrowserAuthority("session", "/workspace/session")
TARGET = BrowserTarget("task", "page", "incarnation", None)


@pytest.mark.parametrize(
    "text,encrypted_text,kind,valid",
    [
        (None, "A" * 64, "fill", True),
        ("", None, "fill", True),
        ("literal", "A" * 64, "fill", False),
        (None, None, "fill", False),
        (None, "A" * 5529, "fill", False),
        (None, "A" * 64, "click", False),
    ],
)
def test_exclusive_encrypted_fill_contract(
    text: str | None,
    encrypted_text: str | None,
    kind: BrowserActionKind,
    valid: bool,
) -> None:
    action = replace(
        _action(kind, ref="r", observation_id="o", text=text),
        encrypted_text=encrypted_text,
    )
    command = BrowserActCommand(AUTHORITY, TARGET, action)
    if valid:
        assert (
            decode_browser_command("browser.act", encode_browser_command(command))
            == command
        )
    else:
        with pytest.raises(BrowserContractError):
            decode_browser_command("browser.act", encode_browser_command(command))


@pytest.mark.parametrize(
    "command",
    [
        BrowserOpenCommand(AUTHORITY, None, None, None),
        BrowserObserveCommand(AUTHORITY, None, "status", False, 10000),
        BrowserObserveCommand(AUTHORITY, TARGET, "glance", False, 10000),
        BrowserActCommand(
            AUTHORITY,
            TARGET,
            _action("fill", ref="r", observation_id="o", text=""),
        ),
        BrowserActCommand(
            AUTHORITY, TARGET, _action("navigate", url="https://fixture.example")
        ),
        BrowserActCommand(
            AUTHORITY,
            TARGET,
            _action("click", ref="r", observation_id="o", expect="download"),
        ),
        BrowserActCommand(
            AUTHORITY,
            TARGET,
            _action("dialog", dialog_id="d", accept=True, text=""),
        ),
    ],
)
def test_command_roundtrip(
    command: BrowserOpenCommand | BrowserObserveCommand | BrowserActCommand,
) -> None:
    assert (
        decode_browser_command(
            browser_operation_type(command), encode_browser_command(command)
        )
        == command
    )


@pytest.mark.parametrize(
    "action",
    [
        _action("fill", text="x"),
        _action("click", ref="r"),
        _action("reload", text="unrelated"),
        _action("scroll", x=1),
        _action("dialog", dialog_id="d"),
        _action("wait"),
        _action("press", key="Enter", expect="popup", url="unrelated"),
        _action("close_page", expect="download"),
    ],
)
def test_action_semantic_validation_before_effects(action: BrowserAction) -> None:
    with pytest.raises(BrowserContractError):
        encode_browser_command(BrowserActCommand(AUTHORITY, TARGET, action))


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "evaluate"),
        ("timeout_ms", True),
        ("timeout_ms", 60001),
        ("checked", "true"),
        ("x", float("nan")),
        ("paths", [42]),
        ("script", "alert(1)"),
    ],
)
def test_unknown_or_coerced_action_fields_are_rejected(
    field: str, value: object
) -> None:
    payload = encode_browser_command(
        BrowserActCommand(AUTHORITY, TARGET, _action("reload"))
    )
    action = payload["action"]
    assert isinstance(action, dict)
    # Test untrusted arbitrary wire data, not a typed production construction.
    action[field] = value
    with pytest.raises(BrowserContractError):
        decode_browser_command("browser.act", payload)


def result() -> BrowserResult:
    page = BrowserPage(
        "page",
        "task",
        "incarnation",
        "about:blank",
        "",
        (BrowserFrame("frame", "about:blank", ""),),
    )
    return BrowserResult(
        (BrowserTask("task", "", "incarnation", (page,)),),
        page,
        "",
        False,
        (BrowserElementRef("ref", "obs", "frame", "input", "Name"),),
        BrowserCapture("/workspace/capture.png", "image/png", 16, 1280, 800),
        None,
        None,
        BrowserDialog("dialog", "alert", ""),
        "none",
    )


def test_completed_projection_roundtrip_without_model_image_bytes() -> None:
    projection = result()
    assert decode_browser_result(encode_browser_result(projection)) == projection
    assert (
        decode_browser_result(
            encode_browser_result(replace(projection, content="x" * 100000))
        ).content
        == "x" * 100000
    )


@pytest.mark.parametrize(
    "field,value", [("title", 42), ("title", False), ("frames", {})]
)
def test_page_result_is_not_coerced(field: str, value: object) -> None:
    payload = encode_browser_result(result())
    page = payload["page"]
    assert isinstance(page, dict)
    page[field] = value
    with pytest.raises(BrowserContractError):
        decode_browser_result(payload)


def test_unknown_field_and_mismatched_operation_fail_closed() -> None:
    payload = encode_browser_command(BrowserOpenCommand(AUTHORITY, None, None, None))
    payload["session_id"] = "other"
    with pytest.raises(BrowserContractError):
        decode_browser_command("browser.open", payload)
    with pytest.raises(BrowserContractError):
        decode_browser_command("browser.evaluate", {})
    observed = BrowserObserveCommand(AUTHORITY, TARGET, "dom", False, 10)
    with pytest.raises(BrowserContractError):
        decode_browser_command("browser.list", encode_browser_command(observed))
