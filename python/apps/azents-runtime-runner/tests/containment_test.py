"""Runner process containment backend tests."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

from azents_runtime_runner.containment import (
    BwrapExecutionBackend,
    ContainmentBootstrapError,
    ContainmentQualificationError,
    DirectExecutionBackend,
    ExecutionProcess,
    ExecutionSpec,
    ProcessTerminationResult,
    execution_backend_from_environment,
    parse_containment_bootstrap,
    shell_execution_spec,
)


class _FakeProcess:
    def __init__(
        self,
        *,
        returncode: int = 0,
        wait_forever: bool = False,
        stdout: bytes = b"",
        termination_error: bool = False,
    ) -> None:
        self._returncode = None if wait_forever else returncode
        self._terminal_returncode = returncode
        self._wait_forever = wait_forever
        self._stdout = asyncio.StreamReader()
        self._stdout.feed_data(stdout)
        self._stdout.feed_eof()
        self._stderr = asyncio.StreamReader()
        self._stderr.feed_eof()
        self.writes: list[bytes] = []
        self.termination_calls = 0
        self.termination_error = termination_error

    @property
    def stdout(self) -> asyncio.StreamReader:
        return self._stdout

    @property
    def stderr(self) -> asyncio.StreamReader:
        return self._stderr

    @property
    def returncode(self) -> int | None:
        return self._returncode

    async def wait(self) -> int:
        if self._wait_forever:
            await asyncio.Future()
        self._returncode = self._terminal_returncode
        return self._terminal_returncode

    async def write_stdin(self, data: bytes) -> None:
        self.writes.append(data)

    async def terminate_descendants(
        self,
        *,
        terminate_timeout_seconds: float,
        kill_timeout_seconds: float,
    ) -> ProcessTerminationResult:
        del terminate_timeout_seconds, kill_timeout_seconds
        self.termination_calls += 1
        if self.termination_error:
            raise RuntimeError("termination failed")
        self._wait_forever = False
        self._returncode = -15
        return ProcessTerminationResult(
            already_exited=False,
            escalated=False,
            timed_out=False,
        )


def _bootstrap(workspace: Path, temporary: Path) -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "backend": "bwrap",
            "agent_workspace_path": str(workspace),
            "agent_temporary_path": str(temporary),
            "runner_private_paths": ["/runner/private", "/run/runner.sock"],
            "qualification_timeout_seconds": 5,
        }
    )


def test_absent_bootstrap_selects_explicit_direct_backend(tmp_path: Path) -> None:
    backend = execution_backend_from_environment(
        workspace_path=str(tmp_path),
        environment={},
    )

    assert isinstance(backend, DirectExecutionBackend)
    assert backend.kind == "direct"


def test_contained_bootstrap_selects_bwrap_backend(tmp_path: Path) -> None:
    temporary = tmp_path.parent / f"{tmp_path.name}-temporary"
    backend = execution_backend_from_environment(
        workspace_path=str(tmp_path),
        environment={
            "AZ_RUNTIME_PROCESS_CONTAINMENT_CONFIG": _bootstrap(
                tmp_path,
                temporary,
            )
        },
    )

    assert isinstance(backend, BwrapExecutionBackend)
    assert backend.kind == "bwrap"


@pytest.mark.parametrize(
    "update",
    [
        {"schema_version": 2},
        {"backend": "unknown"},
        {"agent_workspace_path": "/different"},
        {"agent_temporary_path": "relative/tmp"},
        {"runner_private_paths": []},
        {"qualification_timeout_seconds": 0},
    ],
)
def test_invalid_contained_bootstrap_fails_closed(
    tmp_path: Path,
    update: dict[str, object],
) -> None:
    temporary = tmp_path.parent / f"{tmp_path.name}-temporary"
    document = json.loads(_bootstrap(tmp_path, temporary))
    document.update(update)

    with pytest.raises(ContainmentBootstrapError):
        parse_containment_bootstrap(
            json.dumps(document),
            workspace_path=str(tmp_path),
        )


def test_contained_bootstrap_rejects_workspace_temporary_overlap(
    tmp_path: Path,
) -> None:
    temporary = tmp_path.parent / f"{tmp_path.name}-temporary"
    document = json.loads(_bootstrap(tmp_path, temporary))
    document["agent_temporary_path"] = str(tmp_path / "tmp")

    with pytest.raises(ContainmentBootstrapError, match="must be separate"):
        parse_containment_bootstrap(
            json.dumps(document),
            workspace_path=str(tmp_path),
        )


@pytest.mark.asyncio
async def test_direct_backend_launches_backend_neutral_spec(tmp_path: Path) -> None:
    launched: list[ExecutionSpec] = []
    process = _FakeProcess()

    async def launcher(spec: ExecutionSpec) -> ExecutionProcess:
        launched.append(spec)
        return process

    backend = DirectExecutionBackend(launcher=launcher)
    spec = shell_execution_spec(
        command="printf hello",
        cwd=tmp_path,
        workspace_path=str(tmp_path),
        operation_environment={"TOOL_TOKEN": "value"},
        managed=True,
    )

    assert backend.helper_python_path == sys.executable
    assert await backend.start(spec) is process
    assert launched == [spec]
    assert spec.argv == ("/bin/bash", "-lc", "printf hello")
    assert spec.environment["HOME"] == str(tmp_path)
    assert spec.environment["TOOL_TOKEN"] == "value"


@pytest.mark.asyncio
async def test_bwrap_backend_owns_positive_projection_arguments(tmp_path: Path) -> None:
    temporary = tmp_path.parent / f"{tmp_path.name}-temporary"
    config = parse_containment_bootstrap(
        _bootstrap(tmp_path, temporary),
        workspace_path=str(tmp_path),
    )
    launched: list[ExecutionSpec] = []
    process = _FakeProcess()

    async def launcher(spec: ExecutionSpec) -> ExecutionProcess:
        launched.append(spec)
        return process

    backend = BwrapExecutionBackend(config, launcher=launcher)
    assert backend.helper_python_path == "/usr/local/bin/python"
    await backend.start(
        shell_execution_spec(
            command="id",
            cwd=tmp_path,
            workspace_path=str(tmp_path),
            operation_environment={},
            managed=False,
        )
    )

    wrapped = launched[0]
    assert wrapped.argv[0] == sys.executable
    assert wrapped.argv[1].endswith("/azents_runtime_runner/bwrap_launcher.py")
    assert wrapped.argv[2] == "/usr/bin/bwrap"
    assert "--unshare-pid" in wrapped.argv
    assert "--disable-userns" not in wrapped.argv
    assert "--assert-userns-disabled" not in wrapped.argv
    assert "--uid" not in wrapped.argv
    assert "--gid" not in wrapped.argv
    assert ("--ro-bind", "/dev/null", "/usr/bin/bwrap") == tuple(
        wrapped.argv[
            wrapped.argv.index("/dev/null") - 1 : wrapped.argv.index("/dev/null") + 2
        ]
    )
    assert ("--bind", str(tmp_path), str(tmp_path)) == tuple(
        wrapped.argv[
            wrapped.argv.index(str(tmp_path)) - 1 : wrapped.argv.index(str(tmp_path))
            + 2
        ]
    )
    assert str(temporary) in wrapped.argv
    assert "/runner/private" not in wrapped.argv
    assert "contained_helper.py" in " ".join(wrapped.argv)
    assert "contained_protocol.py" in " ".join(wrapped.argv)
    assert "apply_patch.py" in " ".join(wrapped.argv)
    assert wrapped.argv[-3:] == ("/bin/bash", "-lc", "id")


@pytest.mark.asyncio
async def test_bwrap_qualification_failure_has_bounded_category(tmp_path: Path) -> None:
    temporary = tmp_path.parent / f"{tmp_path.name}-temporary"
    config = parse_containment_bootstrap(
        _bootstrap(tmp_path, temporary),
        workspace_path=str(tmp_path),
    )

    async def launcher(spec: ExecutionSpec) -> ExecutionProcess:
        del spec
        return _FakeProcess(returncode=1)

    backend = BwrapExecutionBackend(config, launcher=launcher)

    with pytest.raises(ContainmentQualificationError) as raised:
        await backend.qualify()

    assert raised.value.category == "probe_failed"


@pytest.mark.asyncio
async def test_bwrap_qualification_unavailable_has_bounded_category(
    tmp_path: Path,
) -> None:
    temporary = tmp_path.parent / f"{tmp_path.name}-temporary"
    config = parse_containment_bootstrap(
        _bootstrap(tmp_path, temporary),
        workspace_path=str(tmp_path),
    )

    async def launcher(spec: ExecutionSpec) -> ExecutionProcess:
        del spec
        raise FileNotFoundError("bwrap")

    backend = BwrapExecutionBackend(config, launcher=launcher)

    with pytest.raises(ContainmentQualificationError) as raised:
        await backend.qualify()

    assert raised.value.category == "backend_unavailable"


@pytest.mark.asyncio
async def test_bwrap_qualification_verifies_descendant_termination(
    tmp_path: Path,
) -> None:
    temporary = tmp_path.parent / f"{tmp_path.name}-temporary"
    config = parse_containment_bootstrap(
        _bootstrap(tmp_path, temporary),
        workspace_path=str(tmp_path),
    )
    launched: list[ExecutionSpec] = []
    canary_process = _FakeProcess(wait_forever=True, stdout=b"ready\n")

    async def launcher(spec: ExecutionSpec) -> ExecutionProcess:
        launched.append(spec)
        if len(launched) == 1:
            return _FakeProcess()
        lock_path = Path(spec.argv[-2])
        lock_path.touch()
        return canary_process

    backend = BwrapExecutionBackend(config, launcher=launcher)

    await backend.qualify()

    assert len(launched) == 2
    assert any("descendant_authority" in argument for argument in launched[0].argv)
    assert canary_process.termination_calls == 1


@pytest.mark.asyncio
async def test_bwrap_qualification_termination_error_has_bounded_category(
    tmp_path: Path,
) -> None:
    temporary = tmp_path.parent / f"{tmp_path.name}-temporary"
    config = parse_containment_bootstrap(
        _bootstrap(tmp_path, temporary),
        workspace_path=str(tmp_path),
    )
    launched = 0
    canary_process = _FakeProcess(
        wait_forever=True,
        stdout=b"ready\n",
        termination_error=True,
    )

    async def launcher(spec: ExecutionSpec) -> ExecutionProcess:
        nonlocal launched
        launched += 1
        if launched == 1:
            return _FakeProcess()
        Path(spec.argv[-2]).touch()
        return canary_process

    backend = BwrapExecutionBackend(config, launcher=launcher)

    with pytest.raises(ContainmentQualificationError) as raised:
        await backend.qualify()

    assert raised.value.category == "termination_failed"
    assert canary_process.termination_calls == 1


@pytest.mark.asyncio
async def test_bwrap_qualification_timeout_terminates_descendants(
    tmp_path: Path,
) -> None:
    temporary = tmp_path.parent / f"{tmp_path.name}-temporary"
    document = json.loads(_bootstrap(tmp_path, temporary))
    document["qualification_timeout_seconds"] = 1
    config = parse_containment_bootstrap(
        json.dumps(document),
        workspace_path=str(tmp_path),
    )
    process = _FakeProcess(wait_forever=True)

    async def launcher(spec: ExecutionSpec) -> ExecutionProcess:
        del spec
        return process

    backend = BwrapExecutionBackend(config, launcher=launcher)

    with pytest.raises(ContainmentQualificationError) as raised:
        await backend.qualify()

    assert raised.value.category == "timeout"
    assert process.termination_calls == 1
