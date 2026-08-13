"""Runtime Runner process execution primitives."""

import asyncio
import logging
import os
import signal
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

_BASH_PATH = "/bin/bash"


@dataclass(frozen=True)
class ExecutionSpec:
    """Process execution request."""

    argv: tuple[str, ...]
    cwd: Path
    environment: Mapping[str, str]
    stdin: bool
    managed: bool


@dataclass(frozen=True)
class ProcessTerminationResult:
    """Bounded complete-descendant termination result."""

    already_exited: bool
    escalated: bool
    timed_out: bool


class ExecutionProcess(Protocol):
    """Started process handle."""

    @property
    def stdout(self) -> asyncio.StreamReader:
        """Return the process stdout stream."""
        ...

    @property
    def stderr(self) -> asyncio.StreamReader:
        """Return the process stderr stream."""
        ...

    @property
    def returncode(self) -> int | None:
        """Return the terminal exit code when available."""
        ...

    async def wait(self) -> int:
        """Wait for terminal process exit."""
        ...

    async def write_stdin(self, data: bytes) -> None:
        """Write bytes to process stdin when available."""
        ...

    async def terminate_descendants(
        self,
        *,
        terminate_timeout_seconds: float,
        kill_timeout_seconds: float,
    ) -> ProcessTerminationResult:
        """Terminate the complete process group."""
        ...


class ExecutionBackend(Protocol):
    """Runner process execution boundary."""

    def agent_environment(
        self,
        *,
        workspace_path: str,
        operation_environment: Mapping[str, str],
    ) -> Mapping[str, str]:
        """Build the Agent process environment."""
        ...

    async def start(self, spec: ExecutionSpec) -> ExecutionProcess:
        """Start one process."""
        ...

    async def close(self) -> None:
        """Close backend-owned resources."""
        ...


type ProcessLauncher = Callable[[ExecutionSpec], Awaitable[ExecutionProcess]]


class DirectExecutionBackend:
    """Direct Runner process execution."""

    def __init__(
        self,
        *,
        inherited_environment: Mapping[str, str] | None = None,
        launcher: ProcessLauncher | None = None,
    ) -> None:
        self._inherited_environment = dict(inherited_environment or {})
        self._launcher = launcher or _launch_subprocess

    def agent_environment(
        self,
        *,
        workspace_path: str,
        operation_environment: Mapping[str, str],
    ) -> Mapping[str, str]:
        del workspace_path
        environment = dict(os.environ)
        environment.update(operation_environment)
        environment.update(self._inherited_environment)
        return environment

    async def start(self, spec: ExecutionSpec) -> ExecutionProcess:
        return await self._launcher(spec)

    async def close(self) -> None:
        return


def shell_execution_spec(
    *,
    backend: ExecutionBackend,
    command: str,
    cwd: Path,
    workspace_path: str,
    operation_environment: Mapping[str, str],
    managed: bool,
) -> ExecutionSpec:
    """Build the fixed shell execution request used by Runner operations."""
    return ExecutionSpec(
        argv=(_BASH_PATH, "-lc", command),
        cwd=cwd,
        environment=backend.agent_environment(
            workspace_path=workspace_path,
            operation_environment=operation_environment,
        ),
        stdin=managed,
        managed=managed,
    )


class _SubprocessExecutionProcess:
    """Process handle backed by one operating-system process group."""

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        if process.stdout is None or process.stderr is None:
            raise RuntimeError("process stdout/stderr pipes are required")
        self._process = process
        self._process_group_id = process.pid
        self._stdout = process.stdout
        self._stderr = process.stderr

    @property
    def stdout(self) -> asyncio.StreamReader:
        return self._stdout

    @property
    def stderr(self) -> asyncio.StreamReader:
        return self._stderr

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    async def wait(self) -> int:
        return await self._process.wait()

    async def write_stdin(self, data: bytes) -> None:
        writer = self._process.stdin
        if writer is None or writer.is_closing():
            return
        try:
            writer.write(data)
            await writer.drain()
        except BrokenPipeError, ConnectionError, RuntimeError:
            return

    async def terminate_descendants(
        self,
        *,
        terminate_timeout_seconds: float,
        kill_timeout_seconds: float,
    ) -> ProcessTerminationResult:
        already_exited = self.returncode is not None
        if already_exited:
            return ProcessTerminationResult(
                already_exited=True,
                escalated=False,
                timed_out=False,
            )
        _signal_process_group(self._process_group_id, signal.SIGTERM)
        if await _wait_process(self._process, terminate_timeout_seconds):
            return ProcessTerminationResult(
                already_exited=False,
                escalated=False,
                timed_out=False,
            )
        _signal_process_group(self._process_group_id, signal.SIGKILL)
        killed = await _wait_process(self._process, kill_timeout_seconds)
        return ProcessTerminationResult(
            already_exited=False,
            escalated=True,
            timed_out=not killed,
        )


async def _launch_subprocess(spec: ExecutionSpec) -> ExecutionProcess:
    process = await asyncio.create_subprocess_exec(
        *spec.argv,
        cwd=spec.cwd,
        env=dict(spec.environment),
        stdin=asyncio.subprocess.PIPE if spec.stdin else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    return _SubprocessExecutionProcess(process)


async def _wait_process(
    process: asyncio.subprocess.Process,
    timeout_seconds: float,
) -> bool:
    wait_task = asyncio.create_task(process.wait())
    try:
        await asyncio.wait_for(
            asyncio.shield(wait_task),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        wait_task.cancel()
        await asyncio.gather(wait_task, return_exceptions=True)
        return False
    return True


def _signal_process_group(
    process_group_id: int,
    requested_signal: signal.Signals,
) -> None:
    try:
        os.killpg(process_group_id, requested_signal)
    except ProcessLookupError:
        return
    except PermissionError as error:
        logger.exception(
            "Runtime Runner process group signal denied",
            extra={
                "process_group_id": process_group_id,
                "signal": requested_signal.name,
            },
        )
        raise RuntimeError("Runtime Runner process group signal was denied.") from error
