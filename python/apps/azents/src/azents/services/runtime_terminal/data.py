"""Typed Public Runtime Terminal service contracts."""

import dataclasses
import enum
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol, TypeAlias


class RuntimeTerminalProjectionState(enum.StrEnum):
    """Server-authored Session Terminal projection states."""

    ABSENT = "absent"
    STOPPED = "stopped"
    STARTING = "starting"
    UNAVAILABLE = "unavailable"
    READY = "ready"
    ACTIVE = "active"
    ENDED = "ended"


class RuntimeTerminalReasonCode(enum.StrEnum):
    """Bounded public reason codes without secret or content data."""

    ACCESS_DENIED = "access_denied"
    AGENT_NOT_FOUND = "agent_not_found"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_AGENT_MISMATCH = "session_agent_mismatch"
    RUNTIME_FREE_AGENT = "runtime_free_agent"
    RUNTIME_STOPPED = "runtime_stopped"
    RUNTIME_STARTING = "runtime_starting"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    PROFILE_UNAVAILABLE = "profile_unavailable"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TERMINAL_DISABLED = "terminal_disabled"
    RUNNER_UNAVAILABLE = "runner_unavailable"
    RUNNER_TERMINAL_UNSUPPORTED = "runner_terminal_unsupported"
    WORKING_FOLDER_UNAVAILABLE = "working_folder_unavailable"
    SESSION_LIMIT = "session_limit"
    USER_LIMIT = "user_limit"
    RUNTIME_LIMIT = "runtime_limit"
    TERMINAL_ENDED = "terminal_ended"
    TERMINAL_REVOKED = "terminal_revoked"
    COORDINATION_UNAVAILABLE = "coordination_unavailable"


class RuntimeTerminalDeniedScope(enum.StrEnum):
    """Policy or authority scope that denied Terminal use."""

    PROVIDER_PROFILE = "provider_profile"
    WORKSPACE_PROFILE = "workspace_profile"
    AGENT = "agent"
    RUNTIME = "runtime"
    RUNNER = "runner"
    SESSION = "session"
    ACCESS = "access"


class RuntimeTerminalTicketStatus(enum.StrEnum):
    """Ticket issuance result without Runtime side effects."""

    ISSUED = "issued"
    RUNTIME_STOPPED = "runtime_stopped"
    UNAVAILABLE = "unavailable"
    DENIED = "denied"


