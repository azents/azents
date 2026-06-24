"""Tests for fixture CLI runner."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from testenv.cli import app
from testenv.fixture_manifest import DoctorCheck
from testenv.fixture_resources import FixtureCommandResult, fixture_providers
from testenv.fixture_runner import UnknownFixtureError, run_fixture_doctor_all, run_fixture_up

_RUNNER = CliRunner()


def test_fixture_cli_registers_fixture_group() -> None:
    """Typer app wires the fixture subcommand group."""
    result = _RUNNER.invoke(app, ["fixture", "--help"])

    assert result.exit_code == 0
    assert "Long-lived fixture lifecycle commands." in result.stdout


def test_fixture_unknown_id_exits_with_usage_error(tmp_path: Path) -> None:
    """Missing fixture id returns a usage error."""
    result = _RUNNER.invoke(app, ["fixture", "up", "unknown-fixture", "--workdir", str(tmp_path)])

    assert result.exit_code == 2
    assert "unknown fixture: unknown-fixture" in result.output


def test_fixture_provider_registry_contains_devserver() -> None:
    """Fixture registry registers devserver and agent-basic providers."""
    providers = fixture_providers()

    assert "devserver" in providers
    assert "agent-basic" in providers


def test_runner_unknown_fixture_raises_usage_error(tmp_path: Path) -> None:
    """Runner raises a typed exception for unknown fixtures."""
    with pytest.raises(UnknownFixtureError):
        run_fixture_up("unknown-fixture", tmp_path)


def test_doctor_all_runs_registered_devserver_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """doctor --all runs every provider in the registry."""

    class FakeProvider:
        """Test provider doctor call."""

        id = "devserver"

        def __init__(self) -> None:
            self.called = False

        def up(self, ctx: object) -> FixtureCommandResult:
            raise NotImplementedError

        def doctor(self, ctx: object) -> FixtureCommandResult:
            self.called = True
            return FixtureCommandResult(
                fixture_id="devserver",
                status="ready",
                checks=(DoctorCheck(id="manifest", status="pass", message="ok"),),
                manifest=None,
                message="Fixture devserver is ready",
                guidance=None,
            )

        def reset(self, ctx: object) -> FixtureCommandResult:
            raise NotImplementedError

    provider = FakeProvider()

    class FakeAgentBasicProvider(FakeProvider):
        """Test provider for agent-basic doctor call."""

        id = "agent-basic"

        def doctor(self, ctx: object) -> FixtureCommandResult:
            self.called = True
            return FixtureCommandResult(
                fixture_id="agent-basic",
                status="ready",
                checks=(DoctorCheck(id="manifest", status="pass", message="ok"),),
                manifest=None,
                message="Fixture agent-basic is ready",
                guidance=None,
            )

    agent_provider = FakeAgentBasicProvider()
    monkeypatch.setattr(
        "testenv.fixture_runner.fixture_providers",
        lambda: {"devserver": provider, "agent-basic": agent_provider},
    )

    results = run_fixture_doctor_all(tmp_path)

    assert provider.called is True
    assert agent_provider.called is True
    assert [result.fixture_id for result in results] == ["devserver", "agent-basic"]
