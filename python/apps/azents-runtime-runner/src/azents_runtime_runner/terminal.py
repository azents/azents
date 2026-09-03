"""Interactive Terminal PTY and Runner-local lifecycle primitives."""

import asyncio
import errno
import os
import signal
import sys
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple, Protocol

from azents_runtime_runner.terminal_launcher import set_pty_size

_TERMINAL_ENVIRONMENT = {
    "TERM": "xterm-256color",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
}
MAX_TERMINAL_CHUNK_BYTES = 16 * 1024
MAX_TERMINAL_OUTPUT_WINDOW_BYTES = 256 * 1024
TERMINATE_GRACE_SECONDS = 2.0
KILL_GRACE_SECONDS = 2.0


class TerminalError(RuntimeError):
    """Base error for Terminal lifecycle failures."""


class TerminalAdmissionError(TerminalError):
    """Terminal admission was denied by a Runner-local invariant."""


class TerminalInputSequenceError(TerminalError):
    """Terminal input sequence is not safe to apply."""


class TerminalOutputBackpressure(TerminalError):
    """Terminal output cannot be read until Control acknowledges bytes."""


class TerminalInvalidatedError(TerminalError):
    """Terminal Runtime authority no longer permits PTY I/O."""


class TerminalDeadline(StrEnum):
    """Terminal deadline outcomes owned by the Runner."""

    IDLE = "idle"
    MAXIMUM_LIFETIME = "maximum_lifetime"
    STREAM_GRACE = "stream_grace"
    STREAM_ATTEMPT = "stream_attempt"


class _ProcessGroupSession(NamedTuple):
    """Live process-group and session identifiers."""

    process_group_id: int
    session_id: int


@dataclass(frozen=True)
class TerminalLimits:
    """Bounded Runner-local Terminal limits."""

    max_active_per_session: int
    max_active_per_runtime: int
    idle_timeout_seconds: float
    maximum_lifetime_seconds: float
    stream_grace_seconds: float
    stream_attempt_timeout_seconds: float
    maximum_chunk_bytes: int
    maximum_unacknowledged_output_bytes: int


@dataclass(frozen=True)
class TerminalSpec:
    """One interactive Terminal allocation request."""

    terminal_id: str
    runtime_id: str
    session_id: str
    workspace_root: Path
    working_directory: Path
    environment: Mapping[str, str]
    columns: int
    rows: int
    idle_deadline_at: datetime
    maximum_deadline_at: datetime
    data_stream_grace_deadline_at: datetime

    def __post_init__(self) -> None:
        """Reject Terminal authority with naïve deadline evidence."""
        _require_aware_datetime(self.idle_deadline_at, "idle_deadline_at")
        _require_aware_datetime(self.maximum_deadline_at, "maximum_deadline_at")
        _require_aware_datetime(
            self.data_stream_grace_deadline_at,
            "data_stream_grace_deadline_at",
        )


@dataclass(frozen=True)
class TerminalExit:
    """Terminal process exit and bounded cleanup outcome."""

    returncode: int | None
    already_exited: bool
    escalated: bool
    timed_out: bool


@dataclass(frozen=True)
class TerminalOutput:
    """Ordered output emitted from one PTY."""

    sequence: int
    data: bytes


@dataclass(frozen=True)
class TerminalInputResult:
    """Result of accepting or deduplicating one input frame."""

    sequence: int
    applied: bool
    highest_applied_sequence: int


@dataclass(frozen=True)
class TerminalResumeState:
    """Runner evidence required to resume a Terminal data stream safely."""

    highest_applied_input_sequence: int
    partial_input_sequence: int | None
    partial_input_bytes_written: int | None
    last_output_sequence: int
    last_acknowledged_output_sequence: int


@dataclass
class _PendingInput:
    """A partially written PTY input frame."""

    sequence: int
    data: bytes
    offset: int


@dataclass(frozen=True)
class _TerminalReservation:
    """One lock-owned admission reservation before PTY allocation finishes."""

    terminal_id: str
    runtime_id: str
    session_id: str
    token: object