class RuntimeTerminalLifecycle(enum.StrEnum):
    """Volatile Terminal lifecycle exposed to the browser."""

    OPENING = "opening"
    ATTACHED = "attached"
    DETACHED = "detached"
    TERMINATING = "terminating"
    EXITED = "exited"


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalResource:
    """Exact Public API resource path identity."""

    workspace_handle: str
    agent_id: str
    session_id: str


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalAuthority:
    """Current PostgreSQL and Runner authority resolved for one Session."""

    user_id: str
    authentication_session_id: str
    authentication_session_expires_at: datetime | None
    workspace_id: str
    resource: RuntimeTerminalResource
    runtime_id: str | None
    desired_generation: int | None
    runner_generation: int | None
    workspace_profile_id: str | None
    workspace_profile_version: int | None
    provider_profile_id: str | None
    provider_profile_version: int | None
    agent_policy_version: str | None
    working_directory: str | None
    working_directory_display: str | None
    shell_label: str
    projection_state: RuntimeTerminalProjectionState
    reason_code: RuntimeTerminalReasonCode | None
    denied_scope: RuntimeTerminalDeniedScope | None
    can_start_runtime: bool
    can_open_or_attach: bool


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalSummary:
    """Content-free active or recently ended Terminal summary."""

    terminal_id: str
    lifecycle: RuntimeTerminalLifecycle
    attached: bool
    started_at: datetime
    ended_at: datetime | None
    final_reason: str | None
    input_bytes: int
    output_bytes: int
    replay_truncated: bool


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalProjection:
    """Complete Session Terminal projection returned by Public API."""

    state: RuntimeTerminalProjectionState
    reason_code: RuntimeTerminalReasonCode | None
    denied_scope: RuntimeTerminalDeniedScope | None
    can_start_runtime: bool
    can_open_or_attach: bool
    terminal: RuntimeTerminalSummary | None


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalTicketClaims:
    """Resource-bound short-lived one-time Terminal ticket claims."""

    ticket_id: str
    user_id: str
    authentication_session_id: str
    workspace_id: str
    resource: RuntimeTerminalResource
    intent: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        """Validate exact non-empty resource identity and aware lifetime."""
        for value in (
            self.ticket_id,
            self.user_id,
            self.authentication_session_id,
            self.workspace_id,
            self.resource.workspace_handle,
            self.resource.agent_id,
            self.resource.session_id,
            self.intent,
        ):
            if not value:
                raise ValueError("Runtime Terminal ticket identity is required")
        if (
            self.issued_at.tzinfo is None
            or self.expires_at.tzinfo is None
            or self.expires_at <= self.issued_at
        ):
            raise ValueError("Runtime Terminal ticket lifetime is invalid")


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalTicketResult:
    """Typed ticket issuance outcome."""

    status: RuntimeTerminalTicketStatus
    reason_code: RuntimeTerminalReasonCode | None
    denied_scope: RuntimeTerminalDeniedScope | None
    ticket: str | None
    expires_at: datetime | None


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalSocketAdmission:
    """Consumed ticket with freshly revalidated authority."""

    claims: RuntimeTerminalTicketClaims
    authority: RuntimeTerminalAuthority


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalAttachRequest:
    """Initial browser attachment request."""

    columns: int
    rows: int
    last_output_sequence: int | None


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalAttachmentAccepted:
    """Current attachment generation and replay evidence."""

    terminal_id: str
    lifecycle: RuntimeTerminalLifecycle
    attachment_generation: int
    desired_generation: int
    runner_generation: int
    shell_label: str
    working_directory_display: str
    next_input_sequence: int
    replay_min_sequence: int
    replay_max_sequence: int
    replay_truncated: bool


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalOutput:
    """One ordered binary output frame."""

    sequence: int
    data: bytes


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalInputAcknowledged:
    """One completely applied input acknowledgement."""

    sequence: int


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalStatusChanged:
    """Content-free lifecycle status update."""

    lifecycle: RuntimeTerminalLifecycle
    reason: str | None


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalExited:
    """Final Terminal exit event."""

    reason: str
    exit_code: int | None


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalRevoked:
    """Active authority revocation event."""

    reason_code: RuntimeTerminalReasonCode


@dataclasses.dataclass(frozen=True)
class RuntimeTerminalErrorEvent:
    """Bounded Terminal protocol error event."""

    code: str


RuntimeTerminalServerEvent: TypeAlias = (
    RuntimeTerminalOutput
    | RuntimeTerminalInputAcknowledged
    | RuntimeTerminalStatusChanged
    | RuntimeTerminalExited
    | RuntimeTerminalRevoked
    | RuntimeTerminalErrorEvent
)


class RuntimeTerminalAttachment(Protocol):
    """One current browser attachment backed by volatile coordination."""

    @property
    def accepted(self) -> RuntimeTerminalAttachmentAccepted:
        """Return accepted attachment and replay evidence."""
        ...

    def replay(self) -> tuple[RuntimeTerminalOutput, ...]:
        """Return the bounded retained replay tail in order."""
        ...

    def events(self) -> AsyncIterator[RuntimeTerminalServerEvent]:
        """Yield live ordered Terminal events until attachment close."""
        ...

    async def input(self, *, sequence: int, data: bytes) -> None:
        """Append one contiguous browser input frame."""
        ...

    async def resize(self, *, sequence: int, columns: int, rows: int) -> None:
        """Apply one latest-wins resize control."""
        ...

    async def acknowledge_output(self, *, sequence: int) -> None:
        """Cumulatively acknowledge browser-visible output."""
        ...

    async def heartbeat(self, *, sequence: int) -> None:
        """Refresh the current attachment lease."""
        ...

    async def terminate(self) -> None:
        """Request explicit Terminal termination."""
        ...

    async def revoke(self, reason_code: RuntimeTerminalReasonCode) -> None:
        """Terminate the PTY after active authority is revoked."""
        ...

    async def close(self) -> None:
        """Release this attachment generation without finalizing the PTY."""
        ...
