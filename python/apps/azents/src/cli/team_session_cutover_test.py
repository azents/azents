"""Team Session cutover operator CLI tests."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace

import pytest
from typer.testing import CliRunner

from azents.cli import team_session_cutover
from azents.services.team_session_cutover_replay import (
    TeamSessionCutoverReplayInvariantFailure,
    TeamSessionCutoverReplayReport,
)


@dataclass
class _Config:
    """Minimal CLI runtime configuration."""

    runtime_env: str = "test"
    sentry_dsn: str | None = None


class _Service:
    """Cutover service double for CLI adapter tests."""

    def __init__(
        self,
        report: TeamSessionCutoverReplayReport,
        replay_failure: TeamSessionCutoverReplayInvariantFailure | None = None,
    ) -> None:
        self.report = report
        self.replay_failure = replay_failure
        self.preflight_calls: list[tuple[int, str | None]] = []
        self.replay_calls: list[tuple[int, str | None]] = []

    async def preflight(
        self,
        *,
        batch_size: int,
        after_session_id: str | None,
    ) -> TeamSessionCutoverReplayReport:
        """Record the preflight adapter call."""
        self.preflight_calls.append((batch_size, after_session_id))
        return self.report

    async def replay(
        self,
        *,
        batch_size: int,
        after_session_id: str | None,
    ) -> TeamSessionCutoverReplayReport:
        """Record replay or raise the configured invariant failure."""
        self.replay_calls.append((batch_size, after_session_id))
        if self.replay_failure is not None:
            raise self.replay_failure
        return self.report


class _Container:
    """Container stub resolving the configured CLI service."""

    def __init__(self, service: _Service) -> None:
        self.service = service

    async def solve(self, _type: type[object]) -> _Service:
        """Return the configured cutover service."""
        return self.service


def _report() -> TeamSessionCutoverReplayReport:
    """Return one content-free report fixture."""
    return TeamSessionCutoverReplayReport(
        scanned_sessions=2,
        valid_sessions=2,
        replayed_sessions=0,
        pending_input_sessions=1,
        pending_command_sessions=1,
        recoverable_run_sessions=0,
        pending_idle_continuation_sessions=0,
        stop_request_sessions=0,
        invariant_failures=(),
        next_session_cursor="session-2",
    )


def _configure_cli(monkeypatch: pytest.MonkeyPatch, service: _Service) -> None:
    """Replace runtime infrastructure with deterministic test doubles."""
    monkeypatch.setattr(team_session_cutover.Config, "from_env", _Config)
    monkeypatch.setattr(
        team_session_cutover,
        "configure_logging_for_runtime",
        lambda **_kwargs: None,
    )

    @asynccontextmanager
    async def run_with_container(
        _config: _Config,
    ) -> AsyncGenerator[_Container, None]:
        yield _Container(service)

    monkeypatch.setattr(team_session_cutover, "run_with_container", run_with_container)


def test_preflight_reports_only_content_free_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI reports bounded counts and cursor without work contents."""
    service = _Service(_report())
    _configure_cli(monkeypatch, service)

    result = CliRunner().invoke(
        team_session_cutover.app,
        ["preflight", "--batch-size", "2", "--after-session-id", "session-0"],
    )

    assert result.exit_code == 0
    assert "scanned_sessions: 2" in result.stdout
    assert "pending_input_sessions: 1" in result.stdout
    assert "next_session_cursor: session-2" in result.stdout
    assert service.preflight_calls == [(2, "session-0")]


def test_preflight_exits_nonzero_when_invariants_are_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preflight is an automation-safe cutover gate."""
    report = _report()
    report = replace(
        report,
        valid_sessions=1,
        invariant_failures=(("canonical_execution_invalid", 1),),
    )
    service = _Service(report)
    _configure_cli(monkeypatch, service)

    result = CliRunner().invoke(team_session_cutover.app, ["preflight"])

    assert result.exit_code == 2
    assert "preflight_blocked: invariant_failures" in result.stdout
    assert "invariant_failure.canonical_execution_invalid: 1" in result.stdout
    assert service.preflight_calls == [(100, None)]


def test_replay_requires_explicit_execute_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI never performs broker mutation without explicit operator confirmation."""
    service = _Service(_report())
    _configure_cli(monkeypatch, service)

    result = CliRunner().invoke(team_session_cutover.app, ["replay"])

    assert result.exit_code == 2
    assert "Replay requires --execute." in result.stderr
    assert service.replay_calls == []


def test_replay_reports_invariant_codes_without_durable_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI blocks replay with only invariant codes and counts."""
    failure = TeamSessionCutoverReplayInvariantFailure(
        invariant_failures=(("canonical_execution_invalid", 1),)
    )
    service = _Service(_report(), replay_failure=failure)
    _configure_cli(monkeypatch, service)

    result = CliRunner().invoke(
        team_session_cutover.app,
        ["replay", "--execute"],
    )

    assert result.exit_code == 2
    assert "replay_blocked: invariant_failures" in result.stdout
    assert "invariant_failure.canonical_execution_invalid: 1" in result.stdout
    assert service.replay_calls == [(100, None)]
