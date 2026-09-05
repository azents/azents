"""In-memory volatile Runtime Terminal coordination."""

import asyncio
import dataclasses
from collections.abc import Iterable
from datetime import datetime, timedelta

from azents_runtime_control.runner_terminal import (
    RunnerTerminalStreamAccepted,
    RunnerTerminalStreamRegistration,
    RunnerTerminalTerminationReason,
)

from azents.runtime.terminal_coordination.data import (
    MAX_ACTIVE_TERMINALS_PER_RUNTIME,
    MAX_ACTIVE_TERMINALS_PER_SESSION,
    MAX_ACTIVE_TERMINALS_PER_USER,
    MAX_LIVE_OUTPUT_BYTES,
    MAX_PENDING_INPUT_BYTES,
    MAX_REPLAY_BYTES,
    MAX_REPLAY_CHUNKS,
    TERMINAL_BROWSER_GRACE_SECONDS,
    TERMINAL_FINAL_TTL_SECONDS,
    TERMINAL_IDLE_SECONDS,
    TERMINAL_RUNNER_GRACE_SECONDS,
    RuntimeTerminalAdmission,
    RuntimeTerminalAttachment,
    RuntimeTerminalInput,
    RuntimeTerminalInputBatch,
    RuntimeTerminalInvalidationResult,
    RuntimeTerminalInvalidationSource,
    RuntimeTerminalLifecycle,
    RuntimeTerminalMutationResult,
    RuntimeTerminalMutationStatus,
    RuntimeTerminalOutput,
    RuntimeTerminalOutputBatch,
    RuntimeTerminalRecord,
    RuntimeTerminalReplay,
    RuntimeTerminalResize,
    RuntimeTerminalRunnerStream,
    RuntimeTerminalRunnerStreamAdmission,
    RuntimeTerminalTicket,
    RuntimeTerminalTicketBinding,
)


