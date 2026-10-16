"""Typed browser commands and completed projections shared by Engine and Runner."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Literal, assert_never

from azents_runtime_control.runner import JsonValue

BrowserView = Literal["status", "dom", "raw_dom", "glance", "image"]
BrowserActionKind = Literal[
    "navigate",
    "back",
    "forward",
    "reload",
    "click",
    "fill",
    "select",
    "check",
    "press",
    "scroll",
    "close_page",
    "dialog",
    "upload",
    "wait",
    "hover",
    "drag",
]


@dataclass(frozen=True)
class BrowserAuthority:
    """Trusted concrete Session and current working-folder association."""

    session_id: str
    working_directory: str


@dataclass(frozen=True)
class BrowserTarget:
    """Exact current task/page scope; no ambient selected page."""

    task_id: str
    page_id: str
    resource_incarnation: str
    frame_id: str | None


@dataclass(frozen=True)
class BrowserAction:
    """Closed action options; combinations are validated before effects."""

    kind: BrowserActionKind
    ref: str | None
    observation_id: str | None
    text: str | None
    encrypted_text: str | None
    url: str | None
    values: tuple[str, ...] | None
    checked: bool | None
    key: str | None
    x: float | None
    y: float | None
    end_ref: str | None
    paths: tuple[str, ...] | None
    dialog_id: str | None
    accept: bool | None
    condition: Literal["visible", "hidden", "url"] | None
    expect: Literal["popup", "download"] | None
    timeout_ms: int


@dataclass(frozen=True)
class BrowserOpenCommand:
    authority: BrowserAuthority
    task_id: str | None
    url: str | None
    label: str | None


@dataclass(frozen=True)
class BrowserObserveCommand:
    authority: BrowserAuthority
    target: BrowserTarget | None
    view: BrowserView
    capture_full_page: bool
    max_characters: int


@dataclass(frozen=True)
class BrowserActCommand:
    authority: BrowserAuthority
    target: BrowserTarget
    action: BrowserAction


type BrowserCommand = BrowserOpenCommand | BrowserObserveCommand | BrowserActCommand


@dataclass(frozen=True)
class BrowserFrame:
    id: str
    url: str
    name: str


@dataclass(frozen=True)
class BrowserPage:
    id: str
    task_id: str
    resource_incarnation: str
    url: str
    title: str
    frames: tuple[BrowserFrame, ...]


@dataclass(frozen=True)
class BrowserTask:
    id: str
    label: str
    resource_incarnation: str
    pages: tuple[BrowserPage, ...]


@dataclass(frozen=True)
class BrowserElementRef:
    id: str
    observation_id: str
    frame_id: str
    tag: str
    label: str


@dataclass(frozen=True)
class BrowserCapture:
    path: str
    media_type: str
    size: int
    width: int | None
    height: int | None


@dataclass(frozen=True)
class BrowserDialog:
    id: str
    type: str
    message: str


@dataclass(frozen=True)
class BrowserResult:
    tasks: tuple[BrowserTask, ...]
    page: BrowserPage | None
    content: str | None
    truncated: bool
    refs: tuple[BrowserElementRef, ...]
    capture: BrowserCapture | None
    popup: BrowserPage | None
    download: BrowserCapture | None
    dialog: BrowserDialog | None
    action_state: Literal["none", "dispatched", "dialog_pending"]


class BrowserContractError(ValueError):
    """Reject malformed command/result before browser effects."""


def browser_operation_type(command: BrowserCommand) -> str:
    """Select the fixed Runtime operation for a typed command."""
    match command:
        case BrowserOpenCommand():
            return "browser.open"
        case BrowserObserveCommand():
            return "browser.list" if command.target is None else "browser.observe"
        case BrowserActCommand():
            return "browser.act"
        case _:
            assert_never(command)


def _json(value: object) -> JsonValue:
    """Normalize dataclass output into the existing Runtime JSON boundary."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json(item) for key, item in value.items()}
    raise BrowserContractError("Unsupported browser wire value")


