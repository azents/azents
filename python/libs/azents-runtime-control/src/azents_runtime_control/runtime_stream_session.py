"""Typed foundation for the Runtime Web persistent session protocol."""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TypeAlias

from google.protobuf import descriptor_pb2
from google.protobuf.descriptor import Descriptor, FieldDescriptor

from azents_runtime_control.proto import (
    runtime_runner_control_pb2,
    runtime_stream_session_pb2,
)

RUNTIME_WEB_CAPABILITY = "runtime-web-http"
MANDATORY_DATA_FRAME_BYTES = 256 * 1024
OPTIONAL_DATA_FRAME_BYTES = 512 * 1024
MAX_ENVELOPE_BYTES = 1024 * 1024
MAX_HEADER_BYTES = 128 * 1024
MAX_CONTROL_FRAME_BYTES = 16 * 1024
CONTROL_RESERVE_BYTES = 256 * 1024
STREAM_WINDOW_BYTES = 1024 * 1024
SESSION_WINDOW_BYTES = 8 * 1024 * 1024
MAX_WEBSOCKET_MESSAGE_BYTES = 1024 * 1024
MAX_REQUEST_BODY_BYTES = 1024 * 1024 * 1024
MAX_STREAM_TOMBSTONES = 4096
_MAX_IDENTIFIER_BYTES = 128
_MAX_NONCE_BYTES = 128
PROTOCOL_STATE_SCHEMA = (
    "session:connecting>hello_sent>active>draining>closed;"
    "hello_once;goaway_boundary;close_clears_streams",
    "stream:open_sent>accepted|rejected;accepted>request_data|request_end|"
    "response_head|reset;response_head>response_data|response_end|websocket|reset;"
    "both_directions_ended>completed;terminal_release_to_bounded_tombstone",
    "stream_id:uint64_monotonic_non_reusable",
    "http:data_only;websocket:typed_frames_only;directional_fragment_state;"
    "control_interleaving;close_ends_direction;utf8_at_text_end;message_limit",
    "credit:absolute_consumed_total;hierarchical_atomic_update;closed_fence",
    "scheduler:bounded_priority_burst;weighted_drr;terminal_metadata_cleanup",
)


class SessionPeerRole(enum.StrEnum):
    """Authenticated role attached to one persistent session."""

    GATEWAY = "gateway"
    CONTROL = "control"
    RUNNER = "runner"


class StreamProtocol(enum.StrEnum):
    """Application protocol selected for one logical stream."""

    HTTP = "http"
    WEBSOCKET = "websocket"


class StreamDirection(enum.StrEnum):
    """Independent application-data direction."""

    REQUEST = "request"
    RESPONSE = "response"


class WebSocketOpcode(enum.StrEnum):
    """Typed WebSocket message and control opcode."""

    TEXT = "text"
    BINARY = "binary"
    CONTINUATION = "continuation"
    PING = "ping"
    PONG = "pong"
    CLOSE = "close"


class CloseReason(enum.StrEnum):
    """Bounded content-free terminal reason."""

    CALLER = "caller"
    SERVICE_EXPIRED = "service_expired"
    AUTHORITY_REVOKED = "authority_revoked"
    GENERATION_REPLACED = "generation_replaced"
    DEADLINE = "deadline"
    SERVICE_DRAIN = "service_drain"
    OWNER_LOST = "owner_lost"
    PROTOCOL_VIOLATION = "protocol_violation"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    APPLICATION_UNAVAILABLE = "application_unavailable"
    TRANSPORT_UNAVAILABLE = "transport_unavailable"


class SessionState(enum.StrEnum):
    """Lifecycle state for one authenticated peer session."""

    CONNECTING = "connecting"
    HELLO_SENT = "hello_sent"
    ACTIVE = "active"
    DRAINING = "draining"
    CLOSED = "closed"


