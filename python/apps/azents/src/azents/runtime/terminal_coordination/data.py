"""Typed volatile Runtime Terminal coordination state."""

import dataclasses
import enum
from datetime import datetime

from azents_runtime_control.runner_terminal import (
    RunnerTerminalStreamAccepted,
    RunnerTerminalTerminationReason,
)

MAX_TERMINAL_CHUNK_BYTES = 16 * 1024
MAX_PENDING_INPUT_BYTES = 64 * 1024
MAX_LIVE_OUTPUT_BYTES = 256 * 1024
MAX_REPLAY_BYTES = 1024 * 1024
MAX_REPLAY_CHUNKS = 64
MAX_ACTIVE_TERMINALS_PER_SESSION = 1
MAX_ACTIVE_TERMINALS_PER_USER = 8
MAX_ACTIVE_TERMINALS_PER_RUNTIME = 16
TERMINAL_IDLE_SECONDS = 30 * 60
TERMINAL_BROWSER_GRACE_SECONDS = 120
TERMINAL_RUNNER_GRACE_SECONDS = 120
TERMINAL_FINAL_TTL_SECONDS = 120
MAX_IDENTIFIER_BYTES = 128
MAX_WORKING_DIRECTORY_BYTES = 4096
MAX_DIAGNOSTIC_ENTRIES = 32
MAX_DIAGNOSTIC_VALUE_BYTES = 256


class RuntimeTerminalLifecycle(enum.StrEnum):
    """Volatile Terminal lifecycle."""

    OPENING = "opening"
    ATTACHED = "attached"
    DETACHED = "detached"
    TERMINATING = "terminating"
    EXITED = "exited"


class RuntimeTerminalMutationStatus(enum.StrEnum):
    """Closed outcome taxonomy for generation-fenced Terminal mutations."""

    APPLIED = "applied"
    NOT_FOUND = "not_found"
    TERMINAL_FINAL = "terminal_final"
    STALE_LIFECYCLE = "stale_lifecycle"
    STALE_ATTACHMENT_GENERATION = "stale_attachment_generation"
    STALE_RUNNER_STREAM_GENERATION = "stale_runner_stream_generation"
    STALE_RUNTIME_AUTHORITY = "stale_runtime_authority"
    SEQUENCE_REJECTED = "sequence_rejected"
    CAPACITY_EXCEEDED = "capacity_exceeded"
    QUOTA_EXCEEDED = "quota_exceeded"
    TICKET_MISSING = "ticket_missing"
    TICKET_EXPIRED = "ticket_expired"
    TICKET_BINDING_MISMATCH = "ticket_binding_mismatch"


class RuntimeTerminalInvalidationSource(enum.StrEnum):
    """Indexed source whose authority may revoke active Terminals."""

    AGENT = "agent"
    RUNTIME = "runtime"
    PROVIDER_PROFILE = "provider_profile"
    WORKSPACE_PROFILE = "workspace_profile"
    USER = "user"
    SESSION = "session"
    ACCESS = "access"


