"""Runner-owned process execution and containment backends."""

import asyncio
import json
import logging
import os
import signal
import sys
import tempfile
import textwrap
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from azents_runtime_runner.environment import build_contained_agent_environment
from azents_runtime_runner.workspace import FilesystemAccessPolicy

logger = logging.getLogger(__name__)

_BOOTSTRAP_ENV_NAME = "AZ_RUNTIME_PROCESS_CONTAINMENT_CONFIG"
_BWRAP_PATH = "/opt/azents-runtime/bin/bwrap"
_BWRAP_LAUNCHER_PATH = Path(__file__).with_name("bwrap_launcher.py").resolve()
_BASH_PATH = "/bin/bash"
_QUALIFICATION_PYTHON_PATH = "/usr/local/bin/python"
_QUALIFICATION_SCHEMA_VERSION = 1
_MIN_QUALIFICATION_TIMEOUT_SECONDS = 1
_MAX_QUALIFICATION_TIMEOUT_SECONDS = 60
_DIRECT_TEMPORARY_PATH = "/tmp"
_TERMINATE_TIMEOUT_SECONDS = 2.0
_KILL_TIMEOUT_SECONDS = 2.0
_QUALIFICATION_DIAGNOSTIC_LIMIT = 1000
_QUALIFICATION_LOCK_FILENAME = "descendant.lock"
_QUALIFICATION_READY_FILENAME = "descendant.ready"
_SYSTEM_READ_ONLY_PATHS = (
    "/usr",
    "/usr/local",
    "/etc/alternatives",
    "/etc/fonts",
    "/etc/hosts",
    "/etc/ld.so.cache",
    "/etc/localtime",
    "/etc/nsswitch.conf",
    "/etc/passwd",
    "/etc/group",
    "/etc/resolv.conf",
    "/etc/ssl",
    "/etc/terminfo",
    "/etc/timezone",
)
_FILESYSTEM_READ_ONLY_PATHS = (
    *(Path(path) for path in _SYSTEM_READ_ONLY_PATHS),
    Path("/bin"),
    Path("/lib"),
    Path("/lib64"),
    Path("/sbin"),
)
_AUTHORITY_PROBE_FUNCTIONS = textwrap.dedent(
    """
    import json
    import os
    import pathlib
    import subprocess
    import sys
    import tempfile

    def status_fields():
        fields = {}
        for line in pathlib.Path("/proc/self/status").read_text().splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                fields[key] = value.strip()
        return fields

    def authority_failures(workspace, hidden_paths):
        status = status_fields()
        capability_fields = ("CapEff", "CapPrm", "CapInh", "CapAmb", "CapBnd")
        checks = {
            "uid": os.getuid() == 1000,
            "gid": os.getgid() == 1000,
            "capabilities": all(
                int(status[name], 16) == 0 for name in capability_fields
            ),
            "no_new_privileges": status.get("NoNewPrivs") == "1",
            "workspace": workspace.is_dir() and os.access(workspace, os.W_OK),
            "temporary": pathlib.Path("/tmp").is_dir() and os.access("/tmp", os.W_OK),
            "system_read_only": not os.access("/usr", os.W_OK),
            "hidden_paths": all(not path.exists() for path in hidden_paths),
            "reserved_environment": not any(
                name.startswith(("AZ_RUNTIME_", "AZENTS_RUNTIME_"))
                for name in os.environ
            ),
            "process_view": len(
                [
                    entry
                    for entry in pathlib.Path("/proc").iterdir()
                    if entry.name.isdigit()
                ]
            )
            <= 4,
        }
        with tempfile.NamedTemporaryFile(dir=workspace, delete=True):
            pass
        with tempfile.NamedTemporaryFile(dir="/tmp", delete=True):
            pass
        nested = subprocess.run(
            ["/usr/bin/unshare", "--user", "true"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        checks["nested_user_namespace"] = nested.returncode != 0
        return sorted(name for name, passed in checks.items() if not passed)
    """
).strip()
_DESCENDANT_AUTHORITY_SCRIPT = (
    _AUTHORITY_PROBE_FUNCTIONS
    + "\n"
    + textwrap.dedent(
        """
        workspace = pathlib.Path(sys.argv[1])
        hidden_paths = tuple(pathlib.Path(value) for value in sys.argv[2:])
        failed = authority_failures(workspace, hidden_paths)
        print(json.dumps({"failed": failed}, separators=(",", ":")))
        raise SystemExit(1 if failed else 0)
        """
    ).strip()
)
_QUALIFICATION_SCRIPT = (
    _AUTHORITY_PROBE_FUNCTIONS
    + "\n"
    + textwrap.dedent(
        f"""
        workspace = pathlib.Path(sys.argv[1])
        hidden_paths = tuple(pathlib.Path(value) for value in sys.argv[2:])
        failed = authority_failures(workspace, hidden_paths)
        descendant = subprocess.run(
            [
                sys.executable,
                "-c",
                {_DESCENDANT_AUTHORITY_SCRIPT!r},
                str(workspace),
                *(str(path) for path in hidden_paths),
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if descendant.returncode != 0:
            failed.append("descendant_authority")
        print(json.dumps({{"failed": sorted(failed)}}, separators=(",", ":")))
        raise SystemExit(1 if failed else 0)
        """
    ).strip()
)
_DESCENDANT_LOCK_HOLDER_SCRIPT = textwrap.dedent(
    """
    import fcntl
    import pathlib
    import sys
    import time

    lock_path = pathlib.Path(sys.argv[1])
    ready_path = pathlib.Path(sys.argv[2])
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        ready_path.write_text("ready")
        while True:
            time.sleep(60)
    """
).strip()
_TERMINATION_CANARY_SCRIPT = textwrap.dedent(
    f"""
    import pathlib
    import subprocess
    import sys
    import time

    lock_path = pathlib.Path(sys.argv[1])
    ready_path = pathlib.Path(sys.argv[2])
    descendant = subprocess.Popen(
        [
            sys.executable,
            "-c",
            {_DESCENDANT_LOCK_HOLDER_SCRIPT!r},
            str(lock_path),
            str(ready_path),
        ]
    )
    while not ready_path.exists():
        if descendant.poll() is not None:
            raise SystemExit(1)
        time.sleep(0.01)
    print("ready", flush=True)
    while True:
        time.sleep(60)
    """
).strip()