class PtyTerminalProcess(Protocol):
    """Operating-system-neutral interactive Terminal process boundary."""

    @property
    def returncode(self) -> int | None:
        """Return the process exit code when the Terminal is finished."""
        ...

    async def read(
        self,
        maximum_bytes: int,
        *,
        active: Callable[[], bool],
    ) -> bytes:
        """Read ordered PTY bytes."""
        ...

    async def write(
        self,
        data: bytes,
        *,
        offset: int,
        active: Callable[[], bool],
    ) -> int:
        """Write bytes beginning at offset and return bytes accepted."""
        ...

    async def resize(
        self,
        *,
        columns: int,
        rows: int,
        active: Callable[[], bool],
    ) -> None:
        """Resize the interactive terminal."""
        ...

    async def wait(self) -> int:
        """Wait for the shell process to exit."""
        ...

    async def terminate_session(
        self,
        *,
        terminate_timeout_seconds: float,
        kill_timeout_seconds: float,
    ) -> TerminalExit:
        """Terminate every process belonging to the PTY session."""
        ...

    async def close(self) -> None:
        """Close local PTY resources."""
        ...


class PtyTerminalBackend(Protocol):
    """Operating-system-neutral PTY allocation boundary."""

    async def open(self, spec: TerminalSpec) -> PtyTerminalProcess:
        """Allocate one interactive PTY terminal."""
        ...


type PtyLauncher = Callable[
    [int, Path, Mapping[str, str]],
    Awaitable[asyncio.subprocess.Process],
]


class LinuxPtyTerminalBackend:
    """Linux implementation of the operating-system-neutral PTY boundary."""

    def __init__(self, *, launcher: PtyLauncher | None = None) -> None:
        self._launcher = launcher or _launch_terminal_launcher

    async def open(self, spec: TerminalSpec) -> PtyTerminalProcess:
        workspace_root = spec.workspace_root.resolve(strict=True)
        working_directory = spec.working_directory.resolve(strict=True)
        if not working_directory.is_relative_to(workspace_root):
            raise TerminalAdmissionError(
                "Terminal working directory is outside the Agent Workspace."
            )
        if not working_directory.is_dir():
            raise TerminalAdmissionError(
                "Terminal working directory is not a directory."
            )
        if spec.columns <= 0 or spec.rows <= 0:
            raise TerminalAdmissionError("Terminal dimensions must be positive.")
        master_fd, slave_fd = os.openpty()
        try:
            os.set_blocking(master_fd, False)
            set_pty_size(fd=slave_fd, columns=spec.columns, rows=spec.rows)
            environment = dict(os.environ)
            environment.update(spec.environment)
            environment.update(_TERMINAL_ENVIRONMENT)
            process = await self._launcher(
                slave_fd,
                working_directory,
                environment,
            )
        except asyncio.CancelledError:
            os.close(master_fd)
            os.close(slave_fd)
            raise
        except Exception:
            os.close(master_fd)
            os.close(slave_fd)
            raise
        os.close(slave_fd)
        return LinuxPtyTerminalProcess(process=process, master_fd=master_fd)


async def _launch_terminal_launcher(
    slave_fd: int,
    working_directory: Path,
    environment: Mapping[str, str],
) -> asyncio.subprocess.Process:
    """Start the separate PTY launcher process without a Python preexec hook."""
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "azents_runtime_runner.terminal_launcher",
        "--slave-fd",
        str(slave_fd),
        "--working-directory",
        str(working_directory),
        env=dict(environment),
        close_fds=True,
        pass_fds=(slave_fd,),
    )