@dataclasses.dataclass(frozen=True)
class SessionProfile:
    """Effective fixed numeric profile for one peer session."""

    data_frame_bytes: int
    request_stream_window_bytes: int
    response_stream_window_bytes: int
    request_session_window_bytes: int
    response_session_window_bytes: int

    def __post_init__(self) -> None:
        """Reject values outside the approved replacement profile."""
        if self.data_frame_bytes not in {
            MANDATORY_DATA_FRAME_BYTES,
            OPTIONAL_DATA_FRAME_BYTES,
        }:
            raise ValueError("Runtime Web data frame size is unsupported")
        if self.request_stream_window_bytes != STREAM_WINDOW_BYTES:
            raise ValueError("Runtime Web request stream window is invalid")
        if self.response_stream_window_bytes != STREAM_WINDOW_BYTES:
            raise ValueError("Runtime Web response stream window is invalid")
        if self.request_session_window_bytes != SESSION_WINDOW_BYTES:
            raise ValueError("Runtime Web request session window is invalid")
        if self.response_session_window_bytes != SESSION_WINDOW_BYTES:
            raise ValueError("Runtime Web response session window is invalid")


APPROVED_SESSION_PROFILE = SessionProfile(
    data_frame_bytes=MANDATORY_DATA_FRAME_BYTES,
    request_stream_window_bytes=STREAM_WINDOW_BYTES,
    response_stream_window_bytes=STREAM_WINDOW_BYTES,
    request_session_window_bytes=SESSION_WINDOW_BYTES,
    response_session_window_bytes=SESSION_WINDOW_BYTES,
)


def _fingerprint_material() -> dict[str, object]:
    return {
        "capability": RUNTIME_WEB_CAPABILITY,
        "control_reserve_bytes": CONTROL_RESERVE_BYTES,
        "mandatory_data_frame_bytes": MANDATORY_DATA_FRAME_BYTES,
        "maximum_control_frame_bytes": MAX_CONTROL_FRAME_BYTES,
        "maximum_envelope_bytes": MAX_ENVELOPE_BYTES,
        "maximum_header_bytes": MAX_HEADER_BYTES,
        "maximum_request_body_bytes": MAX_REQUEST_BODY_BYTES,
        "maximum_websocket_message_bytes": MAX_WEBSOCKET_MESSAGE_BYTES,
        "optional_data_frame_bytes": OPTIONAL_DATA_FRAME_BYTES,
        "protocol_state_schema": PROTOCOL_STATE_SCHEMA,
        "session_window_bytes": SESSION_WINDOW_BYTES,
        "stream_window_bytes": STREAM_WINDOW_BYTES,
    }


