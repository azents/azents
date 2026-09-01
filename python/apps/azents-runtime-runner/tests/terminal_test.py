"""Runtime Runner interactive Terminal tests."""

import asyncio
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from azents_runtime_runner.terminal import (
    KILL_GRACE_SECONDS,
    MAX_TERMINAL_CHUNK_BYTES,
    MAX_TERMINAL_OUTPUT_WINDOW_BYTES,
    TERMINATE_GRACE_SECONDS,
    LinuxPtyTerminalBackend,
    PtyTerminalProcess,
    RunnerTerminal,
    RunnerTerminalRegistry,
    TerminalAdmissionError,
    TerminalDeadline,
    TerminalExit,
    TerminalInputSequenceError,
    TerminalInvalidatedError,
    TerminalLimits,
    TerminalOutputBackpressure,
    TerminalSpec,
    _process_group_and_session,
)


@dataclass
class _Clock:
    value: float

    def __call__(self) -> float:
        return self.value


@dataclass
class _UtcClock:
    value: datetime

    def __call__(self) -> datetime:
        return self.value


class _FakePty:
    def __init__(self, *, output: bytes = b"") -> None:
        self.returncode: int | None = None
        self.output = output
        self.written = bytearray()
        self.write_limit: int | None = None
        self.cancel_on_write_call: int | None = None
        self.write_calls = 0
        self.dimensions: tuple[int, int] | None = None
        self.terminated = False
        self.closed = False

    async def read(
        self,
        maximum_bytes: int,
        *,
        active: Callable[[], bool],
    ) -> bytes:
        if not active():
            raise TerminalInvalidatedError("Terminal Runtime authority changed.")
        data = self.output[:maximum_bytes]
        self.output = self.output[maximum_bytes:]
        return data

    async def write(
        self,
        data: bytes,
        *,
        offset: int,
        active: Callable[[], bool],
    ) -> int:
        self.write_calls += 1
        if self.cancel_on_write_call == self.write_calls:
            raise asyncio.CancelledError
        if not active():
            raise TerminalInvalidatedError("Terminal Runtime authority changed.")
        maximum = self.write_limit or len(data) - offset
        chunk = data[offset : offset + maximum]
        self.written.extend(chunk)
        return len(chunk)

    async def resize(
        self,
        *,
        columns: int,
        rows: int,
        active: Callable[[], bool],
    ) -> None:
        if not active():
            raise TerminalInvalidatedError("Terminal Runtime authority changed.")
        self.dimensions = (columns, rows)

    async def wait(self) -> int:
        self.returncode = 0
        return 0

    async def terminate_session(
        self,
        *,
        terminate_timeout_seconds: float,
        kill_timeout_seconds: float,
    ) -> TerminalExit:
        del terminate_timeout_seconds, kill_timeout_seconds
        self.terminated = True
        self.returncode = 0

        return TerminalExit(
            returncode=0,
            already_exited=False,
            escalated=False,
            timed_out=False,
        )

    async def close(self) -> None:
        self.closed = True


class _GatedPty(_FakePty):
    """PTY fake that holds one read or write before its authority check."""

    def __init__(self, *, output: bytes = b"") -> None:
        super().__init__(output=output)
        self.write_started = asyncio.Event()
        self.allow_write = asyncio.Event()
        self.read_started = asyncio.Event()
        self.allow_read = asyncio.Event()

    async def read(
        self,
        maximum_bytes: int,
        *,
        active: Callable[[], bool],
    ) -> bytes:
        self.read_started.set()
        await self.allow_read.wait()
        return await super().read(maximum_bytes, active=active)

    async def write(
        self,
        data: bytes,
        *,
        offset: int,
        active: Callable[[], bool],
    ) -> int:
        self.write_started.set()
        await self.allow_write.wait()
        return await super().write(data, offset=offset, active=active)