class LinuxPtyTerminalProcess:
    """One Linux PTY and its interactive shell session."""

    def __init__(
        self,
        *,
        process: asyncio.subprocess.Process,
        master_fd: int,
    ) -> None:
        self._process = process
        self._master_fd = master_fd
        self._closed = False

    @property
    def returncode(self) -> int | None:
        """Return the shell exit code when available."""
        return self._process.returncode

    async def read(
        self,
        maximum_bytes: int,
        *,
        active: Callable[[], bool],
    ) -> bytes:
        """Read at most maximum_bytes from the PTY master."""
        if maximum_bytes <= 0:
            raise ValueError("Terminal read limit must be positive.")
        if self._closed:
            return b""
        return await _wait_for_fd_read(
            fd=self._master_fd,
            maximum_bytes=maximum_bytes,
            active=active,
        )

    async def write(
        self,
        data: bytes,
        *,
        offset: int,
        active: Callable[[], bool],
    ) -> int:
        """Write one non-empty suffix to the PTY master."""
        if offset < 0 or offset >= len(data):
            raise ValueError("Terminal input offset is outside the supplied data.")
        if self._closed:
            raise TerminalError("Terminal PTY is closed.")
        while True:
            if not active():
                raise TerminalInvalidatedError("Terminal Runtime authority changed.")
            try:
                return os.write(self._master_fd, data[offset:])
            except BlockingIOError:
                await _wait_for_fd_writable(fd=self._master_fd)
            except OSError as error:
                if error.errno is errno.EIO:
                    raise TerminalError(
                        "Terminal PTY is no longer available."
                    ) from error
                raise

    async def resize(
        self,
        *,
        columns: int,
        rows: int,
        active: Callable[[], bool],
    ) -> None:
        """Apply visible Terminal dimensions."""
        if self._closed:
            raise TerminalError("Terminal PTY is closed.")
        if not active():
            raise TerminalInvalidatedError("Terminal Runtime authority changed.")
        set_pty_size(fd=self._master_fd, columns=columns, rows=rows)

    async def wait(self) -> int:
        """Wait for the login shell process."""
        return await self._process.wait()

    async def terminate_session(
        self,
        *,
        terminate_timeout_seconds: float,
        kill_timeout_seconds: float,
    ) -> TerminalExit:
        """Terminate all verified process groups in the PTY session."""
        session_id = self._process.pid
        if not _session_process_group_ids(session_id=session_id):
            return TerminalExit(
                returncode=self.returncode,
                already_exited=True,
                escalated=False,
                timed_out=False,
            )
        _signal_session_process_groups(
            session_id=session_id,
            requested_signal=signal.SIGTERM,
        )
        if await _wait_for_session_exit(
            session_id=session_id,
            timeout_seconds=terminate_timeout_seconds,
        ):
            await _reap_process(self._process)
            return TerminalExit(
                returncode=self.returncode,
                already_exited=False,
                escalated=False,
                timed_out=False,
            )
        _signal_session_process_groups(
            session_id=session_id,
            requested_signal=signal.SIGKILL,
        )
        killed = await _wait_for_session_exit(
            session_id=session_id,
            timeout_seconds=kill_timeout_seconds,
        )
        if killed:
            await _reap_process(self._process)
        return TerminalExit(
            returncode=self.returncode,
            already_exited=False,
            escalated=True,
            timed_out=not killed,
        )

    async def close(self) -> None:
        """Close the PTY master descriptor."""
        if self._closed:
            return
        self._closed = True
        os.close(self._master_fd)


