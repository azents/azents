"""Closed Browser application wire boundaries independent of Web forwarding."""

import json
from dataclasses import asdict

import pytest

from azents_runtime_control.browser_viewer_contract import (
    MAX_VIEWER_MESSAGE_BYTES,
    BrowserViewerContractError,
    ViewerFieldCancel,
    ViewerFieldOpen,
    ViewerFieldReplace,
    ViewerFieldValue,
    ViewerFrame,
    ViewerFrameAck,
    ViewerInput,
    ViewerNavigation,
    ViewerPaste,
    ViewerPointer,
    ViewerSource,
    ViewerTarget,
    decode_viewer_editables,
    decode_viewer_frame,
    decode_viewer_request,
    encode_viewer_event,
    encode_viewer_frame,
)


def _input() -> dict[str, object]:
    return {
        "type": "input",
        "attachment_id": "attachment",
        "sequence": 1,
        "source": {
            "frame_sequence": 1,
            "navigation_id": "navigation",
            "width": 1280,
            "height": 720,
        },
        "action": {
            "kind": "pointer",
            "phase": "down",
            "x": 12,
            "y": 24,
            "button": "left",
        },
    }


def test_request_roundtrip_and_read_only_frame_ack() -> None:
    parsed = decode_viewer_request(json.dumps(_input()).encode())
    assert isinstance(parsed, ViewerInput)
    assert parsed.action == ViewerPointer("down", 12, 24, "left")
    assert decode_viewer_request(
        b'{"type":"frame_ack","attachment_id":"a","frame_sequence":1}'
    ) == ViewerFrameAck("a", 1)


@pytest.mark.parametrize(
    "payload",
    [
        b"[]",
        b"{}",
        b'{"type":"frame_ack","type":"input"}',
        b'{"type":"frame_ack","attachment_id":"a","frame_sequence":true}',
        b'{"type":"frame_ack","attachment_id":"a","frame_sequence":0}',
        b'{"type":"frame_ack","attachment_id":"a","frame_sequence":1,"extra":1}',
        b'{"type":"evaluate","script":"secret"}',
        b"\xff",
        b"x" * 65537,
    ],
)
def test_malformed_request_is_rejected(payload: bytes) -> None:
    with pytest.raises(BrowserViewerContractError):
        decode_viewer_request(payload)


def test_paste_is_plaintext_bound_to_an_explicit_editable() -> None:
    payload = _input()
    text = ' Synthetic 한글 🔑\n"\\ '
    payload["action"] = {"kind": "paste", "editable_id": "doc-1", "text": text}
    decoded = decode_viewer_request(json.dumps(payload).encode())
    assert isinstance(decoded, ViewerInput)
    assert decoded.action == ViewerPaste("doc-1", text)
    for action in [
        {"kind": "paste", "text": text},
        {"kind": "paste", "editable_id": "", "text": text},
        {"kind": "paste", "editable_id": "x" * 49, "text": text},
        {"kind": "paste", "editable_id": "doc-1", "text": ""},
        {"kind": "paste", "editable_id": "doc-1", "text": "x" * 32769},
        {"kind": "paste", "editable_id": "doc-1", "text": "界" * 24000},
        {"kind": "paste", "editable_id": "doc-1", "text": text, "html": text},
    ]:
        payload["action"] = action
        with pytest.raises(BrowserViewerContractError):
            decode_viewer_request(json.dumps(payload, ensure_ascii=False).encode())


def test_field_editor_requests_are_scoped_and_preserve_empty_replacement() -> None:
    payload = _input()
    for action, expected in [
        ({"kind": "field_open", "editable_id": "doc-1"}, ViewerFieldOpen("doc-1")),
        (
            {
                "kind": "field_replace",
                "editable_id": "doc-1",
                "edit_id": "edit-1",
                "text": "",
            },
            ViewerFieldReplace("doc-1", "edit-1", ""),
        ),
        ({"kind": "field_cancel", "edit_id": "edit-1"}, ViewerFieldCancel("edit-1")),
    ]:
        payload["action"] = action
        decoded = decode_viewer_request(json.dumps(payload).encode())
        assert isinstance(decoded, ViewerInput) and decoded.action == expected
        payload["source"] = None
        with pytest.raises(BrowserViewerContractError):
            decode_viewer_request(json.dumps(payload).encode())
        payload = _input()