class _FakeBackend:
    def __init__(self) -> None:
        self.processes: list[_FakePty] = []

    async def open(self, spec: TerminalSpec) -> PtyTerminalProcess:
        del spec
        process = _FakePty()
        self.processes.append(process)
        return process


class _SlowBackend(_FakeBackend):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def open(self, spec: TerminalSpec) -> PtyTerminalProcess:
        del spec
        self.started.set()
        await self.release.wait()
        process = _FakePty()
        self.processes.append(process)
        return process


def _limits() -> TerminalLimits:
    return TerminalLimits(
        max_active_per_session=1,
        max_active_per_runtime=16,
        idle_timeout_seconds=30 * 60,
        maximum_lifetime_seconds=8 * 60 * 60,
        stream_grace_seconds=2 * 60,
        stream_attempt_timeout_seconds=30,
        maximum_chunk_bytes=MAX_TERMINAL_CHUNK_BYTES,
        maximum_unacknowledged_output_bytes=MAX_TERMINAL_OUTPUT_WINDOW_BYTES,
    )


_TEST_UTC_NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _spec(
    tmp_path: Path,
    *,
    terminal_id: str = "terminal-1",
    idle_deadline_at: datetime | None = None,
    maximum_deadline_at: datetime | None = None,
    data_stream_grace_deadline_at: datetime | None = None,
) -> TerminalSpec:
    return TerminalSpec(
        terminal_id=terminal_id,
        runtime_id="runtime-1",
        session_id="session-1",
        workspace_root=tmp_path,
        working_directory=tmp_path,
        environment={},
        columns=80,
        rows=24,
        idle_deadline_at=idle_deadline_at or (_TEST_UTC_NOW + timedelta(minutes=30)),
        maximum_deadline_at=maximum_deadline_at or (_TEST_UTC_NOW + timedelta(hours=8)),
        data_stream_grace_deadline_at=data_stream_grace_deadline_at
        or (_TEST_UTC_NOW + timedelta(minutes=2)),
    )


@pytest.mark.asyncio
async def test_input_is_applied_once_and_duplicate_is_acknowledged(
    tmp_path: Path,
) -> None:
    clock = _Clock(100)
    process = _FakePty()
    terminal = RunnerTerminal(
        spec=_spec(tmp_path),
        process=process,
        limits=_limits(),
        clock=clock,
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )

    first = await terminal.apply_input(sequence=1, data=b"echo hello\r")
    duplicate = await terminal.apply_input(sequence=1, data=b"echo hello\r")

    assert first.applied is True
    assert duplicate.applied is False
    assert process.written == b"echo hello\r"
    assert terminal.resume_state().highest_applied_input_sequence == 1


@pytest.mark.asyncio
async def test_partial_input_resumes_without_rewriting_prefix(tmp_path: Path) -> None:
    clock = _Clock(100)
    process = _FakePty()
    process.write_limit = 2
    terminal = RunnerTerminal(
        spec=_spec(tmp_path),
        process=process,
        limits=_limits(),
        clock=clock,
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )

    result = await terminal.apply_input(sequence=1, data=b"hello")

    assert result.applied is True
    assert process.written == b"hello"
    assert terminal.resume_state().highest_applied_input_sequence == 1


@pytest.mark.asyncio
async def test_cancelled_partial_input_resumes_without_duplicate_bytes(
    tmp_path: Path,
) -> None:
    clock = _Clock(100)
    process = _FakePty()
    process.write_limit = 2
    process.cancel_on_write_call = 2
    terminal = RunnerTerminal(
        spec=_spec(tmp_path),
        process=process,
        limits=_limits(),
        clock=clock,
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )

    with pytest.raises(asyncio.CancelledError):
        await terminal.apply_input(sequence=1, data=b"hello")
    partial_resume = terminal.resume_state()
    result = await terminal.apply_input(sequence=1, data=b"hello")

    assert result.applied is True
    assert process.written == b"hello"
    assert partial_resume.highest_applied_input_sequence == 0
    assert partial_resume.partial_input_sequence == 1
    assert partial_resume.partial_input_bytes_written == 2
    assert terminal.resume_state().highest_applied_input_sequence == 1
    assert terminal.resume_state().partial_input_sequence is None
    assert terminal.resume_state().partial_input_bytes_written is None


