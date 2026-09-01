"""Volatile-coordination broker for dedicated Runner Terminal streams."""

import asyncio
import dataclasses
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import assert_never

from azents_runtime_control.runner_terminal import (
    RunnerTerminalControlFrame,
    RunnerTerminalEventFrame,
    RunnerTerminalExit,
    RunnerTerminalHeartbeat,
    RunnerTerminalHeartbeatAcknowledgement,
    RunnerTerminalInputAcknowledgement,
    RunnerTerminalInputFrame,
    RunnerTerminalOutputAcknowledgement,
    RunnerTerminalOutputFrame,
    RunnerTerminalResize,
    RunnerTerminalStreamAccepted,
    RunnerTerminalStreamError,
    RunnerTerminalStreamErrorCode,
    RunnerTerminalStreamRegistration,
    RunnerTerminalTerminate,
    RunnerTerminalTerminationReason,
)

from azents.runtime.control_protocol.grpc.runner_terminal_server import (
    RuntimeRunnerTerminalAdmissionError,
    RuntimeRunnerTerminalAuthority,
    RuntimeRunnerTerminalBroker,
    RuntimeRunnerTerminalStream,
)
from azents.runtime.terminal_coordination.data import (
    MAX_PENDING_INPUT_BYTES,
    RuntimeTerminalLifecycle,
    RuntimeTerminalMutationResult,
    RuntimeTerminalMutationStatus,
    RuntimeTerminalRecord,
    RuntimeTerminalRunnerStreamAdmission,
)
from azents.runtime.terminal_coordination.store import (
    RuntimeTerminalCoordinationStore,
)

_RUNNER_STREAM_LEASE_SECONDS = 45
_RUNNER_STREAM_GRACE_SECONDS = 120
_CHANGE_WAIT_SECONDS = 15.0
_MAX_OUTBOUND_CONTROLS = 256
_TERMINAL_OUTPUT_RATE_BYTES_PER_SECOND = 2 * 1024 * 1024
_RUNTIME_OUTPUT_RATE_BYTES_PER_SECOND = 16 * 1024 * 1024


@dataclasses.dataclass
class _RateBucket:
    tokens: float
    updated_at: float


class _OutputRateLimiter:
    """Shared token buckets for exact Terminal and Runtime output limits."""

    def __init__(self, monotonic_clock: Callable[[], float]) -> None:
        self.monotonic_clock = monotonic_clock
        self.lock = asyncio.Lock()
        self.terminal_buckets: dict[str, _RateBucket] = {}
        self.runtime_buckets: dict[str, _RateBucket] = {}

    async def throttle(
        self,
        *,
        terminal_id: str,
        runtime_id: str,
        amount: int,
    ) -> None:
        while True:
            async with self.lock:
                now = self.monotonic_clock()
                terminal = self._bucket(
                    self.terminal_buckets,
                    terminal_id,
                    rate=_TERMINAL_OUTPUT_RATE_BYTES_PER_SECOND,
                    now=now,
                )
                runtime = self._bucket(
                    self.runtime_buckets,
                    runtime_id,
                    rate=_RUNTIME_OUTPUT_RATE_BYTES_PER_SECOND,
                    now=now,
                )
                delay = max(
                    _rate_delay(
                        terminal,
                        amount=amount,
                        rate=_TERMINAL_OUTPUT_RATE_BYTES_PER_SECOND,
                    ),
                    _rate_delay(
                        runtime,
                        amount=amount,
                        rate=_RUNTIME_OUTPUT_RATE_BYTES_PER_SECOND,
                    ),
                )
                if delay <= 0:
                    terminal.tokens -= amount
                    runtime.tokens -= amount
                    return
            await asyncio.sleep(delay)

    @staticmethod
    def _bucket(
        buckets: dict[str, _RateBucket],
        key: str,
        *,
        rate: int,
        now: float,
    ) -> _RateBucket:
        bucket = buckets.get(key)
        if bucket is None:
            bucket = _RateBucket(tokens=float(rate), updated_at=now)
            buckets[key] = bucket
            return bucket
        elapsed = max(0.0, now - bucket.updated_at)
        bucket.tokens = min(float(rate), bucket.tokens + elapsed * rate)
        bucket.updated_at = now
        return bucket