@pytest.mark.parametrize(
    "action",
    [
        {"kind": "field_open", "editable_id": ""},
        {"kind": "field_open", "editable_id": "x", "value": "not allowed"},
        {"kind": "field_replace", "editable_id": "x", "edit_id": "e"},
        {"kind": "field_replace", "editable_id": "x", "edit_id": "e", "text": None},
        {
            "kind": "field_replace",
            "editable_id": "x",
            "edit_id": "e",
            "text": "x" * 32769,
        },
        {"kind": "field_replace", "editable_id": "x", "edit_id": "", "text": ""},
        {"kind": "field_cancel", "edit_id": "e", "text": ""},
    ],
)
def test_field_editor_invalid_requests_fail_before_effects(action: object) -> None:
    payload = _input()
    payload["action"] = action
    with pytest.raises(BrowserViewerContractError):
        decode_viewer_request(json.dumps(payload).encode())


def test_explicit_field_value_reply_is_bounded_and_repr_is_content_free() -> None:
    value = "Synthetic private value 한글 🔑\n"
    reply = ViewerFieldValue("attachment", 1, "doc-1", "edit-1", "password", value)
    encoded = encode_viewer_event(reply)
    assert json.loads(encoded)["value"] == value
    assert json.loads(encoded)["type"] == "field_value"
    assert value not in repr(reply)
    assert value not in repr(ViewerFieldReplace("doc-1", "edit-1", value))
    with pytest.raises(BrowserViewerContractError):
        encode_viewer_event(
            ViewerFieldValue("attachment", 1, "doc-1", "edit-1", "text", "x" * 32769)
        )
    with pytest.raises(BrowserViewerContractError):
        encode_viewer_event(
            ViewerFieldValue("attachment", 1, "doc-1", "edit-1", "text", "界" * 24000)
        )


@pytest.mark.parametrize(
    "action",
    [
        {"kind": "pointer", "phase": "down", "x": 1, "y": 2, "button": None},
        {"kind": "pointer", "phase": "move", "x": 1, "y": 2, "button": "left"},
        {"kind": "wheel", "x": float("nan"), "y": 1, "delta_x": 0, "delta_y": 2},
        {"kind": "key", "phase": "down", "key": "Control+Shift+X"},
        {"kind": "key", "phase": "down", "key": "x" * 129},
        {"kind": "composition", "phase": "start", "text": "duplicate"},
        {"kind": "composition", "phase": "commit", "text": None},
        {"kind": "composition", "phase": "commit", "text": "x" * 32769},
        {"kind": "dialog", "dialog_id": "id", "accept": 1, "text": None},
        {"kind": "close_page", "page_id": "another-page"},
    ],
)
def test_invalid_action_combinations(action: object) -> None:
    payload = _input()
    payload["action"] = action
    with pytest.raises(BrowserViewerContractError):
        decode_viewer_request(json.dumps(payload).encode())


def test_dialog_requires_null_source_without_fake_frame_identity() -> None:
    payload = _input()
    payload["action"] = {
        "kind": "dialog",
        "dialog_id": "current-dialog",
        "accept": True,
        "text": None,
    }
    with pytest.raises(BrowserViewerContractError):
        decode_viewer_request(json.dumps(payload).encode())
    payload["source"] = None
    parsed = decode_viewer_request(json.dumps(payload).encode())
    assert isinstance(parsed, ViewerInput) and parsed.source is None
    payload["action"] = {"kind": "key", "phase": "down", "key": "Enter"}
    with pytest.raises(BrowserViewerContractError):
        decode_viewer_request(json.dumps(payload).encode())
    del payload["source"]
    with pytest.raises(BrowserViewerContractError):
        decode_viewer_request(json.dumps(payload).encode())