class RunnerTerminal:
    """One Runner-owned Terminal with sequence, output, and deadline state."""

    def __init__(
        self,
        *,
        spec: TerminalSpec,
        process: PtyTerminalProcess,
        limits: TerminalLimits,
        clock: Callable[[], float],
        utc_clock: Callable[[], datetime],
    ) -> None:
        self.spec = spec
        self.process = process
        self._limits = limits
        self._clock = clock
        self._utc_clock = utc_clock
        now = clock()
        self._created_at = now
        self._last_activity_at = now
        self._activity_observed = False
        self._stream_established = False
        self._stream_disconnected_at: float | None = None
        self._stream_attempt_started_at: float | None = None
        self._highest_applied_input_sequence = 0
        self._pending_input: _PendingInput | None = None
        self._next_output_sequence = 1
        self._last_acknowledged_output_sequence = 0
        self._unacknowledged_output: deque[TerminalOutput] = deque()
        self._unacknowledged_output_bytes = 0
        self._closed = False
        self._invalidated = False
        self._io_generation = 0

    @property
    def terminal_id(self) -> str:
        """Return the independently addressable Terminal ID."""
        return self.spec.terminal_id

    @property
    def session_id(self) -> str:
        """Return the owning Chat Session ID."""
        return self.spec.session_id

    @property
    def runtime_id(self) -> str:
        """Return the owning Runtime ID."""
        return self.spec.runtime_id

    @property
    def returncode(self) -> int | None:
        """Return the PTY shell exit code when available."""
        return self.process.returncode

    def resume_state(self) -> TerminalResumeState:
        """Return bounded sequence evidence for a replacement data stream."""
        pending = self._pending_input
        return TerminalResumeState(
            highest_applied_input_sequence=self._highest_applied_input_sequence,
            partial_input_sequence=None if pending is None else pending.sequence,
            partial_input_bytes_written=None if pending is None else pending.offset,
            last_output_sequence=self._next_output_sequence - 1,
            last_acknowledged_output_sequence=self._last_acknowledged_output_sequence,
        )

    def invalidate(self) -> None:
        """Synchronously fence every current and later PTY I/O operation."""
        self._invalidated = True
        self._io_generation += 1

    async def apply_input(self, *, sequence: int, data: bytes) -> TerminalInputResult:
        """Apply exactly one contiguous input sequence without duplicate writes."""
        io_generation = self._current_io_generation()
        self._validate_chunk(data)
        pending = self._pending_input
        if sequence <= self._highest_applied_input_sequence:
            return TerminalInputResult(
                sequence=sequence,
                applied=False,
                highest_applied_sequence=self._highest_applied_input_sequence,
            )
        if pending is None:
            expected_sequence = self._highest_applied_input_sequence + 1
            if sequence != expected_sequence:
                raise TerminalInputSequenceError(
                    "Terminal input sequence contains a gap."
                )
            pending = _PendingInput(sequence=sequence, data=data, offset=0)
            self._pending_input = pending
        elif sequence != pending.sequence or data != pending.data:
            raise TerminalInputSequenceError(
                "Terminal input does not match the incomplete sequence."
            )

        while pending.offset < len(pending.data):
            self._require_io_generation(io_generation)
            written = await self.process.write(
                pending.data,
                offset=pending.offset,
                active=lambda: self._io_generation_current(io_generation),
            )
            self._require_io_generation(io_generation)
            if written <= 0:
                raise TerminalError("Terminal PTY accepted no input bytes.")
            pending.offset += written
        self._highest_applied_input_sequence = pending.sequence
        self._pending_input = None
        self._activity_observed = True
        self._last_activity_at = self._clock()
        return TerminalInputResult(
            sequence=sequence,
            applied=True,
            highest_applied_sequence=self._highest_applied_input_sequence,
        )

    async def read_output(self) -> TerminalOutput:
        """Read and retain one bounded output chunk for Control acknowledgement."""
        io_generation = self._current_io_generation()
        if self._unacknowledged_output_bytes >= (
            self._limits.maximum_unacknowledged_output_bytes
        ):
            raise TerminalOutputBackpressure(
                "Terminal output acknowledgement window is full."
            )
        maximum_bytes = min(
            self._limits.maximum_chunk_bytes,
            self._limits.maximum_unacknowledged_output_bytes
            - self._unacknowledged_output_bytes,
        )
        data = await self.process.read(
            maximum_bytes,
            active=lambda: self._io_generation_current(io_generation),
        )
        self._require_io_generation(io_generation)
        if not data:
            raise TerminalError("Terminal PTY reached end of output.")
        output = TerminalOutput(sequence=self._next_output_sequence, data=data)
        self._next_output_sequence += 1
        self._unacknowledged_output.append(output)
        self._unacknowledged_output_bytes += len(data)
        self._activity_observed = True
        self._last_activity_at = self._clock()
        return output

    def acknowledge_output(self, *, sequence: int) -> None:
        """Cumulatively acknowledge output retained for retransmission."""
        self._current_io_generation()
        if sequence < self._last_acknowledged_output_sequence:
            return
        if sequence >= self._next_output_sequence:
            raise TerminalInputSequenceError(
                "Terminal output acknowledgement exceeds emitted output."
            )
        while (
            self._unacknowledged_output
            and self._unacknowledged_output[0].sequence <= sequence
        ):
            output = self._unacknowledged_output.popleft()
            self._unacknowledged_output_bytes -= len(output.data)
        self._last_acknowledged_output_sequence = sequence

    def output_from(self, *, sequence: int) -> tuple[TerminalOutput, ...]:
        """Return retained unacknowledged output at or after sequence."""
        if sequence <= self._last_acknowledged_output_sequence:
            sequence = self._last_acknowledged_output_sequence + 1
        return tuple(
            output
            for output in self._unacknowledged_output
            if output.sequence >= sequence
        )

    async def resize(self, *, columns: int, rows: int) -> None:
        """Resize the PTY without changing Terminal ownership."""
        io_generation = self._current_io_generation()
        await self.process.resize(
            columns=columns,
            rows=rows,
            active=lambda: self._io_generation_current(io_generation),
        )
        self._require_io_generation(io_generation)

    def begin_stream_recovery(self) -> None:
        """Start or continue a generation-stable Terminal data-stream grace."""
        now = self._clock()
        if self._stream_disconnected_at is None:
            self._stream_disconnected_at = now
        self._stream_attempt_started_at = now

    def mark_stream_connected(self) -> None:
        """Establish the data stream and clear a current-generation recovery."""
        self._stream_established = True
        self._stream_disconnected_at = None
        self._stream_attempt_started_at = None

    def stream_grace_remaining_seconds(self) -> float | None:
        """Return the exact remaining overall data-stream grace, if active."""
        now = self._clock()
        if not self._stream_established:
            local_remaining = self._limits.stream_grace_seconds - (
                now - self._created_at
            )
            authority_remaining = (
                self.spec.data_stream_grace_deadline_at - self._utc_clock()
            ).total_seconds()
            return max(0.0, min(local_remaining, authority_remaining))
        if self._stream_disconnected_at is None:
            return None
        return max(
            0.0,
            self._limits.stream_grace_seconds - (now - self._stream_disconnected_at),
        )

    def deadline(self) -> TerminalDeadline | None:
        """Return the current bounded deadline without mutating process state."""
        now = self._clock()
        utc_now = self._utc_clock()
        if utc_now >= self.spec.maximum_deadline_at:
            return TerminalDeadline.MAXIMUM_LIFETIME
        if now - self._created_at >= self._limits.maximum_lifetime_seconds:
            return TerminalDeadline.MAXIMUM_LIFETIME
        if not self._activity_observed and utc_now >= self.spec.idle_deadline_at:
            return TerminalDeadline.IDLE
        if now - self._last_activity_at >= self._limits.idle_timeout_seconds:
            return TerminalDeadline.IDLE
        if not self._stream_established:
            if now - self._created_at >= self._limits.stream_grace_seconds:
                return TerminalDeadline.STREAM_GRACE
            if utc_now >= self.spec.data_stream_grace_deadline_at:
                return TerminalDeadline.STREAM_GRACE
        elif self._stream_disconnected_at is not None:
            if now - self._stream_disconnected_at >= self._limits.stream_grace_seconds:
                return TerminalDeadline.STREAM_GRACE
            if (
                self._stream_attempt_started_at is not None
                and now - self._stream_attempt_started_at
                >= self._limits.stream_attempt_timeout_seconds
            ):
                return TerminalDeadline.STREAM_ATTEMPT
        return None

    async def terminate(self) -> TerminalExit:
        """Terminate the complete PTY session and release local resources."""
        self.invalidate()
        if self._closed:
            return TerminalExit(
                returncode=self.returncode,
                already_exited=True,
                escalated=False,
                timed_out=False,
            )
        self._closed = True
        try:
            return await self.process.terminate_session(
                terminate_timeout_seconds=TERMINATE_GRACE_SECONDS,
                kill_timeout_seconds=KILL_GRACE_SECONDS,
            )
        finally:
            await self.process.close()

    def _validate_chunk(self, data: bytes) -> None:
        if not data:
            raise TerminalInputSequenceError("Terminal input must not be empty.")
        if len(data) > self._limits.maximum_chunk_bytes:
            raise TerminalInputSequenceError("Terminal input exceeds the chunk limit.")

    def _current_io_generation(self) -> int:
        """Return active I/O authority or reject an invalidated Terminal."""
        if self._invalidated:
            raise TerminalInvalidatedError("Terminal Runtime authority changed.")
        return self._io_generation

    def _io_generation_current(self, generation: int) -> bool:
        """Return whether a pending PTY primitive may still mutate Terminal state."""
        return not self._invalidated and self._io_generation == generation

    def _require_io_generation(self, generation: int) -> None:
        """Fail closed when authority changed while an operation awaited I/O."""
        if not self._io_generation_current(generation):
            raise TerminalInvalidatedError("Terminal Runtime authority changed.")


