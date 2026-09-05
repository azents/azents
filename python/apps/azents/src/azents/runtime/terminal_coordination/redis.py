"""Redis-backed volatile Runtime Terminal coordination."""

import base64
import dataclasses
import json
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from azents_runtime_control.runner_terminal import (
    RunnerTerminalStreamAccepted,
    RunnerTerminalStreamRegistration,
    RunnerTerminalTerminationReason,
)
from redis.asyncio import Redis

from azents.runtime.terminal_coordination.data import (
    MAX_ACTIVE_TERMINALS_PER_RUNTIME,
    MAX_ACTIVE_TERMINALS_PER_USER,
    MAX_LIVE_OUTPUT_BYTES,
    MAX_PENDING_INPUT_BYTES,
    TERMINAL_FINAL_TTL_SECONDS,
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
    RuntimeTerminalTicketIntent,
)
from azents.runtime.terminal_coordination.memory import (
    _active_status,
    _append_replay,
    _apply_runner_input_evidence,
    _attachment_status,
    _bounded_chunks,
    _expired_reason,
    _finalization_authorized,
    _record_sources,
    _repair_expired_leases,
    _runner_registration_status,
    _runner_stream_detach_status,
    _runner_stream_status,
    _terminating_finalization_due,
    _updated,
)

_CAS_SCRIPT = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return 0
end
local current = cjson.decode(raw)
if tonumber(current['revision']) ~= tonumber(ARGV[1]) then
  return -1
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', tonumber(ARGV[3]))
redis.call('XADD', KEYS[2], '*', 'terminal_id', ARGV[4], 'revision', ARGV[5])
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[6]))
return 1
"""

_ADMIT_SCRIPT = """
local existing = redis.call('GET', KEYS[2])
if existing and redis.call('EXISTS', ARGV[7] .. existing) == 0 then
  redis.call('DEL', KEYS[2])
  existing = false
end
if existing then
  return {'existing', existing}
end
if redis.call('EXISTS', KEYS[1]) == 1 then
  return {'identity_conflict'}
end
for _, key in ipairs({KEYS[3], KEYS[4]}) do
  local members = redis.call('SMEMBERS', key)
  for _, terminal_id in ipairs(members) do
    if redis.call('EXISTS', ARGV[7] .. terminal_id) == 0 then
      redis.call('SREM', key, terminal_id)
    end
  end
end
if redis.call('SCARD', KEYS[3]) >= tonumber(ARGV[3])
  or redis.call('SCARD', KEYS[4]) >= tonumber(ARGV[4]) then
  return {'quota_exceeded'}
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
redis.call('SET', KEYS[2], ARGV[5], 'EX', tonumber(ARGV[2]))
for index = 3, #KEYS - 1 do
  redis.call('SADD', KEYS[index], ARGV[5])
  redis.call('EXPIRE', KEYS[index], tonumber(ARGV[2]))