@pytest.mark.asyncio
async def test_input_gap_and_changed_partial_input_fail_closed(tmp_path: Path) -> None:
    clock = _Clock(100)
    process = _FakePty()
    terminal = RunnerTerminal(
        spec=_spec(tmp_path),
        process=process,
        limits=_limits(),
        clock=clock,
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )

    with pytest.raises(TerminalInputSequenceError, match="gap"):
        await terminal.apply_input(sequence=2, data=b"bad")


@pytest.mark.asyncio
async def test_output_window_applies_backpressure_until_acknowledged(
    tmp_path: Path,
) -> None:
    limits = TerminalLimits(
        max_active_per_session=1,
        max_active_per_runtime=16,
        idle_timeout_seconds=30 * 60,
        maximum_lifetime_seconds=8 * 60 * 60,
        stream_grace_seconds=2 * 60,
        stream_attempt_timeout_seconds=30,
        maximum_chunk_bytes=4,
        maximum_unacknowledged_output_bytes=4,
    )
    process = _FakePty(output=b"abcdefgh")
    terminal = RunnerTerminal(
        spec=_spec(tmp_path),
        process=process,
        limits=limits,
        clock=_Clock(100),
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )

    first = await terminal.read_output()
    with pytest.raises(TerminalOutputBackpressure):
        await terminal.read_output()
    terminal.acknowledge_output(sequence=first.sequence)
    second = await terminal.read_output()

    assert first.data == b"abcd"
    assert second.data == b"efgh"
    assert terminal.output_from(sequence=1) == (second,)


@pytest.mark.asyncio
async def test_deadlines_keep_pty_for_full_stream_grace(tmp_path: Path) -> None:
    clock = _Clock(100)
    terminal = RunnerTerminal(
        spec=_spec(tmp_path),
        process=_FakePty(),
        limits=_limits(),
        clock=clock,
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )

    terminal.mark_stream_connected()
    terminal.begin_stream_recovery()
    clock.value += 30
    assert terminal.deadline() is TerminalDeadline.STREAM_ATTEMPT
    clock.value += 89
    assert terminal.deadline() is TerminalDeadline.STREAM_ATTEMPT
    clock.value += 1
    assert terminal.deadline() is TerminalDeadline.STREAM_GRACE


@pytest.mark.asyncio
async def test_initial_authority_deadlines_fence_open_idle_and_stream_setup(
    tmp_path: Path,
) -> None:
    clock = _Clock(100)
    utc_clock = _UtcClock(_TEST_UTC_NOW)
    terminal = RunnerTerminal(
        spec=_spec(
            tmp_path,
            idle_deadline_at=_TEST_UTC_NOW + timedelta(seconds=10),
            maximum_deadline_at=_TEST_UTC_NOW + timedelta(seconds=30),
            data_stream_grace_deadline_at=_TEST_UTC_NOW + timedelta(seconds=5),
        ),
        process=_FakePty(),
        limits=_limits(),
        clock=clock,
        utc_clock=utc_clock,
    )

    utc_clock.value += timedelta(seconds=5)
    assert terminal.deadline() is TerminalDeadline.STREAM_GRACE

    terminal.mark_stream_connected()
    utc_clock.value += timedelta(seconds=5)
    assert terminal.deadline() is TerminalDeadline.IDLE