class RuntimeTerminalTicketIntent(enum.StrEnum):
    """One-time browser ticket intent."""

    OPEN_OR_ATTACH = "open_or_attach"


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalAdmission:
    """Complete authority required to create one volatile Terminal."""

    terminal_id: str
    workspace_id: str
    agent_id: str
    session_id: str
    user_id: str
    authentication_session_id: str
    authentication_session_expires_at: datetime
    runtime_id: str
    provider_profile_id: str
    provider_profile_version: int
    workspace_profile_id: str
    workspace_profile_version: int
    agent_policy_version: str
    desired_generation: int
    runner_generation: int
    working_directory: str
    stream_nonce: str
    created_at: datetime
    idle_deadline_at: datetime
    maximum_deadline_at: datetime
    data_stream_grace_deadline_at: datetime
    metadata_ttl_seconds: int

    def __post_init__(self) -> None:
        """Validate bounded authority evidence."""
        for name in (
            "terminal_id",
            "workspace_id",
            "agent_id",
            "session_id",
            "user_id",
            "authentication_session_id",
            "runtime_id",
            "provider_profile_id",
            "workspace_profile_id",
            "agent_policy_version",
            "stream_nonce",
        ):
            _require_identifier(getattr(self, name), name)
        _require_text(
            self.working_directory,
            "working_directory",
            MAX_WORKING_DIRECTORY_BYTES,
        )
        _require_positive(self.desired_generation, "desired_generation")
        _require_positive(self.runner_generation, "runner_generation")
        _require_positive(self.provider_profile_version, "provider_profile_version")
        _require_positive(self.workspace_profile_version, "workspace_profile_version")
        for name in (
            "created_at",
            "authentication_session_expires_at",
            "idle_deadline_at",
            "maximum_deadline_at",
            "data_stream_grace_deadline_at",
        ):
            _require_aware(getattr(self, name), name)
        if self.metadata_ttl_seconds <= 0:
            raise ValueError("metadata_ttl_seconds must be positive")


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalInput:
    """One contiguous browser input chunk retained until Runner acknowledgement."""

    sequence: int
    data: bytes

    def __post_init__(self) -> None:
        """Validate bounded input."""
        _require_positive(self.sequence, "sequence")
        _require_chunk(self.data)


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalOutput:
    """One contiguous Runner output chunk retained for browser delivery."""

    sequence: int
    data: bytes

    def __post_init__(self) -> None:
        """Validate bounded output."""
        _require_positive(self.sequence, "sequence")
        _require_chunk(self.data)


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalResize:
    """Latest coalesced resize command."""

    sequence: int
    columns: int
    rows: int

    def __post_init__(self) -> None:
        """Validate ordered positive dimensions."""
        _require_positive(self.sequence, "sequence")
        if not 1 <= self.columns <= 65_535:
            raise ValueError("columns must be between 1 and 65535")
        if not 1 <= self.rows <= 65_535:
            raise ValueError("rows must be between 1 and 65535")


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalAttachment:
    """Current browser attachment generation and lease."""

    generation: int
    user_id: str
    attached_at: datetime
    heartbeat_at: datetime
    lease_expires_at: datetime

    def __post_init__(self) -> None:
        """Validate attachment authority."""
        _require_positive(self.generation, "generation")
        _require_identifier(self.user_id, "user_id")
        for name in ("attached_at", "heartbeat_at", "lease_expires_at"):
            _require_aware(getattr(self, name), name)


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalRunnerStream:
    """Current dedicated Runner stream generation and lease."""

    generation: int
    connected_at: datetime
    heartbeat_at: datetime
    lease_expires_at: datetime

    def __post_init__(self) -> None:
        """Validate Runner stream authority."""
        _require_positive(self.generation, "generation")
        for name in ("connected_at", "heartbeat_at", "lease_expires_at"):
            _require_aware(getattr(self, name), name)


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalRecord:
    """Complete bounded volatile state for one Terminal."""

    admission: RuntimeTerminalAdmission
    lifecycle: RuntimeTerminalLifecycle
    revision: int
    attachment: RuntimeTerminalAttachment | None
    runner_stream: RuntimeTerminalRunnerStream | None
    runner_stream_connected_once: bool
    pending_inputs: tuple[RuntimeTerminalInput, ...]
    pending_input_bytes: int
    highest_input_sequence: int
    highest_input_acknowledged_sequence: int
    live_outputs: tuple[RuntimeTerminalOutput, ...]
    live_output_bytes: int
    replay_outputs: tuple[RuntimeTerminalOutput, ...]
    replay_output_bytes: int
    highest_output_sequence: int
    browser_output_acknowledged_sequence: int
    latest_resize: RuntimeTerminalResize | None
    browser_grace_expires_at: datetime | None
    runner_stream_grace_expires_at: datetime | None
    termination_reason: RunnerTerminalTerminationReason | None
    exit_code: int | None
    updated_at: datetime
    finalized_at: datetime | None
    input_bytes: int
    output_bytes: int
    replay_truncated: bool
    diagnostics: tuple[tuple[str, str], ...]
    expires_at: datetime
    last_activity_at: datetime

    def __post_init__(self) -> None:
        """Validate canonical state bounds and time."""
        if self.revision < 0:
            raise ValueError("revision must not be negative")
        if self.pending_input_bytes != sum(
            len(item.data) for item in self.pending_inputs
        ):
            raise ValueError("pending_input_bytes does not match pending inputs")
        if self.live_output_bytes != sum(len(item.data) for item in self.live_outputs):
            raise ValueError("live_output_bytes does not match live outputs")
        if self.replay_output_bytes != sum(
            len(item.data) for item in self.replay_outputs
        ):
            raise ValueError("replay_output_bytes does not match replay outputs")
        if self.pending_input_bytes > MAX_PENDING_INPUT_BYTES:
            raise ValueError("pending input exceeds capacity")
        if self.live_output_bytes > MAX_LIVE_OUTPUT_BYTES:
            raise ValueError("live output exceeds capacity")
        if (
            self.replay_output_bytes > MAX_REPLAY_BYTES
            or len(self.replay_outputs) > MAX_REPLAY_CHUNKS
        ):
            raise ValueError("replay output exceeds capacity")
        for name in (
            "updated_at",
            "browser_grace_expires_at",
            "runner_stream_grace_expires_at",
            "finalized_at",
            "expires_at",
            "last_activity_at",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_aware(value, name)
        if self.input_bytes < 0 or self.output_bytes < 0:
            raise ValueError("byte counters must not be negative")
        if len(self.diagnostics) > MAX_DIAGNOSTIC_ENTRIES:
            raise ValueError("diagnostics exceed entry capacity")
        for key, value in self.diagnostics:
            _require_identifier(key, "diagnostic key")
            _require_text(value, "diagnostic value", MAX_DIAGNOSTIC_VALUE_BYTES)


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalTicketBinding:
    """Exact browser resource identity bound to a one-time ticket."""

    user_id: str
    authentication_session_id: str
    workspace_id: str
    agent_id: str
    session_id: str
    intent: RuntimeTerminalTicketIntent

    def __post_init__(self) -> None:
        """Validate ticket resource identity."""
        for name in (
            "user_id",
            "authentication_session_id",
            "workspace_id",
            "agent_id",
            "session_id",
        ):
            _require_identifier(getattr(self, name), name)


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalTicket:
    """One-time short-lived Terminal WebSocket ticket."""

    ticket_id: str
    binding: RuntimeTerminalTicketBinding
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        """Validate ticket lifetime."""
        _require_identifier(self.ticket_id, "ticket_id")
        _require_aware(self.issued_at, "issued_at")
        _require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.issued_at:
            raise ValueError("ticket expiry must follow issuance")


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalReplay:
    """Bounded replay snapshot returned to a browser attachment."""

    requested_after_sequence: int
    minimum_sequence: int
    maximum_sequence: int
    truncated: bool
    outputs: tuple[RuntimeTerminalOutput, ...]


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalInputBatch:
    """Contiguous pending input returned to one Runner stream."""

    inputs: tuple[RuntimeTerminalInput, ...]
    latest_resize: RuntimeTerminalResize | None
    termination_reason: RunnerTerminalTerminationReason | None


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalOutputBatch:
    """Live output returned to one browser attachment."""

    outputs: tuple[RuntimeTerminalOutput, ...]
    termination_reason: RunnerTerminalTerminationReason | None


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalRunnerStreamAdmission:
    """Successful dedicated Runner stream admission."""

    record: RuntimeTerminalRecord
    accepted: RunnerTerminalStreamAccepted


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalMutationResult[ValueT]:
    """Typed result for one fenced Terminal mutation."""

    status: RuntimeTerminalMutationStatus
    value: ValueT | None


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalInvalidationResult:
    """Terminal IDs transitioned by one indexed invalidation."""

    terminal_ids: tuple[str, ...]


def _require_identifier(value: str, name: str) -> None:
    _require_text(value, name, MAX_IDENTIFIER_BYTES)


def _require_text(value: str, name: str, maximum_bytes: int) -> None:
    size = len(value.encode())
    if not 1 <= size <= maximum_bytes:
        raise ValueError(f"{name} must be between 1 and {maximum_bytes} UTF-8 bytes")


def _require_positive(value: int, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _require_chunk(data: bytes) -> None:
    if not 1 <= len(data) <= MAX_TERMINAL_CHUNK_BYTES:
        raise ValueError(
            f"Terminal data must be between 1 and {MAX_TERMINAL_CHUNK_BYTES} bytes"
        )