class RunnerTerminalRegistry:
    """Runner-local active Terminal admission and lifecycle registry."""

    def __init__(
        self,
        *,
        backend: PtyTerminalBackend,
        limits: TerminalLimits,
        clock: Callable[[], float],
        utc_clock: Callable[[], datetime],
    ) -> None:
        self._backend = backend
        self._limits = limits
        self._clock = clock
        self._utc_clock = utc_clock
        self._terminals: dict[str, RunnerTerminal] = {}
        self._reservations: dict[str, _TerminalReservation] = {}
        self._lock = asyncio.Lock()

    async def open(self, spec: TerminalSpec) -> RunnerTerminal:
        """Reserve admission, allocate outside the lock, then install if current."""
        async with self._lock:
            existing = self._terminals.get(spec.terminal_id)
            if existing is not None:
                if (
                    existing.runtime_id != spec.runtime_id
                    or existing.session_id != spec.session_id
                ):
                    raise TerminalAdmissionError(
                        "Terminal ID is already owned by another Runtime or Session."
                    )
                return existing
            if spec.terminal_id in self._reservations:
                raise TerminalAdmissionError("Terminal ID is already opening.")
            self._enforce_admission(spec)
            self._enforce_authority_deadlines(spec)
            reservation = _TerminalReservation(
                terminal_id=spec.terminal_id,
                runtime_id=spec.runtime_id,
                session_id=spec.session_id,
                token=object(),
            )
            self._reservations[spec.terminal_id] = reservation
        process: PtyTerminalProcess | None = None
        try:
            process = await self._backend.open(spec)
        except asyncio.CancelledError:
            await self._remove_reservation(reservation)
            raise
        except Exception:
            await self._remove_reservation(reservation)
            raise
        try:
            async with self._lock:
                current = self._reservations.get(spec.terminal_id)
                if current is not reservation:
                    stale = True
                else:
                    stale = False
                    self._reservations.pop(spec.terminal_id)
                    terminal = RunnerTerminal(
                        spec=spec,
                        process=process,
                        limits=self._limits,
                        clock=self._clock,
                        utc_clock=self._utc_clock,
                    )
                    self._terminals[spec.terminal_id] = terminal
        except asyncio.CancelledError:
            await self._remove_reservation(reservation)
            asyncio.create_task(_cleanup_uninstalled_process(process))
            raise
        if stale:
            asyncio.create_task(_cleanup_uninstalled_process(process))
            raise TerminalInvalidatedError("Terminal open authority was invalidated.")
        return terminal

    async def get(self, *, terminal_id: str) -> RunnerTerminal | None:
        """Return the active Terminal by independent ID."""
        async with self._lock:
            return self._terminals.get(terminal_id)

    async def terminate(self, *, terminal_id: str) -> TerminalExit | None:
        """Terminate and forget one active Terminal."""
        async with self._lock:
            self._remove_reservation_locked(terminal_id)
            terminal = self._terminals.pop(terminal_id, None)
        if terminal is None:
            return None
        return await terminal.terminate()

    async def invalidate(
        self,
        *,
        terminal_id: str,
    ) -> asyncio.Task[TerminalExit] | None:
        """Atomically fence and detach one Terminal before bounded cleanup."""
        async with self._lock:
            self._remove_reservation_locked(terminal_id)
            terminal = self._detach_locked(terminal_id)
        if terminal is None:
            return None
        return asyncio.create_task(terminal.terminate())

    async def invalidate_runtime(
        self,
        *,
        runtime_id: str,
    ) -> tuple[asyncio.Task[TerminalExit], ...]:
        """Detach Runtime Terminals and start bounded cleanup without waiting."""
        async with self._lock:
            for terminal_id, reservation in tuple(self._reservations.items()):
                if reservation.runtime_id == runtime_id:
                    self._remove_reservation_locked(terminal_id)
            terminal_ids = tuple(
                terminal_id
                for terminal_id, terminal in self._terminals.items()
                if terminal.runtime_id == runtime_id
            )
            terminals = [
                terminal
                for terminal_id in terminal_ids
                if (terminal := self._detach_locked(terminal_id)) is not None
            ]
        return tuple(
            asyncio.create_task(terminal.terminate()) for terminal in terminals
        )

    async def close_expired(self) -> dict[str, TerminalDeadline]:
        """Terminate only lifecycle-expired Terminals and report bounded reasons."""
        async with self._lock:
            expired = {
                terminal_id: deadline
                for terminal_id, terminal in self._terminals.items()
                if (deadline := terminal.deadline())
                in {
                    TerminalDeadline.IDLE,
                    TerminalDeadline.MAXIMUM_LIFETIME,
                    TerminalDeadline.STREAM_GRACE,
                }
            }
            terminals = [self._terminals.pop(terminal_id) for terminal_id in expired]
        await asyncio.gather(*(terminal.terminate() for terminal in terminals))
        return expired

    async def close(self) -> tuple[TerminalExit, ...]:
        """Terminate all Runner-local PTYs during Runner shutdown."""
        async with self._lock:
            terminals = tuple(self._terminals.values())
            self._terminals.clear()
        exits = await asyncio.gather(*(terminal.terminate() for terminal in terminals))
        return tuple(exits)

    def _enforce_admission(self, spec: TerminalSpec) -> None:
        session_count = sum(
            terminal.session_id == spec.session_id
            for terminal in self._terminals.values()
        ) + sum(
            reservation.session_id == spec.session_id
            for reservation in self._reservations.values()
        )
        if session_count >= self._limits.max_active_per_session:
            raise TerminalAdmissionError("Terminal Session limit has been reached.")
        runtime_count = sum(
            terminal.runtime_id == spec.runtime_id
            for terminal in self._terminals.values()
        ) + sum(
            reservation.runtime_id == spec.runtime_id
            for reservation in self._reservations.values()
        )
        if runtime_count >= self._limits.max_active_per_runtime:
            raise TerminalAdmissionError("Terminal Runtime limit has been reached.")

    def _detach_locked(self, terminal_id: str) -> RunnerTerminal | None:
        """Remove and immediately invalidate one Terminal under registry ownership."""
        terminal = self._terminals.pop(terminal_id, None)
        if terminal is not None:
            terminal.invalidate()
        return terminal

    async def _remove_reservation(self, reservation: _TerminalReservation) -> None:
        """Release this exact reservation after launch failure or cancellation."""
        async with self._lock:
            if self._reservations.get(reservation.terminal_id) is reservation:
                self._remove_reservation_locked(reservation.terminal_id)

    def _remove_reservation_locked(self, terminal_id: str) -> None:
        """Remove one opening reservation while registry ownership is held."""
        self._reservations.pop(terminal_id, None)

    def _enforce_authority_deadlines(self, spec: TerminalSpec) -> None:
        now = self._utc_clock()
        if spec.maximum_deadline_at <= now:
            raise TerminalAdmissionError(
                "Terminal maximum lifetime authority has already expired."
            )
        if spec.idle_deadline_at <= now:
            raise TerminalAdmissionError(
                "Terminal initial idle authority has already expired."
            )
        if spec.data_stream_grace_deadline_at <= now:
            raise TerminalAdmissionError(
                "Terminal initial data-stream authority has already expired."
            )