class InMemoryRuntimeTerminalCoordinationStore:
    """Process-local Terminal coordination for standalone deployments and tests."""

    def __init__(self) -> None:
        """Initialize empty volatile state."""
        self._condition = asyncio.Condition()
        self._terminals: dict[str, RuntimeTerminalRecord] = {}
        self._tickets: dict[str, RuntimeTerminalTicket] = {}
        self._session_active: dict[str, str] = {}
        self._session_latest_final: dict[str, str] = {}
        self._user_active: dict[str, set[str]] = {}
        self._runtime_active: dict[str, set[str]] = {}
        self._source_indexes: dict[
            tuple[RuntimeTerminalInvalidationSource, str], set[str]
        ] = {}

    async def admit_or_get(
        self,
        admission: RuntimeTerminalAdmission,
        *,
        admitted_at: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRecord]:
        """Atomically create or return the Session-active Terminal."""
        _require_aware(admitted_at)
        async with self._condition:
            self._purge_expired(admitted_at)
            existing_id = self._session_active.get(admission.session_id)
            if existing_id is not None:
                existing = self._terminals.get(existing_id)
                if existing is not None:
                    return _result(RuntimeTerminalMutationStatus.APPLIED, existing)
            if MAX_ACTIVE_TERMINALS_PER_SESSION <= 0:
                return _result(RuntimeTerminalMutationStatus.QUOTA_EXCEEDED)
            if (
                len(self._user_active.get(admission.user_id, set()))
                >= MAX_ACTIVE_TERMINALS_PER_USER
                or len(self._runtime_active.get(admission.runtime_id, set()))
                >= MAX_ACTIVE_TERMINALS_PER_RUNTIME
            ):
                return _result(RuntimeTerminalMutationStatus.QUOTA_EXCEEDED)
            if admission.terminal_id in self._terminals:
                return _result(RuntimeTerminalMutationStatus.STALE_RUNTIME_AUTHORITY)
            record = RuntimeTerminalRecord(
                admission=admission,
                lifecycle=RuntimeTerminalLifecycle.OPENING,
                revision=1,
                attachment=None,
                runner_stream=None,
                runner_stream_connected_once=False,
                pending_inputs=(),
                pending_input_bytes=0,
                highest_input_sequence=0,
                highest_input_acknowledged_sequence=0,
                live_outputs=(),
                live_output_bytes=0,
                replay_outputs=(),
                replay_output_bytes=0,
                highest_output_sequence=0,
                browser_output_acknowledged_sequence=0,
                latest_resize=None,
                browser_grace_expires_at=None,
                runner_stream_grace_expires_at=None,
                termination_reason=None,
                exit_code=None,
                updated_at=admitted_at,
                finalized_at=None,
                input_bytes=0,
                output_bytes=0,
                replay_truncated=False,
                diagnostics=(),
                expires_at=admitted_at
                + timedelta(seconds=admission.metadata_ttl_seconds),
                last_activity_at=admitted_at,
            )
            self._terminals[admission.terminal_id] = record
            self._add_indexes(record)
            self._notify()
            return _result(RuntimeTerminalMutationStatus.APPLIED, record)

    async def get_terminal(
        self,
        terminal_id: str,
        *,
        current_time: datetime,
    ) -> RuntimeTerminalRecord | None:
        """Return current non-expired Terminal metadata."""
        _require_aware(current_time)
        async with self._condition:
            self._purge_expired(current_time)
            return self._terminals.get(terminal_id)

    async def get_session_terminal(
        self,
        session_id: str,
        *,
        current_time: datetime,
    ) -> RuntimeTerminalRecord | None:
        """Return the active singleton or latest non-expired final Terminal."""
        _require_aware(current_time)
        async with self._condition:
            self._purge_expired(current_time)
            terminal_id = self._session_active.get(session_id)
            if terminal_id is None:
                terminal_id = self._session_latest_final.get(session_id)
            return None if terminal_id is None else self._terminals.get(terminal_id)

    async def issue_ticket(
        self,
        ticket: RuntimeTerminalTicket,
        *,
        ttl_seconds: int,
    ) -> None:
        """Store one short-lived one-time browser ticket."""
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if ticket.expires_at > ticket.issued_at + timedelta(seconds=ttl_seconds):
            raise ValueError("ticket expiry exceeds ttl_seconds")
        async with self._condition:
            self._tickets[ticket.ticket_id] = ticket
            self._notify()

    async def consume_ticket(
        self,
        ticket_id: str,
        *,
        expected_binding: RuntimeTerminalTicketBinding,
        consumed_at: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalTicket]:
        """Atomically consume one exact unexpired ticket."""
        _require_aware(consumed_at)
        async with self._condition:
            ticket = self._tickets.get(ticket_id)
            if ticket is None:
                return _result(RuntimeTerminalMutationStatus.TICKET_MISSING)
            if ticket.expires_at <= consumed_at:
                self._tickets.pop(ticket_id, None)
                return _result(RuntimeTerminalMutationStatus.TICKET_EXPIRED)
            if ticket.binding != expected_binding:
                return _result(RuntimeTerminalMutationStatus.TICKET_BINDING_MISMATCH)
            self._tickets.pop(ticket_id, None)
            self._notify()
            return _result(RuntimeTerminalMutationStatus.APPLIED, ticket)

    async def attach_browser(
        self,
        terminal_id: str,
        *,
        user_id: str,
        attached_at: datetime,
        lease_seconds: int,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalAttachment]:
        """Replace the browser attachment generation and lease."""
        _require_lease(attached_at, lease_seconds)
        async with self._condition:
            record = self._terminals.get(terminal_id)
            status = _active_status(record)
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _result(status)
            assert record is not None
            if record.admission.user_id != user_id:
                return _result(RuntimeTerminalMutationStatus.STALE_RUNTIME_AUTHORITY)
            generation = (
                1 if record.attachment is None else record.attachment.generation + 1
            )
            attachment = RuntimeTerminalAttachment(
                generation=generation,
                user_id=user_id,
                attached_at=attached_at,
                heartbeat_at=attached_at,
                lease_expires_at=attached_at + timedelta(seconds=lease_seconds),
            )
            updated = _updated(
                record,
                attached_at,
                attachment=attachment,
                lifecycle=RuntimeTerminalLifecycle.ATTACHED,
                browser_grace_expires_at=None,
            )
            self._set(updated)
            return _result(RuntimeTerminalMutationStatus.APPLIED, attachment)

    async def heartbeat_browser(
        self,
        terminal_id: str,
        *,
        attachment_generation: int,
        heartbeat_at: datetime,
        lease_seconds: int,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalAttachment]:
        """Refresh one exact attachment lease."""
        _require_lease(heartbeat_at, lease_seconds)
        async with self._condition:
            record = self._terminals.get(terminal_id)
            status = _attachment_status(record, attachment_generation, heartbeat_at)
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _result(status)
            assert record is not None and record.attachment is not None
            attachment = dataclasses.replace(
                record.attachment,
                heartbeat_at=heartbeat_at,
                lease_expires_at=heartbeat_at + timedelta(seconds=lease_seconds),
            )
            self._set(_updated(record, heartbeat_at, attachment=attachment))
            return _result(RuntimeTerminalMutationStatus.APPLIED, attachment)

    async def detach_browser(
        self,
        terminal_id: str,
        *,
        attachment_generation: int,
        detached_at: datetime,
        grace_seconds: int,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRecord]:
        """Release one exact browser attachment and begin reattach grace."""
        _require_lease(detached_at, grace_seconds)
        async with self._condition:
            record = self._terminals.get(terminal_id)
            status = _attachment_status(record, attachment_generation, detached_at)
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _result(status)
            assert record is not None
            updated = _updated(
                record,
                detached_at,
                attachment=None,
                lifecycle=RuntimeTerminalLifecycle.DETACHED,
                browser_grace_expires_at=detached_at + timedelta(seconds=grace_seconds),
            )
            self._set(updated)
            return _result(RuntimeTerminalMutationStatus.APPLIED, updated)

    async def register_runner_stream(
        self,
        registration: RunnerTerminalStreamRegistration,
        *,
        desired_generation: int,
        connected_at: datetime,
        lease_seconds: int,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRunnerStreamAdmission]:
        """Atomically fence Runtime, Runner, nonce, sequence, and stream authority."""
        _require_lease(connected_at, lease_seconds)
        async with self._condition:
            terminal_id = registration.identity.terminal_id
            record = self._terminals.get(terminal_id)
            status = _runner_registration_status(record)
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _result(status)
            assert record is not None
            admission = record.admission
            if (
                registration.identity.runtime_id != admission.runtime_id
                or registration.identity.runner_generation
                != admission.runner_generation
                or desired_generation != admission.desired_generation
                or registration.stream_nonce != admission.stream_nonce
            ):
                return _result(RuntimeTerminalMutationStatus.STALE_RUNTIME_AUTHORITY)
            if (
                record.runner_stream is not None
                and registration.stream_generation <= record.runner_stream.generation
            ):
                return _result(
                    RuntimeTerminalMutationStatus.STALE_RUNNER_STREAM_GENERATION
                )
            evidence = _apply_runner_input_evidence(record, registration)
            if evidence is None:
                return _result(RuntimeTerminalMutationStatus.SEQUENCE_REJECTED)
            stream = RuntimeTerminalRunnerStream(
                generation=registration.stream_generation,
                connected_at=connected_at,
                heartbeat_at=connected_at,
                lease_expires_at=connected_at + timedelta(seconds=lease_seconds),
            )
            updated = _updated(
                evidence,
                connected_at,
                runner_stream=stream,
                runner_stream_connected_once=True,
                runner_stream_grace_expires_at=None,
            )
            self._set(updated)
            accepted = RunnerTerminalStreamAccepted(
                stream_generation=stream.generation,
                resume_from_output_sequence=(
                    registration.last_control_acknowledged_output_sequence + 1
                ),
                next_input_sequence=(
                    registration.partial_input_sequence
                    if registration.partial_input_sequence is not None
                    else registration.highest_completely_applied_input_sequence + 1
                ),
            )
            return _result(
                RuntimeTerminalMutationStatus.APPLIED,
                RuntimeTerminalRunnerStreamAdmission(
                    record=updated,
                    accepted=accepted,
                ),
            )

    async def heartbeat_runner_stream(
        self,
        terminal_id: str,
        *,
        runner_stream_generation: int,
        heartbeat_at: datetime,
        lease_seconds: int,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRunnerStream]:
        """Refresh one exact Runner stream lease."""
        _require_lease(heartbeat_at, lease_seconds)
        async with self._condition:
            record = self._terminals.get(terminal_id)
            status = _runner_stream_status(
                record,
                runner_stream_generation,
                heartbeat_at,
            )
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _result(status)
            assert record is not None and record.runner_stream is not None
            stream = dataclasses.replace(
                record.runner_stream,
                heartbeat_at=heartbeat_at,
                lease_expires_at=heartbeat_at + timedelta(seconds=lease_seconds),
            )
            self._set(_updated(record, heartbeat_at, runner_stream=stream))
            return _result(RuntimeTerminalMutationStatus.APPLIED, stream)

    async def detach_runner_stream(
        self,
        terminal_id: str,
        *,
        runner_stream_generation: int,
        detached_at: datetime,
        grace_seconds: int,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRecord]:
        """Release one exact Runner stream and begin data-stream grace."""
        _require_lease(detached_at, grace_seconds)
        async with self._condition:
            record = self._terminals.get(terminal_id)
            status = _runner_stream_detach_status(
                record,
                runner_stream_generation,
                detached_at,
            )
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _result(status)
            assert record is not None
            updated = _updated(
                record,
                detached_at,
                runner_stream=None,
                runner_stream_grace_expires_at=detached_at
                + timedelta(seconds=grace_seconds),
            )
            self._set(updated)
            return _result(RuntimeTerminalMutationStatus.APPLIED, updated)

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
        item = RuntimeTerminalInput(sequence=sequence, data=data)
        async with self._condition:
            record = self._terminals.get(terminal_id)
            status = _attachment_status(record, attachment_generation, accepted_at)
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _result(status)
            assert record is not None
            if sequence <= record.highest_input_sequence:
                duplicate = next(
                    (
                        existing
                        for existing in record.pending_inputs
                        if existing.sequence == sequence
                    ),
                    None,
                )
                if duplicate == item:
                    return _result(RuntimeTerminalMutationStatus.APPLIED, record)
                return _result(RuntimeTerminalMutationStatus.SEQUENCE_REJECTED)
            if sequence != record.highest_input_sequence + 1:
                return _result(RuntimeTerminalMutationStatus.SEQUENCE_REJECTED)
            if record.pending_input_bytes + len(data) > MAX_PENDING_INPUT_BYTES:
                return _result(RuntimeTerminalMutationStatus.CAPACITY_EXCEEDED)
            updated = _updated(
                record,
                accepted_at,
                pending_inputs=(*record.pending_inputs, item),
                pending_input_bytes=record.pending_input_bytes + len(data),
                highest_input_sequence=sequence,
                input_bytes=record.input_bytes + len(data),
                last_activity_at=accepted_at,
            )
            self._set(updated)
            return _result(RuntimeTerminalMutationStatus.APPLIED, updated)

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
        if maximum_bytes <= 0:
            raise ValueError("maximum_bytes must be positive")
        async with self._condition:
            record = self._terminals.get(terminal_id)
            status = _runner_stream_status(
                record,
                runner_stream_generation,
                current_time,
            )
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _result(status)
            assert record is not None
            inputs = _bounded_chunks(
                (
                    item
                    for item in record.pending_inputs
                    if item.sequence > after_sequence
                ),
                maximum_bytes,
            )
            return _result(
                RuntimeTerminalMutationStatus.APPLIED,
                RuntimeTerminalInputBatch(
                    inputs=inputs,
                    latest_resize=record.latest_resize,
                    termination_reason=record.termination_reason,
                ),
            )

    async def acknowledge_input(
        self,
        terminal_id: str,
        *,
        runner_stream_generation: int,
        sequence: int,
        acknowledged_at: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRecord]:
        """Cumulatively acknowledge completely applied Runner input."""
        async with self._condition:
            record = self._terminals.get(terminal_id)
            status = _runner_stream_status(
                record,
                runner_stream_generation,
                acknowledged_at,
            )
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _result(status)
            assert record is not None
            if (
                sequence < record.highest_input_acknowledged_sequence
                or sequence > record.highest_input_sequence
            ):
                return _result(RuntimeTerminalMutationStatus.SEQUENCE_REJECTED)
            remaining = tuple(
                item for item in record.pending_inputs if item.sequence > sequence
            )
            updated = _updated(
                record,
                acknowledged_at,
                pending_inputs=remaining,
                pending_input_bytes=sum(len(item.data) for item in remaining),
                highest_input_acknowledged_sequence=sequence,
            )
            self._set(updated)
            return _result(RuntimeTerminalMutationStatus.APPLIED, updated)

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
        async with self._condition:
            record = self._terminals.get(terminal_id)
            status = _attachment_status(record, attachment_generation, updated_at)
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _result(status)
            assert record is not None
            resize = RuntimeTerminalResize(
                sequence=(
                    1
                    if record.latest_resize is None
                    else record.latest_resize.sequence + 1
                ),
                columns=columns,
                rows=rows,
            )
            self._set(_updated(record, updated_at, latest_resize=resize))
            return _result(RuntimeTerminalMutationStatus.APPLIED, resize)

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
        item = RuntimeTerminalOutput(sequence=sequence, data=data)
        async with self._condition:
            record = self._terminals.get(terminal_id)
            status = _runner_stream_status(
                record,
                runner_stream_generation,
                accepted_at,
            )
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _result(status)
            assert record is not None
            if sequence <= record.highest_output_sequence:
                duplicate = next(
                    (
                        existing
                        for existing in (*record.live_outputs, *record.replay_outputs)
                        if existing.sequence == sequence
                    ),
                    None,
                )
                if duplicate == item:
                    return _result(RuntimeTerminalMutationStatus.APPLIED, record)
                return _result(RuntimeTerminalMutationStatus.SEQUENCE_REJECTED)
            if sequence != record.highest_output_sequence + 1:
                return _result(RuntimeTerminalMutationStatus.SEQUENCE_REJECTED)
            if record.live_output_bytes + len(data) > MAX_LIVE_OUTPUT_BYTES:
                return _result(RuntimeTerminalMutationStatus.CAPACITY_EXCEEDED)
            replay, replay_bytes, truncated = _append_replay(record, item)
            updated = _updated(
                record,
                accepted_at,
                live_outputs=(*record.live_outputs, item),
                live_output_bytes=record.live_output_bytes + len(data),
                replay_outputs=replay,
                replay_output_bytes=replay_bytes,
                highest_output_sequence=sequence,
                output_bytes=record.output_bytes + len(data),
                replay_truncated=record.replay_truncated or truncated,
                last_activity_at=accepted_at,
            )
            self._set(updated)
            return _result(RuntimeTerminalMutationStatus.APPLIED, updated)

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
        if maximum_bytes <= 0:
            raise ValueError("maximum_bytes must be positive")
        async with self._condition:
            record = self._terminals.get(terminal_id)
            status = _attachment_status(record, attachment_generation, current_time)
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _result(status)
            assert record is not None
            outputs = _bounded_chunks(
                (
                    item
                    for item in record.live_outputs
                    if item.sequence > after_sequence
                ),
                maximum_bytes,
            )
            return _result(
                RuntimeTerminalMutationStatus.APPLIED,
                RuntimeTerminalOutputBatch(
                    outputs=outputs,
                    termination_reason=record.termination_reason,
                ),
            )

    async def acknowledge_output(
        self,
        terminal_id: str,
        *,
        attachment_generation: int,
        sequence: int,
        acknowledged_at: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRecord]:
        """Cumulatively acknowledge browser output and release live capacity."""
        async with self._condition:
            record = self._terminals.get(terminal_id)
            status = _attachment_status(
                record,
                attachment_generation,
                acknowledged_at,
            )
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _result(status)
            assert record is not None
            if (
                sequence < record.browser_output_acknowledged_sequence
                or sequence > record.highest_output_sequence
            ):
                return _result(RuntimeTerminalMutationStatus.SEQUENCE_REJECTED)
            remaining = tuple(
                item for item in record.live_outputs if item.sequence > sequence
            )
            updated = _updated(
                record,
                acknowledged_at,
                live_outputs=remaining,
                live_output_bytes=sum(len(item.data) for item in remaining),
                browser_output_acknowledged_sequence=sequence,
            )
            self._set(updated)
            return _result(RuntimeTerminalMutationStatus.APPLIED, updated)

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
        if maximum_bytes <= 0:
            raise ValueError("maximum_bytes must be positive")
        async with self._condition:
            record = self._terminals.get(terminal_id)
            status = _attachment_status(record, attachment_generation, current_time)
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _result(status)
            assert record is not None
            minimum = (
                record.replay_outputs[0].sequence
                if record.replay_outputs
                else record.highest_output_sequence + 1
            )
            outputs = _bounded_chunks(
                (
                    item
                    for item in record.replay_outputs
                    if item.sequence > after_sequence
                ),
                maximum_bytes,
            )
            return _result(
                RuntimeTerminalMutationStatus.APPLIED,
                RuntimeTerminalReplay(
                    requested_after_sequence=after_sequence,
                    minimum_sequence=minimum,
                    maximum_sequence=record.highest_output_sequence,
                    truncated=after_sequence < minimum - 1,
                    outputs=outputs,
                ),
            )

    async def request_termination(
        self,
        terminal_id: str,
        *,
        reason: RunnerTerminalTerminationReason,
        requested_at: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRecord]:
        """Apply the first Terminal termination transition."""
        async with self._condition:
            record = self._terminals.get(terminal_id)
            if record is None:
                return _result(RuntimeTerminalMutationStatus.NOT_FOUND)
            if record.lifecycle is RuntimeTerminalLifecycle.EXITED:
                return _result(RuntimeTerminalMutationStatus.TERMINAL_FINAL, record)
            if record.lifecycle is RuntimeTerminalLifecycle.TERMINATING:
                return _result(RuntimeTerminalMutationStatus.APPLIED, record)
            updated = _termination_transition(
                record,
                reason=reason,
                requested_at=requested_at,
            )
            self._set(updated)
            return _result(RuntimeTerminalMutationStatus.APPLIED, updated)

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
        _require_lease(finalized_at, final_ttl_seconds)
        async with self._condition:
            record = self._terminals.get(terminal_id)
            if record is None:
                return _result(RuntimeTerminalMutationStatus.NOT_FOUND)
            if record.lifecycle is RuntimeTerminalLifecycle.EXITED:
                return _result(RuntimeTerminalMutationStatus.APPLIED, record)
            if not _finalization_authorized(
                record,
                runner_stream_generation=runner_stream_generation,
                finalized_at=finalized_at,
            ):
                return _result(
                    RuntimeTerminalMutationStatus.STALE_RUNNER_STREAM_GENERATION
                )
            updated = _updated(
                record,
                finalized_at,
                lifecycle=RuntimeTerminalLifecycle.EXITED,
                attachment=None,
                runner_stream=None,
                pending_inputs=(),
                pending_input_bytes=0,
                live_outputs=(),
                live_output_bytes=0,
                replay_outputs=(),
                replay_output_bytes=0,
                latest_resize=None,
                runner_stream_grace_expires_at=None,
                termination_reason=record.termination_reason or reason,
                exit_code=exit_code,
                finalized_at=finalized_at,
                expires_at=finalized_at + timedelta(seconds=final_ttl_seconds),
            )
            self._remove_active_indexes(record)
            self._session_latest_final[record.admission.session_id] = terminal_id
            self._set(updated)
            return _result(RuntimeTerminalMutationStatus.APPLIED, updated)

    async def invalidate(
        self,
        *,
        source: RuntimeTerminalInvalidationSource,
        source_id: str,
        reason: RunnerTerminalTerminationReason,
        invalidated_at: datetime,
    ) -> RuntimeTerminalInvalidationResult:
        """Request termination for every Terminal indexed by one source."""
        async with self._condition:
            terminal_ids = tuple(
                sorted(self._source_indexes.get((source, source_id), set()))
            )
            affected: list[str] = []
            for terminal_id in terminal_ids:
                record = self._terminals.get(terminal_id)
                if record is None or record.lifecycle in {
                    RuntimeTerminalLifecycle.TERMINATING,
                    RuntimeTerminalLifecycle.EXITED,
                }:
                    continue
                self._set(
                    _termination_transition(
                        record,
                        reason=reason,
                        requested_at=invalidated_at,
                    )
                )
                affected.append(terminal_id)
            return RuntimeTerminalInvalidationResult(tuple(affected))

    async def repair_expired(
        self,
        *,
        current_time: datetime,
        limit: int,
    ) -> RuntimeTerminalInvalidationResult:
        """Transition bounded expired lifecycle deadlines to terminating."""
        _require_aware(current_time)
        if limit <= 0:
            raise ValueError("limit must be positive")
        async with self._condition:
            affected: list[str] = []
            for terminal_id in sorted(self._terminals):
                if len(affected) >= limit:
                    break
                record = self._terminals[terminal_id]
                lease_repaired = _repair_expired_leases(record, current_time)
                if lease_repaired is not None:
                    self._set(lease_repaired)
                    record = lease_repaired
                if _terminating_finalization_due(record, current_time):
                    finalized = _finalized_record(
                        record,
                        finalized_at=current_time,
                        final_ttl_seconds=TERMINAL_FINAL_TTL_SECONDS,
                        exit_code=None,
                    )
                    self._remove_active_indexes(record)
                    self._session_latest_final[record.admission.session_id] = (
                        terminal_id
                    )
                    self._set(finalized)
                    continue
                reason = _expired_reason(record, current_time)
                if reason is None:
                    continue
                self._set(
                    _termination_transition(
                        record,
                        reason=reason,
                        requested_at=current_time,
                    )
                )
                affected.append(terminal_id)
            return RuntimeTerminalInvalidationResult(tuple(affected))

    async def wait_for_change(
        self,
        terminal_id: str,
        *,
        after_revision: int,
        timeout_seconds: float,
    ) -> RuntimeTerminalRecord | None:
        """Wait for a newer revision or return current state after timeout."""
        if timeout_seconds < 0:
            raise ValueError("timeout_seconds must not be negative")
        async with self._condition:
            current = self._terminals.get(terminal_id)
            if current is None or current.revision > after_revision:
                return current
            try:
                async with asyncio.timeout(timeout_seconds):
                    while True:
                        await self._condition.wait()
                        current = self._terminals.get(terminal_id)
                        if current is None or current.revision > after_revision:
                            return current
            except TimeoutError:
                return self._terminals.get(terminal_id)

    def _set(self, record: RuntimeTerminalRecord) -> None:
        self._terminals[record.admission.terminal_id] = record
        self._notify()

    def _notify(self) -> None:
        self._condition.notify_all()

    def _add_indexes(self, record: RuntimeTerminalRecord) -> None:
        admission = record.admission
        self._session_active[admission.session_id] = admission.terminal_id
        self._user_active.setdefault(admission.user_id, set()).add(
            admission.terminal_id
        )
        self._runtime_active.setdefault(admission.runtime_id, set()).add(
            admission.terminal_id
        )
        for source, source_id in _record_sources(record):
            self._source_indexes.setdefault((source, source_id), set()).add(
                admission.terminal_id
            )

    def _remove_active_indexes(self, record: RuntimeTerminalRecord) -> None:
        admission = record.admission
        if self._session_active.get(admission.session_id) == admission.terminal_id:
            self._session_active.pop(admission.session_id, None)
        _discard(self._user_active, admission.user_id, admission.terminal_id)
        _discard(self._runtime_active, admission.runtime_id, admission.terminal_id)
        for source, source_id in _record_sources(record):
            _discard(self._source_indexes, (source, source_id), admission.terminal_id)

    def _purge_expired(self, current_time: datetime) -> None:
        expired = [
            record
            for record in self._terminals.values()
            if record.expires_at <= current_time
        ]
        for record in expired:
            self._terminals.pop(record.admission.terminal_id, None)
            self._remove_active_indexes(record)
            if (
                self._session_latest_final.get(record.admission.session_id)
                == record.admission.terminal_id
            ):
                self._session_latest_final.pop(record.admission.session_id, None)
        expired_tickets = [
            ticket_id
            for ticket_id, ticket in self._tickets.items()
            if ticket.expires_at <= current_time
        ]
        for ticket_id in expired_tickets:
            self._tickets.pop(ticket_id, None)


