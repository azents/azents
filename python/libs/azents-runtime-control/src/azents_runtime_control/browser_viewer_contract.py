"""Strict bounded Browser viewer messages carried by the common logical stream."""

import enum
import json
import math
from dataclasses import asdict, dataclass
from typing import Literal, assert_never
from urllib.parse import urlsplit

MAX_VIEWER_MESSAGE_BYTES = 1024 * 1024
MAX_VIEWER_TEXT_BYTES = 64 * 1024
MAX_VIEWER_HEADER_BYTES = 4096


class BrowserViewerContractError(ValueError):
    """Reject malformed viewer bytes before any browser effect."""


@dataclass(frozen=True)
class ViewerTarget:
    task_id: str
    page_id: str
    resource_incarnation: str


@dataclass(frozen=True)
class ViewerSource:
    frame_sequence: int
    navigation_id: str
    width: int
    height: int


@dataclass(frozen=True)
class ViewerFrameAck:
    attachment_id: str
    frame_sequence: int


@dataclass(frozen=True)
class ViewerPointer:
    phase: Literal["move", "down", "up", "cancel"]
    x: float
    y: float
    button: Literal["left", "middle", "right"] | None


@dataclass(frozen=True)
class ViewerWheel:
    x: float
    y: float
    delta_x: float
    delta_y: float


@dataclass(frozen=True)
class ViewerKey:
    phase: Literal["down", "up"]
    key: str


@dataclass(frozen=True)
class ViewerComposition:
    phase: Literal["start", "commit", "cancel"]
    text: str | None


@dataclass(frozen=True)
class ViewerDialogResponse:
    dialog_id: str
    accept: bool
    text: str | None


@dataclass(frozen=True)
class ViewerNavigation:
    action: Literal["navigate", "back", "forward", "reload"]
    url: str | None


type ViewerAction = (
    ViewerPointer
    | ViewerWheel
    | ViewerKey
    | ViewerComposition
    | ViewerDialogResponse
    | ViewerNavigation
)


@dataclass(frozen=True)
class ViewerInput:
    attachment_id: str
    sequence: int
    source: ViewerSource | None
    action: ViewerAction


type ViewerRequest = ViewerFrameAck | ViewerInput


@dataclass(frozen=True)
class ViewerDialog:
    id: str
    type: str
    message: str


@dataclass(frozen=True)
class ViewerStatus:
    attachment_id: str
    target: ViewerTarget
    state: Literal["connected", "unavailable", "closed"]
    allow_input: bool
    width: int
    height: int
    navigation_id: str
    dialog: ViewerDialog | None
    conflict: bool


class ViewerInputReason(enum.StrEnum):
    """Closed content-free failure categories, never an SDK exception body."""

    READ_ONLY = "browser_read_only"
    STALE_INPUT = "browser_stale_input"
    STALE_FRAME = "browser_stale_frame"
    STALE_TARGET = "browser_stale_target"
    STALE_GENERATION = "browser_stale_generation"
    INVALID_AUTHORITY = "browser_invalid_authority"
    INVALID_URL = "browser_invalid_url"
    INPUT_CONFLICT = "browser_input_conflict"
    DIALOG_PENDING = "browser_dialog_pending"
    STALE_DIALOG = "browser_stale_dialog"
    RESOURCE_EXHAUSTED = "browser_resource_exhausted"
    UNAVAILABLE = "browser_unavailable"
    DEADLINE = "browser_deadline"
    OUTCOME_UNKNOWN = "browser_outcome_unknown"


@dataclass(frozen=True)
class ViewerInputAck:
    attachment_id: str
    sequence: int
    accepted: bool
    reason_code: ViewerInputReason | None
    outcome: Literal["dispatched", "rejected", "outcome_unknown"]


@dataclass(frozen=True)
class ViewerFrame:
    attachment_id: str
    target: ViewerTarget
    source: ViewerSource
    image: bytes