async def _cleanup_uninstalled_process(process: PtyTerminalProcess) -> None:
    """Terminate a PTY whose reservation lost authority during allocation."""
    try:
        await process.terminate_session(
            terminate_timeout_seconds=TERMINATE_GRACE_SECONDS,
            kill_timeout_seconds=KILL_GRACE_SECONDS,
        )
    finally:
        await process.close()


def _require_aware_datetime(value: datetime, name: str) -> None:
    """Reject deadline values that cannot be compared across clock boundaries."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware.")


async def _wait_for_fd_read(
    *,
    fd: int,
    maximum_bytes: int,
    active: Callable[[], bool],
) -> bytes:
    """Read a nonblocking descriptor after readiness notification."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bytes] = loop.create_future()

    def ready() -> None:
        if not active():
            if not future.done():
                future.set_exception(
                    TerminalInvalidatedError("Terminal Runtime authority changed.")
                )
            loop.remove_reader(fd)
            return
        try:
            data = os.read(fd, maximum_bytes)
        except BlockingIOError:
            return
        except OSError as error:
            if error.errno is errno.EIO:
                data = b""
            else:
                if not future.done():
                    future.set_exception(error)
                loop.remove_reader(fd)
                return
        if not future.done():
            future.set_result(data)
        loop.remove_reader(fd)

    loop.add_reader(fd, ready)
    try:
        return await future
    except asyncio.CancelledError:
        loop.remove_reader(fd)
        raise