def _result[ValueT](
    status: RuntimeTerminalMutationStatus,
    value: ValueT | None = None,
) -> RuntimeTerminalMutationResult[ValueT]:
    return RuntimeTerminalMutationResult(status=status, value=value)


def _updated(
    record: RuntimeTerminalRecord,
    updated_at: datetime,
    **changes: object,
) -> RuntimeTerminalRecord:
    _require_aware(updated_at)
    return dataclasses.replace(
        record,
        revision=record.revision + 1,
        updated_at=updated_at,
        **changes,
    )


def _termination_transition(
    record: RuntimeTerminalRecord,
    *,
    reason: RunnerTerminalTerminationReason,
    requested_at: datetime,
) -> RuntimeTerminalRecord:
    return _updated(
        record,
        requested_at,
        lifecycle=RuntimeTerminalLifecycle.TERMINATING,
        termination_reason=reason,
        attachment=None,
        runner_stream_grace_expires_at=(
            record.runner_stream_grace_expires_at
            if record.runner_stream is not None
            or record.runner_stream_grace_expires_at is not None
            else requested_at + timedelta(seconds=TERMINAL_RUNNER_GRACE_SECONDS)
        ),
    )


def _active_status(
    record: RuntimeTerminalRecord | None,
) -> RuntimeTerminalMutationStatus:
    if record is None:
        return RuntimeTerminalMutationStatus.NOT_FOUND
    if record.lifecycle is RuntimeTerminalLifecycle.EXITED:
        return RuntimeTerminalMutationStatus.TERMINAL_FINAL
    if record.lifecycle is RuntimeTerminalLifecycle.TERMINATING:
        return RuntimeTerminalMutationStatus.STALE_LIFECYCLE
    return RuntimeTerminalMutationStatus.APPLIED