@pytest.mark.asyncio
async def test_activity_resets_local_idle_but_never_extends_maximum_authority(
    tmp_path: Path,
) -> None:
    clock = _Clock(100)
    utc_clock = _UtcClock(_TEST_UTC_NOW)
    terminal = RunnerTerminal(
        spec=_spec(
            tmp_path,
            idle_deadline_at=_TEST_UTC_NOW + timedelta(seconds=10),
            maximum_deadline_at=_TEST_UTC_NOW + timedelta(seconds=20),
        ),
        process=_FakePty(),
        limits=_limits(),
        clock=clock,
        utc_clock=utc_clock,
    )

    clock.value += 5
    utc_clock.value += timedelta(seconds=5)
    await terminal.apply_input(sequence=1, data=b"echo active\r")
    utc_clock.value += timedelta(seconds=10)
    assert terminal.deadline() is None

    utc_clock.value += timedelta(seconds=5)
    assert terminal.deadline() is TerminalDeadline.MAXIMUM_LIFETIME


@pytest.mark.asyncio
async def test_registry_rejects_expired_open_authority(tmp_path: Path) -> None:
    backend = _FakeBackend()
    registry = RunnerTerminalRegistry(
        backend=backend,
        limits=_limits(),
        clock=_Clock(100),
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )

    with pytest.raises(TerminalAdmissionError, match="maximum lifetime authority"):
        await registry.open(
            _spec(
                tmp_path,
                maximum_deadline_at=_TEST_UTC_NOW - timedelta(seconds=1),
            )
        )


@pytest.mark.asyncio
async def test_registry_enforces_session_and_runtime_limits(tmp_path: Path) -> None:
    backend = _FakeBackend()
    registry = RunnerTerminalRegistry(
        backend=backend,
        limits=_limits(),
        clock=_Clock(100),
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )
    first = await registry.open(_spec(tmp_path))

    assert await registry.open(_spec(tmp_path)) is first
    with pytest.raises(TerminalAdmissionError, match="Session"):
        await registry.open(_spec(tmp_path, terminal_id="terminal-2"))


@pytest.mark.asyncio
async def test_pending_open_does_not_block_invalidation_or_install_after_fence(
    tmp_path: Path,
) -> None:
    backend = _SlowBackend()
    registry = RunnerTerminalRegistry(
        backend=backend,
        limits=_limits(),
        clock=_Clock(100),
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )
    opening = asyncio.create_task(registry.open(_spec(tmp_path)))
    await backend.started.wait()

    assert await registry.invalidate(terminal_id="terminal-1") is None
    backend.release.set()

    with pytest.raises(TerminalInvalidatedError):
        await opening
    assert await registry.get(terminal_id="terminal-1") is None


@pytest.mark.asyncio
async def test_pending_open_counts_against_session_quota(tmp_path: Path) -> None:
    backend = _SlowBackend()
    registry = RunnerTerminalRegistry(
        backend=backend,
        limits=_limits(),
        clock=_Clock(100),
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )
    opening = asyncio.create_task(registry.open(_spec(tmp_path)))
    await backend.started.wait()

    with pytest.raises(TerminalAdmissionError, match="Session"):
        await registry.open(_spec(tmp_path, terminal_id="terminal-2"))

    backend.release.set()
    await opening


@pytest.mark.asyncio
async def test_registry_closes_only_terminal_lifecycle_expiry(tmp_path: Path) -> None:
    clock = _Clock(100)
    backend = _FakeBackend()
    registry = RunnerTerminalRegistry(
        backend=backend,
        limits=_limits(),
        clock=clock,
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )
    await registry.open(_spec(tmp_path))
    clock.value += 30 * 60

    closed = await registry.close_expired()

    assert closed == {"terminal-1": TerminalDeadline.IDLE}
    assert backend.processes[0].terminated is True
    assert backend.processes[0].closed is True