def _rate_delay(bucket: _RateBucket, *, amount: int, rate: int) -> float:
    if bucket.tokens >= amount:
        return 0.0
    return (amount - bucket.tokens) / rate


class CoordinatedRuntimeRunnerTerminalBroker(RuntimeRunnerTerminalBroker):
    """Admit Runner streams against exact volatile Terminal coordination."""

    def __init__(
        self,
        *,
        store: RuntimeTerminalCoordinationStore,
        clock: Callable[[], datetime],
        monotonic_clock: Callable[[], float],
    ) -> None:
        """Initialize the coordination-backed Terminal broker."""
        self._store = store
        self._clock = clock
        self._output_rate_limiter = _OutputRateLimiter(monotonic_clock)

    async def connect(
        self,
        registration: RunnerTerminalStreamRegistration,
        *,
        authority: RuntimeRunnerTerminalAuthority,
        connected_at: datetime,
    ) -> RuntimeRunnerTerminalStream:
        """Atomically verify Terminal, desired, Runner, nonce, and stream evidence."""
        result = await self._store.register_runner_stream(
            registration,
            desired_generation=authority.desired_generation,
            connected_at=connected_at,
            lease_seconds=_RUNNER_STREAM_LEASE_SECONDS,
        )
        if (
            result.status is not RuntimeTerminalMutationStatus.APPLIED
            or result.value is None
        ):
            raise RuntimeRunnerTerminalAdmissionError(_stream_error_code(result.status))
        return CoordinatedRuntimeRunnerTerminalStream(
            store=self._store,
            registration=registration,
            admission=result.value,
            clock=self._clock,
            output_rate_limiter=self._output_rate_limiter,
        )