@dataclass(frozen=True)
class ContainmentBootstrapConfig:
    """Trusted Provider-supplied contained Runner bootstrap configuration."""

    backend: Literal["bwrap"]
    agent_workspace_path: Path
    agent_temporary_path: Path
    runner_private_paths: tuple[Path, ...]
    qualification_timeout_seconds: int


@dataclass(frozen=True)
class ExecutionSpec:
    """Backend-neutral process execution request."""

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
    """Backend-neutral started process handle."""

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
        """Terminate the complete backend-owned descendant group."""
        ...


class ExecutionBackend(Protocol):
    """Backend-neutral Runner process execution boundary."""

    @property
    def kind(self) -> str:
        """Return the safe backend family identifier."""
        ...

    @property
    def filesystem_access_policy(self) -> FilesystemAccessPolicy:
        """Return the common filesystem authority enforced by this Runtime."""
        ...

    def agent_environment(
        self,
        *,
        workspace_path: str,
        operation_environment: Mapping[str, str],
    ) -> Mapping[str, str]:
        """Build the Agent process environment enforced by this backend."""
        ...

    async def qualify(self) -> None:
        """Qualify the backend before normal Runner registration."""
        ...

    async def start(self, spec: ExecutionSpec) -> ExecutionProcess:
        """Start one process through this backend."""
        ...

    async def close(self) -> None:
        """Close backend-owned resources."""
        ...


class ContainmentBootstrapError(ValueError):
    """Trusted containment bootstrap is invalid."""


class ContainmentQualificationError(RuntimeError):
    """Contained backend qualification failed."""

    def __init__(self, category: str) -> None:
        super().__init__(
            f"Runtime process containment qualification failed: {category}"
        )
        self.category = category


type ProcessLauncher = Callable[[ExecutionSpec], Awaitable[ExecutionProcess]]


class DirectExecutionBackend:
    """Explicit uncontained process backend retained for Profile v1."""

    def __init__(self, *, launcher: ProcessLauncher | None = None) -> None:
        self._launcher = launcher or _launch_subprocess

    @property
    def kind(self) -> str:
        return "direct"

    @property
    def filesystem_access_policy(self) -> FilesystemAccessPolicy:
        return FilesystemAccessPolicy.unrestricted()

    def agent_environment(
        self,
        *,
        workspace_path: str,
        operation_environment: Mapping[str, str],
    ) -> Mapping[str, str]:
        del workspace_path
        environment = dict(os.environ)
        environment.update(operation_environment)
        return environment

    async def qualify(self) -> None:
        return

    async def start(self, spec: ExecutionSpec) -> ExecutionProcess:
        return await self._launcher(spec)

    async def close(self) -> None:
        return