@pytest.mark.asyncio
async def test_runtime_invalidation_detaches_without_waiting_for_cleanup(
    tmp_path: Path,
) -> None:
    backend = _FakeBackend()
    registry = RunnerTerminalRegistry(
        backend=backend,
        limits=_limits(),
        clock=_Clock(100),
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )
    await registry.open(_spec(tmp_path))

    cleanup_tasks = await registry.invalidate_runtime(runtime_id="runtime-1")

    assert len(cleanup_tasks) == 1
    assert await registry.get(terminal_id="terminal-1") is None
    await asyncio.gather(*cleanup_tasks)
    assert backend.processes[0].terminated is True


@pytest.mark.asyncio
async def test_invalidation_fences_inflight_input_before_suffix_write(
    tmp_path: Path,
) -> None:
    process = _GatedPty()
    terminal = RunnerTerminal(
        spec=_spec(tmp_path),
        process=process,
        limits=_limits(),
        clock=_Clock(100),
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )

    write_task = asyncio.create_task(
        terminal.apply_input(sequence=1, data=b"cannot-write")
    )
    await process.write_started.wait()
    terminal.invalidate()
    process.allow_write.set()

    with pytest.raises(TerminalInvalidatedError):
        await write_task

    assert process.written == b""
    assert terminal.resume_state().highest_applied_input_sequence == 0
    assert terminal.resume_state().partial_input_sequence == 1


@pytest.mark.asyncio
async def test_invalidation_fences_inflight_read_and_all_mutations(
    tmp_path: Path,
) -> None:
    process = _GatedPty(output=b"terminal-output")
    terminal = RunnerTerminal(
        spec=_spec(tmp_path),
        process=process,
        limits=_limits(),
        clock=_Clock(100),
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )

    read_task = asyncio.create_task(terminal.read_output())
    await process.read_started.wait()
    terminal.invalidate()
    process.allow_read.set()

    with pytest.raises(TerminalInvalidatedError):
        await read_task
    with pytest.raises(TerminalInvalidatedError):
        terminal.acknowledge_output(sequence=0)
    with pytest.raises(TerminalInvalidatedError):
        await terminal.resize(columns=120, rows=40)

    assert terminal.resume_state().last_output_sequence == 0
    assert process.dimensions is None


@pytest.mark.asyncio
async def test_registry_invalidate_fences_and_detaches_before_cleanup(
    tmp_path: Path,
) -> None:
    backend = _FakeBackend()
    registry = RunnerTerminalRegistry(
        backend=backend,
        limits=_limits(),
        clock=_Clock(100),
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )
    terminal = await registry.open(_spec(tmp_path))

    cleanup_task = await registry.invalidate(terminal_id=terminal.terminal_id)

    assert cleanup_task is not None
    assert await registry.get(terminal_id=terminal.terminal_id) is None
    with pytest.raises(TerminalInvalidatedError):
        terminal.acknowledge_output(sequence=0)
    await cleanup_task


@pytest.mark.asyncio
async def test_initial_stream_establishment_has_monotonic_grace_cap(
    tmp_path: Path,
) -> None:
    clock = _Clock(100)
    terminal = RunnerTerminal(
        spec=_spec(
            tmp_path,
            data_stream_grace_deadline_at=_TEST_UTC_NOW + timedelta(hours=1),
        ),
        process=_FakePty(),
        limits=_limits(),
        clock=clock,
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )

    clock.value += 2 * 60

    assert terminal.deadline() is TerminalDeadline.STREAM_GRACE


@pytest.mark.asyncio
async def test_resize_does_not_extend_idle_activity(tmp_path: Path) -> None:
    clock = _Clock(100)
    terminal = RunnerTerminal(
        spec=_spec(tmp_path),
        process=_FakePty(),
        limits=_limits(),
        clock=clock,
        utc_clock=_UtcClock(_TEST_UTC_NOW),
    )
    await terminal.apply_input(sequence=1, data=b"active")
    clock.value += _limits().idle_timeout_seconds - 1

    await terminal.resize(columns=120, rows=40)
    clock.value += 1

    assert terminal.deadline() is TerminalDeadline.IDLE


