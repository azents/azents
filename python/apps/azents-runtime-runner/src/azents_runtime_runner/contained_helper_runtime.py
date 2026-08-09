"""Shared synchronous process runtime for contained helper entrypoints."""

import select
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from azents_runtime_runner.contained_protocol import (
    PROTOCOL_VERSION,
    ContainedProtocolError,
    FrameKind,
    JsonValue,
    read_sync_frame,
    write_sync_binary,
    write_sync_control,
)


@dataclass(frozen=True)
class ContainedHelperRequest:
    """Validated opening request shared by one helper process."""

    operation: str
    workspace_path: str
    metadata: Mapping[str, JsonValue]


type ContainedHelperDispatch = Callable[
    [ContainedHelperRequest, tuple[bytes, ...], threading.Event],
    None,
]


def read_helper_request() -> ContainedHelperRequest:
    """Read and validate one helper opening control frame."""
    request = read_sync_frame(sys.stdin.buffer)
    control = request.control
    if control is None:
        raise RuntimeError("contained helper request must be a control frame")
    if control.get("protocol_version") != PROTOCOL_VERSION:
        raise RuntimeError("contained helper protocol version is unsupported")
    operation = control.get("operation")
    workspace_path = control.get("workspace_path")
    metadata = control.get("metadata")
    if (
        not isinstance(operation, str)
        or not isinstance(workspace_path, str)
        or not isinstance(metadata, dict)
    ):
        raise RuntimeError("contained helper request shape is invalid")
    return ContainedHelperRequest(
        operation=operation,
        workspace_path=workspace_path,
        metadata=metadata,
    )


def read_request_bodies(request: ContainedHelperRequest) -> tuple[bytes, ...]:
    """Read the exact binary bodies declared by one opening request."""
    body_count = (
        0
        if request.operation == "ping"
        else _integer(request.metadata.get("body_count"), "body_count")
    )
    return tuple(_read_binary() for _ in range(body_count))


def run_cancellable_dispatch(
    request: ContainedHelperRequest,
    bodies: tuple[bytes, ...],
    dispatch: ContainedHelperDispatch,
) -> None:
    """Run one operation worker while receiving one cooperative cancellation."""
    cancellation = threading.Event()
    worker = threading.Thread(
        target=dispatch,
        args=(request, bodies, cancellation),
        name="azents-contained-operation",
    )
    worker.start()
    cancellation_received = False
    while worker.is_alive():
        if not cancellation_received:
            readable, _, _ = select.select([sys.stdin.buffer], [], [], 0.05)
            if readable:
                _receive_cancellation(cancellation)
                cancellation_received = True
        else:
            worker.join(timeout=0.05)
    worker.join()


def emit_success(payload: Mapping[str, JsonValue]) -> None:
    """Emit one terminal success event."""
    emit_event("final_success", payload, final=True)


def emit_error(code: str, message: str) -> None:
    """Emit one terminal error event."""
    emit_event(
        "final_error",
        {"error_code": code, "error_message": message},
        final=True,
    )


def emit_event(
    event_type: str,
    payload: Mapping[str, JsonValue],
    *,
    binary: bytes | None = None,
    final: bool = False,
) -> None:
    """Emit one ordered control event and its optional binary body."""
    write_sync_control(
        sys.stdout.buffer,
        {
            "kind": "event",
            "event_type": event_type,
            "payload": dict(payload),
            "binary_follows": binary is not None,
            "final": final,
        },
    )
    if binary is not None:
        write_sync_binary(sys.stdout.buffer, binary)


def mapping(value: JsonValue | None, label: str) -> Mapping[str, JsonValue]:
    """Validate one protocol object field."""
    if not isinstance(value, dict):
        raise RuntimeError(f"contained helper {label} is invalid")
    return value


def optional_datetime(value: JsonValue | None, label: str) -> datetime | None:
    """Decode one nullable protocol datetime field."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"contained helper {label} is invalid")
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise RuntimeError(f"contained helper {label} is invalid") from error


def _read_binary() -> bytes:
    frame = read_sync_frame(sys.stdin.buffer)
    if frame.kind is not FrameKind.BINARY or frame.binary is None:
        raise RuntimeError("contained helper binary request frame is invalid")
    return frame.binary


def _receive_cancellation(cancellation: threading.Event) -> None:
    """Signal cooperative kernels when the Runner sends the cancel frame."""
    try:
        frame = read_sync_frame(sys.stdin.buffer)
    except ContainedProtocolError, OSError:
        cancellation.set()
        return
    control = frame.control
    if (
        frame.kind is not FrameKind.CONTROL
        or control is None
        or control.get("kind") != "cancel"
    ):
        cancellation.set()
        return
    cancellation.set()


def _integer(value: JsonValue | None, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(f"contained helper {label} is invalid")
    return value