async def _wait_for_fd_writable(*, fd: int) -> None:
    """Wait until a nonblocking descriptor accepts more bytes."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[None] = loop.create_future()

    def ready() -> None:
        if not future.done():
            future.set_result(None)
        loop.remove_writer(fd)

    loop.add_writer(fd, ready)
    try:
        await future
    except asyncio.CancelledError:
        loop.remove_writer(fd)
        raise


async def _wait_for_process(
    process: asyncio.subprocess.Process,
    timeout_seconds: float,
) -> bool:
    """Wait for process exit without cancelling its underlying waiter."""
    wait_task = asyncio.create_task(process.wait())
    try:
        await asyncio.wait_for(asyncio.shield(wait_task), timeout=timeout_seconds)
    except TimeoutError:
        wait_task.cancel()
        await asyncio.gather(wait_task, return_exceptions=True)
        return False
    return True


async def _wait_for_session_exit(
    *,
    session_id: int,
    timeout_seconds: float,
) -> bool:
    """Wait until no process group remains in the PTY POSIX session."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while _session_process_group_ids(session_id=session_id):
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(0.05, remaining))
    return True


async def _reap_process(process: asyncio.subprocess.Process) -> None:
    """Collect the shell return code after its POSIX session is empty."""
    if process.returncode is None:
        await _wait_for_process(process, 0.2)