def _runner_registration_status(
    record: RuntimeTerminalRecord | None,
) -> RuntimeTerminalMutationStatus:
    if record is None:
        return RuntimeTerminalMutationStatus.NOT_FOUND
    if record.lifecycle is RuntimeTerminalLifecycle.EXITED:
        return RuntimeTerminalMutationStatus.TERMINAL_FINAL
    return RuntimeTerminalMutationStatus.APPLIED


def _attachment_status(
    record: RuntimeTerminalRecord | None,
    generation: int,
    current_time: datetime,
) -> RuntimeTerminalMutationStatus:
    status = _active_status(record)
    if status is not RuntimeTerminalMutationStatus.APPLIED:
        return status
    assert record is not None
    attachment = record.attachment
    if (
        attachment is None
        or attachment.generation != generation
        or attachment.lease_expires_at <= current_time
    ):
        return RuntimeTerminalMutationStatus.STALE_ATTACHMENT_GENERATION
    return RuntimeTerminalMutationStatus.APPLIED


def _runner_stream_status(
    record: RuntimeTerminalRecord | None,
    generation: int,
    current_time: datetime,
) -> RuntimeTerminalMutationStatus:
    status = _active_status(record)
    if status is not RuntimeTerminalMutationStatus.APPLIED:
        return status
    assert record is not None
    stream = record.runner_stream
    if (
        stream is None
        or stream.generation != generation
        or stream.lease_expires_at <= current_time
    ):
        return RuntimeTerminalMutationStatus.STALE_RUNNER_STREAM_GENERATION
    return RuntimeTerminalMutationStatus.APPLIED