class BwrapExecutionBackend:
    """Initial bubblewrap contained process backend."""

    def __init__(
        self,
        config: ContainmentBootstrapConfig,
        *,
        launcher: ProcessLauncher | None = None,
    ) -> None:
        self._config = config
        self._launcher = launcher or _launch_subprocess

    @property
    def kind(self) -> str:
        return "bwrap"

    @property
    def filesystem_access_policy(self) -> FilesystemAccessPolicy:
        return FilesystemAccessPolicy.contained(
            temporary_backing_path=self._config.agent_temporary_path,
            read_only_paths=_FILESYSTEM_READ_ONLY_PATHS,
            denied_paths=self._config.runner_private_paths,
        )

    def agent_environment(
        self,
        *,
        workspace_path: str,
        operation_environment: Mapping[str, str],
    ) -> Mapping[str, str]:
        return build_contained_agent_environment(
            workspace_path=workspace_path,
            operation_environment=operation_environment,
        )

    async def qualify(self) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._config.qualification_timeout_seconds
        qualification = ExecutionSpec(
            argv=(
                _QUALIFICATION_PYTHON_PATH,
                "-c",
                _QUALIFICATION_SCRIPT,
                str(self._config.agent_workspace_path),
                _BWRAP_PATH,
                *(str(path) for path in self._config.runner_private_paths),
            ),
            cwd=self._config.agent_workspace_path,
            environment=self.agent_environment(
                workspace_path=str(self._config.agent_workspace_path),
                operation_environment={},
            ),
            stdin=False,
            managed=False,
        )
        try:
            process = await self._start_qualification_process(
                qualification,
                deadline=deadline,
            )
            returncode = await asyncio.wait_for(
                process.wait(),
                timeout=_remaining_timeout(deadline),
            )
        except TimeoutError as error:
            if "process" in locals():
                await _terminate_qualification_process(
                    process,
                    terminate_timeout_seconds=_TERMINATE_TIMEOUT_SECONDS,
                    kill_timeout_seconds=_KILL_TIMEOUT_SECONDS,
                )
            raise ContainmentQualificationError("timeout") from error
        if returncode != 0:
            stdout, stderr = await asyncio.gather(
                process.stdout.read(),
                process.stderr.read(),
            )
            logger.error(
                "Runtime Runner process containment authority probe failed",
                extra={
                    "failure_category": "probe_failed",
                    "probe_failures": _qualification_probe_failures(stdout),
                    "backend_stderr": _bounded_diagnostic_text(stderr),
                },
            )
            raise ContainmentQualificationError("probe_failed")
        with tempfile.TemporaryDirectory(
            dir=self._config.agent_workspace_path,
            prefix=".azents-containment-qualification-",
        ) as probe_directory:
            probe_path = Path(probe_directory)
            lock_path = probe_path / _QUALIFICATION_LOCK_FILENAME
            ready_path = probe_path / _QUALIFICATION_READY_FILENAME
            termination_canary = ExecutionSpec(
                argv=(
                    _QUALIFICATION_PYTHON_PATH,
                    "-c",
                    _TERMINATION_CANARY_SCRIPT,
                    str(lock_path),
                    str(ready_path),
                ),
                cwd=self._config.agent_workspace_path,
                environment=self.agent_environment(
                    workspace_path=str(self._config.agent_workspace_path),
                    operation_environment={},
                ),
                stdin=False,
                managed=False,
            )
            try:
                process = await self._start_qualification_process(
                    termination_canary,
                    deadline=deadline,
                )
                ready = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=_remaining_timeout(deadline),
                )
            except TimeoutError as error:
                if "process" in locals():
                    await _terminate_qualification_process(
                        process,
                        terminate_timeout_seconds=_TERMINATE_TIMEOUT_SECONDS,
                        kill_timeout_seconds=_KILL_TIMEOUT_SECONDS,
                    )
                raise ContainmentQualificationError("timeout") from error
            if ready != b"ready\n":
                await _terminate_qualification_process(
                    process,
                    terminate_timeout_seconds=_TERMINATE_TIMEOUT_SECONDS,
                    kill_timeout_seconds=_KILL_TIMEOUT_SECONDS,
                )
                raise ContainmentQualificationError("probe_failed")
            remaining = _remaining_timeout(deadline)
            await _terminate_qualification_process(
                process,
                terminate_timeout_seconds=min(
                    _TERMINATE_TIMEOUT_SECONDS,
                    remaining / 2,
                ),
                kill_timeout_seconds=min(
                    _KILL_TIMEOUT_SECONDS,
                    remaining / 2,
                ),
            )
            if not _exclusive_lock_available(lock_path):
                raise ContainmentQualificationError("termination_failed")

    async def _start_qualification_process(
        self,
        spec: ExecutionSpec,
        *,
        deadline: float,
    ) -> ExecutionProcess:
        try:
            return await asyncio.wait_for(
                self.start(spec),
                timeout=_remaining_timeout(deadline),
            )
        except TimeoutError:
            raise
        except (OSError, RuntimeError) as error:
            raise ContainmentQualificationError("backend_unavailable") from error

    async def start(self, spec: ExecutionSpec) -> ExecutionProcess:
        return await self._launcher(
            ExecutionSpec(
                argv=self._bwrap_argv(spec),
                cwd=Path("/"),
                environment={},
                stdin=spec.stdin,
                managed=spec.managed,
            )
        )

    async def close(self) -> None:
        return

    def _bwrap_argv(self, spec: ExecutionSpec) -> tuple[str, ...]:
        argv = [
            sys.executable,
            str(_BWRAP_LAUNCHER_PATH),
            _BWRAP_PATH,
            "--die-with-parent",
            "--new-session",
            "--unshare-user",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--cap-drop",
            "ALL",
            "--clearenv",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/run",
            "--dir",
            "/etc",
            "--dir",
            "/workspace",
            "--symlink",
            "usr/bin",
            "/bin",
            "--symlink",
            "usr/lib",
            "/lib",
            "--symlink",
            "usr/lib64",
            "/lib64",
            "--symlink",
            "usr/sbin",
            "/sbin",
        ]
        for path in _SYSTEM_READ_ONLY_PATHS:
            argv.extend(("--ro-bind-try", path, path))
        argv.extend(_parent_directory_arguments(self._config.agent_workspace_path))
        argv.extend(
            (
                "--bind",
                str(self._config.agent_workspace_path),
                str(self._config.agent_workspace_path),
                "--bind",
                str(self._config.agent_temporary_path),
                "/tmp",
                "--dir",
                "/tmp/agent",
            )
        )
        for name, value in sorted(spec.environment.items()):
            argv.extend(("--setenv", name, value))
        argv.extend(("--chdir", str(spec.cwd), "--", *spec.argv))
        return tuple(argv)