class CoordinatedRuntimeRunnerTerminalStream(RuntimeRunnerTerminalStream):
    """Bridge one accepted Runner stream to volatile Terminal coordination."""

    def __init__(
        self,
        *,
        store: RuntimeTerminalCoordinationStore,
        registration: RunnerTerminalStreamRegistration,
        admission: RuntimeTerminalRunnerStreamAdmission,
        clock: Callable[[], datetime],
        output_rate_limiter: _OutputRateLimiter,
    ) -> None:
        """Initialize exact stream generation and resume cursors."""
        self._store = store
        self._registration = registration
        self._accepted = admission.accepted
        self._clock = clock
        self._output_rate_limiter = output_rate_limiter
        self._record_revision = admission.record.revision
        self._last_input_sent = self._accepted.next_input_sequence - 1
        self._last_resize_sent = 0
        self._last_heartbeat_sequence = 0
        self._termination_sent = False
        self._closed = False
        self._outbound: asyncio.Queue[RunnerTerminalControlFrame] = asyncio.Queue(
            maxsize=_MAX_OUTBOUND_CONTROLS
        )

    @property
    def accepted(self) -> RunnerTerminalStreamAccepted:
        """Return exact accepted stream and resume evidence."""
        return self._accepted

    async def receive(self, frame: RunnerTerminalEventFrame) -> None:
        """Apply one Runner event through exact stream-generation fencing."""
        if self._closed:
            return
        match frame:
            case RunnerTerminalOutputFrame(sequence=sequence, data=data):
                await self._append_output(sequence=sequence, data=data)
            case RunnerTerminalInputAcknowledgement(sequence=sequence):
                result = await self._store.acknowledge_input(
                    self.terminal_id,
                    runner_stream_generation=self.stream_generation,
                    sequence=sequence,
                    acknowledged_at=self._now(),
                )
                await self._accept_or_reject(result)
            case RunnerTerminalHeartbeat(monotonic_sequence=sequence):
                if sequence <= self._last_heartbeat_sequence:
                    await self._reject(RuntimeTerminalMutationStatus.SEQUENCE_REJECTED)
                    return
                result = await self._store.heartbeat_runner_stream(
                    self.terminal_id,
                    runner_stream_generation=self.stream_generation,
                    heartbeat_at=self._now(),
                    lease_seconds=_RUNNER_STREAM_LEASE_SECONDS,
                )
                if await self._accept_or_reject(result):
                    self._last_heartbeat_sequence = sequence
                    await self._outbound.put(
                        RunnerTerminalHeartbeatAcknowledgement(
                            monotonic_sequence=sequence
                        )
                    )
            case RunnerTerminalExit(reason=reason, exit_code=exit_code):
                result = await self._store.finalize_terminal(
                    self.terminal_id,
                    runner_stream_generation=self.stream_generation,
                    reason=reason,
                    exit_code=exit_code,
                    finalized_at=self._now(),
                    final_ttl_seconds=_RUNNER_STREAM_GRACE_SECONDS,
                )
                await self._accept_or_reject(result)
                self._closed = True
            case RunnerTerminalStreamError():
                await self._store.request_termination(
                    self.terminal_id,
                    reason=RunnerTerminalTerminationReason.PROTOCOL_VIOLATION,
                    requested_at=self._now(),
                )
            case _ as unreachable:
                assert_never(unreachable)

    def control_frames(self) -> AsyncIterator[RunnerTerminalControlFrame]:
        """Yield queued acknowledgements and coordinated input/resize/termination."""
        return self._control_frames()

    async def close(self) -> None:
        """Detach only this stream generation and start the Runner grace."""
        if self._closed:
            return
        self._closed = True
        await self._store.detach_runner_stream(
            self.terminal_id,
            runner_stream_generation=self.stream_generation,
            detached_at=self._now(),
            grace_seconds=_RUNNER_STREAM_GRACE_SECONDS,
        )

    @property
    def terminal_id(self) -> str:
        """Return the coordinated Terminal identifier."""
        return self._registration.identity.terminal_id

    @property
    def stream_generation(self) -> int:
        """Return the current dedicated stream generation."""
        return self._registration.stream_generation

    async def _append_output(self, *, sequence: int, data: bytes) -> None:
        await self._output_rate_limiter.throttle(
            terminal_id=self.terminal_id,
            runtime_id=self._registration.identity.runtime_id,
            amount=len(data),
        )
        while not self._closed:
            result = await self._store.append_output(
                self.terminal_id,
                runner_stream_generation=self.stream_generation,
                sequence=sequence,
                data=data,
                accepted_at=self._now(),
            )
            if result.status is RuntimeTerminalMutationStatus.CAPACITY_EXCEEDED:
                record = await self._store.get_terminal(
                    self.terminal_id,
                    current_time=self._now(),
                )
                if record is None:
                    await self._reject(RuntimeTerminalMutationStatus.NOT_FOUND)
                    return
                self._record_revision = record.revision
                changed = await self._store.wait_for_change(
                    self.terminal_id,
                    after_revision=record.revision,
                    timeout_seconds=_CHANGE_WAIT_SECONDS,
                )
                if changed is not None:
                    self._record_revision = changed.revision
                continue
            if await self._accept_or_reject(result):
                await self._outbound.put(
                    RunnerTerminalOutputAcknowledgement(sequence=sequence)
                )
            return

    async def _control_frames(self) -> AsyncIterator[RunnerTerminalControlFrame]:
        while True:
            while not self._outbound.empty():
                yield self._outbound.get_nowait()
            if self._closed:
                return
            record = await self._store.get_terminal(
                self.terminal_id,
                current_time=self._now(),
            )
            if record is None or record.lifecycle is RuntimeTerminalLifecycle.EXITED:
                return
            self._record_revision = record.revision
            if (
                record.lifecycle is RuntimeTerminalLifecycle.TERMINATING
                and not self._termination_sent
            ):
                self._termination_sent = True
                yield RunnerTerminalTerminate(
                    reason=(
                        record.termination_reason
                        or RunnerTerminalTerminationReason.PROTOCOL_VIOLATION
                    )
                )
                continue
            if record.lifecycle is RuntimeTerminalLifecycle.TERMINATING:
                outbound = await self._wait_for_outbound_or_change()
                if outbound is not None:
                    yield outbound
                continue
            inputs = await self._store.read_inputs(
                self.terminal_id,
                runner_stream_generation=self.stream_generation,
                after_sequence=self._last_input_sent,
                maximum_bytes=MAX_PENDING_INPUT_BYTES,
                current_time=self._now(),
            )
            if not await self._accept_or_reject(inputs):
                continue
            if inputs.value is not None:
                for item in inputs.value.inputs:
                    self._last_input_sent = item.sequence
                    yield RunnerTerminalInputFrame(
                        sequence=item.sequence,
                        data=item.data,
                    )
            resize = await self._store.read_resize(
                self.terminal_id,
                runner_stream_generation=self.stream_generation,
                after_sequence=self._last_resize_sent,
                current_time=self._now(),
            )
            if not await self._accept_or_reject(resize):
                continue
            if resize.value is not None:
                self._last_resize_sent = resize.value.sequence
                yield RunnerTerminalResize(
                    sequence=resize.value.sequence,
                    columns=resize.value.columns,
                    rows=resize.value.rows,
                )
            outbound = await self._wait_for_outbound_or_change()
            if outbound is not None:
                yield outbound
            if self._closed and self._outbound.empty():
                return

    async def _wait_for_outbound_or_change(
        self,
    ) -> RunnerTerminalControlFrame | None:
        outbound_task = asyncio.create_task(self._outbound.get())
        change_task = asyncio.create_task(
            self._store.wait_for_change(
                self.terminal_id,
                after_revision=self._record_revision,
                timeout_seconds=_CHANGE_WAIT_SECONDS,
            )
        )
        done = set()
        try:
            done, _pending = await asyncio.wait(
                (outbound_task, change_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if outbound_task in done:
                return outbound_task.result()
            changed = change_task.result()
            if changed is not None:
                self._record_revision = changed.revision
            return None
        finally:
            for task in (outbound_task, change_task):
                if task not in done:
                    task.cancel()
            await asyncio.gather(
                outbound_task,
                change_task,
                return_exceptions=True,
            )

    async def _accept_or_reject[ValueT](
        self,
        result: RuntimeTerminalMutationResult[ValueT],
    ) -> bool:
        if result.status is RuntimeTerminalMutationStatus.APPLIED:
            if isinstance(result.value, RuntimeTerminalRecord):
                self._record_revision = result.value.revision
            return True
        await self._reject(result.status)
        return False

    async def _reject(self, status: RuntimeTerminalMutationStatus) -> None:
        code = _stream_error_code(status)
        if code is RunnerTerminalStreamErrorCode.PROTOCOL_VIOLATION:
            await self._store.request_termination(
                self.terminal_id,
                reason=RunnerTerminalTerminationReason.PROTOCOL_VIOLATION,
                requested_at=self._now(),
            )
        await self._outbound.put(RunnerTerminalStreamError(code=code))
        self._closed = True

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Runtime Terminal broker clock must be timezone-aware")
        return now


def _stream_error_code(
    status: RuntimeTerminalMutationStatus,
) -> RunnerTerminalStreamErrorCode:
    if status is RuntimeTerminalMutationStatus.STALE_RUNNER_STREAM_GENERATION:
        return RunnerTerminalStreamErrorCode.STALE_STREAM_GENERATION
    if status in {
        RuntimeTerminalMutationStatus.STALE_RUNTIME_AUTHORITY,
        RuntimeTerminalMutationStatus.STALE_ATTACHMENT_GENERATION,
        RuntimeTerminalMutationStatus.TICKET_BINDING_MISMATCH,
    }:
        return RunnerTerminalStreamErrorCode.STALE_AUTHORITY
    if status in {
        RuntimeTerminalMutationStatus.CAPACITY_EXCEEDED,
        RuntimeTerminalMutationStatus.QUOTA_EXCEEDED,
    }:
        return RunnerTerminalStreamErrorCode.RESOURCE_EXHAUSTED
    if status in {
        RuntimeTerminalMutationStatus.TERMINAL_FINAL,
        RuntimeTerminalMutationStatus.STALE_LIFECYCLE,
        RuntimeTerminalMutationStatus.NOT_FOUND,
    }:
        return RunnerTerminalStreamErrorCode.TERMINATED
    return RunnerTerminalStreamErrorCode.PROTOCOL_VIOLATION
