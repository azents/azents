"""Shared typed contracts for Runtime Web Runner transport intents."""

import dataclasses
import enum
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TypeAlias

RUNNER_WEB_CAPABILITY = "runtime-web-http.v1"
MAX_RUNTIME_WEB_FRAME_BYTES = 64 * 1024
MAX_RUNTIME_WEB_SOCKET_MESSAGE_BYTES = 1024 * 1024
_MAX_IDENTIFIER_BYTES = 128
_MAX_NONCE_BYTES = 128


class RunnerWebCancelReason(enum.StrEnum):
    """Bounded reasons for terminating one Runner Web transport."""

    CALLER = "caller"
    APPROVAL_EXPIRED = "approval_expired"
    AUTHORITY_REVOKED = "authority_revoked"
    RUNTIME_REPLACED = "runtime_replaced"
    DEADLINE = "deadline"
    SHUTDOWN = "shutdown"
    PROTOCOL_VIOLATION = "protocol_violation"


class RunnerWebProtocol(enum.StrEnum):
    """Application protocol selected for one transport."""

    HTTP = "http"
    WEBSOCKET = "websocket"


class RunnerWebSocketOpcode(enum.StrEnum):
    """Supported WebSocket frame opcode."""

    TEXT = "text"
    BINARY = "binary"
    PING = "ping"
    PONG = "pong"
    CLOSE = "close"


class RunnerWebStreamErrorCode(enum.StrEnum):
    """Bounded transport failure safe to project between trusted peers."""

    STALE_AUTHORITY = "stale_authority"
    STALE_RUNTIME_GENERATION = "stale_runtime_generation"
    STALE_ROUTE = "stale_route"
    DUPLICATE_JOIN = "duplicate_join"
    PROTOCOL_VIOLATION = "protocol_violation"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    APPLICATION_UNAVAILABLE = "application_unavailable"
    TRANSPORT_UNAVAILABLE = "transport_unavailable"