@pytest.mark.asyncio
async def test_linux_launcher_failure_and_cancellation_close_open_boundary(
    tmp_path: Path,
) -> None:
    async def fail_launcher(
        slave_fd: int,
        working_directory: Path,
        environment: Mapping[str, str],
    ) -> asyncio.subprocess.Process:
        del slave_fd, working_directory, environment
        raise OSError("launcher unavailable")

    async def cancel_launcher(
        slave_fd: int,
        working_directory: Path,
        environment: Mapping[str, str],
    ) -> asyncio.subprocess.Process:
        del slave_fd, working_directory, environment
        raise asyncio.CancelledError

    with pytest.raises(OSError, match="launcher unavailable"):
        await LinuxPtyTerminalBackend(launcher=fail_launcher).open(_spec(tmp_path))
    with pytest.raises(asyncio.CancelledError):
        await LinuxPtyTerminalBackend(launcher=cancel_launcher).open(_spec(tmp_path))


@pytest.mark.asyncio
async def test_linux_backend_runs_interactive_shell_in_working_directory(
    tmp_path: Path,
) -> None:
    backend = LinuxPtyTerminalBackend()
    process = await backend.open(_spec(tmp_path))
    try:
        expected = f"__TERMINAL_READY__{tmp_path}:24 80:가".encode()
        await process.write(
            (
                "printf '__TERMINAL_READY__%s:%s:%s\\n' \"$PWD\" "
                '"$(stty size)" "가"; exit\r'
            ).encode(),
            offset=0,
            active=lambda: True,
        )
        output = await _read_until(process, expected=expected)
        assert expected in output
        assert await asyncio.wait_for(process.wait(), timeout=2) == 0
    finally:
        await process.terminate_session(
            terminate_timeout_seconds=TERMINATE_GRACE_SECONDS,
            kill_timeout_seconds=KILL_GRACE_SECONDS,
        )
        await process.close()


@pytest.mark.asyncio
async def test_linux_backend_ctrl_c_keeps_the_interactive_shell_alive(
    tmp_path: Path,
) -> None:
    backend = LinuxPtyTerminalBackend()
    process = await backend.open(_spec(tmp_path))
    try:
        await process.write(
            (
                b"printf '__TERMINAL_SLEEPING__%s\\n' \"$$\"; "
                b"sleep 20; printf '__NOT_INTERRUPTED__'\r"
            ),
            offset=0,
            active=lambda: True,
        )
        await _read_until_marker_number(
            process,
            marker=b"__TERMINAL_SLEEPING__",
        )
        await process.write(b"\x03", offset=0, active=lambda: True)
        await process.write(
            b"printf '__TERMINAL_AFTER_INTERRUPT__'\r",
            offset=0,
            active=lambda: True,
        )

        output = await _read_until(
            process,
            expected=b"__TERMINAL_AFTER_INTERRUPT__",
        )

        assert b"__NOT_INTERRUPTED__" not in output
        assert process.returncode is None
    finally:
        await process.terminate_session(
            terminate_timeout_seconds=TERMINATE_GRACE_SECONDS,
            kill_timeout_seconds=KILL_GRACE_SECONDS,
        )
        await process.close()


@pytest.mark.asyncio
async def test_linux_backend_terminates_background_job_in_pty_session(
    tmp_path: Path,
) -> None:
    backend = LinuxPtyTerminalBackend()
    process = await backend.open(_spec(tmp_path))
    try:
        await process.write(
            b"sleep 30 & printf '__TERMINAL_CHILD__%s\\n' \"$!\"; wait\r",
            offset=0,
            active=lambda: True,
        )
        output = await _read_until_child_process_id(process)
        child_process_id = _child_process_id(output)

        termination = await process.terminate_session(
            terminate_timeout_seconds=TERMINATE_GRACE_SECONDS,
            kill_timeout_seconds=KILL_GRACE_SECONDS,
        )

        assert termination.already_exited is False
        await _assert_process_gone(process_id=child_process_id)
    finally:
        await process.close()