def encode_browser_command(command: BrowserCommand) -> dict[str, JsonValue]:
    """Encode a validated typed command without alternate execution paths."""
    result = _json(asdict(command))
    assert isinstance(result, dict)
    decode_browser_command(browser_operation_type(command), result)
    return result


class _Object:
    """Strict primitive/object ingress used once by browser decoders."""

    def __init__(self, value: object, allowed: set[str]) -> None:
        if not isinstance(value, Mapping) or not all(isinstance(k, str) for k in value):
            raise BrowserContractError("Browser payload must be an object")
        if set(value) != allowed:
            raise BrowserContractError("Missing or unknown browser payload field")
        self.value = value

    def string(
        self, name: str, *, nullable: bool = False, empty: bool = False
    ) -> str | None:
        value = self.value.get(name)
        if value is None and nullable:
            return None
        if (
            not isinstance(value, str)
            or (not empty and not value.strip())
            or len(value) > 100000
        ):
            raise BrowserContractError(f"Browser {name} must be a nonempty string")
        return value

    def required(self, name: str) -> str:
        value = self.string(name)
        assert value is not None
        return value

    def boolean(self, name: str, *, nullable: bool = False) -> bool | None:
        value = self.value.get(name)
        if value is None and nullable:
            return None
        if not isinstance(value, bool):
            raise BrowserContractError(f"Browser {name} must be boolean")
        return value

    def integer(self, name: str, minimum: int, maximum: int) -> int:
        value = self.value.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not minimum <= value <= maximum
        ):
            raise BrowserContractError(f"Browser {name} is out of bounds")
        return value

    def strings(self, name: str) -> tuple[str, ...] | None:
        value = self.value.get(name)
        if value is None:
            return None
        if (
            not isinstance(value, (tuple, list))
            or not value
            or len(value) > 100
            or not all(isinstance(v, str) and len(v) <= 32768 for v in value)
        ):
            raise BrowserContractError(f"Browser {name} must be a bounded string list")
        return tuple(value)

    def number(self, name: str) -> float | None:
        value = self.value.get(name)
        if value is None:
            return None
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not -100000 <= value <= 100000
        ):
            raise BrowserContractError(f"Browser {name} must be a bounded number")
        return float(value)


def _authority(value: object) -> BrowserAuthority:
    o = _Object(value, {"session_id", "working_directory"})
    return BrowserAuthority(o.required("session_id"), o.required("working_directory"))


def _target(value: object) -> BrowserTarget:
    o = _Object(value, {"task_id", "page_id", "resource_incarnation", "frame_id"})
    return BrowserTarget(
        o.required("task_id"),
        o.required("page_id"),
        o.required("resource_incarnation"),
        o.string("frame_id", nullable=True),
    )