def _runner_stream_detach_status(
    record: RuntimeTerminalRecord | None,
    generation: int,
    current_time: datetime,
) -> RuntimeTerminalMutationStatus:
    if record is None:
        return RuntimeTerminalMutationStatus.NOT_FOUND
    if record.lifecycle is RuntimeTerminalLifecycle.EXITED:
        return RuntimeTerminalMutationStatus.TERMINAL_FINAL
    stream = record.runner_stream
    if (
        stream is None
        or stream.generation != generation
        or stream.lease_expires_at <= current_time
    ):
        return RuntimeTerminalMutationStatus.STALE_RUNNER_STREAM_GENERATION
    return RuntimeTerminalMutationStatus.APPLIED


def _apply_runner_input_evidence(
    record: RuntimeTerminalRecord,
    registration: RunnerTerminalStreamRegistration,
) -> RuntimeTerminalRecord | None:
    highest = registration.highest_completely_applied_input_sequence
    if (
        highest < record.highest_input_acknowledged_sequence
        or highest > record.highest_input_sequence
        or registration.last_control_acknowledged_output_sequence
        > record.highest_output_sequence
    ):
        return None
    partial = registration.partial_input_sequence
    if partial is not None and not any(
        item.sequence == partial for item in record.pending_inputs
    ):
        return None
    remaining = tuple(item for item in record.pending_inputs if item.sequence > highest)
    return dataclasses.replace(
        record,
        pending_inputs=remaining,
        pending_input_bytes=sum(len(item.data) for item in remaining),
        highest_input_acknowledged_sequence=highest,
    )