class _Fields:
    def __init__(self, value: object, names: set[str]) -> None:
        if not isinstance(value, dict) or set(value) != names:
            raise BrowserViewerContractError("Missing or unknown Browser viewer field")
        self.value = value

    def text(self, key: str, limit: int = 128, *, empty: bool = False) -> str:
        value = self.value[key]
        if (
            not isinstance(value, str)
            or len(value) > limit
            or (not value and not empty)
        ):
            raise BrowserViewerContractError("Invalid Browser viewer text")
        return value

    def nullable_text(self, key: str, limit: int = 32768) -> str | None:
        return None if self.value[key] is None else self.text(key, limit, empty=True)

    def integer(self, key: str, maximum: int = (1 << 53) - 1) -> int:
        value = self.value[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= maximum
        ):
            raise BrowserViewerContractError("Invalid Browser viewer integer")
        return value

    def number(self, key: str, maximum: int = 100000) -> float:
        value = self.value[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BrowserViewerContractError("Invalid Browser viewer number")
        if not math.isfinite(value) or abs(value) > maximum:
            raise BrowserViewerContractError("Invalid Browser viewer number")
        return float(value)

    def boolean(self, key: str) -> bool:
        value = self.value[key]
        if not isinstance(value, bool):
            raise BrowserViewerContractError("Invalid Browser viewer boolean")
        return value


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise BrowserViewerContractError("Duplicate Browser viewer field")
        value[key] = item
    return value


def _load(data: bytes, limit: int) -> object:
    if len(data) > limit:
        raise BrowserViewerContractError("Browser viewer message exceeds its bound")
    try:
        return json.loads(data, object_pairs_hook=_object)
    except (ValueError, UnicodeError) as error:
        raise BrowserViewerContractError("Malformed Browser viewer JSON") from error


def _source(value: object) -> ViewerSource:
    fields = _Fields(value, {"frame_sequence", "navigation_id", "width", "height"})
    return ViewerSource(
        fields.integer("frame_sequence"),
        fields.text("navigation_id"),
        fields.integer("width", 32768),
        fields.integer("height", 32768),
    )


def _target(value: object) -> ViewerTarget:
    fields = _Fields(value, {"task_id", "page_id", "resource_incarnation"})
    return ViewerTarget(
        fields.text("task_id"),
        fields.text("page_id"),
        fields.text("resource_incarnation"),
    )


def _action(value: object) -> ViewerAction:
    if not isinstance(value, dict):
        raise BrowserViewerContractError("Invalid Browser viewer action")
    match value.get("kind"):
        case "pointer":
            fields = _Fields(value, {"kind", "phase", "x", "y", "button"})
            phase, button = fields.text("phase"), fields.nullable_text("button", 8)
            if phase not in {"move", "down", "up", "cancel"} or button not in {
                None,
                "left",
                "middle",
                "right",
            }:
                raise BrowserViewerContractError(
                    "Invalid Browser pointer phase or button"
                )
            if (phase in {"down", "up"}) != (button is not None):
                raise BrowserViewerContractError(
                    "Browser pointer button combination is invalid"
                )
            return ViewerPointer(
                phase, fields.number("x", 32768), fields.number("y", 32768), button
            )
        case "wheel":
            fields = _Fields(value, {"kind", "x", "y", "delta_x", "delta_y"})
            return ViewerWheel(
                fields.number("x", 32768),
                fields.number("y", 32768),
                fields.number("delta_x"),
                fields.number("delta_y"),
            )
        case "key":
            fields = _Fields(value, {"kind", "phase", "key"})
            phase = fields.text("phase")
            if phase not in {"down", "up"}:
                raise BrowserViewerContractError("Invalid Browser key phase")
            key = fields.text("key", 64)
            named = {
                "Alt",
                "AltGraph",
                "Backspace",
                "CapsLock",
                "Control",
                "Delete",
                "End",
                "Enter",
                "Escape",
                "Home",
                "Insert",
                "Meta",
                "NumLock",
                "PageDown",
                "PageUp",
                "Pause",
                "PrintScreen",
                "ScrollLock",
                "Shift",
                "Space",
                "Tab",
                "ArrowDown",
                "ArrowLeft",
                "ArrowRight",
                "ArrowUp",
            }
            named.update(f"F{number}" for number in range(1, 25))
            if key not in named and (len(key) != 1 or not key.isprintable()):
                raise BrowserViewerContractError("Unsupported Browser key")
            return ViewerKey(phase, key)
        case "composition":
            fields = _Fields(value, {"kind", "phase", "text"})
            phase, text = fields.text("phase"), fields.nullable_text("text")
            if phase not in {"start", "commit", "cancel"} or (
                (phase == "commit") != (text is not None)
            ):
                raise BrowserViewerContractError(
                    "Invalid Browser composition combination"
                )
            return ViewerComposition(phase, text)
        case "dialog":
            fields = _Fields(value, {"kind", "dialog_id", "accept", "text"})
            return ViewerDialogResponse(
                fields.text("dialog_id"),
                fields.boolean("accept"),
                fields.nullable_text("text"),
            )
        case "navigation":
            fields = _Fields(value, {"kind", "action", "url"})
            action = fields.text("action")
            url = fields.nullable_text("url")
            if action not in {"navigate", "back", "forward", "reload"} or (
                (action == "navigate") != (url is not None and bool(url.strip()))
            ):
                raise BrowserViewerContractError(
                    "Invalid Browser navigation combination"
                )
            if action != "navigate" and url is not None:
                raise BrowserViewerContractError(
                    "Browser history and reload require null URL"
                )
            if url is not None:
                try:
                    destination = urlsplit(url)
                    _ = destination.port
                except ValueError:
                    raise BrowserViewerContractError(
                        "Invalid Browser navigation URL"
                    ) from None
                if (
                    destination.scheme not in {"http", "https"}
                    or not destination.hostname
                    or destination.username is not None
                    or destination.password is not None
                ):
                    raise BrowserViewerContractError(
                        "Browser navigation requires an HTTP(S) URL without credentials"
                    )
            return ViewerNavigation(action, url)
        case _:
            raise BrowserViewerContractError("Unsupported Browser viewer action")


def decode_viewer_request(data: bytes) -> ViewerRequest:
    """Decode a complete text message, not an individual transport fragment."""
    value = _load(data, MAX_VIEWER_TEXT_BYTES)
    if not isinstance(value, dict):
        raise BrowserViewerContractError("Invalid Browser viewer message")
    match value.get("type"):
        case "frame_ack":
            fields = _Fields(value, {"type", "attachment_id", "frame_sequence"})
            return ViewerFrameAck(
                fields.text("attachment_id"), fields.integer("frame_sequence")
            )
        case "input":
            fields = _Fields(
                value, {"type", "attachment_id", "sequence", "source", "action"}
            )
            action = _action(fields.value["action"])
            raw_source = fields.value["source"]
            if isinstance(action, ViewerDialogResponse):
                if raw_source is not None:
                    raise BrowserViewerContractError(
                        "Dialog response requires null source and current dialog ID"
                    )
                source = None
            else:
                source = _source(raw_source)
            return ViewerInput(
                fields.text("attachment_id"),
                fields.integer("sequence"),
                source,
                action,
            )
        case _:
            raise BrowserViewerContractError("Unsupported Browser viewer message")


def _dump(value: object, limit: int) -> bytes:
    data = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()
    if len(data) > limit:
        raise BrowserViewerContractError("Browser viewer message exceeds its bound")
    return data


def encode_viewer_event(event: ViewerStatus | ViewerInputAck) -> bytes:
    """Encode bounded text metadata; never include image or input bodies in logs."""
    match event:
        case ViewerStatus():
            value = {
                "type": "status",
                "attachment_id": event.attachment_id,
                "target": asdict(event.target),
                "state": event.state,
                "allow_input": event.allow_input,
                "viewport": {"width": event.width, "height": event.height},
                "navigation_id": event.navigation_id,
                "dialog": None if event.dialog is None else asdict(event.dialog),
                "conflict": event.conflict,
            }
        case ViewerInputAck():
            value = {"type": "input_ack", **asdict(event)}
        case _:
            assert_never(event)
    return _dump(value, MAX_VIEWER_TEXT_BYTES)


def encode_viewer_frame(frame: ViewerFrame) -> bytes:
    """Pair exact JPEG bytes with a length-prefixed, bounded metadata header."""
    header = _dump(
        {
            "type": "frame",
            "attachment_id": frame.attachment_id,
            "target": asdict(frame.target),
            **asdict(frame.source),
            "media_type": "image/jpeg",
        },
        MAX_VIEWER_HEADER_BYTES,
    )
    data = len(header).to_bytes(4, "big") + header + frame.image
    if not frame.image or len(data) > MAX_VIEWER_MESSAGE_BYTES:
        raise BrowserViewerContractError("Browser viewer frame exceeds its bound")
    return data


def decode_viewer_frame(data: bytes) -> ViewerFrame:
    """Validate paired binary messages for contract tests and non-UI consumers."""
    if len(data) > MAX_VIEWER_MESSAGE_BYTES or len(data) < 5:
        raise BrowserViewerContractError("Invalid Browser viewer binary message")
    size = int.from_bytes(data[:4], "big")
    if not 1 <= size <= MAX_VIEWER_HEADER_BYTES or 4 + size >= len(data):
        raise BrowserViewerContractError("Invalid Browser viewer frame header")
    fields = _Fields(
        _load(data[4 : 4 + size], MAX_VIEWER_HEADER_BYTES),
        {
            "type",
            "attachment_id",
            "target",
            "frame_sequence",
            "navigation_id",
            "width",
            "height",
            "media_type",
        },
    )
    if fields.text("type") != "frame" or fields.text("media_type") != "image/jpeg":
        raise BrowserViewerContractError("Unsupported Browser viewer frame")
    source = ViewerSource(
        fields.integer("frame_sequence"),
        fields.text("navigation_id"),
        fields.integer("width", 32768),
        fields.integer("height", 32768),
    )
    return ViewerFrame(
        fields.text("attachment_id"),
        _target(fields.value["target"]),
        source,
        data[4 + size :],
    )