@pytest.mark.asyncio
async def test_linux_backend_cleans_background_job_after_shell_exits(
    tmp_path: Path,
) -> None:
    backend = LinuxPtyTerminalBackend()
    process = await backend.open(_spec(tmp_path))
    try:
        await process.write(
            (
                b"nohup sleep 30 >/dev/null 2>&1 & "
                b"printf '__TERMINAL_CHILD__%s\\n' \"$!\"; exit\r"
            ),
            offset=0,
            active=lambda: True,
        )
        output = await _read_until_child_process_id(process)
        child_process_id = _child_process_id(output)
        assert await asyncio.wait_for(process.wait(), timeout=2) == 0

        termination = await process.terminate_session(
            terminate_timeout_seconds=TERMINATE_GRACE_SECONDS,
            kill_timeout_seconds=KILL_GRACE_SECONDS,
        )

        assert termination.already_exited is False
        await _assert_process_gone(process_id=child_process_id)
    finally:
        await process.close()


def test_proc_stat_parser_preserves_spaced_or_parenthesized_command() -> None:
    assert _process_group_and_session("123 (terminal worker) S 1 456 789 0 0 0") == (
        456,
        789,
    )
    assert _process_group_and_session("123 (terminal) worker) S 1 456 789 0 0 0") == (
        456,
        789,
    )
    assert _process_group_and_session("123 (terminal worker) Z 1 456 789 0 0 0") is None
    assert _process_group_and_session("invalid") is None


async def _read_until(
    process: PtyTerminalProcess,
    *,
    expected: bytes,
) -> bytearray:
    """Read PTY output until expected bytes arrive or the bounded test fails."""
    output = bytearray()
    for _ in range(20):
        output.extend(
            await asyncio.wait_for(process.read(4096, active=lambda: True), timeout=1)
        )
        if expected in output:
            return output
    pytest.fail("Terminal PTY did not produce the expected output.")


def _child_process_id(output: bytes | bytearray) -> int:
    """Extract the bounded background process ID printed by the shell."""
    match = re.search(rb"__TERMINAL_CHILD__(\d+)", output)
    if match is None:
        pytest.fail("Terminal PTY did not report the background process ID.")
    return int(match.group(1))


async def _read_until_child_process_id(
    process: PtyTerminalProcess,
) -> bytearray:
    """Read until the shell emits a concrete background process ID."""
    output = bytearray()
    for _ in range(20):
        output.extend(
            await asyncio.wait_for(process.read(4096, active=lambda: True), timeout=1)
        )
        if re.search(rb"__TERMINAL_CHILD__(\d+)", output) is not None:
            return output
    pytest.fail("Terminal PTY did not report the background process ID.")


async def _read_until_marker_number(
    process: PtyTerminalProcess,
    *,
    marker: bytes,
) -> bytearray:
    """Read until a shell expands a numeric marker suffix."""
    output = bytearray()
    expression = re.compile(re.escape(marker) + rb"(\d+)")
    for _ in range(20):
        output.extend(
            await asyncio.wait_for(process.read(4096, active=lambda: True), timeout=1)
        )
        if expression.search(output) is not None:
            return output
    pytest.fail("Terminal PTY did not report the expected numeric marker.")


async def _assert_process_gone(*, process_id: int) -> None:
    """Wait for the OS to make a terminated process unavailable."""
    for _ in range(100):
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            return
        stat_path = Path(f"/proc/{process_id}/stat")
        try:
            stat = stat_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        command_end = stat.rfind(") ")
        if command_end >= 0 and stat[command_end + 2 :].startswith("Z "):
            return
        await asyncio.sleep(0.01)
    pytest.fail("Terminal background process survived PTY session termination.")
