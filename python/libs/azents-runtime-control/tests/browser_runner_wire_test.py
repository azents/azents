"""Closed Browser payloads survive the real Runner protobuf serialization."""

import dataclasses
import json
from datetime import UTC, datetime

import pytest

from azents_runtime_control.browser_contract import (
    BrowserActCommand,
    BrowserAction,
    BrowserAuthority,
    BrowserCapture,
    BrowserCommand,
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
from azents_runtime_control.browser_runner_wire import (
    BROWSER_RUNNER_MAX_PAYLOAD_BYTES,
    browser_command_from_wire,
    browser_command_to_wire,
    browser_result_from_wire,
    browser_result_to_wire,
)
from azents_runtime_control.grpc_runner_client import (
    _event_message,
    _operation,
    runner_event_from_message,
)
from azents_runtime_control.proto import runtime_runner_control_pb2 as pb
from azents_runtime_control.runner import (
    RunnerOperationEvent,
    RuntimeRunnerEventType,
)

AUTHORITY = BrowserAuthority("session-1", "/workspace/session-1")
TARGET = BrowserTarget("task-1", "page-1", "incarnation-1", None)
ACTION = BrowserAction(
    kind="reload",
    ref=None,
    observation_id=None,
    text=None,
    encrypted_text=None,
    url=None,
    values=None,
    checked=None,
    key=None,
    x=None,
    y=None,
    end_ref=None,
    paths=None,
    dialog_id=None,
    accept=None,
    condition=None,
    expect=None,
    timeout_ms=60000,
)
COMMANDS: list[BrowserCommand] = [
    BrowserOpenCommand(AUTHORITY, None, None, None),
    BrowserOpenCommand(AUTHORITY, "task-1", "https://fixture.example", "Task"),
    BrowserObserveCommand(AUTHORITY, None, "status", False, 100000),
    BrowserObserveCommand(AUTHORITY, TARGET, "dom", False, 100000),
    BrowserObserveCommand(
        AUTHORITY, dataclasses.replace(TARGET, frame_id="frame-1"), "image", True, 1
    ),
    BrowserActCommand(AUTHORITY, TARGET, ACTION),
    BrowserActCommand(
        AUTHORITY,
        TARGET,
        dataclasses.replace(ACTION, kind="fill", ref="r", observation_id="o", text=""),
    ),
    BrowserActCommand(
        AUTHORITY,
        TARGET,
        dataclasses.replace(ACTION, kind="scroll", x=1.5, y=-100000),
    ),
    BrowserActCommand(
        AUTHORITY,
        TARGET,
        dataclasses.replace(ACTION, kind="dialog", dialog_id="dialog-1", accept=False),
    ),
]
PAGE = BrowserPage(
    "page-1",
    "task-1",
    "incarnation-1",
    "https://fixture.example",
    "",
    (BrowserFrame("frame-1", "https://fixture.example", ""),),
)
EMPTY_RESULT = BrowserResult((), None, None, False, (), None, None, None, None, "none")
RICH_RESULT = BrowserResult(
    tasks=(BrowserTask("task-1", "", "task-incarnation", (PAGE,)),),
    page=PAGE,
    content="",
    truncated=True,
    refs=(BrowserElementRef("r", "o", "frame-1", "input", "Field"),),
    capture=BrowserCapture("/workspace/image.png", "image/png", 1 << 40, 100000, 1),
    popup=dataclasses.replace(
        PAGE, id="popup-1", resource_incarnation="popup-incarnation"
    ),
    download=BrowserCapture(
        "/workspace/download.bin", "application/octet-stream", 0, None, None
    ),
    dialog=BrowserDialog("dialog-1", "prompt", ""),
    action_state="dialog_pending",
)


@pytest.mark.parametrize("command", COMMANDS)
def test_command_protobuf_roundtrip(command: BrowserCommand) -> None:
    operation_type = browser_operation_type(command)
    payload = encode_browser_command(command)
    message = pb.RunnerControlMessage(
        request_id="request-1",
        operation_request=pb.RunnerOperationRequest(
            runtime_id="runtime-1",
            runner_generation=7,
            operation_type=operation_type,
            owner_session_id=AUTHORITY.session_id,
            reply_stream_id="reply-1",
            browser=pb.BrowserOperationPayload(
                canonical_command=browser_command_to_wire(operation_type, payload)
            ),
        ),
    )
    received = pb.RunnerControlMessage.FromString(message.SerializeToString())
    assert received.operation_request.WhichOneof("payload") == "browser"
    envelope = _operation(received)
    assert envelope.payload == payload
    assert envelope.owner_session_id == AUTHORITY.session_id
    assert decode_browser_command(operation_type, envelope.payload) == command
    if isinstance(command, BrowserObserveCommand):
        assert type(envelope.payload["max_characters"]) is int
    if isinstance(command, BrowserActCommand):
        action = envelope.payload["action"]
        assert isinstance(action, dict)
        assert type(action["timeout_ms"]) is int


@pytest.mark.parametrize(
    "result",
    [
        EMPTY_RESULT,
        RICH_RESULT,
        dataclasses.replace(RICH_RESULT, content="🙂" * 100000),
    ],
)
def test_result_protobuf_roundtrip(result: BrowserResult) -> None:
    payload = encode_browser_result(result)
    event = RunnerOperationEvent(
        request_id="request-1",
        runtime_id="runtime-1",
        generation=7,
        event_type=RuntimeRunnerEventType.FINAL_SUCCESS,
        payload=payload,
        created_at=datetime.now(UTC),
        final=True,
    )
    message = _event_message(event)
    received = pb.RunnerOperationEvent.FromString(message.SerializeToString())
    assert received.final_success.WhichOneof("result") == "browser"
    decoded = runner_event_from_message(received, request_id=event.request_id)
    assert decoded.payload == payload
    assert decode_browser_result(decoded.payload) == result
    if result.capture is not None:
        capture = decoded.payload["capture"]
        assert isinstance(capture, dict)
        assert type(capture["size"]) is int
        assert type(capture["width"]) is int
        assert type(capture["height"]) is int


@pytest.mark.parametrize("wrong_type", ["bash", "browser.open", "browser.unknown"])
def test_command_type_and_oneof_mismatch_is_denied(wrong_type: str) -> None:
    payload = encode_browser_command(COMMANDS[2])
    message = pb.RunnerControlMessage(
        operation_request=pb.RunnerOperationRequest(
            operation_type=wrong_type,
            browser=pb.BrowserOperationPayload(
                canonical_command=browser_command_to_wire("browser.list", payload)
            ),
        )
    )
    with pytest.raises(BrowserContractError):
        _operation(pb.RunnerControlMessage.FromString(message.SerializeToString()))


@pytest.mark.parametrize("use_wrong_arm", [False, True])
def test_browser_command_cannot_fall_back_to_empty_or_other_payload(
    use_wrong_arm: bool,
) -> None:
    message = pb.RunnerControlMessage(
        operation_request=pb.RunnerOperationRequest(operation_type="browser.list")
    )
    if use_wrong_arm:
        message.operation_request.bash.command = "echo forbidden"
    with pytest.raises(BrowserContractError):
        _operation(pb.RunnerControlMessage.FromString(message.SerializeToString()))


@pytest.mark.parametrize(
    "wire",
    [
        b"",
        b"{",
        b"[]",
        b"null",
        b"\xff",
        b'{"tasks":[],"tasks":[]}',
        b"NaN",
        b"[" * 2000 + b"]" * 2000,
        b" " * (BROWSER_RUNNER_MAX_PAYLOAD_BYTES + 1),
    ],
)
def test_malformed_or_oversize_wire_is_denied(wire: bytes) -> None:
    with pytest.raises(BrowserContractError):
        browser_command_from_wire("browser.list", wire)
    message = pb.RunnerOperationEvent(
        event_type="final_success",
        final_success=pb.RunnerOperationFinalSuccessPayload(
            browser=pb.BrowserFinalSuccess(canonical_result=wire)
        ),
    )
    with pytest.raises(BrowserContractError):
        runner_event_from_message(
            pb.RunnerOperationEvent.FromString(message.SerializeToString()),
            request_id="request-1",
        )


@pytest.mark.parametrize("value", [True, 1.0, "1", 0, 100001])
def test_command_integer_fields_remain_strict(value: object) -> None:
    payload: dict[str, object] = dict(encode_browser_command(COMMANDS[2]))
    payload["max_characters"] = value
    with pytest.raises(BrowserContractError):
        browser_command_to_wire("browser.list", payload)
    with pytest.raises(BrowserContractError):
        browser_command_from_wire("browser.list", json.dumps(payload).encode())


@pytest.mark.parametrize("value", [True, 1.0, "1", -1, (1 << 40) + 1])
def test_result_integer_fields_remain_strict(value: object) -> None:
    payload: dict[str, object] = dict(encode_browser_result(RICH_RESULT))
    raw_capture = payload["capture"]
    assert isinstance(raw_capture, dict)
    capture: dict[str, object] = dict(raw_capture)
    capture["size"] = value
    payload["capture"] = capture
    with pytest.raises(BrowserContractError):
        browser_result_to_wire(payload)
    with pytest.raises(BrowserContractError):
        browser_result_from_wire(json.dumps(payload).encode())


def test_domain_encoding_cannot_emit_an_oversize_result() -> None:
    large = dataclasses.replace(
        RICH_RESULT,
        tasks=tuple(
            dataclasses.replace(
                RICH_RESULT.tasks[0], id=f"task-{i}", label="x" * 100000
            )
            for i in range(11)
        ),
    )
    with pytest.raises(BrowserContractError, match="size"):
        browser_result_to_wire(encode_browser_result(large))


def test_malformed_browser_success_never_selects_another_result_arm() -> None:
    event = RunnerOperationEvent(
        request_id="request-1",
        runtime_id="runtime-1",
        generation=7,
        event_type=RuntimeRunnerEventType.FINAL_SUCCESS,
        payload={"action_state": "none", "exit_code": 0},
        created_at=datetime.now(UTC),
        final=True,
    )
    with pytest.raises(BrowserContractError):
        _event_message(event)
