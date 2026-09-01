"""Public Runtime Terminal REST and WebSocket schemas."""

from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from azents.services.runtime_terminal.data import (
    RuntimeTerminalAttachmentAccepted,
    RuntimeTerminalDeniedScope,
    RuntimeTerminalLifecycle,
    RuntimeTerminalProjection,
    RuntimeTerminalReasonCode,
    RuntimeTerminalSummary,
    RuntimeTerminalTicketResult,
    RuntimeTerminalTicketStatus,
)


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeTerminalSummaryResponse(_ClosedModel):
    """Content-free visible Terminal summary."""

    terminal_id: str
    lifecycle: RuntimeTerminalLifecycle
    attached: bool
    started_at: datetime
    ended_at: datetime | None
    final_reason: str | None
    input_bytes: int = Field(ge=0)
    output_bytes: int = Field(ge=0)
    replay_truncated: bool

    @classmethod
    def convert_from(
        cls,
        summary: RuntimeTerminalSummary,
    ) -> "RuntimeTerminalSummaryResponse":
        return cls(**summary.__dict__)


class RuntimeTerminalProjectionResponse(_ClosedModel):
    """Session Terminal availability and action projection."""

    state: str
    reason_code: RuntimeTerminalReasonCode | None
    denied_scope: RuntimeTerminalDeniedScope | None
    can_start_runtime: bool
    can_open_or_attach: bool
    terminal: RuntimeTerminalSummaryResponse | None

    @classmethod
    def convert_from(
        cls,
        projection: RuntimeTerminalProjection,
    ) -> "RuntimeTerminalProjectionResponse":
        return cls(
            state=projection.state.value,
            reason_code=projection.reason_code,
            denied_scope=projection.denied_scope,
            can_start_runtime=projection.can_start_runtime,
            can_open_or_attach=projection.can_open_or_attach,
            terminal=(
                None
                if projection.terminal is None
                else RuntimeTerminalSummaryResponse.convert_from(projection.terminal)
            ),
        )


class RuntimeTerminalTicketResponse(_ClosedModel):
    """Typed open-or-attach ticket issuance response."""

    status: RuntimeTerminalTicketStatus
    reason_code: RuntimeTerminalReasonCode | None
    denied_scope: RuntimeTerminalDeniedScope | None
    ticket: str | None
    expires_at: datetime | None

    @classmethod
    def convert_from(
        cls,
        result: RuntimeTerminalTicketResult,
    ) -> "RuntimeTerminalTicketResponse":
        return cls(**result.__dict__)


class TerminalAttachControl(_ClosedModel):
    """Required first browser control after WebSocket acceptance."""

    type: Literal["attach"]
    columns: int = Field(ge=1, le=65_535)
    rows: int = Field(ge=1, le=65_535)
    last_output_sequence: int | None = Field(default=None, ge=0)


class TerminalResizeControl(_ClosedModel):
    type: Literal["resize"]
    sequence: int = Field(ge=1)
    columns: int = Field(ge=1, le=65_535)
    rows: int = Field(ge=1, le=65_535)


class TerminalOutputAckControl(_ClosedModel):
    type: Literal["output_ack"]
    sequence: int = Field(ge=0)


class TerminalHeartbeatControl(_ClosedModel):
    type: Literal["heartbeat"]
    sequence: int = Field(ge=1)


class TerminalTerminateControl(_ClosedModel):
    type: Literal["terminate"]


TerminalClientControl: TypeAlias = Annotated[
    TerminalResizeControl
    | TerminalOutputAckControl
    | TerminalHeartbeatControl
    | TerminalTerminateControl,
    Field(discriminator="type"),
]
TERMINAL_CLIENT_CONTROL_ADAPTER = TypeAdapter(TerminalClientControl)


class TerminalAcceptedControl(_ClosedModel):
    type: Literal["accepted"] = "accepted"
    terminal_id: str
    lifecycle: RuntimeTerminalLifecycle
    attachment_generation: int = Field(ge=1)
    desired_generation: int = Field(ge=1)
    runner_generation: int = Field(ge=1)
    shell_label: str
    working_directory_display: str
    next_input_sequence: int = Field(ge=1)
    replay_min_sequence: int = Field(ge=0)
    replay_max_sequence: int = Field(ge=0)
    replay_truncated: bool

    @classmethod
    def convert_from(
        cls,
        accepted: RuntimeTerminalAttachmentAccepted,
    ) -> "TerminalAcceptedControl":
        return cls(**accepted.__dict__)


class TerminalReplayBeginControl(_ClosedModel):
    type: Literal["replay_begin"] = "replay_begin"
    minimum_sequence: int = Field(ge=0)
    maximum_sequence: int = Field(ge=0)


class TerminalReplayTruncatedControl(_ClosedModel):
    type: Literal["replay_truncated"] = "replay_truncated"
    minimum_sequence: int = Field(ge=0)


class TerminalReplayEndControl(_ClosedModel):
    type: Literal["replay_end"] = "replay_end"
    maximum_sequence: int = Field(ge=0)


class TerminalInputAckControl(_ClosedModel):
    type: Literal["input_ack"] = "input_ack"
    sequence: int = Field(ge=1)


class TerminalStatusControl(_ClosedModel):
    type: Literal["status"] = "status"
    lifecycle: RuntimeTerminalLifecycle
    reason: str | None


class TerminalExitControl(_ClosedModel):
    type: Literal["exit"] = "exit"
    reason: str
    exit_code: int | None


class TerminalRevokedControl(_ClosedModel):
    type: Literal["revoked"] = "revoked"
    reason_code: RuntimeTerminalReasonCode


class TerminalErrorControl(_ClosedModel):
    type: Literal["error"] = "error"
    code: str


class TerminalHeartbeatAckControl(_ClosedModel):
    type: Literal["heartbeat_ack"] = "heartbeat_ack"
    sequence: int = Field(ge=1)
