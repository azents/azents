"""Runner integration for Terminal Control intents and dedicated data streams."""

import asyncio
import contextlib
import dataclasses
import logging
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Protocol

import grpc
from azents_runtime_control.grpc_runner_terminal_client import (
    GrpcRunnerTerminalClient,
    RuntimeRunnerTerminalStreamClosed,
)
from azents_runtime_control.grpc_tls import GrpcClientTlsConfig
from azents_runtime_control.runner_terminal import (
    RunnerTerminalControlFrame,
    RunnerTerminalEventFrame,
    RunnerTerminalExit,
    RunnerTerminalHeartbeat,
    RunnerTerminalHeartbeatAcknowledgement,
    RunnerTerminalIdentity,
    RunnerTerminalInputAcknowledgement,
    RunnerTerminalInputFrame,
    RunnerTerminalOpenIntent,
    RunnerTerminalOutputAcknowledgement,
    RunnerTerminalOutputFrame,
    RunnerTerminalResize,
    RunnerTerminalStreamAccepted,
    RunnerTerminalStreamError,
    RunnerTerminalStreamErrorCode,
    RunnerTerminalStreamRegistration,
    RunnerTerminalTerminate,
    RunnerTerminalTerminateIntent,
    RunnerTerminalTerminationReason,
)

from azents_runtime_runner.terminal import (
    RunnerTerminal,
    RunnerTerminalRegistry,
    TerminalAdmissionError,
    TerminalDeadline,
    TerminalError,
    TerminalInputSequenceError,
    TerminalOutputBackpressure,
    TerminalSpec,
)
from azents_runtime_runner.terminal import (
    TerminalExit as PtyTerminalExit,
)

_HEARTBEAT_INTERVAL_SECONDS = 10.0
_HEARTBEAT_ACK_TIMEOUT_SECONDS = 30.0
_RECONNECT_DELAY_SECONDS = 1.0
_DEADLINE_POLL_SECONDS = 1.0
_LOGGER = logging.getLogger(__name__)


class RunnerTerminalClient(Protocol):
    """Typed data-stream client dependency used by one Terminal."""

    def set_control_handler(
        self,
        handler: Callable[[RunnerTerminalControlFrame], Awaitable[None]],
    ) -> None:
        """Set the ordered Control-frame handler."""
        ...

    async def start(
        self,
        registration: RunnerTerminalStreamRegistration,
    ) -> RunnerTerminalStreamAccepted:
        """Open and register one Terminal stream."""
        ...

    async def send(self, frame: RunnerTerminalEventFrame) -> None:
        """Send one Runner event frame."""
        ...

    async def close(self) -> None:
        """Close the Terminal stream."""
        ...


RunnerTerminalClientFactory = Callable[[], RunnerTerminalClient]


@dataclasses.dataclass(frozen=True)
class _TerminalFinal:
    reason: RunnerTerminalTerminationReason
    exit_code: int | None


@dataclasses.dataclass
class _HeartbeatState:
    """Mutable per-connection Terminal heartbeat progress."""

    sent_sequence: int = 0
    acknowledged_sequence: int = 0
    progress: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)


