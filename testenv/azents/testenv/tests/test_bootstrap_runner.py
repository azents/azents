"""Tests for the bootstrap local runner."""

import datetime as dt
import subprocess
from collections.abc import Sequence
from pathlib import Path

from typer.testing import CliRunner

from testenv.bootstrap_runner import run_bootstrap_local
from testenv.cli import app
from testenv.fixture_manifest import (
    DoctorCheck,
    FixtureManifest,
    WorktreeFingerprint,
    save_fixture_manifest,
)
from testenv.fixture_resources import FixtureCommandResult

_RUNNER = CliRunner()


def test_bootstrap_cli_registers_bootstrap_group() -> None:
    """Typer app wires the bootstrap subcommand group."""
    result = _RUNNER.invoke(app, ["bootstrap", "--help"])

    assert result.exit_code == 0
    assert "Local environment bootstrap commands." in result.stdout


def test_bootstrap_local_prepares_devserver_boundary(tmp_path: Path) -> None:
    """bootstrap local prepares env, devserver, and fixture for QA runs."""
    (tmp_path / ".env.example").write_text("AZ_RUNTIME_ENV=local\n", encoding="utf-8")
    _write_agent_fixture_manifest(tmp_path, agent_id="agent-testenv")
    commands: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        commands.append(tuple(command))
        if command[:2] == ["docker", "ps"]:
            return subprocess.CompletedProcess(command, 0, stdout="azents-agent-old\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    fixture = _fixture_result("devserver", "ready")

    result = run_bootstrap_local(
        tmp_path,
        runner=runner,
        fixture_up_runner=lambda fixture_id, workdir: fixture,
        fixture_doctor_runner=lambda fixture_id, workdir: fixture,
    )

    assert result.status == "ready"
    assert result.env_created is True
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "AZ_RUNTIME_ENV=local\n"
    assert (
        "docker",
        "ps",
        "-a",
        "--filter",
        "name=^/azents-agent-",
        "--filter",
        "label=azents/agent-id=agent-testenv",
        "--filter",
        "status=exited",
        "--format",
        "{{.Names}}",
    ) in commands
    assert ("uv", "run", "devserver.py", "down", "--force") in commands
    assert ("uv", "run", "devserver.py", "up", "--force") in commands
    assert not any(
        command[:3] == ("uv", "run", "testenv") and "qa" in command for command in commands
    )
    assert all("AZ_RUNTIME_ENV" not in step.message for step in result.steps)


def test_bootstrap_local_stops_when_devserver_fails(tmp_path: Path) -> None:
    """devserver failure prevents fixture and QA progress."""
    (tmp_path / ".env.example").write_text("AZ_RUNTIME_ENV=local\n", encoding="utf-8")
    _write_agent_fixture_manifest(tmp_path, agent_id="agent-testenv")
    fixture_called = False

    def runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["docker", "ps"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if tuple(command) == ("uv", "run", "devserver.py", "up", "--force"):
            return subprocess.CompletedProcess(
                command,
                1,
                stdout="AZ_CREDENTIAL_ENCRYPTION_KEY=secret",
                stderr="devserver failed",
            )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    def fixture_up(fixture_id: str, workdir: Path) -> FixtureCommandResult:
        nonlocal fixture_called
        fixture_called = True
        return _fixture_result(fixture_id, "ready")

    result = run_bootstrap_local(
        tmp_path,
        runner=runner,
        fixture_up_runner=fixture_up,
        fixture_doctor_runner=lambda fixture_id, workdir: _fixture_result("devserver", "ready"),
    )

    assert result.status == "error"
    assert fixture_called is False
    assert result.steps[-1].id == "devserver-up"
    assert result.steps[-1].status == "fail"
    assert result.steps[-1].message == "Command failed with exit code 1"
    assert "AZ_CREDENTIAL_ENCRYPTION_KEY" not in result.steps[-1].message


def test_bootstrap_local_reports_fixture_not_ready(tmp_path: Path) -> None:
    """doctor-all runs after fixture up is ready."""
    (tmp_path / ".env").write_text("AZ_RUNTIME_ENV=local\n", encoding="utf-8")
    _write_agent_fixture_manifest(tmp_path, agent_id="agent-testenv")
    doctor_called = False

    def runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["docker", "ps"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    def doctor(fixture_id: str, workdir: Path) -> FixtureCommandResult:
        nonlocal doctor_called
        doctor_called = True
        return _fixture_result(fixture_id, "ready")

    result = run_bootstrap_local(
        tmp_path,
        runner=runner,
        fixture_up_runner=lambda fixture_id, workdir: _fixture_result(fixture_id, "error"),
        fixture_doctor_runner=doctor,
    )

    assert result.status == "error"
    assert result.env_created is False
    assert doctor_called is False
    assert result.fixture is not None
    assert result.fixture.status == "error"


def test_bootstrap_local_skips_agent_cleanup_without_fixture_manifest(tmp_path: Path) -> None:
    """Docker cleanup is safe when agent-basic manifest is missing."""
    (tmp_path / ".env.example").write_text("AZ_RUNTIME_ENV=local\n", encoding="utf-8")
    commands: list[tuple[str, ...]] = []

    def runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        commands.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    fixture = _fixture_result("devserver", "ready")

    result = run_bootstrap_local(
        tmp_path,
        runner=runner,
        fixture_up_runner=lambda fixture_id, workdir: fixture,
        fixture_doctor_runner=lambda fixture_id, workdir: fixture,
    )

    assert result.status == "ready"
    assert not any(command[:2] == ("docker", "ps") for command in commands)
    assert any(
        step.id == "cleanup-stale-agent-containers"
        and step.message == "No testenv-owned agent fixture found"
        for step in result.steps
    )


def _fixture_result(fixture_id: str, status: str) -> FixtureCommandResult:
    """Create a fixture result for bootstrap tests."""
    return FixtureCommandResult(
        fixture_id=fixture_id,
        status="ready" if status == "ready" else "error",
        checks=(DoctorCheck(id="manifest", status="pass", message="ok"),),
        manifest=None,
        message=f"Fixture {fixture_id} is {status}",
        guidance=None,
        error_code=None if status == "ready" else "FIXTURE_ERROR",
    )


def _write_agent_fixture_manifest(testenv_root: Path, *, agent_id: str) -> None:
    """Save a manifest for testenv-owned agent container cleanup tests."""
    now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    save_fixture_manifest(
        FixtureManifest(
            schema_version=1,
            fixture_id="agent-basic",
            status="ready",
            created_at=now,
            updated_at=now,
            worktree=WorktreeFingerprint(
                repo_root=str(testenv_root),
                head_sha="abcdef0",
                dirty_hash=None,
                env_hash=None,
                fingerprint="fixture-fingerprint",
            ),
            resources={"agent": {"id": agent_id}},
            provides={"agent.id": agent_id},
            doctor=None,
        ),
        testenv_root,
    )