def _action(value: object) -> BrowserAction:
    o = _Object(value, set(BrowserAction.__dataclass_fields__))
    kind = o.required("kind")
    if kind not in {
        "navigate",
        "back",
        "forward",
        "reload",
        "click",
        "fill",
        "select",
        "check",
        "press",
        "scroll",
        "close_page",
        "dialog",
        "upload",
        "wait",
        "hover",
        "drag",
    }:
        raise BrowserContractError("Unsupported browser action")
    condition = o.string("condition", nullable=True)
    expect = o.string("expect", nullable=True)
    if condition not in {None, "visible", "hidden", "url"} or expect not in {
        None,
        "popup",
        "download",
    }:
        raise BrowserContractError("Unsupported browser condition or expectation")
    # Literal values are narrowed by constructing the validated closed branches.
    action = BrowserAction(
        kind=kind,
        ref=o.string("ref", nullable=True),
        observation_id=o.string("observation_id", nullable=True),
        text=o.string("text", nullable=True, empty=True),
        encrypted_text=o.string("encrypted_text", nullable=True),
        url=o.string("url", nullable=True),
        values=o.strings("values"),
        checked=o.boolean("checked", nullable=True),
        key=o.string("key", nullable=True),
        x=o.number("x"),
        y=o.number("y"),
        end_ref=o.string("end_ref", nullable=True),
        paths=o.strings("paths"),
        dialog_id=o.string("dialog_id", nullable=True),
        accept=o.boolean("accept", nullable=True),
        condition=condition,
        expect=expect,
        timeout_ms=o.integer("timeout_ms", 1, 60000),
    )
    if kind == "navigate" and action.url is None:
        raise BrowserContractError("Navigation requires a URL")
    if kind in {"click", "fill", "select", "check", "hover", "drag", "upload"} and (
        action.ref is None or action.observation_id is None
    ):
        raise BrowserContractError(
            "Element action requires a current observation reference"
        )
    if kind == "fill" and (action.text is None) == (action.encrypted_text is None):
        raise BrowserContractError("Fill requires exactly one text input")
    if action.encrypted_text is not None and len(action.encrypted_text) > 5528:
        raise BrowserContractError("Browser encrypted input is out of bounds")
    if (
        kind == "select"
        and action.values is None
        or kind == "check"
        and action.checked is None
        or kind == "press"
        and action.key is None
        or kind == "upload"
        and action.paths is None
        or kind == "drag"
        and action.end_ref is None
    ):
        raise BrowserContractError("Browser action arguments are incomplete")
    if kind == "dialog" and (action.dialog_id is None or action.accept is None):
        raise BrowserContractError(
            "Dialog response requires current dialog and acceptance"
        )
    if kind == "wait" and (
        condition is None
        or condition == "url"
        and action.url is None
        or condition != "url"
        and (action.ref is None or action.observation_id is None)
    ):
        raise BrowserContractError("Wait requires an explicit condition and target")
    if kind == "scroll" and (action.x is None or action.y is None):
        raise BrowserContractError("Scroll requires both deltas")
    if expect is not None and kind not in {"click", "press", "navigate"}:
        raise BrowserContractError("Expectation requires a triggering action")
    permitted = {
        "navigate": {"url"},
        "back": set(),
        "forward": set(),
        "reload": set(),
        "click": {"ref", "observation_id"},
        "fill": {"ref", "observation_id", "text", "encrypted_text"},
        "select": {"ref", "observation_id", "values"},
        "check": {"ref", "observation_id", "checked"},
        "press": {"ref", "observation_id", "key"},
        "scroll": {"x", "y"},
        "close_page": set(),
        "dialog": {"dialog_id", "accept", "text"},
        "upload": {"ref", "observation_id", "paths"},
        "hover": {"ref", "observation_id"},
        "drag": {"ref", "observation_id", "end_ref"},
        "wait": {"condition", "url", "ref", "observation_id"},
    }[kind] | {"kind", "timeout_ms", "expect"}
    if any(
        value is not None and key not in permitted for key, value in o.value.items()
    ):
        raise BrowserContractError("Browser action has unrelated arguments")
    if (action.ref is None) != (action.observation_id is None):
        raise BrowserContractError(
            "Browser reference requires its observation identity"
        )
    return action


def decode_browser_command(operation_type: str, payload: object) -> BrowserCommand:
    """Decode exact operation-specific payloads into frozen browser commands."""
    match operation_type:
        case "browser.open":
            o = _Object(payload, {"authority", "task_id", "url", "label"})
            return BrowserOpenCommand(
                _authority(o.value.get("authority")),
                o.string("task_id", nullable=True),
                o.string("url", nullable=True),
                o.string("label", nullable=True),
            )
        case "browser.observe" | "browser.list":
            o = _Object(
                payload,
                {"authority", "target", "view", "capture_full_page", "max_characters"},
            )
            view = o.required("view")
            if view not in {"status", "dom", "raw_dom", "glance", "image"}:
                raise BrowserContractError("Unsupported browser observation")
            target = (
                None
                if o.value.get("target") is None
                else _target(o.value.get("target"))
            )
            if (
                operation_type == "browser.list"
                and (target is not None or view != "status")
                or operation_type == "browser.observe"
                and target is None
            ):
                raise BrowserContractError("Browser observation target mismatch")
            full_page = o.boolean("capture_full_page")
            assert full_page is not None
            return BrowserObserveCommand(
                _authority(o.value.get("authority")),
                target,
                view,
                full_page,
                o.integer("max_characters", 1, 100000),
            )
        case "browser.act":
            o = _Object(payload, {"authority", "target", "action"})
            return BrowserActCommand(
                _authority(o.value.get("authority")),
                _target(o.value.get("target")),
                _action(o.value.get("action")),
            )
        case _:
            raise BrowserContractError("Unsupported browser operation")