def execution_backend_from_environment(
    *,
    workspace_path: str,
    environment: Mapping[str, str] | None = None,
    launcher: ProcessLauncher | None = None,
) -> ExecutionBackend:
    """Select one explicit direct or configured contained backend."""
    source = os.environ if environment is None else environment
    raw_config = source.get(_BOOTSTRAP_ENV_NAME)
    if raw_config is None:
        return DirectExecutionBackend(launcher=launcher)
    config = parse_containment_bootstrap(
        raw_config,
        workspace_path=workspace_path,
    )
    return BwrapExecutionBackend(config, launcher=launcher)


def parse_containment_bootstrap(
    value: str,
    *,
    workspace_path: str,
) -> ContainmentBootstrapConfig:
    """Parse one exact trusted containment bootstrap document."""
    try:
        document = json.loads(value)
    except json.JSONDecodeError as error:
        raise ContainmentBootstrapError(
            "Runtime process containment bootstrap JSON is invalid."
        ) from error
    if not isinstance(document, dict):
        raise ContainmentBootstrapError(
            "Runtime process containment bootstrap must contain an object."
        )
    expected_fields = {
        "schema_version",
        "backend",
        "agent_workspace_path",
        "agent_temporary_path",
        "runner_private_paths",
        "qualification_timeout_seconds",
    }
    if set(document) != expected_fields:
        raise ContainmentBootstrapError(
            "Runtime process containment bootstrap document shape is invalid."
        )
    if document["schema_version"] != _QUALIFICATION_SCHEMA_VERSION:
        raise ContainmentBootstrapError(
            "Runtime process containment bootstrap schema version is unsupported."
        )
    if document["backend"] != "bwrap":
        raise ContainmentBootstrapError(
            "Runtime process containment backend is unsupported."
        )
    configured_workspace = _absolute_path(
        document["agent_workspace_path"],
        "Agent Workspace",
    )
    resolved_workspace = Path(workspace_path).resolve(strict=False)
    if configured_workspace != resolved_workspace:
        raise ContainmentBootstrapError(
            "Runtime process containment Agent Workspace does not match Runner input."
        )
    temporary_path = _absolute_path(
        document["agent_temporary_path"],
        "Agent temporary path",
    )
    if _paths_overlap(configured_workspace, temporary_path):
        raise ContainmentBootstrapError(
            "Runtime process containment Agent temporary path must be separate."
        )
    raw_private_paths = document["runner_private_paths"]
    if not isinstance(raw_private_paths, list) or not raw_private_paths:
        raise ContainmentBootstrapError(
            "Runtime process containment Runner-private paths are required."
        )
    private_paths = tuple(
        _absolute_path(item, "Runner-private path") for item in raw_private_paths
    )
    if len(set(private_paths)) != len(private_paths):
        raise ContainmentBootstrapError(
            "Runtime process containment Runner-private paths must be unique."
        )
    if any(
        _paths_overlap(path, configured_workspace)
        or _paths_overlap(path, temporary_path)
        for path in private_paths
    ):
        raise ContainmentBootstrapError(
            "Runtime process containment Runner-private paths must be separate."
        )
    timeout = document["qualification_timeout_seconds"]
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, int)
        or not _MIN_QUALIFICATION_TIMEOUT_SECONDS
        <= timeout
        <= _MAX_QUALIFICATION_TIMEOUT_SECONDS
    ):
        raise ContainmentBootstrapError(
            "Runtime process containment qualification timeout is invalid."
        )
    return ContainmentBootstrapConfig(
        backend="bwrap",
        agent_workspace_path=configured_workspace,
        agent_temporary_path=temporary_path,
        runner_private_paths=private_paths,
        qualification_timeout_seconds=timeout,
    )


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
    """Process handle backed by one isolated operating-system process group."""

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


