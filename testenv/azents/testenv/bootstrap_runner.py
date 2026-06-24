"""local bootstrap orchestration."""

import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from testenv.fixture_errors import (
    FixtureManifestNotFoundError,
    FixtureManifestReadError,
    FixtureManifestSchemaError,
    FixtureSecretValidationError,
)
from testenv.fixture_manifest import load_fixture_manifest
from testenv.fixture_resources import FixtureCommandResult
from testenv.fixture_runner import run_fixture_doctor, run_fixture_up

BootstrapStatus = Literal["ready", "error"]
StepStatus = Literal["pass", "fail", "skip"]
CommandRunner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]
FixtureUpRunner = Callable[[str, Path], FixtureCommandResult]
FixtureDoctorRunner = Callable[[str, Path], FixtureCommandResult]


@dataclass(frozen=True)
class BootstrapStep:
    """One bootstrap step result."""

    id: str
    status: StepStatus
    message: str

    def to_json_dict(self) -> dict[str, str]:
        """Return the CLI JSON output payload."""
        return {
            "id": self.id,
            "status": self.status,
            "message": self.message,
        }


@dataclass(frozen=True)
class BootstrapLocalResult:
    """``bootstrap local`` run result."""

    status: BootstrapStatus
    steps: tuple[BootstrapStep, ...]
    env_created: bool
    fixture: FixtureCommandResult | None
    doctors: tuple[FixtureCommandResult, ...]

    def to_json_dict(self) -> dict[str, object]:
        """Return the CLI JSON output payload."""
        payload: dict[str, object] = {
            "status": self.status,
            "env_created": self.env_created,
            "steps": [step.to_json_dict() for step in self.steps],
            "doctors": [doctor.to_json_dict() for doctor in self.doctors],
        }
        if self.fixture is not None:
            payload["fixture"] = self.fixture.to_json_dict()
        return payload


def run_bootstrap_local(
    testenv_root: Path,
    *,
    runner: CommandRunner | None = None,
    fixture_up_runner: FixtureUpRunner | None = None,
    fixture_doctor_runner: FixtureDoctorRunner | None = None,
) -> BootstrapLocalResult:
    """Prepare the default local run environment."""
    command_runner = runner or _run_command
    run_fixture = fixture_up_runner or run_fixture_up
    run_doctor = fixture_doctor_runner or run_fixture_doctor
    steps: list[BootstrapStep] = []

    env_step, env_created = _ensure_env_file(testenv_root)
    steps.append(env_step)

    cleanup_step = _cleanup_stale_agent_containers(testenv_root, command_runner)
    steps.append(cleanup_step)
    if cleanup_step.status == "fail":
        return _error_result(steps, env_created)

    for step in _restart_devserver(testenv_root, command_runner):
        steps.append(step)
        if step.status == "fail":
            return _error_result(steps, env_created)

    fixture = run_fixture("devserver", testenv_root)
    steps.append(
        BootstrapStep(
            id="fixture-up-devserver",
            status="pass" if fixture.status == "ready" else "fail",
            message=fixture.message,
        )
    )
    if fixture.status != "ready":
        return BootstrapLocalResult(
            status="error",
            steps=tuple(steps),
            env_created=env_created,
            fixture=fixture,
            doctors=(),
        )

    doctors = (run_doctor("devserver", testenv_root),)
    steps.append(
        BootstrapStep(
            id="fixture-doctor-all",
            status="pass" if all(doctor.status == "ready" for doctor in doctors) else "fail",
            message=_doctor_summary_message(doctors),
        )
    )
    return BootstrapLocalResult(
        status="ready" if steps[-1].status == "pass" else "error",
        steps=tuple(steps),
        env_created=env_created,
        fixture=fixture,
        doctors=doctors,
    )


def _ensure_env_file(testenv_root: Path) -> tuple[BootstrapStep, bool]:
    """Ensure the non-secret .env file exists, creating it from defaults if needed."""
    env_path = testenv_root / ".env"
    example_path = testenv_root / ".env.example"
    if env_path.exists():
        return (
            BootstrapStep(
                id="env-file",
                status="pass",
                message="Existing .env file preserved",
            ),
            False,
        )
    if not example_path.exists():
        return (
            BootstrapStep(
                id="env-file",
                status="fail",
                message="Missing .env.example; cannot create .env",
            ),
            False,
        )
    shutil.copyfile(example_path, env_path)
    return (
        BootstrapStep(
            id="env-file",
            status="pass",
            message="Created .env from .env.example",
        ),
        True,
    )


