"""Shared typed contracts for one interactive Runtime Runner Terminal."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypeAlias

MAX_TERMINAL_DATA_CHUNK_BYTES = 16 * 1024
RUNNER_TERMINAL_CAPABILITY = "terminal.v1"
_MAX_IDENTIFIER_BYTES = 128
_MAX_STREAM_NONCE_BYTES = 128
_MAX_WORKING_DIRECTORY_BYTES = 4096
_MAX_TERMINAL_DIMENSION = 65_535


class RunnerTerminalTerminationReason(StrEnum):
    """Bounded reasons for Terminal termination."""

    CALLER = "caller"
    IDLE = "idle"
    MAXIMUM_LIFETIME = "maximum_lifetime"
    DATA_STREAM_GRACE_EXPIRED = "data_stream_grace_expired"
    RUNTIME_INVALIDATED = "runtime_invalidated"
    RUNNER_REPLACED = "runner_replaced"
    POLICY_REVOKED = "policy_revoked"
    ACCESS_REVOKED = "access_revoked"
    SHUTDOWN = "shutdown"
    PROTOCOL_VIOLATION = "protocol_violation"
    PROCESS_EXIT = "process_exit"


class RunnerTerminalStreamErrorCode(StrEnum):
    """Closed Terminal stream error classification."""

    STALE_AUTHORITY = "stale_authority"
    STALE_STREAM_GENERATION = "stale_stream_generation"
    PROTOCOL_VIOLATION = "protocol_violation"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    TERMINATED = "terminated"


@dataclass(frozen=True)
class RunnerTerminalIdentity:
    """Terminal identity fenced by its current Runtime Runner generation."""

    terminal_id: str
    runtime_id: str
    runner_generation: int

    def __post_init__(self) -> None:
        """Reject invalid identity evidence."""
        _validate_identifier(self.terminal_id, "terminal_id")
        _validate_identifier(self.runtime_id, "runtime_id")
        _validate_positive(self.runner_generation, "runner_generation")


@dataclass(frozen=True)
class RunnerTerminalOpenIntent:
    """Bounded Control-stream instruction that admits one Terminal PTY."""

    identity: RunnerTerminalIdentity
    owner_session_id: str
    working_directory: str
    columns: int
    rows: int
    idle_deadline_at: datetime
    maximum_deadline_at: datetime
    data_stream_grace_deadline_at: datetime
    stream_nonce: str
    initial_stream_generation: int

    def __post_init__(self) -> None:
        """Reject invalid Terminal admission metadata."""
        _validate_identifier(self.owner_session_id, "owner_session_id")
        _validate_bounded_text(
            self.working_directory,
            "working_directory",
            maximum=_MAX_WORKING_DIRECTORY_BYTES,
        )
        _validate_dimension(self.columns, "columns")
        _validate_dimension(self.rows, "rows")
        _validate_datetime(self.idle_deadline_at, "idle_deadline_at")
        _validate_datetime(self.maximum_deadline_at, "maximum_deadline_at")
        _validate_datetime(
            self.data_stream_grace_deadline_at,
            "data_stream_grace_deadline_at",
        )
        _validate_bounded_text(
            self.stream_nonce,
            "stream_nonce",
            maximum=_MAX_STREAM_NONCE_BYTES,
        )
        _validate_positive(self.initial_stream_generation, "initial_stream_generation")


@dataclass(frozen=True)
class RunnerTerminalTerminateIntent:
    """Bounded Control-stream instruction that ends one Terminal PTY."""

    identity: RunnerTerminalIdentity
    reason: RunnerTerminalTerminationReason


@dataclass(frozen=True)
class RunnerTerminalTerminate:
    """Bounded data-stream request that ends the registered Terminal PTY."""

    reason: RunnerTerminalTerminationReason


@dataclass(frozen=True)
class RunnerTerminalStreamRegistration:
    """First data-stream frame used to fence one Runner Terminal stream."""

    identity: RunnerTerminalIdentity
    stream_generation: int
    stream_nonce: str
    last_control_acknowledged_output_sequence: int
    highest_completely_applied_input_sequence: int
    partial_input_sequence: int | None
    partial_input_bytes_written: int | None

    def __post_init__(self) -> None:
        """Reject impossible output/input resume evidence."""
        _validate_positive(self.stream_generation, "stream_generation")
        _validate_bounded_text(
            self.stream_nonce,
            "stream_nonce",
            maximum=_MAX_STREAM_NONCE_BYTES,
        )
        _validate_nonnegative(
            self.last_control_acknowledged_output_sequence,
            "last_control_acknowledged_output_sequence",
        )
        _validate_nonnegative(
            self.highest_completely_applied_input_sequence,
            "highest_completely_applied_input_sequence",
        )
        if self.partial_input_sequence is None:
            if self.partial_input_bytes_written is not None:
                raise ValueError(
                    "partial_input_bytes_written requires partial_input_sequence"
                )
            return
        if self.partial_input_bytes_written is None:
            raise ValueError(
                "partial_input_sequence requires partial_input_bytes_written"
            )
        if (
            self.partial_input_sequence
            != self.highest_completely_applied_input_sequence + 1
        ):
            raise ValueError(
                "partial_input_sequence must follow the highest applied sequence"
            )
        if not 0 <= self.partial_input_bytes_written < MAX_TERMINAL_DATA_CHUNK_BYTES:
            raise ValueError(
                "partial_input_bytes_written must be within one Terminal data chunk"
            )


@dataclass(frozen=True)
class RunnerTerminalStreamAccepted:
    """Control acknowledgement establishing one current Terminal stream generation."""

    stream_generation: int
    resume_from_output_sequence: int
    next_input_sequence: int

    def __post_init__(self) -> None:
        """Reject invalid Control resume evidence."""
        _validate_positive(self.stream_generation, "stream_generation")
        _validate_nonnegative(
            self.resume_from_output_sequence,
            "resume_from_output_sequence",
        )
        _validate_positive(self.next_input_sequence, "next_input_sequence")


@dataclass(frozen=True)
class RunnerTerminalInputFrame:
    """One ordered bounded input frame sent from Control to the PTY owner."""

    sequence: int
    data: bytes

    def __post_init__(self) -> None:
        """Reject non-contiguous-frame candidates before transport."""
        _validate_positive(self.sequence, "sequence")
        _validate_data(self.data)


@dataclass(frozen=True)
class RunnerTerminalInputAcknowledgement:
    """Evidence that the Runner completely applied one input sequence exactly once."""

    sequence: int

    def __post_init__(self) -> None:
        """Reject invalid input acknowledgement sequence."""
        _validate_positive(self.sequence, "sequence")


@dataclass(frozen=True)
class RunnerTerminalOutputFrame:
    """One ordered bounded PTY output frame sent from Runner to Control."""

    sequence: int
    data: bytes

    def __post_init__(self) -> None:
        """Reject invalid Terminal output frame."""
        _validate_positive(self.sequence, "sequence")
        _validate_data(self.data)


@dataclass(frozen=True)
class RunnerTerminalOutputAcknowledgement:
    """Cumulative Control acknowledgement for ordered PTY output."""

    sequence: int

    def __post_init__(self) -> None:
        """Reject invalid cumulative output acknowledgement."""
        _validate_nonnegative(self.sequence, "sequence")


@dataclass(frozen=True)
class RunnerTerminalResize:
    """Latest-wins Terminal dimensions with an ordered resize sequence."""

    sequence: int
    columns: int
    rows: int

    def __post_init__(self) -> None:
        """Reject invalid Terminal dimensions."""
        _validate_positive(self.sequence, "sequence")
        _validate_dimension(self.columns, "columns")
        _validate_dimension(self.rows, "rows")


@dataclass(frozen=True)
class RunnerTerminalHeartbeat:
    """One monotonic Terminal stream health frame."""

    monotonic_sequence: int

    def __post_init__(self) -> None:
        """Reject invalid heartbeat sequence."""
        _validate_positive(self.monotonic_sequence, "monotonic_sequence")


@dataclass(frozen=True)
class RunnerTerminalHeartbeatAcknowledgement:
    """Control acknowledgement of one Terminal stream heartbeat."""

    monotonic_sequence: int

    def __post_init__(self) -> None:
        """Reject invalid heartbeat acknowledgement sequence."""
        _validate_positive(self.monotonic_sequence, "monotonic_sequence")


@dataclass(frozen=True)
class RunnerTerminalExit:
    """Content-free final Terminal outcome reported by the Runner."""

    reason: RunnerTerminalTerminationReason
    exit_code: int | None

    def __post_init__(self) -> None:
        """Reject exit code values outside the wire representation."""
        if self.exit_code is not None and not -(2**31) <= self.exit_code < 2**31:
            raise ValueError("exit_code must fit signed 32-bit wire representation")


@dataclass(frozen=True)
class RunnerTerminalStreamError:
    """Closed content-free stream error reported by either Terminal peer."""

    code: RunnerTerminalStreamErrorCode


RunnerTerminalControlFrame: TypeAlias = (
    RunnerTerminalInputFrame
    | RunnerTerminalResize
    | RunnerTerminalOutputAcknowledgement
    | RunnerTerminalTerminate
    | RunnerTerminalHeartbeatAcknowledgement
    | RunnerTerminalStreamError
)
RunnerTerminalEventFrame: TypeAlias = (
    RunnerTerminalOutputFrame
    | RunnerTerminalInputAcknowledgement
    | RunnerTerminalHeartbeat
    | RunnerTerminalExit
    | RunnerTerminalStreamError
)
RunnerTerminalOpenIntentHandler: TypeAlias = Callable[
    [RunnerTerminalOpenIntent], Awaitable[None]
]
RunnerTerminalTerminateIntentHandler: TypeAlias = Callable[
    [RunnerTerminalTerminateIntent], Awaitable[None]
]
RunnerTerminalControlFrameHandler: TypeAlias = Callable[
    [RunnerTerminalControlFrame], Awaitable[None]
]


def _validate_identifier(value: str, name: str) -> None:
    _validate_bounded_text(value, name, maximum=_MAX_IDENTIFIER_BYTES)


def _validate_bounded_text(value: str, name: str, *, maximum: int) -> None:
    size = len(value.encode())
    if not 1 <= size <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum} UTF-8 bytes")


def _validate_positive(value: int, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _validate_nonnegative(value: int, name: str) -> None:
    if value < 0:
        raise ValueError(f"{name} must not be negative")


def _validate_dimension(value: int, name: str) -> None:
    if not 1 <= value <= _MAX_TERMINAL_DIMENSION:
        raise ValueError(f"{name} must be between 1 and {_MAX_TERMINAL_DIMENSION}")


def _validate_datetime(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _validate_data(value: bytes) -> None:
    if not 1 <= len(value) <= MAX_TERMINAL_DATA_CHUNK_BYTES:
        raise ValueError(
            f"Terminal data must be between 1 and {MAX_TERMINAL_DATA_CHUNK_BYTES} bytes"
        )