end
redis.call('XADD', KEYS[#KEYS], '*', 'terminal_id', ARGV[5], 'revision', '1')
redis.call('EXPIRE', KEYS[#KEYS], tonumber(ARGV[6]))
return {'created'}
"""

_CONSUME_TICKET_SCRIPT = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return {'missing'}
end
local ticket = cjson.decode(raw)
if ticket['binding_key'] ~= ARGV[1] then
  return {'binding_mismatch'}
end
redis.call('DEL', KEYS[1])
return {'applied', raw}
"""

_FINALIZE_SCRIPT = """
local raw = redis.call('GET', KEYS[1])
if not raw then
  return 0
end
local current = cjson.decode(raw)
if tonumber(current['revision']) ~= tonumber(ARGV[1]) then
  return -1
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', tonumber(ARGV[3]))
local session_value = redis.call('GET', KEYS[2])
if session_value == ARGV[4] then
  redis.call('DEL', KEYS[2])
end
redis.call('SET', KEYS[3], ARGV[4], 'EX', tonumber(ARGV[3]))
for index = 4, #KEYS - 1 do
  redis.call('SREM', KEYS[index], ARGV[4])
end
redis.call('XADD', KEYS[#KEYS], '*', 'terminal_id', ARGV[4], 'revision', ARGV[5])
redis.call('EXPIRE', KEYS[#KEYS], tonumber(ARGV[6]))
return 1
"""

_MAX_CAS_ATTEMPTS = 8
_NOTIFICATION_TTL_SECONDS = 9 * 60 * 60


@dataclasses.dataclass(frozen=True)
class _Mutation[ValueT]:
    status: RuntimeTerminalMutationStatus
    value: ValueT | None
    record: RuntimeTerminalRecord | None


class RedisRuntimeTerminalCoordinationStore:
    """Redis coordination with Lua-fenced record and index mutations."""

    def __init__(
        self,
        redis: Redis,
        *,
        key_prefix: str = "runtime-terminal:v1",
    ) -> None:
        """Initialize the Redis namespace."""
        self._redis = redis
        self._prefix = key_prefix.rstrip(":")

    async def admit_or_get(
        self,
        admission: RuntimeTerminalAdmission,
        *,
        admitted_at: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalRecord]:
        """Atomically create or return the Session-active Terminal."""
        _require_aware(admitted_at)
        record = _initial_record(admission, admitted_at)
        ttl = _ttl_seconds(record.expires_at, admitted_at)
        index_keys = self._index_keys(record)
        response = await self._redis.eval(
            _ADMIT_SCRIPT,
            5 + len(index_keys),
            self._record_key(admission.terminal_id),
            self._session_key(admission.session_id),
            self._user_key(admission.user_id),
            self._runtime_key(admission.runtime_id),
            *index_keys,
            self._notification_key(admission.terminal_id),
            _record_to_json(record),
            ttl,
            MAX_ACTIVE_TERMINALS_PER_USER,
            MAX_ACTIVE_TERMINALS_PER_RUNTIME,
            admission.terminal_id,
            _NOTIFICATION_TTL_SECONDS,
            f"{self._prefix}:terminal:",
        )
        values = _response_values(response)
        status = values[0]
        if status == "created":
            return _result(RuntimeTerminalMutationStatus.APPLIED, record)
        if status == "existing" and len(values) > 1:
            existing = await self.get_terminal(
                values[1],
                current_time=admitted_at,
            )
            if existing is not None:
                return _result(RuntimeTerminalMutationStatus.APPLIED, existing)
        if status == "quota_exceeded":
            return _result(RuntimeTerminalMutationStatus.QUOTA_EXCEEDED)
        return _result(RuntimeTerminalMutationStatus.STALE_RUNTIME_AUTHORITY)

    async def get_terminal(
        self,
        terminal_id: str,
        *,
        current_time: datetime,
    ) -> RuntimeTerminalRecord | None:
        """Return current non-expired Terminal metadata."""
        _require_aware(current_time)
        raw = await self._redis.get(self._record_key(terminal_id))
        if raw is None:
            return None
        record = _record_from_json(_text(raw))
        if record.expires_at <= current_time:
            return None
        return record

    async def get_session_terminal(
        self,
        session_id: str,
        *,
        current_time: datetime,
    ) -> RuntimeTerminalRecord | None:
        """Return the active singleton or latest non-expired final Terminal."""
        _require_aware(current_time)
        terminal_id = await self._redis.get(self._session_key(session_id))
        if terminal_id is not None and not await self._redis.exists(
            self._record_key(_text(terminal_id))
        ):
            await self._redis.delete(self._session_key(session_id))
            terminal_id = None
        if terminal_id is None:
            terminal_id = await self._redis.get(self._session_final_key(session_id))
        if terminal_id is not None and not await self._redis.exists(
            self._record_key(_text(terminal_id))
        ):
            await self._redis.delete(self._session_final_key(session_id))
            terminal_id = None
        if terminal_id is None:
            return None
        return await self.get_terminal(_text(terminal_id), current_time=current_time)

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
        await self._redis.set(
            self._ticket_key(ticket.ticket_id),
            _ticket_to_json(ticket),
            ex=ttl_seconds,
        )

    async def consume_ticket(
        self,
        ticket_id: str,
        *,
        expected_binding: RuntimeTerminalTicketBinding,
        consumed_at: datetime,
    ) -> RuntimeTerminalMutationResult[RuntimeTerminalTicket]:
        """Atomically consume one exact unexpired ticket."""
        _require_aware(consumed_at)
        response = await self._redis.eval(
            _CONSUME_TICKET_SCRIPT,
            1,
            self._ticket_key(ticket_id),
            _binding_key(expected_binding),
        )
        values = _response_values(response)
        if values[0] == "missing":
            return _result(RuntimeTerminalMutationStatus.TICKET_MISSING)
        if values[0] == "binding_mismatch":
            return _result(RuntimeTerminalMutationStatus.TICKET_BINDING_MISMATCH)
        ticket = _ticket_from_json(values[1])
        if ticket.expires_at <= consumed_at:
            return _result(RuntimeTerminalMutationStatus.TICKET_EXPIRED)
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

        def transform(
            record: RuntimeTerminalRecord,
        ) -> _Mutation[RuntimeTerminalAttachment]:
            status = _active_status(record)
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _Mutation(status, None, None)
            if record.admission.user_id != user_id:
                return _Mutation(
                    RuntimeTerminalMutationStatus.STALE_RUNTIME_AUTHORITY,
                    None,
                    None,
                )
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
            return _Mutation(
                RuntimeTerminalMutationStatus.APPLIED,
                attachment,
                _updated(
                    record,
                    attached_at,
                    attachment=attachment,
                    lifecycle=RuntimeTerminalLifecycle.ATTACHED,
                    browser_grace_expires_at=None,
                ),
            )

        return await self._mutate(terminal_id, attached_at, transform)

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

        def transform(
            record: RuntimeTerminalRecord,
        ) -> _Mutation[RuntimeTerminalAttachment]:
            status = _attachment_status(
                record,
                attachment_generation,
                heartbeat_at,
            )
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _Mutation(status, None, None)
            assert record.attachment is not None
            attachment = dataclasses.replace(
                record.attachment,
                heartbeat_at=heartbeat_at,
                lease_expires_at=heartbeat_at + timedelta(seconds=lease_seconds),
            )
            return _Mutation(
                RuntimeTerminalMutationStatus.APPLIED,
                attachment,
                _updated(record, heartbeat_at, attachment=attachment),
            )

        return await self._mutate(terminal_id, heartbeat_at, transform)

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

        def transform(
            record: RuntimeTerminalRecord,
        ) -> _Mutation[RuntimeTerminalRecord]:
            status = _attachment_status(
                record,
                attachment_generation,
                detached_at,
            )
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _Mutation(status, None, None)
            updated = _updated(
                record,
                detached_at,
                attachment=None,
                lifecycle=RuntimeTerminalLifecycle.DETACHED,
                browser_grace_expires_at=detached_at + timedelta(seconds=grace_seconds),
            )
            return _Mutation(RuntimeTerminalMutationStatus.APPLIED, updated, updated)

        return await self._mutate(terminal_id, detached_at, transform)

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
        terminal_id = registration.identity.terminal_id

        def transform(
            record: RuntimeTerminalRecord,
        ) -> _Mutation[RuntimeTerminalRunnerStreamAdmission]:
            status = _runner_registration_status(record)
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _Mutation(status, None, None)
            admission = record.admission
            if (
                registration.identity.runtime_id != admission.runtime_id
                or registration.identity.runner_generation
                != admission.runner_generation
                or desired_generation != admission.desired_generation
                or registration.stream_nonce != admission.stream_nonce
            ):
                return _Mutation(
                    RuntimeTerminalMutationStatus.STALE_RUNTIME_AUTHORITY,
                    None,
                    None,
                )
            if (
                record.runner_stream is not None
                and registration.stream_generation <= record.runner_stream.generation
            ):
                return _Mutation(
                    RuntimeTerminalMutationStatus.STALE_RUNNER_STREAM_GENERATION,
                    None,
                    None,
                )
            evidence = _apply_runner_input_evidence(record, registration)
            if evidence is None:
                return _Mutation(
                    RuntimeTerminalMutationStatus.SEQUENCE_REJECTED,
                    None,
                    None,
                )
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
            value = RuntimeTerminalRunnerStreamAdmission(
                record=updated,
                accepted=accepted,
            )
            return _Mutation(RuntimeTerminalMutationStatus.APPLIED, value, updated)

        return await self._mutate(terminal_id, connected_at, transform)

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

        def transform(
            record: RuntimeTerminalRecord,
        ) -> _Mutation[RuntimeTerminalRunnerStream]:
            status = _runner_stream_status(
                record,
                runner_stream_generation,
                heartbeat_at,
            )
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _Mutation(status, None, None)
            assert record.runner_stream is not None
            stream = dataclasses.replace(
                record.runner_stream,
                heartbeat_at=heartbeat_at,
                lease_expires_at=heartbeat_at + timedelta(seconds=lease_seconds),
            )
            return _Mutation(
                RuntimeTerminalMutationStatus.APPLIED,
                stream,
                _updated(record, heartbeat_at, runner_stream=stream),
            )

        return await self._mutate(terminal_id, heartbeat_at, transform)

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

        def transform(
            record: RuntimeTerminalRecord,
        ) -> _Mutation[RuntimeTerminalRecord]:
            status = _runner_stream_detach_status(
                record,
                runner_stream_generation,
                detached_at,
            )
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _Mutation(status, None, None)
            updated = _updated(
                record,
                detached_at,
                runner_stream=None,
                runner_stream_grace_expires_at=detached_at
                + timedelta(seconds=grace_seconds),
            )
            return _Mutation(RuntimeTerminalMutationStatus.APPLIED, updated, updated)

        return await self._mutate(terminal_id, detached_at, transform)

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

        def transform(
            record: RuntimeTerminalRecord,
        ) -> _Mutation[RuntimeTerminalRecord]:
            status = _attachment_status(record, attachment_generation, accepted_at)
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _Mutation(status, None, None)
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
                    return _Mutation(
                        RuntimeTerminalMutationStatus.APPLIED,
                        record,
                        None,
                    )
                return _Mutation(
                    RuntimeTerminalMutationStatus.SEQUENCE_REJECTED,
                    None,
                    None,
                )
            if sequence != record.highest_input_sequence + 1:
                return _Mutation(
                    RuntimeTerminalMutationStatus.SEQUENCE_REJECTED,
                    None,
                    None,
                )
            if record.pending_input_bytes + len(data) > MAX_PENDING_INPUT_BYTES:
                return _Mutation(
                    RuntimeTerminalMutationStatus.CAPACITY_EXCEEDED,
                    None,
                    None,
                )
            updated = _updated(
                record,
                accepted_at,
                pending_inputs=(*record.pending_inputs, item),
                pending_input_bytes=record.pending_input_bytes + len(data),
                highest_input_sequence=sequence,
                input_bytes=record.input_bytes + len(data),
                last_activity_at=accepted_at,
            )
            return _Mutation(RuntimeTerminalMutationStatus.APPLIED, updated, updated)

        return await self._mutate(terminal_id, accepted_at, transform)

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
        record = await self.get_terminal(terminal_id, current_time=current_time)
        status = _runner_stream_status(
            record,
            runner_stream_generation,
            current_time,
        )
        if status is not RuntimeTerminalMutationStatus.APPLIED:
            return _result(status)
        assert record is not None
        inputs = _bounded_chunks(
            (item for item in record.pending_inputs if item.sequence > after_sequence),
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

        def transform(
            record: RuntimeTerminalRecord,
        ) -> _Mutation[RuntimeTerminalRecord]:
            status = _runner_stream_status(
                record,
                runner_stream_generation,
                acknowledged_at,
            )
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _Mutation(status, None, None)
            if (
                sequence < record.highest_input_acknowledged_sequence
                or sequence > record.highest_input_sequence
            ):
                return _Mutation(
                    RuntimeTerminalMutationStatus.SEQUENCE_REJECTED,
                    None,
                    None,
                )
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
            return _Mutation(RuntimeTerminalMutationStatus.APPLIED, updated, updated)

        return await self._mutate(terminal_id, acknowledged_at, transform)

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

        def transform(
            record: RuntimeTerminalRecord,
        ) -> _Mutation[RuntimeTerminalResize]:
            status = _attachment_status(record, attachment_generation, updated_at)
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _Mutation(status, None, None)
            resize = RuntimeTerminalResize(
                sequence=(
                    1
                    if record.latest_resize is None
                    else record.latest_resize.sequence + 1
                ),
                columns=columns,
                rows=rows,
            )
            return _Mutation(
                RuntimeTerminalMutationStatus.APPLIED,
                resize,
                _updated(record, updated_at, latest_resize=resize),
            )

        return await self._mutate(terminal_id, updated_at, transform)

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

        def transform(
            record: RuntimeTerminalRecord,
        ) -> _Mutation[RuntimeTerminalRecord]:
            status = _runner_stream_status(
                record,
                runner_stream_generation,
                accepted_at,
            )
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _Mutation(status, None, None)
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
                    return _Mutation(
                        RuntimeTerminalMutationStatus.APPLIED,
                        record,
                        None,
                    )
                return _Mutation(
                    RuntimeTerminalMutationStatus.SEQUENCE_REJECTED,
                    None,
                    None,
                )
            if sequence != record.highest_output_sequence + 1:
                return _Mutation(
                    RuntimeTerminalMutationStatus.SEQUENCE_REJECTED,
                    None,
                    None,
                )
            if record.live_output_bytes + len(data) > MAX_LIVE_OUTPUT_BYTES:
                return _Mutation(
                    RuntimeTerminalMutationStatus.CAPACITY_EXCEEDED,
                    None,
                    None,
                )
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
            return _Mutation(RuntimeTerminalMutationStatus.APPLIED, updated, updated)

        return await self._mutate(terminal_id, accepted_at, transform)

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
        record = await self.get_terminal(terminal_id, current_time=current_time)
        status = _attachment_status(record, attachment_generation, current_time)
        if status is not RuntimeTerminalMutationStatus.APPLIED:
            return _result(status)
        assert record is not None
        outputs = _bounded_chunks(
            (item for item in record.live_outputs if item.sequence > after_sequence),
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

        def transform(
            record: RuntimeTerminalRecord,
        ) -> _Mutation[RuntimeTerminalRecord]:
            status = _attachment_status(
                record,
                attachment_generation,
                acknowledged_at,
            )
            if status is not RuntimeTerminalMutationStatus.APPLIED:
                return _Mutation(status, None, None)
            if (
                sequence < record.browser_output_acknowledged_sequence
                or sequence > record.highest_output_sequence
            ):
                return _Mutation(
                    RuntimeTerminalMutationStatus.SEQUENCE_REJECTED,
                    None,
                    None,
                )
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
            return _Mutation(RuntimeTerminalMutationStatus.APPLIED, updated, updated)

        return await self._mutate(terminal_id, acknowledged_at, transform)

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
        record = await self.get_terminal(terminal_id, current_time=current_time)
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
            (item for item in record.replay_outputs if item.sequence > after_sequence),
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

        def transform(
            record: RuntimeTerminalRecord,
        ) -> _Mutation[RuntimeTerminalRecord]:
            if record.lifecycle is RuntimeTerminalLifecycle.EXITED:
                return _Mutation(
                    RuntimeTerminalMutationStatus.TERMINAL_FINAL,
                    record,
                    None,
                )
            if record.lifecycle is RuntimeTerminalLifecycle.TERMINATING:
                return _Mutation(
                    RuntimeTerminalMutationStatus.APPLIED,
                    record,
                    None,
                )
            updated = _updated(
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
            return _Mutation(RuntimeTerminalMutationStatus.APPLIED, updated, updated)

        return await self._mutate(terminal_id, requested_at, transform)

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
        for _ in range(_MAX_CAS_ATTEMPTS):
            record = await self.get_terminal(terminal_id, current_time=finalized_at)
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
            keys = (
                self._record_key(terminal_id),
                self._session_key(record.admission.session_id),
                self._session_final_key(record.admission.session_id),
                self._user_key(record.admission.user_id),
                self._runtime_key(record.admission.runtime_id),
                *self._index_keys(record),
                self._notification_key(terminal_id),
            )
            result = await self._redis.eval(
                _FINALIZE_SCRIPT,
                len(keys),
                *keys,
                record.revision,
                _record_to_json(updated),
                final_ttl_seconds,
                terminal_id,
                updated.revision,
                _NOTIFICATION_TTL_SECONDS,
            )
            if int(result) == 1:
                return _result(RuntimeTerminalMutationStatus.APPLIED, updated)
            if int(result) == 0:
                return _result(RuntimeTerminalMutationStatus.NOT_FOUND)
        raise RuntimeError("Terminal finalization CAS capacity exhausted")

    async def invalidate(
        self,
        *,
        source: RuntimeTerminalInvalidationSource,
        source_id: str,
        reason: RunnerTerminalTerminationReason,
        invalidated_at: datetime,
    ) -> RuntimeTerminalInvalidationResult:
        """Request termination for every Terminal indexed by one source."""
        members = await self._redis.smembers(self._source_key(source, source_id))
        affected: list[str] = []
        for member in sorted(_text(value) for value in members):
            result = await self.request_termination(
                member,
                reason=reason,
                requested_at=invalidated_at,
            )
            if (
                result.status is RuntimeTerminalMutationStatus.APPLIED
                and result.value is not None
                and result.value.lifecycle is RuntimeTerminalLifecycle.TERMINATING
            ):
                affected.append(member)
            elif result.status is RuntimeTerminalMutationStatus.NOT_FOUND:
                await self._redis.srem(self._source_key(source, source_id), member)
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
        pattern = f"{self._prefix}:terminal:*"
        affected: list[str] = []
        async for raw_key in self._redis.scan_iter(match=pattern, count=limit):
            if len(affected) >= limit:
                break
            terminal_id = _text(raw_key).removeprefix(f"{self._prefix}:terminal:")
            record = await self.get_terminal(terminal_id, current_time=current_time)
            if record is None:
                continue
            lease_repaired = _repair_expired_leases(record, current_time)
            if lease_repaired is not None:
                result = await self._mutate(
                    terminal_id,
                    current_time,
                    lambda current: _Mutation(
                        RuntimeTerminalMutationStatus.APPLIED,
                        _repair_expired_leases(current, current_time) or current,
                        _repair_expired_leases(current, current_time),
                    ),
                )
                if result.value is None:
                    continue
                record = result.value
            if _terminating_finalization_due(record, current_time):
                await self.finalize_terminal(
                    terminal_id,
                    runner_stream_generation=None,
                    reason=(
                        record.termination_reason
                        or RunnerTerminalTerminationReason.RUNTIME_INVALIDATED
                    ),
                    exit_code=None,
                    finalized_at=current_time,
                    final_ttl_seconds=TERMINAL_FINAL_TTL_SECONDS,
                )
                continue
            reason = _expired_reason(record, current_time)
            if reason is None:
                continue
            result = await self.request_termination(
                terminal_id,
                reason=reason,
                requested_at=current_time,
            )
            if result.status is RuntimeTerminalMutationStatus.APPLIED:
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
        current_time = _utc_from_redis_time(await self._redis.time())
        current = await self.get_terminal(terminal_id, current_time=current_time)
        if current is None or current.revision > after_revision:
            return current
        stream_key = self._notification_key(terminal_id)
        latest = await self._redis.xrevrange(stream_key, count=1)
        cursor = _text(latest[0][0]) if latest else "0-0"
        current_time = _utc_from_redis_time(await self._redis.time())
        current = await self.get_terminal(terminal_id, current_time=current_time)
        if current is None or current.revision > after_revision:
            return current
        block_ms = max(0, math.ceil(timeout_seconds * 1000))
        if block_ms > 0:
            await self._redis.xread({stream_key: cursor}, block=block_ms, count=1)
        current_time = _utc_from_redis_time(await self._redis.time())
        return await self.get_terminal(terminal_id, current_time=current_time)

    async def _mutate[ValueT](
        self,
        terminal_id: str,
        current_time: datetime,
        transform: Callable[[RuntimeTerminalRecord], _Mutation[ValueT]],
    ) -> RuntimeTerminalMutationResult[ValueT]:
        _require_aware(current_time)
        for _ in range(_MAX_CAS_ATTEMPTS):
            record = await self.get_terminal(terminal_id, current_time=current_time)
            if record is None:
                return _result(RuntimeTerminalMutationStatus.NOT_FOUND)
            mutation = transform(record)
            if mutation.record is None:
                return _result(mutation.status, mutation.value)
            ttl = _ttl_seconds(mutation.record.expires_at, current_time)
            result = await self._redis.eval(
                _CAS_SCRIPT,
                2,
                self._record_key(terminal_id),
                self._notification_key(terminal_id),
                record.revision,
                _record_to_json(mutation.record),
                ttl,
                terminal_id,
                mutation.record.revision,
                _NOTIFICATION_TTL_SECONDS,
            )
            if int(result) == 1:
                return _result(mutation.status, mutation.value)
            if int(result) == 0:
                return _result(RuntimeTerminalMutationStatus.NOT_FOUND)
        raise RuntimeError("Terminal mutation CAS capacity exhausted")

    def _record_key(self, terminal_id: str) -> str:
        return f"{self._prefix}:terminal:{terminal_id}"

    def _session_key(self, session_id: str) -> str:
        return f"{self._prefix}:session:{session_id}"

    def _user_key(self, user_id: str) -> str:
        return f"{self._prefix}:user:{user_id}"

    def _session_final_key(self, session_id: str) -> str:
        return f"{self._prefix}:session-final:{session_id}"

    def _runtime_key(self, runtime_id: str) -> str:
        return f"{self._prefix}:runtime:{runtime_id}"

    def _ticket_key(self, ticket_id: str) -> str:
        return f"{self._prefix}:ticket:{ticket_id}"

    def _notification_key(self, terminal_id: str) -> str:
        return f"{self._prefix}:notify:{terminal_id}"

    def _source_key(
        self,
        source: RuntimeTerminalInvalidationSource,
        source_id: str,
    ) -> str:
        return f"{self._prefix}:source:{source.value}:{source_id}"

    def _index_keys(self, record: RuntimeTerminalRecord) -> tuple[str, ...]:
        return tuple(
            self._source_key(source, source_id)
            for source, source_id in _record_sources(record)
        )


def _initial_record(
    admission: RuntimeTerminalAdmission,
    admitted_at: datetime,
) -> RuntimeTerminalRecord:
    return RuntimeTerminalRecord(
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
        expires_at=admitted_at + timedelta(seconds=admission.metadata_ttl_seconds),
        last_activity_at=admitted_at,
    )


def _record_to_json(record: RuntimeTerminalRecord) -> str:
    admission = record.admission
    payload: dict[str, Any] = {
        "admission": {
            "terminal_id": admission.terminal_id,
            "workspace_id": admission.workspace_id,
            "agent_id": admission.agent_id,
            "session_id": admission.session_id,
            "user_id": admission.user_id,
            "authentication_session_id": admission.authentication_session_id,
            "authentication_session_expires_at": _datetime_text(
                admission.authentication_session_expires_at
            ),
            "runtime_id": admission.runtime_id,
            "provider_profile_id": admission.provider_profile_id,
            "provider_profile_version": admission.provider_profile_version,
            "workspace_profile_id": admission.workspace_profile_id,
            "workspace_profile_version": admission.workspace_profile_version,
            "agent_policy_version": admission.agent_policy_version,
            "desired_generation": admission.desired_generation,
            "runner_generation": admission.runner_generation,
            "working_directory": admission.working_directory,
            "stream_nonce": admission.stream_nonce,
            "created_at": _datetime_text(admission.created_at),
            "idle_deadline_at": _datetime_text(admission.idle_deadline_at),
            "maximum_deadline_at": _datetime_text(admission.maximum_deadline_at),
            "data_stream_grace_deadline_at": _datetime_text(
                admission.data_stream_grace_deadline_at
            ),
            "metadata_ttl_seconds": admission.metadata_ttl_seconds,
        },
        "lifecycle": record.lifecycle.value,
        "revision": record.revision,
        "attachment": (
            None
            if record.attachment is None
            else {
                "generation": record.attachment.generation,
                "user_id": record.attachment.user_id,
                "attached_at": _datetime_text(record.attachment.attached_at),
                "heartbeat_at": _datetime_text(record.attachment.heartbeat_at),
                "lease_expires_at": _datetime_text(record.attachment.lease_expires_at),
            }
        ),
        "runner_stream": (
            None
            if record.runner_stream is None
            else {
                "generation": record.runner_stream.generation,
                "connected_at": _datetime_text(record.runner_stream.connected_at),
                "heartbeat_at": _datetime_text(record.runner_stream.heartbeat_at),
                "lease_expires_at": _datetime_text(
                    record.runner_stream.lease_expires_at
                ),
            }
        ),
        "runner_stream_connected_once": record.runner_stream_connected_once,
        "pending_inputs": [_chunk_to_json(item) for item in record.pending_inputs],
        "pending_input_bytes": record.pending_input_bytes,
        "highest_input_sequence": record.highest_input_sequence,
        "highest_input_acknowledged_sequence": (
            record.highest_input_acknowledged_sequence
        ),
        "live_outputs": [_chunk_to_json(item) for item in record.live_outputs],
        "live_output_bytes": record.live_output_bytes,
        "replay_outputs": [_chunk_to_json(item) for item in record.replay_outputs],
        "replay_output_bytes": record.replay_output_bytes,
        "highest_output_sequence": record.highest_output_sequence,
        "browser_output_acknowledged_sequence": (
            record.browser_output_acknowledged_sequence
        ),
        "latest_resize": (
            None
            if record.latest_resize is None
            else {
                "sequence": record.latest_resize.sequence,
                "columns": record.latest_resize.columns,
                "rows": record.latest_resize.rows,
            }
        ),
        "browser_grace_expires_at": _optional_datetime_text(
            record.browser_grace_expires_at
        ),
        "runner_stream_grace_expires_at": _optional_datetime_text(
            record.runner_stream_grace_expires_at
        ),
        "termination_reason": (
            None
            if record.termination_reason is None
            else record.termination_reason.value
        ),
        "exit_code": record.exit_code,
        "updated_at": _datetime_text(record.updated_at),
        "finalized_at": _optional_datetime_text(record.finalized_at),
        "input_bytes": record.input_bytes,
        "output_bytes": record.output_bytes,
        "replay_truncated": record.replay_truncated,
        "diagnostics": [list(item) for item in record.diagnostics],
        "expires_at": _datetime_text(record.expires_at),
        "last_activity_at": _datetime_text(record.last_activity_at),
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _record_from_json(raw: str) -> RuntimeTerminalRecord:
    value = _json_object(raw)
    admission_value = _object(value, "admission")
    attachment_value = _optional_object(value, "attachment")
    stream_value = _optional_object(value, "runner_stream")
    resize_value = _optional_object(value, "latest_resize")
    reason_value = _optional_string(value, "termination_reason")
    return RuntimeTerminalRecord(
        admission=RuntimeTerminalAdmission(
            terminal_id=_string(admission_value, "terminal_id"),
            workspace_id=_string(admission_value, "workspace_id"),
            agent_id=_string(admission_value, "agent_id"),
            session_id=_string(admission_value, "session_id"),
            user_id=_string(admission_value, "user_id"),
            authentication_session_id=_string(
                admission_value,
                "authentication_session_id",
            ),
            authentication_session_expires_at=_datetime(
                admission_value,
                "authentication_session_expires_at",
            ),
            runtime_id=_string(admission_value, "runtime_id"),
            provider_profile_id=_string(admission_value, "provider_profile_id"),
            provider_profile_version=_integer(
                admission_value,
                "provider_profile_version",
            ),
            workspace_profile_id=_string(
                admission_value,
                "workspace_profile_id",
            ),
            workspace_profile_version=_integer(
                admission_value,
                "workspace_profile_version",
            ),
            agent_policy_version=_string(
                admission_value,
                "agent_policy_version",
            ),
            desired_generation=_integer(admission_value, "desired_generation"),
            runner_generation=_integer(admission_value, "runner_generation"),
            working_directory=_string(admission_value, "working_directory"),
            stream_nonce=_string(admission_value, "stream_nonce"),
            created_at=_datetime(admission_value, "created_at"),
            idle_deadline_at=_datetime(admission_value, "idle_deadline_at"),
            maximum_deadline_at=_datetime(admission_value, "maximum_deadline_at"),
            data_stream_grace_deadline_at=_datetime(
                admission_value,
                "data_stream_grace_deadline_at",
            ),
            metadata_ttl_seconds=_integer(
                admission_value,
                "metadata_ttl_seconds",
            ),
        ),
        lifecycle=RuntimeTerminalLifecycle(_string(value, "lifecycle")),
        revision=_integer(value, "revision"),
        attachment=(
            None
            if attachment_value is None
            else RuntimeTerminalAttachment(
                generation=_integer(attachment_value, "generation"),
                user_id=_string(attachment_value, "user_id"),
                attached_at=_datetime(attachment_value, "attached_at"),
                heartbeat_at=_datetime(attachment_value, "heartbeat_at"),
                lease_expires_at=_datetime(
                    attachment_value,
                    "lease_expires_at",
                ),
            )
        ),
        runner_stream=(
            None
            if stream_value is None
            else RuntimeTerminalRunnerStream(
                generation=_integer(stream_value, "generation"),
                connected_at=_datetime(stream_value, "connected_at"),
                heartbeat_at=_datetime(stream_value, "heartbeat_at"),
                lease_expires_at=_datetime(stream_value, "lease_expires_at"),
            )
        ),
        runner_stream_connected_once=_boolean(
            value,
            "runner_stream_connected_once",
        ),
        pending_inputs=tuple(
            RuntimeTerminalInput(
                sequence=_integer(item, "sequence"),
                data=_bytes(item, "data"),
            )
            for item in _object_list(value, "pending_inputs")
        ),
        pending_input_bytes=_integer(value, "pending_input_bytes"),
        highest_input_sequence=_integer(value, "highest_input_sequence"),
        highest_input_acknowledged_sequence=_integer(
            value,
            "highest_input_acknowledged_sequence",
        ),
        live_outputs=tuple(
            RuntimeTerminalOutput(
                sequence=_integer(item, "sequence"),
                data=_bytes(item, "data"),
            )
            for item in _object_list(value, "live_outputs")
        ),
        live_output_bytes=_integer(value, "live_output_bytes"),
        replay_outputs=tuple(
            RuntimeTerminalOutput(
                sequence=_integer(item, "sequence"),
                data=_bytes(item, "data"),
            )
            for item in _object_list(value, "replay_outputs")
        ),
        replay_output_bytes=_integer(value, "replay_output_bytes"),
        highest_output_sequence=_integer(value, "highest_output_sequence"),
        browser_output_acknowledged_sequence=_integer(
            value,
            "browser_output_acknowledged_sequence",
        ),
        latest_resize=(
            None
            if resize_value is None
            else RuntimeTerminalResize(
                sequence=_integer(resize_value, "sequence"),
                columns=_integer(resize_value, "columns"),
                rows=_integer(resize_value, "rows"),
            )
        ),
        browser_grace_expires_at=_optional_datetime(
            value,
            "browser_grace_expires_at",
        ),
        runner_stream_grace_expires_at=_optional_datetime(
            value,
            "runner_stream_grace_expires_at",
        ),
        termination_reason=(
            None
            if reason_value is None
            else RunnerTerminalTerminationReason(reason_value)
        ),
        exit_code=_optional_integer(value, "exit_code"),
        updated_at=_datetime(value, "updated_at"),
        finalized_at=_optional_datetime(value, "finalized_at"),
        input_bytes=_integer(value, "input_bytes"),
        output_bytes=_integer(value, "output_bytes"),
        replay_truncated=_boolean(value, "replay_truncated"),
        diagnostics=tuple(
            (_list_string(item, 0), _list_string(item, 1))
            for item in _list_list(value, "diagnostics")
        ),
        expires_at=_datetime(value, "expires_at"),
        last_activity_at=_datetime(value, "last_activity_at"),
    )


def _ticket_to_json(ticket: RuntimeTerminalTicket) -> str:
    return json.dumps(
        {
            "ticket_id": ticket.ticket_id,
            "binding_key": _binding_key(ticket.binding),
            "binding": {
                "user_id": ticket.binding.user_id,
                "authentication_session_id": (ticket.binding.authentication_session_id),
                "workspace_id": ticket.binding.workspace_id,
                "agent_id": ticket.binding.agent_id,
                "session_id": ticket.binding.session_id,
                "intent": ticket.binding.intent.value,
            },
            "issued_at": _datetime_text(ticket.issued_at),
            "expires_at": _datetime_text(ticket.expires_at),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _ticket_from_json(raw: str) -> RuntimeTerminalTicket:
    value = _json_object(raw)
    binding = _object(value, "binding")
    return RuntimeTerminalTicket(
        ticket_id=_string(value, "ticket_id"),
        binding=RuntimeTerminalTicketBinding(
            user_id=_string(binding, "user_id"),
            authentication_session_id=_string(
                binding,
                "authentication_session_id",
            ),
            workspace_id=_string(binding, "workspace_id"),
            agent_id=_string(binding, "agent_id"),
            session_id=_string(binding, "session_id"),
            intent=RuntimeTerminalTicketIntent(_string(binding, "intent")),
        ),
        issued_at=_datetime(value, "issued_at"),
        expires_at=_datetime(value, "expires_at"),
    )


def _binding_key(binding: RuntimeTerminalTicketBinding) -> str:
    return "\0".join(
        (
            binding.user_id,
            binding.authentication_session_id,
            binding.workspace_id,
            binding.agent_id,
            binding.session_id,
            binding.intent.value,
        )
    )


def _chunk_to_json(
    chunk: RuntimeTerminalInput | RuntimeTerminalOutput,
) -> dict[str, Any]:
    return {
        "sequence": chunk.sequence,
        "data": base64.b64encode(chunk.data).decode(),
    }


def _ttl_seconds(expires_at: datetime, current_time: datetime) -> int:
    return max(1, math.ceil((expires_at - current_time).total_seconds()))


def _datetime_text(value: datetime) -> str:
    _require_aware(value)
    return value.isoformat()


def _optional_datetime_text(value: datetime | None) -> str | None:
    return None if value is None else _datetime_text(value)


def _datetime(payload: dict[str, Any], key: str) -> datetime:
    value = datetime.fromisoformat(_string(payload, key))
    _require_aware(value)
    return value


def _optional_datetime(payload: dict[str, Any], key: str) -> datetime | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a datetime string")
    parsed = datetime.fromisoformat(value)
    _require_aware(parsed)
    return parsed


def _json_object(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Redis Terminal payload must be an object")
    return value


def _object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _optional_object(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    return value


def _object_list(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{key} must be an object list")
    return value


def _list_list(payload: dict[str, Any], key: str) -> list[list[Any]]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, list) for item in value):
        raise ValueError(f"{key} must be a list list")
    return value


def _list_string(value: list[Any], index: int) -> str:
    try:
        item = value[index]
    except IndexError:
        raise ValueError("diagnostic entry is incomplete") from None
    if not isinstance(item, str):
        raise ValueError("diagnostic entry must contain strings")
    return item


def _string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _integer(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _optional_integer(payload: dict[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _boolean(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _bytes(payload: dict[str, Any], key: str) -> bytes:
    return base64.b64decode(_string(payload, key), validate=True)


def _response_values(response: object) -> list[str]:
    if not isinstance(response, list):
        raise ValueError("Redis Terminal script response must be a list")
    return [_text(value) for value in response]


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode()
    if isinstance(value, str):
        return value
    raise ValueError("Redis Terminal value must be text")


def _utc_from_redis_time(value: tuple[int, int]) -> datetime:
    seconds, microseconds = value
    return datetime.fromtimestamp(seconds + microseconds / 1_000_000, UTC)


def _result[ValueT](
    status: RuntimeTerminalMutationStatus,
    value: ValueT | None = None,
) -> RuntimeTerminalMutationResult[ValueT]:
    return RuntimeTerminalMutationResult(status=status, value=value)


def _require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")


def _require_lease(value: datetime, lease_seconds: int) -> None:
    _require_aware(value)
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")