def encode_browser_result(result: BrowserResult) -> dict[str, JsonValue]:
    """Encode completed typed projections only, never hidden errors."""
    value = _json(asdict(result))
    assert isinstance(value, dict)
    return value


def _items(value: object) -> list[object]:
    if not isinstance(value, (list, tuple)) or len(value) > 10000:
        raise BrowserContractError("Browser result list is invalid")
    return list(value)


def _page(value: object) -> BrowserPage:
    o = _Object(value, set(BrowserPage.__dataclass_fields__))
    frames = []
    for raw in _items(o.value.get("frames")):
        f = _Object(raw, set(BrowserFrame.__dataclass_fields__))
        frames.append(
            BrowserFrame(
                f.required("id"), f.required("url"), f.string("name", empty=True) or ""
            )
        )
    return BrowserPage(
        o.required("id"),
        o.required("task_id"),
        o.required("resource_incarnation"),
        o.required("url"),
        o.string("title", empty=True) or "",
        tuple(frames),
    )


def _capture(value: object) -> BrowserCapture | None:
    if value is None:
        return None
    o = _Object(value, set(BrowserCapture.__dataclass_fields__))
    width = None if o.value.get("width") is None else o.integer("width", 1, 100000)
    height = None if o.value.get("height") is None else o.integer("height", 1, 100000)
    return BrowserCapture(
        o.required("path"),
        o.required("media_type"),
        o.integer("size", 0, 1 << 40),
        width,
        height,
    )


def decode_browser_result(payload: object) -> BrowserResult:
    """Validate completed Runtime projections before Engine/UI consumption."""
    o = _Object(payload, set(BrowserResult.__dataclass_fields__))
    tasks = []
    for raw in _items(o.value.get("tasks")):
        t = _Object(raw, set(BrowserTask.__dataclass_fields__))
        tasks.append(
            BrowserTask(
                t.required("id"),
                t.string("label", empty=True) or "",
                t.required("resource_incarnation"),
                tuple(_page(v) for v in _items(t.value.get("pages"))),
            )
        )
    refs = []
    for raw in _items(o.value.get("refs")):
        r = _Object(raw, set(BrowserElementRef.__dataclass_fields__))
        refs.append(
            BrowserElementRef(
                *(
                    r.required(k)
                    for k in ("id", "observation_id", "frame_id", "tag", "label")
                )
            )
        )
    dialog = None
    if o.value.get("dialog") is not None:
        q = _Object(o.value.get("dialog"), set(BrowserDialog.__dataclass_fields__))
        dialog = BrowserDialog(
            q.required("id"), q.required("type"), q.string("message", empty=True) or ""
        )
    truncated = o.boolean("truncated")
    assert truncated is not None
    action_state = o.required("action_state")
    if action_state not in {"none", "dispatched", "dialog_pending"}:
        raise BrowserContractError("Unknown browser action state")
    return BrowserResult(
        tuple(tasks),
        None if o.value.get("page") is None else _page(o.value.get("page")),
        o.string("content", nullable=True, empty=True),
        truncated,
        tuple(refs),
        _capture(o.value.get("capture")),
        None if o.value.get("popup") is None else _page(o.value.get("popup")),
        _capture(o.value.get("download")),
        dialog,
        action_state,
    )
