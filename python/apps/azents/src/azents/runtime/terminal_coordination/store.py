"""Volatile Runtime Terminal coordination store Protocol."""

from datetime import datetime
from typing import Protocol

from azents_runtime_control.runner_terminal import (
    RunnerTerminalStreamRegistration,
    RunnerTerminalTerminationReason,
)

from azents.runtime.terminal_coordination.data import (
    RuntimeTerminalAdmission,
    RuntimeTerminalAttachment,
    RuntimeTerminalInputBatch,
    RuntimeTerminalInvalidationResult,
    RuntimeTerminalInvalidationSource,
    RuntimeTerminalMutationResult,
    RuntimeTerminalOutputBatch,
    RuntimeTerminalRecord,
    RuntimeTerminalReplay,
    RuntimeTerminalResize,
    RuntimeTerminalRunnerStream,
    RuntimeTerminalRunnerStreamAdmission,
    RuntimeTerminalTicket,
    RuntimeTerminalTicketBinding,
)


class RuntimeTerminalCoordinationStore(Protocol):
    """Redis-optional volatile Terminal state boundary."""

    async def admit_or_get(
        self,
        admission: RuntimeTerminalAdmission,
        *,
        admitted_at: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRecord]:
        """Atomically create or return the Session-active Terminal."""
        ...

    async def get_terminal(
        self,
        terminal_id: str,
        *,
        current_time: datetime,
    ) -> RuntimeTerminalRecord | None:
        """Return current non-expired Terminal metadata."""
        ...

    async def get_session_terminal(
        self,
        session_id: str,
        *,
        current_time: datetime,
    ) -> RuntimeTerminalRecord | None:
        """Return the active singleton or latest non-expired final Terminal."""
        ...

    async def issue_ticket(
        self,
        ticket: RuntimeTerminalTicket,
        *,
        ttl_seconds: int,
    ) -> None:
        """Store one short-lived one-time browser ticket."""
        ...

    async def consume_ticket(
        self,
        ticket_id: str,
        *,
        expected_binding: RuntimeTerminalTicketBinding,
        consumed_at: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalTicket]:
        """Atomically consume one exact unexpired ticket."""
        ...

    async def attach_browser(
        self,
        terminal_id: str,
        *,
        user_id: str,
        attached_at: datetime,
        lease_seconds: int,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalAttachment]:
        """Replace the browser attachment generation and lease."""
        ...

    async def heartbeat_browser(
        self,
        terminal_id: str,
        *,
        attachment_generation: int,
        heartbeat_at: datetime,
        lease_seconds: int,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalAttachment]:
        """Refresh one exact attachment lease."""
        ...

    async def detach_browser(
        self,
        terminal_id: str,
        *,
        attachment_generation: int,
        detached_at: datetime,
        grace_seconds: int,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRecord]:
        """Release one exact browser attachment and begin reattach grace."""
        ...

    async def register_runner_stream(
        self,
        registration: RunnerTerminalStreamRegistration,
        *,
        desired_generation: int,
        connected_at: datetime,
        lease_seconds: int,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRunnerStreamAdmission]:
        """Atomically fence Runtime, Runner, nonce, sequence, and stream authority."""
        ...

    async def heartbeat_runner_stream(
        self,
        terminal_id: str,
        *,
        runner_stream_generation: int,
        heartbeat_at: datetime,
        lease_seconds: int,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRunnerStream]:
        """Refresh one exact Runner stream lease."""
        ...

    async def detach_runner_stream(
        self,
        terminal_id: str,
        *,
        runner_stream_generation: int,
        detached_at: datetime,
        grace_seconds: int,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRecord]:
        """Release one exact Runner stream and begin data-stream grace."""
        ...

    async def enqueue_input(
        self,
        terminal_id: str,
        *,
        attachment_generation: int,
        sequence: int,
        data: bytes,
        accepted_at: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRecord]:
        """Append one contiguous bounded browser input chunk."""
        ...

    async def read_inputs(
        self,
        terminal_id: str,
        *,
        runner_stream_generation: int,
        after_sequence: int,
        maximum_bytes: int,
        current_time: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalInputBatch]:
        """Read bounded contiguous input and latest resize for a Runner stream."""
        ...

    async def acknowledge_input(
        self,
        terminal_id: str,
        *,
        runner_stream_generation: int,
        sequence: int,
        acknowledged_at: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRecord]:
        """Cumulatively acknowledge completely applied Runner input."""
        ...

    async def update_resize(
        self,
        terminal_id: str,
        *,
        attachment_generation: int,
        columns: int,
        rows: int,
        updated_at: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalResize]:
        """Coalesce latest browser dimensions."""
        ...

    async def append_output(
        self,
        terminal_id: str,
        *,
        runner_stream_generation: int,
        sequence: int,
        data: bytes,
        accepted_at: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRecord]:
        """Accept one contiguous Runner output only when live capacity remains."""
        ...

    async def read_output(
        self,
        terminal_id: str,
        *,
        attachment_generation: int,
        after_sequence: int,
        maximum_bytes: int,
        current_time: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalOutputBatch]:
        """Read bounded live output for one browser attachment."""
        ...

    async def acknowledge_output(
        self,
        terminal_id: str,
        *,
        attachment_generation: int,
        sequence: int,
        acknowledged_at: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRecord]:
        """Cumulatively acknowledge browser output and release live capacity."""
        ...

    async def replay_output(
        self,
        terminal_id: str,
        *,
        attachment_generation: int,
        after_sequence: int,
        maximum_bytes: int,
        current_time: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalReplay]:
        """Read a bounded retained replay tail."""
        ...

    async def request_termination(
        self,
        terminal_id: str,
        *,
        reason: RunnerTerminalTerminationReason,
        requested_at: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRecord]:
        """Apply the first Terminal termination transition."""
        ...

    async def finalize_terminal(
        self,
        terminal_id: str,
        *,
        runner_stream_generation: int | None,
        reason: RunnerTerminalTerminationReason,
        exit_code: int | None,
        finalized_at: datetime,
        final_ttl_seconds: int,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRecord]:
        """Finalize metadata through the exact current Runner stream generation."""
        ...

    async def invalidate(
        self,
        *,
        source: RuntimeTerminalInvalidationSource,
        source_id: str,
        reason: RunnerTerminalTerminationReason,
        invalidated_at: datetime,
    ) -> RuntimeTerminalInvalidationResult:
        """Request termination for every Terminal indexed by one source."""
        ...

    async def repair_expired(
        self,
        *,
        current_time: datetime,
        limit: int,
    ) -> RuntimeTerminalInvalidationResult:
        """Transition bounded expired lifecycle deadlines to terminating."""
        ...

    async def wait_for_change(
        self,
        terminal_id: str,
        *,
        after_revision: int,
        timeout_seconds: float,
    ) -> RuntimeTerminalRecord | None:
        """Wait for a newer revision or return current state after timeout."""
        ...