@pytest.mark.parametrize(
    ("action", "url"),
    [
        ("navigate", "https://example.test/path?query=synthetic#part"),
        ("back", None),
        ("forward", None),
        ("reload", None),
    ],
)
def test_navigation_uses_the_current_acknowledged_source(
    action: str, url: str | None
) -> None:
    payload = _input()
    payload["action"] = {"kind": "navigation", "action": action, "url": url}
    parsed = decode_viewer_request(json.dumps(payload).encode())
    assert isinstance(parsed, ViewerInput)
    assert isinstance(parsed.action, ViewerNavigation)
    assert parsed.action.action == action
    assert parsed.action.url == url
    assert parsed.source == ViewerSource(1, "navigation", 1280, 720)
    payload["source"] = None
    with pytest.raises(BrowserViewerContractError):
        decode_viewer_request(json.dumps(payload).encode())


@pytest.mark.parametrize(
    ("action", "url"),
    [
        ("navigate", None),
        ("navigate", ""),
        ("navigate", "javascript:alert(1)"),
        ("navigate", "file:///etc/passwd"),
        ("navigate", "https://user:secret@example.test/"),
        ("navigate", "https://example.test:invalid/"),
        ("navigate", "https://[invalid/"),
        ("back", "https://example.test/"),
        ("forward", ""),
        ("reload", "https://example.test/"),
        ("unknown", None),
    ],
)
def test_invalid_navigation_is_rejected_before_effects(
    action: str, url: str | None
) -> None:
    payload = _input()
    payload["action"] = {"kind": "navigation", "action": action, "url": url}
    with pytest.raises(BrowserViewerContractError):
        decode_viewer_request(json.dumps(payload).encode())


def test_binary_header_and_image_are_exact_and_bounded() -> None:
    frame = ViewerFrame(
        "attachment",
        ViewerTarget("task", "page", "incarnation"),
        ViewerSource(1, "nav", 1280, 720),
        b"\xff\xd8JPEG\xff\xd9",
        (),
    )
    encoded = encode_viewer_frame(frame)
    assert decode_viewer_frame(encoded) == frame
    size = int.from_bytes(encoded[:4], "big")
    header = json.loads(encoded[4 : 4 + size])
    assert header["target"] == asdict(frame.target)
    assert encoded[4 + size :] == frame.image
    with pytest.raises(BrowserViewerContractError):
        encode_viewer_frame(
            ViewerFrame(
                frame.attachment_id,
                frame.target,
                frame.source,
                b"x" * MAX_VIEWER_MESSAGE_BYTES,
                (),
            )
        )
    for invalid in [
        b"",
        encoded[:4],
        (5000).to_bytes(4, "big") + encoded[4:],
        encoded[: 4 + size],
    ]:
        with pytest.raises(BrowserViewerContractError):
            decode_viewer_frame(invalid)


def test_editable_regions_are_bounded_content_free_and_viewport_scoped() -> None:
    region = {
        "id": "native-1",
        "x": 10,
        "y": 20,
        "width": 100,
        "height": 40,
        "input_mode": "text",
    }
    decoded = decode_viewer_editables([region], 1280, 800)
    assert len(decoded) == 1 and decoded[0].id == "native-1"
    for invalid in [
        [region, region],
        [region] * 17,
        [{**region, "value": "never part of geometry"}],
        [{**region, "x": -1}],
        [{**region, "width": 0}],
        [{**region, "y": 790}],
        [{**region, "input_mode": "unknown"}],
        [{**region, "x": float("nan")}],
    ]:
        with pytest.raises(BrowserViewerContractError):
            decode_viewer_editables(invalid, 1280, 800)
