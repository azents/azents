"""External Channel cutover operator CLI tests."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from typer.testing import CliRunner

from azents.cli import external_channel_cutover
from azents.services.external_channel.cutover_preflight import (
    ExternalChannelCutoverPreflightReport,
)


@dataclass
class _Config:
    """Minimal CLI runtime configuration."""

    runtime_env: str = "test"
    sentry_dsn: str | None = None


class _Service:
    """Preflight service double for CLI adapter tests."""

    def __init__(self, report: ExternalChannelCutoverPreflightReport) -> None:
        self.report = report
        self.calls = 0

    async def preflight(self) -> ExternalChannelCutoverPreflightReport:
        """Record one preflight call."""
        self.calls += 1
        return self.report


class _Container:
    """Container stub resolving the configured CLI service."""

    def __init__(self, service: _Service) -> None:
        self.service = service

    async def solve(self, _type: type[object]) -> _Service:
        """Return the configured preflight service."""
        return self.service


def _configure_cli(monkeypatch: pytest.MonkeyPatch, service: _Service) -> None:
    """Replace runtime infrastructure with deterministic test doubles."""
    monkeypatch.setattr(external_channel_cutover.Config, "from_env", _Config)
    monkeypatch.setattr(
        external_channel_cutover,
        "configure_logging_for_runtime",
        lambda **_kwargs: None,
    )

    @asynccontextmanager
    async def run_with_container(
        _config: _Config,
    ) -> AsyncGenerator[_Container, None]:
        yield _Container(service)

    monkeypatch.setattr(
        external_channel_cutover,
        "run_with_container",
        run_with_container,
    )


def test_preflight_reports_only_categories_and_ready_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI returns success for a fully drained content-free report."""
    service = _Service(
        ExternalChannelCutoverPreflightReport(
            category_counts=(
                ("legacy_events_not_drained", 0),
                ("pending_context_present", 0),
            )
        )
    )
    _configure_cli(monkeypatch, service)

    result = CliRunner().invoke(external_channel_cutover.app, ["preflight"])

    assert result.exit_code == 0
    assert "category.legacy_events_not_drained: 0" in result.stdout
    assert "preflight_ready: true" in result.stdout
    assert service.calls == 1


def test_preflight_exits_nonzero_when_a_category_is_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI is an automation-safe abort gate without repair behavior."""
    service = _Service(
        ExternalChannelCutoverPreflightReport(
            category_counts=(("access_requests_pending", 2),)
        )
    )
    _configure_cli(monkeypatch, service)

    result = CliRunner().invoke(external_channel_cutover.app, ["preflight"])

    assert result.exit_code == 2
    assert "category.access_requests_pending: 2" in result.stdout
    assert "preflight_ready: false" in result.stdout
    assert "preflight_blocked: invariant_failures" in result.stdout
    assert service.calls == 1