@dataclasses.dataclass(frozen=True)
class RunnerWebIdentity:
    """Exact tunnel, approval, Runtime, and deadline authority."""

    tunnel_id: str
    endpoint_id: str
    cycle_id: str
    endpoint_authority_revision: int
    close_barrier: int
    runtime_id: str
    desired_generation: int
    runner_generation: int
    port: int
    join_nonce: str
    registration_deadline_at: datetime
    approval_deadline_at: datetime
    transport_deadline_at: datetime

    def __post_init__(self) -> None:
        """Reject incomplete or unbounded authority evidence."""
        for name, value in (
            ("tunnel_id", self.tunnel_id),
            ("endpoint_id", self.endpoint_id),
            ("cycle_id", self.cycle_id),
            ("runtime_id", self.runtime_id),
        ):
            _validate_text(value, name, _MAX_IDENTIFIER_BYTES)
        _validate_text(self.join_nonce, "join_nonce", _MAX_NONCE_BYTES)
        if self.endpoint_authority_revision < 0 or self.close_barrier < 0:
            raise ValueError("Runtime Web authority revisions must not be negative")
        if self.desired_generation <= 0 or self.runner_generation <= 0:
            raise ValueError("Runtime Web generations must be positive")
        if not 1 <= self.port <= 65_535:
            raise ValueError("Runtime Web port must be between 1 and 65535")
        for name, value in (
            ("registration_deadline_at", self.registration_deadline_at),
            ("approval_deadline_at", self.approval_deadline_at),
            ("transport_deadline_at", self.transport_deadline_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.registration_deadline_at > self.transport_deadline_at:
            raise ValueError("Registration deadline must not exceed transport deadline")
        if self.approval_deadline_at > self.transport_deadline_at:
            raise ValueError("Approval deadline must not exceed transport deadline")


@dataclasses.dataclass(frozen=True)
class RunnerWebOpenIntent:
    """Metadata-only instruction to open one exact loopback transport."""

    identity: RunnerWebIdentity


@dataclasses.dataclass(frozen=True)
class RunnerWebCancelIntent:
    """Metadata-only instruction to cancel one exact loopback transport."""

    identity: RunnerWebIdentity
    reason: RunnerWebCancelReason


@dataclasses.dataclass(frozen=True)
class RunnerWebHeader:
    """One raw ordered HTTP header pair."""

    name: bytes
    value: bytes

    def __post_init__(self) -> None:
        """Reject empty names and individually oversized header fields."""
        if not 1 <= len(self.name) <= MAX_RUNTIME_WEB_FRAME_BYTES:
            raise ValueError("Runtime Web header name has an invalid size")
        if len(self.value) > MAX_RUNTIME_WEB_FRAME_BYTES:
            raise ValueError("Runtime Web header value is too large")
        if any(byte in self.name for byte in (0, 10, 13)):
            raise ValueError("Runtime Web header name contains a forbidden byte")
        if any(byte in self.value for byte in (0, 10, 13)):
            raise ValueError("Runtime Web header value contains a forbidden byte")


@dataclasses.dataclass(frozen=True)
class RunnerWebRequestHead:
    """First Control frame describing the exact loopback request."""

    identity: RunnerWebIdentity
    protocol: RunnerWebProtocol
    method: bytes
    target: bytes
    headers: tuple[RunnerWebHeader, ...]

    def __post_init__(self) -> None:
        """Reject malformed or oversized request metadata."""
        if not 1 <= len(self.method) <= 32 or not self.method.isascii():
            raise ValueError("Runtime Web method is invalid")
        if not 1 <= len(self.target) <= MAX_RUNTIME_WEB_FRAME_BYTES:
            raise ValueError("Runtime Web target has an invalid size")
        _validate_head_size(self.headers, len(self.method) + len(self.target))


@dataclasses.dataclass(frozen=True)
class RunnerWebResponseHead:
    """First Runner frame describing the upstream response."""

    status: int
    headers: tuple[RunnerWebHeader, ...]

    def __post_init__(self) -> None:
        """Reject invalid response metadata."""
        if not 100 <= self.status <= 599:
            raise ValueError("Runtime Web response status is invalid")
        _validate_head_size(self.headers, 4)


@dataclasses.dataclass(frozen=True)
class RunnerWebBodyChunk:
    """One ordered bounded HTTP body chunk."""

    sequence: int
    data: bytes

    def __post_init__(self) -> None:
        """Reject empty, oversized or non-positive chunks."""
        if self.sequence <= 0:
            raise ValueError("Runtime Web body sequence must be positive")
        _validate_frame_data(self.data)


@dataclasses.dataclass(frozen=True)
class RunnerWebStreamEnd:
    """Content-free end marker after the final body sequence."""

    final_sequence: int

    def __post_init__(self) -> None:
        """Reject negative final sequence evidence."""
        if self.final_sequence < 0:
            raise ValueError("Runtime Web final sequence must not be negative")


@dataclasses.dataclass(frozen=True)
class RunnerWebSocketFrame:
    """One ordered bounded WebSocket message/control frame."""

    sequence: int
    opcode: RunnerWebSocketOpcode
    final: bool
    data: bytes

    def __post_init__(self) -> None:
        """Reject invalid WebSocket frame data."""
        if self.sequence <= 0:
            raise ValueError("Runtime WebSocket sequence must be positive")
        if len(self.data) > MAX_RUNTIME_WEB_FRAME_BYTES:
            raise ValueError("Runtime WebSocket frame is too large")
        if self.opcode is RunnerWebSocketOpcode.TEXT:
            self.data.decode("utf-8")
        if (
            self.opcode
            in {
                RunnerWebSocketOpcode.PING,
                RunnerWebSocketOpcode.PONG,
                RunnerWebSocketOpcode.CLOSE,
            }
            and len(self.data) > 125
        ):
            raise ValueError("Runtime WebSocket control frame is too large")


@dataclasses.dataclass(frozen=True)
class RunnerWebHeartbeat:
    """One monotonic transport heartbeat."""

    monotonic_sequence: int

    def __post_init__(self) -> None:
        """Reject invalid heartbeat sequence."""
        if self.monotonic_sequence <= 0:
            raise ValueError("Runtime Web heartbeat sequence must be positive")


@dataclasses.dataclass(frozen=True)
class RunnerWebHeartbeatAcknowledgement:
    """Acknowledgement of one monotonic transport heartbeat."""

    monotonic_sequence: int

    def __post_init__(self) -> None:
        """Reject invalid heartbeat acknowledgement."""
        if self.monotonic_sequence <= 0:
            raise ValueError("Runtime Web heartbeat acknowledgement must be positive")


@dataclasses.dataclass(frozen=True)
class RunnerWebCancel:
    """In-stream transport cancellation."""

    reason: RunnerWebCancelReason


@dataclasses.dataclass(frozen=True)
class RunnerWebStreamError:
    """Content-free bounded transport error."""

    code: RunnerWebStreamErrorCode


@dataclasses.dataclass(frozen=True)
class RunnerWebStreamAccepted:
    """Control acknowledgement for one registered tunnel."""

    tunnel_id: str

    def __post_init__(self) -> None:
        """Reject invalid accepted tunnel identity."""
        _validate_text(self.tunnel_id, "tunnel_id", _MAX_IDENTIFIER_BYTES)


RunnerWebControlFrame: TypeAlias = (
    RunnerWebRequestHead
    | RunnerWebBodyChunk
    | RunnerWebStreamEnd
    | RunnerWebSocketFrame
    | RunnerWebHeartbeat
    | RunnerWebHeartbeatAcknowledgement
    | RunnerWebCancel
    | RunnerWebStreamError
)
RunnerWebEventFrame: TypeAlias = (
    RunnerWebResponseHead
    | RunnerWebBodyChunk
    | RunnerWebStreamEnd
    | RunnerWebSocketFrame
    | RunnerWebHeartbeat
    | RunnerWebHeartbeatAcknowledgement
    | RunnerWebStreamError
)
RunnerWebControlFrameHandler: TypeAlias = Callable[
    [RunnerWebControlFrame], Awaitable[None]
]
RunnerWebOpenIntentHandler: TypeAlias = Callable[[RunnerWebOpenIntent], Awaitable[None]]
RunnerWebCancelIntentHandler: TypeAlias = Callable[
    [RunnerWebCancelIntent], Awaitable[None]
]


def _validate_text(value: str, name: str, maximum: int) -> None:
    size = len(value.encode())
    if not 1 <= size <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum} UTF-8 bytes")


def _validate_frame_data(value: bytes) -> None:
    if not 1 <= len(value) <= MAX_RUNTIME_WEB_FRAME_BYTES:
        raise ValueError(
            "Runtime Web data must be between 1 and "
            f"{MAX_RUNTIME_WEB_FRAME_BYTES} bytes"
        )


def _validate_head_size(headers: tuple[RunnerWebHeader, ...], base_size: int) -> None:
    size = base_size + sum(len(header.name) + len(header.value) for header in headers)
    if size > MAX_RUNTIME_WEB_FRAME_BYTES:
        raise ValueError("Runtime Web head exceeds the frame limit")