class RunnerTerminalStreamManager:
    """Own admitted PTYs and one reconnectable data stream per Terminal."""

    def __init__(
        self,
        *,
        registry: RunnerTerminalRegistry,
        runtime_id: str,
        workspace_root: Path,
        environment: Mapping[str, str],
        accepted_generation: Callable[[], int | None],
        client_factory: RunnerTerminalClientFactory,
    ) -> None:
        """Initialize one Runner-control-generation Terminal manager."""
        self._registry = registry
        self._runtime_id = runtime_id
        self._workspace_root = workspace_root
        self._environment = environment
        self._accepted_generation = accepted_generation
        self._client_factory = client_factory
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._clients: dict[str, RunnerTerminalClient] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def from_endpoint(
        cls,
        *,
        registry: RunnerTerminalRegistry,
        endpoint: str,
        runner_auth_token: str,
        tls: GrpcClientTlsConfig | None,
        allow_insecure: bool,
        runtime_id: str,
        workspace_root: Path,
        environment: Mapping[str, str],
        accepted_generation: Callable[[], int | None],
    ) -> "RunnerTerminalStreamManager":
        """Create a manager whose Terminals use independently pooled channels."""

        def client_factory() -> GrpcRunnerTerminalClient:
            return GrpcRunnerTerminalClient.from_endpoint(
                endpoint,
                runner_auth_token=runner_auth_token,
                tls=tls,
                allow_insecure=allow_insecure,
            )

        return cls(
            registry=registry,
            runtime_id=runtime_id,
            workspace_root=workspace_root,
            environment=environment,
            accepted_generation=accepted_generation,
            client_factory=client_factory,
        )

    async def handle_open(self, intent: RunnerTerminalOpenIntent) -> None:
        """Admit exactly one current-generation Terminal open intent."""
        if not self._identity_current(intent.identity):
            _LOGGER.warning(
                "Runtime Runner Terminal open intent rejected",
                extra={
                    "terminal_id": intent.identity.terminal_id,
                    "runtime_id": intent.identity.runtime_id,
                    "runner_generation": intent.identity.runner_generation,
                    "reason": "stale_runner_authority",
                },
            )
            return
        async with self._lock:
            existing = self._tasks.get(intent.identity.terminal_id)
            if existing is not None and not existing.done():
                return
            self._tasks[intent.identity.terminal_id] = asyncio.create_task(
                self._open_and_run(intent),
                name=f"runner-terminal:{intent.identity.terminal_id}",
            )

    async def handle_terminate(
        self,
        intent: RunnerTerminalTerminateIntent,
    ) -> None:
        """Terminate one exact current-generation Terminal intent."""
        if not self._identity_current(intent.identity):
            return
        cleanup = await self._registry.invalidate(
            terminal_id=intent.identity.terminal_id
        )
        async with self._lock:
            task = self._tasks.pop(intent.identity.terminal_id, None)
            client = self._clients.pop(intent.identity.terminal_id, None)
        asyncio.create_task(
            self._finish_detached(
                terminal_id=intent.identity.terminal_id,
                task=task,
                client=client,
                cleanup=cleanup,
            ),
            name=f"runner-terminal-explicit-cleanup:{intent.identity.terminal_id}",
        )

    async def _open_and_run(self, intent: RunnerTerminalOpenIntent) -> None:
        terminal_id = intent.identity.terminal_id
        try:
            terminal = await self._registry.open(
                TerminalSpec(
                    terminal_id=terminal_id,
                    runtime_id=intent.identity.runtime_id,
                    session_id=intent.owner_session_id,
                    workspace_root=self._workspace_root,
                    working_directory=Path(intent.working_directory),
                    environment=self._environment,
                    columns=intent.columns,
                    rows=intent.rows,
                    idle_deadline_at=intent.idle_deadline_at,
                    maximum_deadline_at=intent.maximum_deadline_at,
                    data_stream_grace_deadline_at=(
                        intent.data_stream_grace_deadline_at
                    ),
                )
            )
            await self._run_terminal(terminal, intent)
        except asyncio.CancelledError:
            raise
        except TerminalAdmissionError, OSError:
            _LOGGER.warning(
                "Runtime Runner Terminal open intent rejected",
                extra={
                    "terminal_id": terminal_id,
                    "runtime_id": intent.identity.runtime_id,
                    "runner_generation": intent.identity.runner_generation,
                    "reason": "local_admission_failed",
                },
            )
        except Exception:
            _LOGGER.exception(
                "Runtime Runner Terminal task failed",
                extra={
                    "terminal_id": terminal_id,
                    "runtime_id": intent.identity.runtime_id,
                    "runner_generation": intent.identity.runner_generation,
                },
            )
        finally:
            cleanup = await self._registry.invalidate(terminal_id=terminal_id)
            if cleanup is not None:
                await cleanup
            current = asyncio.current_task()
            async with self._lock:
                if self._tasks.get(terminal_id) is current:
                    self._tasks.pop(terminal_id, None)

    async def invalidate_runtime(self) -> tuple[asyncio.Task[PtyTerminalExit], ...]:
        """Fence PTYs, then close all data streams before returning authority."""
        cleanup_tasks = await self._registry.invalidate_runtime(
            runtime_id=self._runtime_id
        )
        async with self._lock:
            tasks = tuple(self._tasks.values())
            clients = tuple(self._clients.values())
            self._tasks.clear()
            self._clients.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if clients:
            await asyncio.gather(
                *(client.close() for client in clients),
                return_exceptions=True,
            )
        return tuple(cleanup_tasks)

    async def close(self) -> None:
        """Close streams and await bounded Runner-shutdown PTY cleanup."""
        cleanup_tasks = await self.invalidate_runtime()
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)

    async def _finish_detached(
        self,
        *,
        terminal_id: str,
        task: asyncio.Task[None] | None,
        client: RunnerTerminalClient | None,
        cleanup: asyncio.Task[PtyTerminalExit] | None,
    ) -> None:
        """Observe detached stream and PTY cleanup outside Runner Control."""
        if task is not None:
            task.cancel()
        results: list[object] = []
        if task is not None:
            results.extend(await asyncio.gather(task, return_exceptions=True))
        if client is not None:
            results.extend(await asyncio.gather(client.close(), return_exceptions=True))
        if cleanup is not None:
            results.extend(await asyncio.gather(cleanup, return_exceptions=True))
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                continue
            if isinstance(result, BaseException):
                _LOGGER.warning(
                    "Runtime Runner Terminal detached cleanup failed",
                    exc_info=(type(result), result, result.__traceback__),
                    extra={"terminal_id": terminal_id, "runtime_id": self._runtime_id},
                )

    async def _run_terminal(
        self,
        terminal: RunnerTerminal,
        intent: RunnerTerminalOpenIntent,
    ) -> None:
        stream_generation = intent.initial_stream_generation
        final: _TerminalFinal | None = None
        try:
            while final is None:
                if self._accepted_generation() != intent.identity.runner_generation:
                    final = _TerminalFinal(
                        RunnerTerminalTerminationReason.RUNNER_REPLACED,
                        None,
                    )
                    break
                deadline = terminal.deadline()
                if (
                    deadline is not None
                    and deadline is not TerminalDeadline.STREAM_ATTEMPT
                ):
                    final = _deadline_final(deadline)
                    break
                terminal.begin_stream_recovery()
                client = self._client_factory()
                async with self._lock:
                    if self._tasks.get(terminal.terminal_id) is asyncio.current_task():
                        self._clients[terminal.terminal_id] = client
                try:
                    final = await self._run_connection_with_grace(
                        terminal,
                        intent,
                        client,
                        stream_generation=stream_generation,
                    )
                except asyncio.CancelledError:
                    raise
                except grpc.aio.AioRpcError as error:
                    terminal.begin_stream_recovery()
                    final = _grpc_final(error)
                    if final is None:
                        stream_generation += 1
                        deadline = terminal.deadline()
                        if deadline is not None and (
                            deadline is not TerminalDeadline.STREAM_ATTEMPT
                        ):
                            final = _deadline_final(deadline)
                        else:
                            await _sleep_before_reconnect(terminal)
                except RuntimeRunnerTerminalStreamClosed, TimeoutError:
                    terminal.begin_stream_recovery()
                    stream_generation += 1
                    deadline = terminal.deadline()
                    if deadline is not None and (
                        deadline is not TerminalDeadline.STREAM_ATTEMPT
                    ):
                        final = _deadline_final(deadline)
                    else:
                        await _sleep_before_reconnect(terminal)
                except TerminalInputSequenceError:
                    final = _TerminalFinal(
                        RunnerTerminalTerminationReason.PROTOCOL_VIOLATION,
                        None,
                    )
                except TerminalAdmissionError, TerminalError, ValueError:
                    final = _TerminalFinal(
                        RunnerTerminalTerminationReason.PROTOCOL_VIOLATION,
                        None,
                    )
                finally:
                    await client.close()
                    async with self._lock:
                        if self._clients.get(terminal.terminal_id) is client:
                            self._clients.pop(terminal.terminal_id, None)
        except asyncio.CancelledError:
            raise

    async def _run_connection_with_grace(
        self,
        terminal: RunnerTerminal,
        intent: RunnerTerminalOpenIntent,
        client: RunnerTerminalClient,
        *,
        stream_generation: int,
    ) -> _TerminalFinal:
        connection_task = asyncio.create_task(
            self._run_connection(
                terminal,
                intent,
                client,
                stream_generation=stream_generation,
            )
        )
        grace_task = asyncio.create_task(_wait_for_stream_grace(terminal))
        done = set()
        try:
            done, _pending = await asyncio.wait(
                (connection_task, grace_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if grace_task in done:
                return _deadline_final(TerminalDeadline.STREAM_GRACE)
            return connection_task.result()
        finally:
            for task in (connection_task, grace_task):
                if task not in done:
                    task.cancel()
            await asyncio.gather(
                connection_task,
                grace_task,
                return_exceptions=True,
            )

    async def _run_connection(
        self,
        terminal: RunnerTerminal,
        intent: RunnerTerminalOpenIntent,
        client: RunnerTerminalClient,
        *,
        stream_generation: int,
    ) -> _TerminalFinal:
        stop: asyncio.Future[_TerminalFinal] = (
            asyncio.get_running_loop().create_future()
        )
        output_acknowledged = asyncio.Event()
        last_resize_sequence = 0
        heartbeat = _HeartbeatState()

        async def handle_control(frame: RunnerTerminalControlFrame) -> None:
            nonlocal last_resize_sequence
            try:
                match frame:
                    case RunnerTerminalInputFrame(sequence=sequence, data=data):
                        await terminal.apply_input(sequence=sequence, data=data)
                        await client.send(
                            RunnerTerminalInputAcknowledgement(sequence=sequence)
                        )
                    case RunnerTerminalResize(
                        sequence=sequence,
                        columns=columns,
                        rows=rows,
                    ):
                        if sequence <= last_resize_sequence:
                            return
                        await terminal.resize(columns=columns, rows=rows)
                        last_resize_sequence = sequence
                    case RunnerTerminalOutputAcknowledgement(sequence=sequence):
                        terminal.acknowledge_output(sequence=sequence)
                        output_acknowledged.set()
                    case RunnerTerminalTerminate(reason=reason):
                        _set_future_result(
                            stop,
                            _TerminalFinal(reason=reason, exit_code=None),
                        )
                    case RunnerTerminalHeartbeatAcknowledgement(
                        monotonic_sequence=sequence
                    ):
                        if sequence > heartbeat.sent_sequence:
                            raise ValueError(
                                "Terminal heartbeat acknowledgement exceeds "
                                "sent sequence"
                            )
                        if sequence > heartbeat.acknowledged_sequence:
                            heartbeat.acknowledged_sequence = sequence
                            heartbeat.progress.set()
                    case RunnerTerminalStreamError(code=code):
                        if code is RunnerTerminalStreamErrorCode.STALE_AUTHORITY:
                            _set_future_result(
                                stop,
                                _TerminalFinal(
                                    reason=(
                                        RunnerTerminalTerminationReason.RUNTIME_INVALIDATED
                                    ),
                                    exit_code=None,
                                ),
                            )
                        elif code is RunnerTerminalStreamErrorCode.PROTOCOL_VIOLATION:
                            _set_future_result(
                                stop,
                                _TerminalFinal(
                                    reason=(
                                        RunnerTerminalTerminationReason.PROTOCOL_VIOLATION
                                    ),
                                    exit_code=None,
                                ),
                            )
                        elif code is RunnerTerminalStreamErrorCode.TERMINATED:
                            _set_future_result(
                                stop,
                                _TerminalFinal(
                                    reason=RunnerTerminalTerminationReason.CALLER,
                                    exit_code=None,
                                ),
                            )
                        else:
                            _set_future_exception(
                                stop,
                                RuntimeRunnerTerminalStreamClosed(code.value),
                            )
            except (TerminalError, ValueError) as error:
                _set_future_exception(stop, error)

        client.set_control_handler(handle_control)
        resume = terminal.resume_state()
        accepted = await asyncio.wait_for(
            client.start(
                RunnerTerminalStreamRegistration(
                    identity=intent.identity,
                    stream_generation=stream_generation,
                    stream_nonce=intent.stream_nonce,
                    last_control_acknowledged_output_sequence=(
                        resume.last_acknowledged_output_sequence
                    ),
                    highest_completely_applied_input_sequence=(
                        resume.highest_applied_input_sequence
                    ),
                    partial_input_sequence=resume.partial_input_sequence,
                    partial_input_bytes_written=resume.partial_input_bytes_written,
                )
            ),
            timeout=30.0,
        )
        if accepted.stream_generation != stream_generation:
            raise RuntimeRunnerTerminalStreamClosed(
                "Control accepted a different Terminal stream generation"
            )
        expected_input_sequence = (
            resume.partial_input_sequence
            if resume.partial_input_sequence is not None
            else resume.highest_applied_input_sequence + 1
        )
        if accepted.next_input_sequence != expected_input_sequence:
            raise RuntimeRunnerTerminalStreamClosed(
                "Control accepted an unsafe Terminal input resume sequence"
            )
        if accepted.resume_from_output_sequence > resume.last_output_sequence + 1:
            raise RuntimeRunnerTerminalStreamClosed(
                "Control accepted an unsafe Terminal output resume sequence"
            )
        for output in terminal.output_from(
            sequence=max(accepted.resume_from_output_sequence, 1)
        ):
            await client.send(
                RunnerTerminalOutputFrame(
                    sequence=output.sequence,
                    data=output.data,
                )
            )
        terminal.mark_stream_connected()
        output_task = asyncio.create_task(
            _pump_output(terminal, client, output_acknowledged),
            name=f"runner-terminal-output:{terminal.terminal_id}",
        )
        heartbeat_task = asyncio.create_task(
            _send_heartbeats(client, heartbeat),
            name=f"runner-terminal-heartbeat:{terminal.terminal_id}",
        )
        heartbeat_health_task = asyncio.create_task(
            _watch_heartbeat_health(heartbeat),
            name=f"runner-terminal-heartbeat-health:{terminal.terminal_id}",
        )
        deadline_task = asyncio.create_task(
            _watch_deadline(terminal),
            name=f"runner-terminal-deadline:{terminal.terminal_id}",
        )
        process_task = asyncio.create_task(
            terminal.process.wait(),
            name=f"runner-terminal-process:{terminal.terminal_id}",
        )
        tasks = (
            stop,
            output_task,
            heartbeat_task,
            heartbeat_health_task,
            deadline_task,
            process_task,
        )
        done = set()
        try:
            done, _pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop in done:
                final = stop.result()
            elif process_task in done:
                final = _TerminalFinal(
                    reason=RunnerTerminalTerminationReason.PROCESS_EXIT,
                    exit_code=process_task.result(),
                )
            elif deadline_task in done:
                final = _deadline_final(deadline_task.result())
            else:
                for task in (
                    output_task,
                    heartbeat_task,
                    heartbeat_health_task,
                ):
                    if task in done:
                        task.result()
                raise RuntimeRunnerTerminalStreamClosed("Terminal data stream stopped")
            with contextlib.suppress(
                RuntimeRunnerTerminalStreamClosed,
                grpc.aio.AioRpcError,
            ):
                await client.send(
                    RunnerTerminalExit(
                        reason=final.reason,
                        exit_code=final.exit_code,
                    )
                )
            return final
        finally:
            for task in tasks:
                if task not in done:
                    task.cancel()
            await asyncio.gather(
                output_task,
                heartbeat_task,
                heartbeat_health_task,
                deadline_task,
                process_task,
                return_exceptions=True,
            )

    def _identity_current(self, identity: RunnerTerminalIdentity) -> bool:
        if identity.runtime_id != self._runtime_id:
            return False
        return self._accepted_generation() == identity.runner_generation


async def _pump_output(
    terminal: RunnerTerminal,
    client: RunnerTerminalClient,
    output_acknowledged: asyncio.Event,
) -> None:
    while True:
        try:
            output = await terminal.read_output()
        except TerminalOutputBackpressure:
            await output_acknowledged.wait()
            output_acknowledged.clear()
            continue
        await client.send(
            RunnerTerminalOutputFrame(
                sequence=output.sequence,
                data=output.data,
            )
        )


async def _send_heartbeats(
    client: RunnerTerminalClient,
    state: _HeartbeatState,
) -> None:
    while True:
        await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
        state.sent_sequence += 1
        await client.send(
            RunnerTerminalHeartbeat(monotonic_sequence=state.sent_sequence)
        )


async def _watch_heartbeat_health(state: _HeartbeatState) -> None:
    """Fail one accepted stream after 30 seconds without ack progress."""
    loop = asyncio.get_running_loop()
    observed = state.acknowledged_sequence
    last_progress_at = loop.time()
    while True:
        state.progress.clear()
        if state.acknowledged_sequence > observed:
            observed = state.acknowledged_sequence
            last_progress_at = loop.time()
            continue
        remaining = last_progress_at + _HEARTBEAT_ACK_TIMEOUT_SECONDS - loop.time()
        if remaining <= 0:
            raise RuntimeRunnerTerminalStreamClosed(
                "Terminal heartbeat acknowledgement timed out"
            )
        try:
            await asyncio.wait_for(state.progress.wait(), timeout=remaining)
        except TimeoutError:
            raise RuntimeRunnerTerminalStreamClosed(
                "Terminal heartbeat acknowledgement timed out"
            ) from None


async def _watch_deadline(terminal: RunnerTerminal) -> TerminalDeadline:
    while True:
        deadline = terminal.deadline()
        if deadline is not None and deadline is not TerminalDeadline.STREAM_ATTEMPT:
            return deadline
        await asyncio.sleep(_DEADLINE_POLL_SECONDS)


async def _wait_for_stream_grace(terminal: RunnerTerminal) -> None:
    """Wait exactly until the active overall data-stream grace expires."""
    while True:
        remaining = terminal.stream_grace_remaining_seconds()
        if remaining is None:
            await asyncio.Future()
            continue
        if remaining <= 0:
            return
        await asyncio.sleep(remaining)


async def _sleep_before_reconnect(terminal: RunnerTerminal) -> None:
    """Keep reconnect delay inside the remaining overall stream grace."""
    remaining = terminal.stream_grace_remaining_seconds()
    delay = _RECONNECT_DELAY_SECONDS
    if remaining is not None:
        delay = min(delay, remaining)
    if delay > 0:
        await asyncio.sleep(delay)


def _deadline_final(deadline: TerminalDeadline) -> _TerminalFinal:
    return _TerminalFinal(
        reason={
            TerminalDeadline.IDLE: RunnerTerminalTerminationReason.IDLE,
            TerminalDeadline.MAXIMUM_LIFETIME: (
                RunnerTerminalTerminationReason.MAXIMUM_LIFETIME
            ),
            TerminalDeadline.STREAM_GRACE: (
                RunnerTerminalTerminationReason.DATA_STREAM_GRACE_EXPIRED
            ),
            TerminalDeadline.STREAM_ATTEMPT: (
                RunnerTerminalTerminationReason.DATA_STREAM_GRACE_EXPIRED
            ),
        }[deadline],
        exit_code=None,
    )


def _grpc_final(error: grpc.aio.AioRpcError) -> _TerminalFinal | None:
    if error.code() in {
        grpc.StatusCode.UNAUTHENTICATED,
        grpc.StatusCode.PERMISSION_DENIED,
    }:
        return _TerminalFinal(
            reason=RunnerTerminalTerminationReason.RUNTIME_INVALIDATED,
            exit_code=None,
        )
    if error.code() is grpc.StatusCode.INVALID_ARGUMENT:
        return _TerminalFinal(
            reason=RunnerTerminalTerminationReason.PROTOCOL_VIOLATION,
            exit_code=None,
        )
    if error.code() is grpc.StatusCode.FAILED_PRECONDITION:
        return _TerminalFinal(
            reason=RunnerTerminalTerminationReason.CALLER,
            exit_code=None,
        )
    return None


def _set_future_result(
    future: asyncio.Future[_TerminalFinal],
    value: _TerminalFinal,
) -> None:
    if not future.done():
        future.set_result(value)


def _set_future_exception(
    future: asyncio.Future[_TerminalFinal],
    error: Exception,
) -> None:
    if not future.done():
        future.set_exception(error)