def _signal_session_process_groups(
    *,
    session_id: int,
    requested_signal: signal.Signals,
) -> None:
    """Signal distinct current process groups whose processes remain in session."""
    process_group_ids = _session_process_group_ids(session_id=session_id)
    for process_group_id in process_group_ids:
        try:
            os.killpg(process_group_id, requested_signal)
        except ProcessLookupError:
            continue


def _session_process_group_ids(*, session_id: int) -> tuple[int, ...]:
    """Return distinct live process groups verified through Linux /proc."""
    process_group_ids: set[int] = set()
    proc_root = Path("/proc")
    for stat_path in proc_root.glob("[0-9]*/stat"):
        try:
            identity = _process_group_and_session(stat_path.read_text(encoding="utf-8"))
        except FileNotFoundError, PermissionError:
            continue
        if identity is None:
            continue
        process_group_id, process_session_id = identity
        if process_session_id == session_id:
            process_group_ids.add(process_group_id)
    return tuple(sorted(process_group_ids))


def _process_group_and_session(stat: str) -> _ProcessGroupSession | None:
    """Parse Linux proc stat without splitting spaces inside the command name."""
    command_end = stat.rfind(") ")
    if command_end < 0:
        return None
    fields = stat[command_end + 2 :].split()
    if len(fields) < 4:
        return None
    if fields[0] == "Z":
        return None
    try:
        return _ProcessGroupSession(
            process_group_id=int(fields[2]),
            session_id=int(fields[3]),
        )
    except ValueError:
        return None