def protocol_fingerprint(
    *,
    descriptor: bytes | None = None,
    runner_offer_descriptor: bytes | None = None,
    runner_offer_field_descriptor: bytes | None = None,
    material: dict[str, object] | None = None,
) -> str:
    """Return the exact replacement-protocol equality fingerprint."""
    digest = hashlib.sha256()
    digest.update(
        runtime_stream_session_pb2.DESCRIPTOR.serialized_pb
        if descriptor is None
        else descriptor
    )
    digest.update(
        _message_descriptor_bytes(
            runtime_runner_control_pb2.RunnerSessionOffer.DESCRIPTOR
        )
        if runner_offer_descriptor is None
        else runner_offer_descriptor
    )
    digest.update(
        _field_descriptor_bytes(
            runtime_runner_control_pb2.RunnerControlMessage.DESCRIPTOR.fields_by_name[
                "stream_session_offer"
            ],
            runtime_runner_control_pb2.DESCRIPTOR.serialized_pb,
        )
        if runner_offer_field_descriptor is None
        else runner_offer_field_descriptor
    )
    digest.update(
        json.dumps(
            _fingerprint_material() if material is None else material,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    return digest.hexdigest()


def _message_descriptor_bytes(descriptor: Descriptor) -> bytes:
    file_descriptor = descriptor_pb2.FileDescriptorProto.FromString(
        descriptor.file.serialized_pb
    )
    message = next(
        message
        for message in file_descriptor.message_type
        if message.name == descriptor.name
    )
    return message.SerializeToString(deterministic=True)


def _field_descriptor_bytes(
    descriptor: FieldDescriptor,
    file_descriptor_bytes: bytes,
) -> bytes:
    file_descriptor = descriptor_pb2.FileDescriptorProto.FromString(
        file_descriptor_bytes
    )
    containing_type = descriptor.containing_type
    if containing_type is None:
        raise ValueError("Runtime Web session offer field must have a containing type")
    message = next(
        message
        for message in file_descriptor.message_type
        if message.name == containing_type.name
    )
    field = next(field for field in message.field if field.name == descriptor.name)
    return field.SerializeToString(deterministic=True)


RUNTIME_STREAM_PROTOCOL_FINGERPRINT = protocol_fingerprint()


@dataclasses.dataclass(frozen=True)
class OwnerSessionEpoch:
    """Exact Runtime generation and Owner lease epoch."""

    owner_boot_id: str
    session_lease_id: str
    lease_generation: int
    runtime_id: str
    desired_generation: int
    runner_generation: int

    def __post_init__(self) -> None:
        """Reject incomplete or stale-capable Owner identity."""
        for name, value in (
            ("owner_boot_id", self.owner_boot_id),
            ("session_lease_id", self.session_lease_id),
            ("runtime_id", self.runtime_id),
        ):
            _validate_text(value, name, _MAX_IDENTIFIER_BYTES)
        if self.lease_generation <= 0:
            raise ValueError("Runtime Web session lease generation must be positive")
        if self.desired_generation <= 0 or self.runner_generation <= 0:
            raise ValueError("Runtime Web session generations must be positive")


@dataclasses.dataclass(frozen=True)
class RunnerSessionOffer:
    """One-time authority for joining an exact Owner session."""

    owner: OwnerSessionEpoch
    session_nonce: str
    protocol_fingerprint: str
    deadline_at: datetime

    def __post_init__(self) -> None:
        """Reject an incomplete, stale-capable, or incompatible offer."""
        _validate_text(self.session_nonce, "session_nonce", _MAX_NONCE_BYTES)
        _validate_deadline(self.deadline_at, "deadline_at")
        if self.protocol_fingerprint != RUNTIME_STREAM_PROTOCOL_FINGERPRINT:
            raise ValueError("Runtime Web session protocol fingerprint is incompatible")


RunnerSessionOfferHandler: TypeAlias = Callable[
    [RunnerSessionOffer],
    Awaitable[None],
]


@dataclasses.dataclass(frozen=True)
class SessionIdentity:
    """Exact peer session with an optional Runtime Owner epoch."""

    session_id: str
    peer_boot_id: str
    role: SessionPeerRole
    owner: OwnerSessionEpoch | None
    session_nonce: str
    deadline_at: datetime

    def __post_init__(self) -> None:
        """Reject role and Owner epoch combinations that can leak authority."""
        _validate_text(self.session_id, "session_id", _MAX_IDENTIFIER_BYTES)
        _validate_text(self.peer_boot_id, "peer_boot_id", _MAX_IDENTIFIER_BYTES)
        _validate_text(self.session_nonce, "session_nonce", _MAX_NONCE_BYTES)
        _validate_deadline(self.deadline_at, "deadline_at")
        if self.role is SessionPeerRole.GATEWAY:
            if self.owner is not None:
                raise ValueError("Gateway peer session must not carry an Owner epoch")
        elif self.owner is None:
            raise ValueError("Control and Runner sessions require an Owner epoch")


@dataclasses.dataclass(frozen=True)
class Header:
    """One ordered normalized HTTP header pair."""

    name: bytes
    value: bytes

    def __post_init__(self) -> None:
        """Reject malformed or individually oversized header fields."""
        if not 1 <= len(self.name) <= MAX_HEADER_BYTES:
            raise ValueError("Runtime Web header name has an invalid size")
        if len(self.value) > MAX_HEADER_BYTES:
            raise ValueError("Runtime Web header value is too large")
        if any(byte in self.name for byte in (0, 10, 13)):
            raise ValueError("Runtime Web header name contains a forbidden byte")
        if any(byte in self.value for byte in (0, 10, 13)):
            raise ValueError("Runtime Web header value contains a forbidden byte")


@dataclasses.dataclass(frozen=True)
class StreamAuthority:
    """Immutable service, Runtime, port, and deadline authority."""

    correlation_id: str
    service_id: str
    service_revision: int
    identity_id: str
    authentication_session_id: str
    user_id: str
    agent_id: str
    runtime_id: str
    desired_generation: int
    runner_generation: int
    port: int
    open_deadline_at: datetime
    exposure_deadline_at: datetime
    transport_deadline_at: datetime

    def __post_init__(self) -> None:
        """Reject incomplete or inconsistent logical-stream authority."""
        for name, value in (
            ("correlation_id", self.correlation_id),
            ("service_id", self.service_id),
            ("identity_id", self.identity_id),
            ("authentication_session_id", self.authentication_session_id),
            ("user_id", self.user_id),
            ("agent_id", self.agent_id),
            ("runtime_id", self.runtime_id),
        ):
            _validate_text(value, name, _MAX_IDENTIFIER_BYTES)
        if self.service_revision < 0:
            raise ValueError("Runtime Web service revision must not be negative")
        if self.desired_generation <= 0 or self.runner_generation <= 0:
            raise ValueError("Runtime Web authority generations must be positive")
        if not 1 <= self.port <= 65_535:
            raise ValueError("Runtime Web port must be between 1 and 65535")
        for name, value in (
            ("open_deadline_at", self.open_deadline_at),
            ("exposure_deadline_at", self.exposure_deadline_at),
            ("transport_deadline_at", self.transport_deadline_at),
        ):
            _validate_deadline(value, name)
        if self.open_deadline_at > self.transport_deadline_at:
            raise ValueError("Open deadline must not exceed transport deadline")
        if self.transport_deadline_at > self.exposure_deadline_at:
            raise ValueError("Transport deadline must not exceed exposure deadline")


@dataclasses.dataclass(frozen=True)
class RequestHead:
    """Normalized HTTP or WebSocket request metadata."""

    protocol: StreamProtocol
    method: bytes
    target: bytes
    headers: tuple[Header, ...]

    def __post_init__(self) -> None:
        """Reject malformed or oversized request metadata."""
        if not 1 <= len(self.method) <= 32 or not self.method.isascii():
            raise ValueError("Runtime Web method is invalid")
        if not 1 <= len(self.target) <= MAX_HEADER_BYTES:
            raise ValueError("Runtime Web target has an invalid size")
        size = len(self.method) + len(self.target)
        size += sum(len(header.name) + len(header.value) for header in self.headers)
        if size > MAX_HEADER_BYTES:
            raise ValueError("Runtime Web request head exceeds the header limit")


@dataclasses.dataclass(frozen=True)
class StreamSnapshot:
    """Immutable observable state for one logical stream."""

    accepted: bool
    rejected: bool
    request_sequence: int
    response_sequence: int
    request_ended: bool
    response_head_received: bool
    response_ended: bool
    completed: bool
    terminal_reason: CloseReason | None


class LogicalStreamState:
    """Validate one logical stream independently from the peer session."""

    def __init__(
        self,
        *,
        stream_id: int,
        authority: StreamAuthority,
        request_head: RequestHead,
        profile: SessionProfile,
    ) -> None:
        if stream_id <= 0:
            raise ValueError("Runtime Web stream ID must be positive")
        self.stream_id = stream_id
        self.authority = authority
        self.request_head = request_head
        self.profile = profile
        self.accepted = False
        self.rejected = False
        self.request_sequence = 0
        self.response_sequence = 0
        self.request_body_bytes = 0
        self.request_ended = False
        self.response_head_received = False
        self.response_ended = False
        self.completed = False
        self.terminal_reason: CloseReason | None = None
        self.websocket_opcode = {
            StreamDirection.REQUEST: None,
            StreamDirection.RESPONSE: None,
        }
        self.websocket_message_data = {
            StreamDirection.REQUEST: bytearray(),
            StreamDirection.RESPONSE: bytearray(),
        }
        self.websocket_closed = {
            StreamDirection.REQUEST: False,
            StreamDirection.RESPONSE: False,
        }

    def accept(self) -> None:
        """Accept application data exactly once."""
        if self.accepted or self.rejected or self.terminal_reason is not None:
            raise ValueError(
                "Runtime Web stream cannot be accepted in its current state"
            )
        self.accepted = True

    def reject(self, reason: CloseReason) -> None:
        """Reject an unopened stream with one bounded reason."""
        if self.accepted or self.rejected or self.terminal_reason is not None:
            raise ValueError(
                "Runtime Web stream cannot be rejected in its current state"
            )
        self.rejected = True
        self.terminal_reason = reason

    def receive_data(
        self, direction: StreamDirection, sequence: int, data: bytes
    ) -> None:
        """Validate one ordered HTTP application-data frame."""
        self._require_active()
        if self.request_head.protocol is not StreamProtocol.HTTP:
            raise ValueError("Runtime WebSocket streams require typed frames")
        if not 1 <= len(data) <= self.profile.data_frame_bytes:
            raise ValueError("Runtime Web data frame has an invalid size")
        if (
            direction is StreamDirection.REQUEST
            and self.request_body_bytes + len(data) > MAX_REQUEST_BODY_BYTES
        ):
            raise ValueError("Runtime Web request body exceeds the maximum size")
        self._advance_sequence(direction, sequence)
        if direction is StreamDirection.REQUEST:
            self.request_body_bytes += len(data)

    def _advance_sequence(self, direction: StreamDirection, sequence: int) -> None:
        if direction is StreamDirection.REQUEST:
            if self.request_ended or sequence != self.request_sequence + 1:
                raise ValueError("Runtime Web request data sequence is invalid")
            self.request_sequence = sequence
            return
        if not self.response_head_received or self.response_ended:
            raise ValueError(
                "Runtime Web response data is invalid in its current state"
            )
        if sequence != self.response_sequence + 1:
            raise ValueError("Runtime Web response data sequence is invalid")
        self.response_sequence = sequence

    def receive_response_head(self, status: int, headers: tuple[Header, ...]) -> None:
        """Accept exactly one bounded response head."""
        self._require_active()
        if self.response_head_received:
            raise ValueError("Runtime Web response head was already received")
        if not 100 <= status <= 599:
            raise ValueError("Runtime Web response status is invalid")
        size = 4 + sum(len(header.name) + len(header.value) for header in headers)
        if size > MAX_HEADER_BYTES:
            raise ValueError("Runtime Web response head exceeds the header limit")
        self.response_head_received = True

    def end_direction(self, direction: StreamDirection, final_sequence: int) -> None:
        """Half-close one direction at its exact final sequence."""
        self._require_active()
        if final_sequence < 0:
            raise ValueError("Runtime Web final sequence must not be negative")
        if direction is StreamDirection.REQUEST:
            if self.request_ended or final_sequence != self.request_sequence:
                raise ValueError("Runtime Web request end sequence is invalid")
            self.request_ended = True
            return
        if (
            not self.response_head_received
            or self.response_ended
            or final_sequence != self.response_sequence
        ):
            raise ValueError("Runtime Web response end sequence is invalid")
        self.response_ended = True

    def receive_websocket(
        self,
        *,
        direction: StreamDirection,
        sequence: int,
        opcode: WebSocketOpcode,
        final: bool,
        data: bytes,
    ) -> None:
        """Validate one ordered WebSocket message or control frame."""
        if self.request_head.protocol is not StreamProtocol.WEBSOCKET:
            raise ValueError("Runtime WebSocket data requires a WebSocket stream")
        self._require_active()
        if self.websocket_closed[direction]:
            raise ValueError("Runtime WebSocket direction is already closed")
        if len(data) > self.profile.data_frame_bytes:
            raise ValueError("Runtime WebSocket frame is too large")
        self._advance_sequence(direction, sequence)
        open_opcode = self.websocket_opcode[direction]
        if opcode in {
            WebSocketOpcode.PING,
            WebSocketOpcode.PONG,
            WebSocketOpcode.CLOSE,
        }:
            if not final or len(data) > 125:
                raise ValueError("Runtime WebSocket control frame is invalid")
            if opcode is WebSocketOpcode.CLOSE:
                _validate_websocket_close(data)
                self.websocket_closed[direction] = True
                self.websocket_opcode[direction] = None
                self.websocket_message_data[direction].clear()
            return
        if opcode is WebSocketOpcode.CONTINUATION:
            if open_opcode is None:
                raise ValueError("Runtime WebSocket continuation has no open message")
        elif open_opcode is not None:
            raise ValueError("Runtime WebSocket message opcode changed mid-message")
        else:
            self.websocket_opcode[direction] = opcode
        message_data = self.websocket_message_data[direction]
        message_data.extend(data)
        if len(message_data) > MAX_WEBSOCKET_MESSAGE_BYTES:
            raise ValueError("Runtime WebSocket message exceeds the maximum size")
        if final:
            if self.websocket_opcode[direction] is WebSocketOpcode.TEXT:
                bytes(message_data).decode("utf-8")
            self.websocket_opcode[direction] = None
            message_data.clear()

    def reset(self, reason: CloseReason) -> None:
        """Terminate one attributable stream without affecting its session."""
        if self.completed or self.terminal_reason is not None:
            raise ValueError("Runtime Web stream is already terminal")
        self.terminal_reason = reason
        self._release_payloads()

    def finish(self) -> None:
        """Complete one accepted stream after both directions are closed."""
        self._require_active()
        if not self.request_ended or not self.response_ended:
            raise ValueError("Runtime Web stream directions are not both complete")
        self.completed = True
        self._release_payloads()

    def snapshot(self) -> StreamSnapshot:
        """Return content-free current state."""
        return StreamSnapshot(
            accepted=self.accepted,
            rejected=self.rejected,
            request_sequence=self.request_sequence,
            response_sequence=self.response_sequence,
            request_ended=self.request_ended,
            response_head_received=self.response_head_received,
            response_ended=self.response_ended,
            completed=self.completed,
            terminal_reason=self.terminal_reason,
        )

    def _require_active(self) -> None:
        if not self.accepted or self.completed or self.terminal_reason is not None:
            raise ValueError("Runtime Web stream is not active")

    def _release_payloads(self) -> None:
        for direction in StreamDirection:
            self.websocket_opcode[direction] = None
            self.websocket_message_data[direction].clear()


class PeerSessionState:
    """Validate session handshake, stream identity, drain, and closure."""

    def __init__(self, *, identity: SessionIdentity) -> None:
        self.identity = identity
        self.role = identity.role
        self.state = SessionState.CONNECTING
        self.profile: SessionProfile | None = None
        self.last_stream_id = 0
        self.last_accepted_stream_id: int | None = None
        self.streams: dict[int, LogicalStreamState] = {}
        self.tombstones: deque[int] = deque(maxlen=MAX_STREAM_TOMBSTONES)
        self.tombstone_set: set[int] = set()

    def hello_sent(self) -> None:
        """Advance to the one permitted outbound hello."""
        if self.state is not SessionState.CONNECTING:
            raise ValueError(
                "Runtime Web session hello is invalid in its current state"
            )
        self.state = SessionState.HELLO_SENT

    def accept(self, profile: SessionProfile) -> None:
        """Activate one exactly matched session profile."""
        if self.state is not SessionState.HELLO_SENT:
            raise ValueError("Runtime Web session acceptance is invalid")
        self.profile = profile
        self.state = SessionState.ACTIVE

    def open_stream(
        self,
        *,
        stream_id: int,
        authority: StreamAuthority,
        request_head: RequestHead,
    ) -> LogicalStreamState:
        """Register one monotonic non-reusable logical stream."""
        if self.state is not SessionState.ACTIVE or self.profile is None:
            raise ValueError("Runtime Web session does not accept new streams")
        if stream_id <= self.last_stream_id:
            raise ValueError(
                "Runtime Web stream IDs must be monotonic and non-reusable"
            )
        owner = self.identity.owner
        if owner is not None and (
            authority.runtime_id != owner.runtime_id
            or authority.desired_generation != owner.desired_generation
            or authority.runner_generation != owner.runner_generation
        ):
            raise ValueError("Runtime Web stream authority does not match Owner epoch")
        stream = LogicalStreamState(
            stream_id=stream_id,
            authority=authority,
            request_head=request_head,
            profile=self.profile,
        )
        self.streams[stream_id] = stream
        self.last_stream_id = stream_id
        return stream

    def release_stream(self, stream_id: int) -> None:
        """Release terminal stream state into a bounded tombstone."""
        stream = self.streams.get(stream_id)
        if stream is None:
            raise ValueError("Runtime Web stream is not registered")
        snapshot = stream.snapshot()
        if not snapshot.completed and snapshot.terminal_reason is None:
            raise ValueError("Runtime Web stream is not terminal")
        self.streams.pop(stream_id)
        if len(self.tombstones) == MAX_STREAM_TOMBSTONES:
            expired = self.tombstones.popleft()
            self.tombstone_set.remove(expired)
        self.tombstones.append(stream_id)
        self.tombstone_set.add(stream_id)

    def start_draining(self, last_accepted_stream_id: int) -> tuple[int, ...]:
        """Refuse new streams and terminate registered work above GOAWAY."""
        if self.state is not SessionState.ACTIVE:
            raise ValueError("Runtime Web session cannot drain in its current state")
        if not 0 <= last_accepted_stream_id <= self.last_stream_id:
            raise ValueError("Runtime Web GOAWAY stream boundary is invalid")
        self.last_accepted_stream_id = last_accepted_stream_id
        terminated: list[int] = []
        for stream_id, stream in sorted(self.streams.items()):
            if stream_id <= last_accepted_stream_id:
                continue
            snapshot = stream.snapshot()
            if snapshot.completed or snapshot.terminal_reason is not None:
                continue
            if snapshot.accepted:
                stream.reset(CloseReason.SERVICE_DRAIN)
            else:
                stream.reject(CloseReason.SERVICE_DRAIN)
            terminated.append(stream_id)
        self.state = SessionState.DRAINING
        return tuple(terminated)

    def close(self) -> None:
        """Close the session and release all stream and tombstone state."""
        if self.state is SessionState.CLOSED:
            raise ValueError("Runtime Web session is already closed")
        for stream in self.streams.values():
            snapshot = stream.snapshot()
            if not snapshot.completed and snapshot.terminal_reason is None:
                stream.reset(CloseReason.TRANSPORT_UNAVAILABLE)
        self.streams.clear()
        self.tombstones.clear()
        self.tombstone_set.clear()
        self.state = SessionState.CLOSED


def _validate_text(value: str, name: str, maximum: int) -> None:
    size = len(value.encode())
    if not 1 <= size <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum} UTF-8 bytes")


def _validate_deadline(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _validate_websocket_close(data: bytes) -> None:
    if len(data) == 1:
        raise ValueError("Runtime WebSocket close payload is invalid")
    if len(data) < 2:
        return
    code = int.from_bytes(data[:2], "big")
    standard = 1000 <= code <= 1014 and code not in {1004, 1005, 1006}
    application = 3000 <= code <= 4999
    if not standard and not application:
        raise ValueError("Runtime WebSocket close code is invalid")
    data[2:].decode("utf-8")