def _append_replay(
    record: RuntimeTerminalRecord,
    item: RuntimeTerminalOutput,
) -> tuple[tuple[RuntimeTerminalOutput, ...], int, bool]:
    replay = [*record.replay_outputs, item]
    size = record.replay_output_bytes + len(item.data)
    truncated = False
    while len(replay) > MAX_REPLAY_CHUNKS or size > MAX_REPLAY_BYTES:
        removed = replay.pop(0)
        size -= len(removed.data)
        truncated = True
    return tuple(replay), size, truncated


def _bounded_chunks[ChunkT: (RuntimeTerminalInput, RuntimeTerminalOutput)](
    chunks: Iterable[ChunkT],
    maximum_bytes: int,
) -> tuple[ChunkT, ...]:
    selected: list[ChunkT] = []
    size = 0
    for chunk in chunks:
        if size + len(chunk.data) > maximum_bytes:
            break
        selected.append(chunk)
        size += len(chunk.data)
    return tuple(selected)


def _record_sources(
    record: RuntimeTerminalRecord,
) -> tuple[tuple[RuntimeTerminalInvalidationSource, str], ...]:
    admission = record.admission
    return (
        (RuntimeTerminalInvalidationSource.AGENT, admission.agent_id),
        (RuntimeTerminalInvalidationSource.RUNTIME, admission.runtime_id),
        (
            RuntimeTerminalInvalidationSource.PROVIDER_PROFILE,
            admission.provider_profile_id,
        ),
        (
            RuntimeTerminalInvalidationSource.WORKSPACE_PROFILE,
            admission.workspace_profile_id,
        ),
        (RuntimeTerminalInvalidationSource.USER, admission.user_id),
        (RuntimeTerminalInvalidationSource.SESSION, admission.session_id),
        (
            RuntimeTerminalInvalidationSource.ACCESS,
            admission.authentication_session_id,
        ),
    )