def _cleanup_stale_agent_containers(
    testenv_root: Path,
    runner: CommandRunner,
) -> BootstrapStep:
    """Remove exited agent containers owned by the testenv fixture."""
    agent_id = _agent_basic_agent_id(testenv_root)
    if agent_id is None:
        return BootstrapStep(
            id="cleanup-stale-agent-containers",
            status="pass",
            message="No testenv-owned agent fixture found",
        )

    listed = runner(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            "name=^/azents-agent-",
            "--filter",
            f"label=azents/agent-id={agent_id}",
            "--filter",
            "status=exited",
            "--format",
            "{{.Names}}",
        ],
        testenv_root,
    )
    if listed.returncode != 0:
        return _failed_command_step("cleanup-stale-agent-containers", listed)

    container_names = tuple(line.strip() for line in listed.stdout.splitlines() if line.strip())
    if not container_names:
        return BootstrapStep(
            id="cleanup-stale-agent-containers",
            status="pass",
            message="No exited testenv-owned azents-agent containers found",
        )

    removed = runner(["docker", "rm", "-f", *container_names], testenv_root)
    if removed.returncode != 0:
        return _failed_command_step("cleanup-stale-agent-containers", removed)
    return BootstrapStep(
        id="cleanup-stale-agent-containers",
        status="pass",
        message=f"Removed {len(container_names)} exited testenv-owned azents-agent containers",
    )


def _agent_basic_agent_id(testenv_root: Path) -> str | None:
    """Return the testenv agent id recorded in the agent-basic manifest."""
    try:
        manifest = load_fixture_manifest("agent-basic", testenv_root)
    except (
        FixtureManifestNotFoundError,
        FixtureManifestReadError,
        FixtureManifestSchemaError,
        FixtureSecretValidationError,
    ):
        return None

    agent = manifest.resources.get("agent")
    if not isinstance(agent, dict):
        return None
    agent_id = agent.get("id")
    if not isinstance(agent_id, str) or not agent_id:
        return None
    return agent_id


def _restart_devserver(testenv_root: Path, runner: CommandRunner) -> tuple[BootstrapStep, ...]:
    """Restart the devserver for the current worktree."""
    down = runner(["uv", "run", "devserver.py", "down", "--force"], testenv_root)
    if down.returncode != 0:
        return (_failed_command_step("devserver-down", down),)

    up = runner(["uv", "run", "devserver.py", "up", "--force"], testenv_root)
    if up.returncode != 0:
        return (
            BootstrapStep(
                id="devserver-down",
                status="pass",
                message="Stopped existing devserver if present",
            ),
            _failed_command_step("devserver-up", up),
        )

    return (
        BootstrapStep(
            id="devserver-down",
            status="pass",
            message="Stopped existing devserver if present",
        ),
        BootstrapStep(
            id="devserver-up",
            status="pass",
            message="Started devserver for current worktree",
        ),
    )


def _run_command(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run an external command while capturing stdout and stderr."""
    try:
        return subprocess.run(
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=127,
            stdout="",
            stderr=str(exc),
        )


def _failed_command_step(step_id: str, process: subprocess.CompletedProcess[str]) -> BootstrapStep:
    """Convert a failed subprocess result into a safe step message."""
    return BootstrapStep(
        id=step_id,
        status="fail",
        message=f"Command failed with exit code {process.returncode}",
    )


def _doctor_summary_message(doctors: tuple[FixtureCommandResult, ...]) -> str:
    """Summarize fixture doctor results."""
    if not doctors:
        return "No fixture doctors registered"
    ready = sum(1 for doctor in doctors if doctor.status == "ready")
    return f"Fixture doctors ready: {ready}/{len(doctors)}"


def _error_result(steps: list[BootstrapStep], env_created: bool) -> BootstrapLocalResult:
    """Create a bootstrap failure result."""
    return BootstrapLocalResult(
        status="error",
        steps=tuple(steps),
        env_created=env_created,
        fixture=None,
        doctors=(),
    )