def _absolute_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ContainmentBootstrapError(
            f"Runtime process containment {label} is invalid."
        )
    path = Path(value)
    if not path.is_absolute():
        raise ContainmentBootstrapError(
            f"Runtime process containment {label} must be absolute."
        )
    return path.resolve(strict=False)


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _parent_directory_arguments(path: Path) -> tuple[str, ...]:
    arguments: list[str] = []
    parents: Sequence[Path] = tuple(reversed(path.parents))
    for parent in parents:
        if parent == Path("/"):
            continue
        arguments.extend(("--dir", str(parent)))
    return tuple(arguments)


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise TimeoutError
    return remaining


def _qualification_probe_failures(stdout: bytes) -> str:
    try:
        payload = json.loads(stdout)
    except UnicodeDecodeError, json.JSONDecodeError:
        return "unavailable"
    if not isinstance(payload, dict):
        return "unavailable"
    failures = payload.get("failed")
    if not isinstance(failures, list) or not all(
        isinstance(item, str) for item in failures
    ):
        return "unavailable"
    return ",".join(sorted(failures)) or "none"


def _bounded_diagnostic_text(value: bytes) -> str:
    text = value.decode(errors="replace").strip().replace("\n", " ")
    if not text:
        return "unavailable"
    return text[:_QUALIFICATION_DIAGNOSTIC_LIMIT]


async def _terminate_qualification_process(
    process: ExecutionProcess,
    *,
    terminate_timeout_seconds: float,
    kill_timeout_seconds: float,
) -> None:
    try:
        termination = await process.terminate_descendants(
            terminate_timeout_seconds=terminate_timeout_seconds,
            kill_timeout_seconds=kill_timeout_seconds,
        )
    except (OSError, RuntimeError) as error:
        raise ContainmentQualificationError("termination_failed") from error
    if termination.timed_out:
        raise ContainmentQualificationError("termination_failed")


def _exclusive_lock_available(path: Path) -> bool:
    # Keep the Linux-only bwrap probe off the module import path.
    import fcntl  # noqa: PLC0415

    with path.open("a") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(lock_file, fcntl.LOCK_UN)
    return True