def _repair_expired_leases(
    record: RuntimeTerminalRecord,
    current_time: datetime,
) -> RuntimeTerminalRecord | None:
    attachment_expired = (
        record.attachment is not None
        and record.attachment.lease_expires_at <= current_time
    )
    runner_stream_expired = (
        record.runner_stream is not None
        and record.runner_stream.lease_expires_at <= current_time
    )
    if not attachment_expired and not runner_stream_expired:
        return None
    lifecycle = record.lifecycle
    if attachment_expired and lifecycle is not RuntimeTerminalLifecycle.TERMINATING:
        lifecycle = RuntimeTerminalLifecycle.DETACHED
    return _updated(
        record,
        current_time,
        lifecycle=lifecycle,
        attachment=None if attachment_expired else record.attachment,
        browser_grace_expires_at=(
            current_time + timedelta(seconds=TERMINAL_BROWSER_GRACE_SECONDS)
            if attachment_expired
            else record.browser_grace_expires_at
        ),
        runner_stream=(None if runner_stream_expired else record.runner_stream),
        runner_stream_grace_expires_at=(
            current_time + timedelta(seconds=TERMINAL_RUNNER_GRACE_SECONDS)
            if runner_stream_expired
            else record.runner_stream_grace_expires_at
        ),
    )


def _terminating_finalization_due(
    record: RuntimeTerminalRecord,
    current_time: datetime,
) -> bool:
    return (
        record.lifecycle is RuntimeTerminalLifecycle.TERMINATING
        and record.runner_stream is None
        and record.runner_stream_grace_expires_at is not None
        and record.runner_stream_grace_expires_at <= current_time
    )


def _finalized_record(
    record: RuntimeTerminalRecord,
    *,
    finalized_at: datetime,
    final_ttl_seconds: int,
    exit_code: int | None,
) -> RuntimeTerminalRecord:
    return _updated(
        record,
        finalized_at,
        lifecycle=RuntimeTerminalLifecycle.EXITED,
        attachment=None,
        runner_stream=None,
        pending_inputs=(),
        pending_input_bytes=0,
        live_outputs=(),
        live_output_bytes=0,
        replay_outputs=(),
        replay_output_bytes=0,
        latest_resize=None,
        runner_stream_grace_expires_at=None,
        exit_code=exit_code,
        finalized_at=finalized_at,
        expires_at=finalized_at + timedelta(seconds=final_ttl_seconds),
    )


def _expired_reason(
    record: RuntimeTerminalRecord,
    current_time: datetime,
) -> RunnerTerminalTerminationReason | None:
    if record.lifecycle in {
        RuntimeTerminalLifecycle.TERMINATING,
        RuntimeTerminalLifecycle.EXITED,
    }:
        return None
    if current_time >= record.admission.authentication_session_expires_at:
        return RunnerTerminalTerminationReason.ACCESS_REVOKED
    if current_time >= record.admission.maximum_deadline_at:
        return RunnerTerminalTerminationReason.MAXIMUM_LIFETIME
    idle_deadline = (
        record.admission.idle_deadline_at
        if record.input_bytes == 0 and record.output_bytes == 0
        else record.last_activity_at + timedelta(seconds=TERMINAL_IDLE_SECONDS)
    )
    if current_time >= idle_deadline:
        return RunnerTerminalTerminationReason.IDLE
    if record.runner_stream is None and (
        (
            not record.runner_stream_connected_once
            and current_time >= record.admission.data_stream_grace_deadline_at
        )
        or (
            record.runner_stream_grace_expires_at is not None
            and current_time >= record.runner_stream_grace_expires_at
        )
    ):
        return RunnerTerminalTerminationReason.DATA_STREAM_GRACE_EXPIRED
    if (
        record.attachment is None
        and record.browser_grace_expires_at is not None
        and current_time >= record.browser_grace_expires_at
    ):
        return RunnerTerminalTerminationReason.DATA_STREAM_GRACE_EXPIRED
    return None


def _finalization_authorized(
    record: RuntimeTerminalRecord,
    *,
    runner_stream_generation: int | None,
    finalized_at: datetime,
) -> bool:
    if runner_stream_generation is not None:
        return (
            record.runner_stream is not None
            and record.runner_stream.generation == runner_stream_generation
        )
    return (
        record.lifecycle is RuntimeTerminalLifecycle.TERMINATING
        and record.runner_stream is None
    )


def _discard[KeyT](
    mapping: dict[KeyT, set[str]],
    key: KeyT,
    terminal_id: str,
) -> None:
    values = mapping.get(key)
    if values is None:
        return
    values.discard(terminal_id)
    if not values:
        mapping.pop(key, None)


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")


def _require_lease(value: datetime, lease_seconds: int) -> None:
    _require_aware(value)
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
